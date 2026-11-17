"""AIOS request.json contract: parse the envelope, validate the request, resolve inputs by name."""
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import common
import compose
import receipt

REQUEST_MAX_BYTES = 4 * 1024 * 1024
SCRIPT_MAX_BYTES = 1024 * 1024
SMALL_JSON_MAX_BYTES = 1024 * 1024
ORIGINALITY_MAX_BYTES = 64 * 1024
FINAL_SUFFIX = "_40_Short_Final.mp4"
SHOT_KINDS = ("grok_t2v", "grok_i2v_continue")
GATE_MESSAGE = "ด่านกันลอก: สคริปต์ไม่ได้ผ่านด่านกันลอก / ถูกแก้หลังผ่านด่าน — รันขั้นสคริปต์ใหม่"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RequestError(common.GgError):
    pass


@dataclass
class Envelope:
    request: dict
    request_path: Path
    run_dir: Path            # real directory that holds request.json (result.json and the final live here)
    result_path: Path
    correlation: dict


@dataclass
class Plan:
    task_dir: Path
    shots: list
    script_text: str
    texts_raw: list
    mood: object = None
    script_path: Path = None


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def parse_envelope(request_path):
    """Minimum needed to write a receipt safely. Failure here = write NOTHING, exit non-zero."""
    rp = Path(request_path)
    if not rp.is_absolute():
        raise RequestError(f"--request ต้องเป็น absolute path: {request_path}")
    try:
        if rp.stat().st_size > REQUEST_MAX_BYTES:
            raise RequestError("request.json ใหญ่เกินไป")
        request = json.loads(rp.read_text(encoding="utf-8"))
    except RequestError:
        raise
    except (OSError, ValueError) as e:
        raise RequestError(f"อ่าน request.json ไม่ได้: {e}")
    if not isinstance(request, dict):
        raise RequestError("request.json ต้องเป็น object")
    for k in ("task_id", "step_id", "run_id", "dispatch_id"):
        if not isinstance(request.get(k), str) or not request[k]:
            raise RequestError(f"request.json ขาด {k}")
    if not isinstance(request.get("target"), dict) or "schema" not in request:
        raise RequestError("request.json ขาด target/schema")
    result_path = request.get("result_path")
    if not isinstance(result_path, str) or not os.path.isabs(result_path):
        raise RequestError("result_path ต้องเป็น absolute path")
    run_dir = Path(os.path.realpath(rp.parent))
    result = Path(result_path)
    if Path(os.path.realpath(result.parent)) != run_dir:
        raise RequestError("result_path ต้องอยู่โฟลเดอร์เดียวกับ request.json (ไม่เขียนไปที่อื่น)")
    return Envelope(request, rp, run_dir, result, receipt.correlation_of(request))


def validate_outputs(env):
    """Exactly one absolute output named *_40_Short_Final.mp4 inside the run dir."""
    outs = env.request.get("outputs")
    if not isinstance(outs, list) or len(outs) != 1 or not isinstance(outs[0], str):
        raise RequestError("outputs ต้องมีไฟล์เดียว (*_40_Short_Final.mp4)")
    final = Path(outs[0])
    if not final.is_absolute() or not final.name.endswith(FINAL_SUFFIX) or final.name == FINAL_SUFFIX:
        raise RequestError(f"output ต้องเป็น absolute path ที่ลงท้าย {FINAL_SUFFIX}")
    if Path(os.path.realpath(final.parent)) != env.run_dir:
        raise RequestError("output ต้องอยู่ในโฟลเดอร์ run เดียวกับ request.json")
    return Path(os.path.realpath(final.parent)) / final.name


