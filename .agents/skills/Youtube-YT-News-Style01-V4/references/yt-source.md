# YouTube-source recon & clip cutting (ขั้นที่แทน web-capture)

format นี้เรื่องที่รายงานคือ **วิดีโอ YouTube** ภาพฝั่งซ้ายมาจาก clip ที่ตัดจากวิดีโอนั้น ส่วนที่เหลือ (avatar morph, geometry, captions, การ์ดข้อความ, mux) ดู `format-spec.md` และ `v4-contract.md` หลักคิดของขั้นนี้: **หาให้เจอว่าต้นฉบับ "แสดง" สิ่งที่บรรทัดนั้น "พูด" ตรงไหน แล้วตัดให้ภาพนั้นอยู่บนจอตลอด beat** ไม่ใช่ตัดตามชื่อ chapter

ทุกคำสั่งในไฟล์นี้อยู่ใต้ `SKILL=.claude/skills/Youtube-YT-News-Style01-V4`, `P=projects/<slug>` และรันจาก root ของ worktree

## 1. Download + chapters + transcript

```bash
bash "$SKILL/scripts/yt_survey.sh" "<YOUTUBE_URL>" $P/assets/ytsource
# ถ้าไฟล์ source.mp4 อยู่แล้วแต่คำสั่งถูกตัด/ขาด sheet: สร้าง dense sheets ใหม่ได้โดยไม่ต่อเน็ต
bash "$SKILL/scripts/yt_survey.sh" --frames-only $P/assets/ytsource/source.mp4 $P/assets/ytsource
```

ผลลัพธ์ใน `$P/assets/ytsource/`: `source.mp4`, `chapters.txt`, `survey/sheetA.jpg` + `sheetB.jpg` (ภาพรวม), `survey/dense/sheet_<start>-<end>.jpg` + `survey/dense/index.json` (ทั้งวิดีโอ: 1 tile ต่อ 10 วินาที, 6×5 tile = 5 นาทีต่อ sheet, tile i = `start + 10*i`, เรียงซ้าย→ขวา บน→ล่าง) และ `transcript_timed.json` `[{start,end,text}]` เมื่อดึง auto-subtitle ได้

- **Chapters** = แผนที่หัวข้อ (ชื่อ + เวลาเริ่ม) ช่วยบอกว่าควรดูตรงไหนก่อน ไม่ใช่หลักฐานว่าภาพอะไรอยู่บนจอ
- **Timed transcript** = หลักฐานว่าต้นฉบับ "พูด/แสดง" อะไรเมื่อไร ถ้า `yt_survey.sh` พิมพ์ WARNING ว่าไม่มี transcript (429/ไม่มี subtitle) ให้สร้างเองแบบ local offline — ห้ามข้าม เพราะ `lint_content.py` ใช้ตรวจว่าช่วงที่ตัดมีหัวข้อที่ป้ายอ้าง:

```bash
# ไม่มี transcript_timed.json: สร้างแบบ local offline เป็นหน้าต่างละไม่เกิน 300 s (คำสั่งเดียวต้องจบ < 8 นาที) แล้วรวม
# เรียกซ้ำด้วยอาร์กิวเมนต์เดิมได้ (พิมพ์ "already done")
python3 "$SKILL/scripts/source_timed.py" from-audio $P/assets/ytsource/source.mp4 --out $P/assets/ytsource/part_0000.json --start 0 --duration 300
#   ... --start 300 --out part_0300.json ... จนครบความยาววิดีโอ แล้ว:
python3 "$SKILL/scripts/source_timed.py" merge $P/assets/ytsource/part_*.json --out $P/assets/ytsource/transcript_timed.json
# ทุกกรณี: transcript ข้อความล้วนสำหรับตรวจที่มาของตัวเลข (ผลจากไฟล์ ไม่ใช่พิมพ์มือ)
python3 -c "import json,sys;print('\n'.join(r['text'] for r in json.load(open(sys.argv[1]))))" $P/assets/ytsource/transcript_timed.json > $P/assets/ytsource/transcript.txt
```

exit 4 = ไม่มี model/venv (ไม่ดาวน์โหลดให้) → ขั้นล้ม รายงานเหตุผล

## 2. Look before you cut (ต้องเปิดภาพดูด้วยเครื่องมือ Read ทุกครั้ง)

