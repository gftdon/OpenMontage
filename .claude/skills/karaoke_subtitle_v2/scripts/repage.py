"""Repage caption pages so no page spans a script-line boundary, then emit a
Remotion-ready TypeScript data module.

Why: Thai has no inter-word spaces, so a caption page that crosses a sentence
seam welds the last word of one sentence onto the first word of the next and
reads as a false compound. Splitting at script-line ends costs a few extra
page flips (cheap, the gold highlight keeps continuity) and eliminates the
whole defect class. A substring assertion against the script makes a violation
loud instead of silent.

  python3 repage.py --pages caption_pages.json --script script.txt \
      --out-pages caption_pages_final.json --out-ts ../src/myCaptions.ts

--out-ts is optional; omit it to only emit the repaged JSON.
"""
import argparse
import json
import re


def norm(s):
    return re.sub(r"\s+", "", s)


def repage(pages, script_lines):
    norm_lines = [norm(l) for l in script_lines if l.strip()]

    # Map each word to its script line by walking the concatenated text in order.
    line_of_word = []
    li = 0
    pos = 0
    for p in pages:
        for w in p["words"]:
            t = norm(w["w"])
            while li < len(norm_lines) and not norm_lines[li][pos:].startswith(t):
                pos += 1
                if pos >= len(norm_lines[li]):
                    li += 1
                    pos = 0
                    if li >= len(norm_lines):
                        break
            line_of_word.append(li if li < len(norm_lines) else len(norm_lines) - 1)
            pos += len(t)
            if li < len(norm_lines) and pos >= len(norm_lines[li]):
                li += 1
                pos = 0

    # Rebuild pages, splitting whenever the script line changes.
    out = []
    idx = 0
    for p in pages:
        cur = None
        for w in p["words"]:
            ln = line_of_word[idx]
            idx += 1
            if cur is None or cur["line"] != ln:
                if cur:
                    out.append(cur)
                cur = {"line": ln, "start": w["s"], "end": w["e"], "words": [w]}
            else:
                cur["words"].append(w)
                cur["end"] = w["e"]
        if cur:
            out.append(cur)

    # Regression: every page's text must be a substring of its script line.
    bad = 0
    for p in out:
        text = norm("".join(w["w"] for w in p["words"]))
        if text not in norm_lines[p["line"]]:
            bad += 1
            print("SPAN!", p["line"], text)
    print(f"{len(pages)} -> {len(out)} pages; violations: {bad}")
    if bad:
        raise SystemExit("sentence-boundary violations found — inspect SPAN! lines")
    for p in out:
        del p["line"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", required=True)
    ap.add_argument("--script", required=True)
    ap.add_argument("--out-pages", required=True)
    ap.add_argument("--out-ts", help="optional TypeScript module path")
    ap.add_argument("--export-name", default="CAPTION_PAGES")
    a = ap.parse_args()

    pages = json.load(open(a.pages))
    script_lines = open(a.script).read().splitlines()
    final = repage(pages, script_lines)
    json.dump(final, open(a.out_pages, "w"), ensure_ascii=False, indent=1)
    print(f"wrote {a.out_pages}")

    if a.out_ts:
        ts = (
            "export interface CaptionWord { w: string; s: number; e: number }\n"
            "export interface CaptionPage { start: number; end: number; words: CaptionWord[] }\n"
            f"export const {a.export_name}: CaptionPage[] = "
            + json.dumps(final, ensure_ascii=False, separators=(",", ":"))
            + ";\n"
        )
        open(a.out_ts, "w").write(ts)
        print(f"wrote {a.out_ts} ({len(final)} pages)")


if __name__ == "__main__":
    main()