def validate_request(env):
    r = env.request
    if r.get("schema") != 1 or isinstance(r.get("schema"), bool):
        raise RequestError("schema ต้องเป็น 1")
    if r.get("kind") != "edit_short":
        raise RequestError(f"kind ต้องเป็น edit_short (ได้ {r.get('kind')!r})")
    if r.get("aspect") != "9:16":
        raise RequestError(f"aspect ต้องเป็น 9:16 (ได้ {r.get('aspect')!r})")
    if not isinstance(r.get("inputs"), list):
        raise RequestError("inputs ต้องเป็น list")


def derive_task_dir(env):
    """<task>/steps/<stepId>/runs/<n>/request.json (AIOS v2RunRelDir)."""
    p = env.run_dir
    if p.parent.name != "runs" or p.parent.parent.parent.name != "steps":
        raise RequestError("request.json ไม่ได้อยู่ใน <task>/steps/<step>/runs/<n>/ — หาโฟลเดอร์งาน (task dir) ไม่ได้")
    return p.parent.parent.parent.parent


def _input(request, role):
    found = [i for i in request["inputs"] if isinstance(i, dict) and i.get("role") == role]
    if len(found) != 1:
        raise RequestError(f"ต้องมี input role {role} ตัวเดียว (พบ {len(found)})")
    inp = found[0]
    files = inp.get("files")
    if not isinstance(files, list) or not files or not all(isinstance(f, str) and os.path.isabs(f) for f in files):
        raise RequestError(f"input {role}: files ต้องเป็น list ของ absolute path")
    return inp, files


def _read_capped(path, cap, what):
    try:
        if os.path.getsize(path) > cap:
            raise RequestError(f"{what} ใหญ่เกินไป")
        return Path(path).read_bytes()
    except OSError as e:
        raise RequestError(f"อ่าน{what}ไม่ได้: {e}")


def _json_obj(raw, what):
    try:
        v = json.loads(raw.decode("utf-8").strip())
    except (UnicodeDecodeError, ValueError):
        raise RequestError(f"{what} ไม่ใช่ JSON ที่ถูกต้อง (JSON)")
    if not isinstance(v, dict):
        raise RequestError(f"{what} ต้องเป็น JSON object")
    return v