1. เปิด `survey/sheetA.jpg` + `sheetB.jpg` เพื่อภาพรวม: diagram / หน้าจอ UI / ฉากสาธิต / การ์ดสถิติอยู่ตรงไหน
2. เปิด **ทุกไฟล์** ใน `survey/dense/sheet_*.jpg` (ดู `index.json` เพื่อแปลง tile → เวลา) แล้วจดลง `$P/artifacts/survey_notes.md` **หนึ่งบรรทัดต่อ chapter**: `<เวลาเริ่ม-จบ> | <สิ่งที่เห็นจริงบนจอ ณ เวลานั้น> | <ใช้กับบรรทัด script ไหนได้/ไม่ได้>` บันทึกเฉพาะสิ่งที่เห็นในภาพ ห้ามเขียนจากชื่อ chapter หรือชื่อไฟล์ ถ้ามีหน้าจอที่อ่านไม่ออกใน tile ให้ดึงเฟรมเดี่ยว `ffmpeg -ss T -i source.mp4 -frames:v 1 f.jpg` แล้วเปิดดู
3. จับคู่ transcript กับ sheet: ช่วงที่ต้นฉบับพูดถึงสิ่งนั้น (transcript) กับช่วงที่สิ่งนั้นอยู่บนจอ (sheet) มักเหลื่อมกัน ให้ยึด "บนจอ"
4. ก่อนสรุปช่วงตัด ดูช่วงนั้นทั้งช่วง: `ffmpeg -ss A -to B -i source.mp4 -vf "fps=1/2,scale=480:270,tile=5x2" -frames:v 1 $P/qc/arcs/arc_A_B.jpg` — เฟรมเดียวกลาง chapter โกหกได้ (title card / file dialog / กราฟคะแนนมักอยู่ 2–3 วินาทีแรกของช่วงที่ดูสมบูรณ์)
5. ข้ามตอนที่เป็นสปอนเซอร์/โค้ดโปรโมชัน/end card ของต้นฉบับเสมอ

ช่วงตัดเป็นอันสิ้นสุดเมื่อผ่านครบ 4 ข้อ

## 3. Cut + `from`

```bash
bash "$SKILL/scripts/cut_clips.sh" $P/assets/ytsource/source.mp4 $P/assets/ytsource/clips \
  yt_prompt_demo:312:327 yt_code_editor:401:419 ...          # name:start:end (วินาทีในวิดีโอต้นฉบับ)
cp $P/assets/ytsource/clips/_cuts.json $P/artifacts/_cuts.json   # ทำทุกครั้งหลังตัด (merge ของเดิมให้เอง)
mkdir -p remotion-composer/public/<assetDir>/broll && cp $P/assets/ytsource/clips/yt_*.mp4 remotion-composer/public/<assetDir>/broll/
```

- ตั้งชื่อ `yt_<topic>` (ต้องตรงกับ `^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$`) ไม่ชนกับ stock
- **`from`** ใน `episode.json` = วินาทีที่เริ่มเล่น **ภายในไฟล์ที่ตัดแล้ว** (ไม่ใช่เวลาในวิดีโอต้นฉบับ; เวลาต้นฉบับอยู่ใน `_cuts.json`: `source_in` + `from` = เวลาที่เห็นจริง) ไม่ใส่ = เล่นตั้งแต่เฟรมแรก ซึ่งพลาดสิ่งที่ป้ายอ้างถึงได้ง่าย ถ้าภาพที่ต้องการเริ่มที่วินาทีที่ 9 ของ clip ให้ตั้ง `from:9` หรือ (ดีกว่า) ตัดใหม่ให้เริ่มที่นั่น เว้นช่วงนำ 0.5–1 วินาทีเผื่อ transition
- ตัดให้ "สิ่งที่ป้ายพูดถึง" อยู่บนจอ**ตลอด beat** ไม่ใช่แค่เฟรมแรก: จำนวนวินาทีที่แสดงต้อง ≤ `brollDur[src] − from − ~0.1 s` เพราะ source beat เล่นวนไม่ได้ (`source-loop` = error) beat ยาว 12 s ต้องมี clip ≥ 12.1 s หลัง `from`
- `brollDur[src]` ใน `episode.json` = ความยาวจริงของไฟล์ใน **public** (`ffprobe`) ไม่ใช่ตัวเลขที่ `cut_clips.sh` พิมพ์จากความตั้งใจ และไฟล์ใน `public/<assetDir>/broll/` ต้องเป็นไฟล์เดียวกับใน `assets/ytsource/clips/` (`cmp`)
- ใช้ source clip แต่ละช่วงครั้งเดียว: ช่วงเวลาเดียวกันภายใต้สองชื่อยังนับเป็นการซ้ำ (`source-reuse`, `shot-reuse`)

## 4. จับคู่บรรทัด script → ช่วงต้นฉบับ

สร้างแผนจาก `artifacts/line_starts.json` (เวลาพูดของแต่ละบรรทัด) + `survey_notes.md` + transcript:

