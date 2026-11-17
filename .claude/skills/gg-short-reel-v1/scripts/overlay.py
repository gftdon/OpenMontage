"""On-screen text: Pillow-rendered PNG per item, burned with ffmpeg overlay inside the Instagram safe zone."""
import math
import os
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import common

# Instagram Reels safe zone on 1080x1920 (top dead 210 px, bottom dead 310 px, side margins 90 px)
SAFE_X0, SAFE_Y0, SAFE_X1, SAFE_Y1 = 90, 210, 990, 1600
MIN_FONT, START_FONT, FONT_STEP, MAX_LINES = 42, 72, 2, 6
PLACEMENTS = ("top", "center", "bottom")
CENTER_X, CENTER_Y = 540, (SAFE_Y0 + SAFE_Y1) // 2  # 905
FONT_NAME = "Kanit-Bold.ttf"
MAIN_CHECKOUT_FONT = Path("/Volumes/Ext_SS990Pro/Dev/openMontage-video-production/remotion-composer/public/fonts") / FONT_NAME
LEADING_VOWELS = "เแโใไ"
ATTACHING = "ะาำๆฯ"


class OverlayError(common.GgError):
    pass


def resolve_font(env=None, repo_fonts=None):
    """GG_SHORT_FONT -> <repo of this script>/remotion-composer/public/fonts -> main checkout. Missing = error."""
    env = os.environ if env is None else env
    explicit = (env.get("GG_SHORT_FONT") or "").strip()
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise OverlayError(f"GG_SHORT_FONT ชี้ไปที่ไฟล์ที่ไม่มีอยู่: {explicit}")
        return p
    if repo_fonts is None:
        repo = Path(__file__).resolve().parents[4]
        repo_fonts = [repo / "remotion-composer" / "public" / "fonts" / FONT_NAME, MAIN_CHECKOUT_FONT]
    for cand in repo_fonts:
        if Path(cand).is_file():
            return Path(cand)
    raise OverlayError(f"ไม่พบฟอนต์ {FONT_NAME} (ตั้ง GG_SHORT_FONT หรือวางไว้ใน remotion-composer/public/fonts)")


@dataclass(frozen=True)
class TextItem:
    text: str
    start_s: float
    end_s: float
    placement: str


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def parse_items(raw):
    if not isinstance(raw, list):
        raise OverlayError("on_screen_text ต้องเป็น list")
    items = []
    for i, it in enumerate(raw):
        p = f"on_screen_text[{i}]"
        if not isinstance(it, dict):
            raise OverlayError(f"{p} ต้องเป็น object")
        text = it.get("text")
        if not isinstance(text, str) or not text.strip():
            raise OverlayError(f"{p}.text ต้องเป็นข้อความที่ไม่ว่าง")
        if not _num(it.get("start_s")) or not _num(it.get("end_s")) or it["start_s"] < 0:
            raise OverlayError(f"{p}.start_s/end_s ต้องเป็นตัวเลขจำกัด (start_s >= 0)")
        if it.get("placement") not in PLACEMENTS:
            raise OverlayError(f"{p}.placement ต้องเป็น top, center หรือ bottom (placement)")
        items.append(TextItem(text.strip(), float(it["start_s"]), float(it["end_s"]), it["placement"]))
    return items


def clamp_items(items, duration_s):
    """Clamp times to the video; items with end <= start after clamping are dropped."""
    kept = []
    for it in items:
        s, e = max(0.0, it.start_s), min(float(duration_s), it.end_s)
        if e > s:
            kept.append(TextItem(it.text, s, e, it.placement))
    return kept


@lru_cache(maxsize=64)
def _font(path, size):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(str(path), size)
    except OSError as e:
        raise OverlayError(f"โหลดฟอนต์ไม่ได้: {path} ({e})")


def _clusters(word):
    out = []
    for ch in word:
        if out and (unicodedata.category(ch) in ("Mn", "Me") or ch in ATTACHING):
            out[-1] += ch
        else:
            out.append(ch)
    return out


def _break_word(word, width_of, max_w):
    """Break a space-less run (Thai) by grapheme cluster; never strand a leading vowel at a line end."""
    out, cur = [], []
    for cl in _clusters(word):
        if cur and width_of("".join(cur) + cl) > max_w:
            carry = []
            while cur and cur[-1][0] in LEADING_VOWELS:
                carry.insert(0, cur.pop())
            if not cur:
                cur, carry = carry, []
            out.append("".join(cur))
            cur = carry
        cur.append(cl)
    out.append("".join(cur))
    return out


def wrap_text(text, width_of, max_w):
    lines = []
    for para in text.replace("\r", "").split("\n"):
        words = para.split()
        cur = ""
        for w in words:
            cand = f"{cur} {w}" if cur else w
            if width_of(cand) <= max_w:
                cur = cand
                continue
            if cur:
                lines.append(cur)
                cur = ""
            if width_of(w) <= max_w:
                cur = w
                continue
            pieces = _break_word(w, width_of, max_w)
            lines.extend(pieces[:-1])
            cur = pieces[-1]
        if cur:
            lines.append(cur)
    return lines