def _check_originality(script_file, script_bytes, script_files):
    """originality.json is always written beside the G&G script by the AIOS script step (viral-script-step.ts)."""
    sib = [f for f in script_files if os.path.dirname(f) == os.path.dirname(script_file) and os.path.basename(f) == "originality.json"]
    if len(sib) != 1:
        raise RequestError(GATE_MESSAGE + " (ไม่พบ originality.json ข้างไฟล์สคริปต์ใน input)")
    try:
        rec = json.loads(_read_capped(sib[0], ORIGINALITY_MAX_BYTES, "originality.json").decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise RequestError(GATE_MESSAGE + " (originality.json อ่านไม่ได้)")
    sha = rec.get("script_sha256") if isinstance(rec, dict) else None
    if not (isinstance(rec, dict) and rec.get("schema") == 1 and rec.get("pass") is True
            and isinstance(sha, str) and SHA256_RE.match(sha) and sha == hashlib.sha256(script_bytes).hexdigest()):
        raise RequestError(GATE_MESSAGE)


def _read_mood(task_dir):
    try:
        wf = json.loads((task_dir / "workflow.json").read_text(encoding="utf-8"))
        mood = wf["viral"]["production_plan"]["audio"]["mood"]
        return mood.strip() if isinstance(mood, str) and mood.strip() else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def load_plan(env):
    r = env.request
    task_dir = derive_task_dir(env)
    real_task = os.path.realpath(task_dir)

    clips_in, clips_files = _input(r, "clips")
    script_in, script_files = _input(r, "script")

    # --- script (by name, never by list order) ---
    scripts = [f for f in script_files if os.path.basename(f).endswith("_00_Script.txt")]
    if len(scripts) != 1:
        raise RequestError(f"ไม่พบไฟล์ *_00_Script.txt ตัวเดียวใน input script (พบ {len(scripts)})")
    script_bytes = _read_capped(scripts[0], SCRIPT_MAX_BYTES, "ไฟล์สคริปต์")
    _check_originality(scripts[0], script_bytes, script_files)
    script = _json_obj(script_bytes, "สคริปต์ G&G")
    if not isinstance(script.get("on_screen_text"), list):
        raise RequestError("สคริปต์ไม่มี on_screen_text (list) — เป็น JSON ของโหมด G&G หรือไม่")

    # --- clips manifest ---
    manifests = [f for f in clips_files if os.path.basename(f) == "manifest.json"
                 and os.path.basename(os.path.dirname(f)).endswith("_20_Clips")]
    if len(manifests) != 1:
        raise RequestError(f"ไม่พบ manifest.json ใน *_20_Clips ตัวเดียวใน input clips (พบ {len(manifests)})")
    manifest = _json_obj(_read_capped(manifests[0], SMALL_JSON_MAX_BYTES, "manifest"), "manifest.json")
    if manifest.get("schema") != 1:
        raise RequestError("manifest schema ต้องเป็น 1")
    if not isinstance(manifest.get("run_id"), str) or manifest["run_id"] != clips_in.get("run_id"):
        raise RequestError(f"manifest run_id ({manifest.get('run_id')!r}) ไม่ตรงกับ run_id ของ input clips ({clips_in.get('run_id')!r})")
    raw_shots = manifest.get("shots")
    if not isinstance(raw_shots, list) or not raw_shots:
        raise RequestError("manifest ไม่มี shots")
    shots_by_seq = {}
    for s in raw_shots:
        if not isinstance(s, dict) or not _is_int(s.get("seq")) or s["seq"] in shots_by_seq:
            raise RequestError("manifest shots: seq ไม่ถูกต้องหรือซ้ำ")
        shots_by_seq[s["seq"]] = s
    if sorted(shots_by_seq) != list(range(1, len(shots_by_seq) + 1)):
        raise RequestError(f"manifest shots: seq ต้องเป็น 1..N ต่อเนื่อง (ได้ {sorted(shots_by_seq)})")

    listed = {os.path.realpath(f) for f in clips_files}
    shots = []
    for seq in sorted(shots_by_seq):
        s = shots_by_seq[seq]
        kind, cont = s.get("kind"), s.get("continues_from_seq")
        if kind not in SHOT_KINDS:
            raise RequestError(f"ช็อต {seq}: kind ต้องเป็น {' หรือ '.join(SHOT_KINDS)}")
        if kind == "grok_i2v_continue":
            if cont != seq - 1 or not _is_int(cont) or seq == 1:
                raise RequestError(f"ช็อต {seq}: continues_from_seq ต้องเท่ากับ seq ก่อนหน้า ({seq - 1})")
        elif cont is not None:
            raise RequestError(f"ช็อต {seq}: grok_t2v ต้องไม่มี continues_from_seq")
        rel = s.get("file")
        if not isinstance(rel, str) or not rel or os.path.isabs(rel):
            raise RequestError(f"ช็อต {seq}: file ต้องเป็น path สัมพัทธ์กับโฟลเดอร์งาน")
        real = os.path.realpath(os.path.join(real_task, rel))
        if not real.startswith(real_task + os.sep):
            raise RequestError(f"ช็อต {seq}: ไฟล์อยู่นอกโฟลเดอร์งาน (task dir)")
        if real not in listed:
            raise RequestError(f"ช็อต {seq}: ไฟล์ไม่อยู่ในรายการ files ของ input clips")
        if not os.path.isfile(real):
            raise RequestError(f"ช็อต {seq}: ไม่พบไฟล์คลิป")
        shots.append(compose.Shot(seq=seq, path=Path(real), continues=kind == "grok_i2v_continue"))

    return Plan(task_dir=Path(real_task), shots=shots, script_text="", texts_raw=script["on_screen_text"],
                mood=_read_mood(Path(real_task)), script_path=Path(scripts[0]))