| บรรทัดที่พูดถึง | ภาพ |
|---|---|
| Cold open / ประโยคเปิดที่อ้างผลลัพธ์ | ฉากสาธิต/ผลลัพธ์ของต้นฉบับ (`media:"clip"`, `layout:"stage"`) |
| "ตัวที่ N คือ…" แนะนำเครื่องมือ | หน้าจอ UI ของเครื่องมือนั้น (`clip` stage, หรือ `wide` เมื่อรายละเอียดบนจอสำคัญ) |
| ขั้นตอน/การตรวจสอบ | หน้าจอ dashboard / โค้ด / ผลตัดสิน (`clip`) |
| ประโยคทั่วไปที่ต้นฉบับไม่มีภาพให้ | **การ์ดข้อความจาก script** (`media:"typo"`) ไม่ใช่ stock |
| สรุป | การ์ด `summary3`/`final4` จาก script หรือการ์ดสถิติของต้นฉบับถ้าถูกพูดถึง |

- ข้อความบน beat (`headline`/`sub`/`stats`/การ์ด) ต้องมาจากสิ่งที่พูดใน script หรือแสดงในต้นฉบับ ตัวเลข/ลำดับ (รอบที่ 1, 8/10 ฯลฯ) ที่ไม่มีทั้งสองที่ห้ามใส่ (`provenance-number`, `provenance-ordinal`)
- ตัวเลขที่ปรากฏในต้นฉบับแต่ไม่ถูกพูดใน VO แสดงได้เมื่อมี headline/sub ภาษาไทยอธิบาย และเห็นตัวเลขนั้นจริงใน clip ช่วงนั้น
- ป้ายเวลา (`stats[].at`, `cards[].at`, `items[].at`, `lower.at`) ใช้เวลาที่พูดจาก `cue_times.py` เสมอ
- ต้องสลับ media สม่ำเสมอ ~7 beat ต่อนาที beat ละ ~3–10 วินาที; presenter-only รวม ≤ 25 % ของ VO, ช่วงต่อเนื่อง ≤ 12 s ที่เหลือเติมด้วย source หรือการ์ด
- Source beat แสดง `SOURCE · <ช่อง>` ผ่าน `officialTag` ของ episode (เครดิตอยู่ใน chrome ของจอ และ `endcard`)

## 5. `srcCrop` (เมื่อภาพสำคัญเป็นแค่ส่วนหนึ่งของเฟรมต้นฉบับ)

`srcCrop {x,y,w,h}` เป็นพิกเซลบนเฟรม 1920×1080 ของต้นฉบับ สัดส่วน ≈16:9 (คลาดเกิน 25 % = error, เกิน 10 % = warning) ไม่ใส่ = ใส่ทั้งเฟรม; ใส่แล้วภาพถูก cover ลงกรอบ และ punch ซูมต่อจากการ crop

```bash
python3 "$SKILL/scripts/frame_checks.py" crop-propose --video remotion-composer/public/<assetDir>/broll/<src>.mp4 --in <A> --out <B> --report $P/qc/crop_<src>.json
python3 "$SKILL/scripts/frame_checks.py" crop-check   --video <เดิม> --in <A> --out <B> --crop x:y:w:h --report $P/qc/cropcheck_<src>.json
```

`crop-propose` เป็นข้อเสนอเท่านั้น: **เปิดเฟรมที่ crop แล้วดู** ว่าสิ่งที่ป้ายอ้างถึงอยู่ครบ ไม่ถูกตัดขอบ และไม่ติดแถบดำ/watermark `--in/--out` = วินาทีภายในไฟล์ clip ช่วงที่แสดงจริง

## 6. หลักฐานภาพ (`artifacts/visual_evidence.json`)

หลังเขียน `episode.json` ให้ดึงเฟรมจากช่วงที่ "แสดงจริง" ของทุก source cutaway แล้วเปิดดูทีละภาพ (`frame_checks.py cutaways` เขียน jpg ชื่อ `b<idx>_<src>_<ms>.jpg` ใน `--frames-dir`) แล้วเขียนหนึ่ง entry ต่อ source beat: `{ "t": <beat.t>, "src": "yt_...", "cue_line": <เลขบรรทัด script ที่พูดตอนนั้น>, "subject_terms": ["<คำภาษาอังกฤษตามที่ปรากฏในเสียง/บนจอของต้นฉบับ>"], "seen": "<สิ่งที่เห็นจริงในเฟรม>" }` `lint_content.py` ตรวจว่า `cue_line` ทับ beat นั้น และ `subject_terms` ครบทุกคำอยู่ในช่วงที่แสดง (transcript ±3 s / OCR เฟรม / chapter) ถ้าสิ่งที่เห็นไม่ใช่สิ่งที่บรรทัดนั้นพูดถึง ให้แก้ **การตัด** (`from`, ช่วงตัด, clip อื่น, หรือเปลี่ยนเป็นการ์ด) ไม่ใช่แก้หลักฐาน

## 7. สิ่งที่ใช้ร่วมกับ format web-news

การ์ดข้อความ (`summary3` / `vs` / `final4` / `card`), CTA, endcard, karaoke captions, music bed, และลูป render/mux QA เหมือน format web-news — ทำตาม `SKILL.md`