@dataclass(frozen=True)
class Layout:
    box: tuple            # (x0, y0, x1, y1) on the 1080x1920 frame, includes stroke/shadow padding
    lines: tuple
    line_widths: tuple    # ink width of every line
    font_size: int
    stroke: int
    shadow: int
    pad: int
    baseline0: int        # y of the first baseline inside the box
    pitch: int            # distance between baselines
    offsets: tuple        # x origin of every line inside the box


def _ink(font, line, stroke):
    l, t, r, b = font.getbbox(line, stroke_width=stroke, anchor="ls")
    return l, t, r, b


def layout_item(text, placement, font_path):
    if placement not in PLACEMENTS:
        raise OverlayError(f"placement ไม่ถูกต้อง: {placement}")
    for size in range(START_FONT, MIN_FONT - 1, -FONT_STEP):
        font = _font(str(font_path), size)
        stroke, shadow = max(3, round(size / 12)), max(2, round(size / 20))
        pad = stroke + shadow + 4
        max_w = (SAFE_X1 - SAFE_X0) - 2 * pad

        def width_of(s):
            l, _, r, _ = _ink(font, s, stroke)
            return r - l

        lines = wrap_text(text, width_of, max_w)
        if not lines or len(lines) > MAX_LINES:
            continue
        asc, desc = font.getmetrics()
        inks = [_ink(font, ln, stroke) for ln in lines]
        above = max(asc + stroke, max(-t for _, t, _, _ in inks))
        below = max(desc + stroke, max(b for _, _, _, b in inks))
        pitch = max(round((asc + desc) * 1.05), 1)
        height = pad + above + (len(lines) - 1) * pitch + below + pad
        if height > SAFE_Y1 - SAFE_Y0:
            continue
        widths = [r - l for l, _, r, _ in inks]
        width = max(widths) + 2 * pad
        if width > SAFE_X1 - SAFE_X0:
            continue
        x0 = CENTER_X - width // 2
        y0 = {"top": SAFE_Y0, "bottom": SAFE_Y1 - height, "center": CENTER_Y - height // 2}[placement]
        offsets = tuple((width - w) // 2 - l for w, (l, _, _, _) in zip(widths, inks))
        return Layout((x0, y0, x0 + width, y0 + height), tuple(lines), tuple(widths), size, stroke, shadow, pad,
                      pad + above, pitch, offsets)
    raise OverlayError("ข้อความบนจอยาวเกินพื้นที่ปลอดภัย (safe zone) แม้ใช้ฟอนต์เล็กสุดแล้ว")


def render_png(layout, font_path, out_path):
    from PIL import Image, ImageDraw
    font = _font(str(font_path), layout.font_size)
    w, h = layout.box[2] - layout.box[0], layout.box[3] - layout.box[1]
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    shadow_fill = (0, 0, 0, 170)
    for i, line in enumerate(layout.lines):
        x, y = layout.offsets[i], layout.baseline0 + i * layout.pitch
        draw.text((x + layout.shadow, y + layout.shadow), line, font=font, fill=shadow_fill, anchor="ls",
                  stroke_width=layout.stroke, stroke_fill=shadow_fill)
    for i, line in enumerate(layout.lines):
        x, y = layout.offsets[i], layout.baseline0 + i * layout.pitch
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255), anchor="ls",
                  stroke_width=layout.stroke, stroke_fill=(10, 10, 10, 255))
    img.save(str(out_path), "PNG")


def burn(base_video, items, font_path, out_video, workdir, deadline):
    """Overlay every (already clamped) item between its start/end; video-only output, re-encoded once."""
    if not items:
        raise OverlayError("ไม่มีข้อความให้ burn")
    workdir = Path(workdir)
    args = [common.find_tool("ffmpeg"), "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", base_video]
    chain, prev = [], "0:v"
    for i, it in enumerate(items, start=1):
        lay = layout_item(it.text, it.placement, font_path)
        png = workdir / f"overlay-{i}.png"
        render_png(lay, font_path, png)
        args += ["-i", png]
        label = f"o{i}"
        chain.append(f"[{prev}][{i}:v]overlay=x={lay.box[0]}:y={lay.box[1]}:format=auto:"
                     f"enable='between(t,{it.start_s:.3f},{it.end_s:.3f})'[{label}]")
        prev = label
    chain.append(f"[{prev}]format=yuv420p[vout]")
    args += ["-filter_complex", ";".join(chain), "-map", "[vout]", "-an",
             "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
             "-r", "30", "-fps_mode", "cfr", "-movflags", "+faststart", out_video]
    common.run_cmd(args, deadline, "ffmpeg overlay")
