---
name: gg-short-reel-v1
description: ใช้เมื่อ AIOS สั่งขั้น edit_short ของงาน G&G Short Reel (request.json kind=edit_short, aspect 9:16, ผลลัพธ์ *_40_Short_Final.mp4) — รันสคริปต์เดียวที่ตัดต่อคลิป AI + ข้อความบนจอ + เสียงเพลง แล้วเขียน result.json เอง
---

# gg-short-reel-v1

ขั้น `edit_short` ของงาน G&G Short Reel (Instagram Reel 9:16) ทำด้วยสคริปต์ที่ทำงานแบบ deterministic ตัวเดียว
สคริปต์อ่าน `request.json` ของ AIOS, ต่อคลิปที่ขั้น `ai_clip` สร้างไว้, ใส่ข้อความบนจอ, ผสมเพลงพื้นหลัง, ตรวจความดัง/ความยาว
แล้ว **เขียน `result.json` (receipt) เองทุกกรณี** ทั้งสำเร็จและล้มเหลว

## คำสั่งเดียวที่ต้องรัน

รันจากราก repo (โฟลเดอร์ที่มี `.claude/skills/gg-short-reel-v1/`):

```bash
SKILL="$PWD/.claude/skills/gg-short-reel-v1"
PY="$PWD/.venv/bin/python"; [ -x "$PY" ] || PY=/Volumes/Ext_SS990Pro/Dev/openMontage-video-production/.venv/bin/python
"$PY" "$SKILL/scripts/gg_short_reel.py" --request <absolute path ของ request.json>
```

- path ของ `request.json` อยู่ในข้อความสั่งงาน (`AIOS runtime request: ...`) — ต้องเป็น absolute path
- `--timeout-s N` (ไม่ใส่ = 900) คือเวลารวมของทั้งงาน หมดเวลา = receipt ล้มเหลว
- exit code 0 = สำเร็จ, ไม่ใช่ 0 = ล้มเหลว (เหตุผลอยู่ใน `result.json` และ stderr)
- ใช้ ffmpeg/ffprobe ที่ `/opt/homebrew/bin` ฟอนต์ Kanit-Bold หาจาก `GG_SHORT_FONT` → `remotion-composer/public/fonts/` ของ repo → checkout หลัก

## สิ่งที่สคริปต์ทำ (อ่านเพื่อเข้าใจผล ไม่ต้องทำเอง)

1. ตรวจ request: `schema 1`, `kind edit_short`, `aspect 9:16`, output เดียวที่ลงท้าย `_40_Short_Final.mp4`
2. หา input ตามชื่อไฟล์ ไม่ใช่ตามลำดับ: `manifest.json` ใน `*_20_Clips` และ `*_00_Script.txt`; ตรวจ `run_id` ของ manifest, seq 1..N ต่อเนื่อง, ไฟล์คลิปอยู่ในโฟลเดอร์งานและอยู่ใน input, และ `originality.json` ที่ผ่านด่านกันลอกตรงกับ hash ของสคริปต์
3. ต่อคลิป (ใช้ video stream แรกเท่านั้น, ทิ้งเสียงต้นทาง, ช็อตต่อทิ้งเฟรมแรก) เป็น 1080×1920, 30 fps คงที่, H.264
4. ใส่ข้อความ `on_screen_text` ด้วยฟอนต์ Kanit-Bold ใน safe zone ของ Instagram (x 90–990, y 210–1600)
5. ขอเพลงจาก music provider แล้วปรับความดัง −14 LUFS (TP ≤ −1) ตรวจไฟล์สุดท้ายซ้ำจริง
6. ตรวจความยาว 10–90 วินาที, ไม่เขียนทับไฟล์เดิม (เขียน `.partial.mp4` แล้วค่อยย้ายเข้าที่)
7. ล้มเหลว → ลบไฟล์ครึ่งๆ กลางๆ, เขียน `<final>.FAILED.json` และ receipt `status: failed` พร้อม `retry_safe`

## ข้อห้าม

- **ห้ามเขียนหรือแก้ `result.json` เอง** — สคริปต์เป็นเจ้าของไฟล์นี้ (เขียนแบบ atomic พร้อม correlation ครบ)
- **ห้ามตัดต่อ/แก้วิดีโอด้วยมือ** ห้าม ffmpeg เพิ่มเอง ห้ามสร้างหรือ copy ไฟล์ `*_40_Short_Final.mp4` ด้วยวิธีอื่น
- **ห้ามหาเพลงมาแทน**: ห้ามใช้ stock/Pixabay/ไฟล์เพลงที่หามาเอง/เครื่องมือเพลงอื่นใน repo — ตัวสร้างเพลง AI ยังไม่ได้ติดตั้ง (CF-A85) ตอนนี้สคริปต์จึงล้มเหลวด้วยข้อความ
  `ยังไม่ได้ตั้งตัวสร้างเพลง AI (CF-A85 รอแผนเพลง)` — นี่คือผลที่ถูกต้อง ให้รายงานตามนั้น
- **ห้าม retry งานที่เสียเงิน** และห้ามรันซ้ำวนเพื่อ "ให้ผ่าน" — รันสคริปต์ครั้งเดียว ถ้า receipt เป็น failed ให้หยุดแล้วรายงาน
  (ค่า `retry_safe` ใน receipt เป็นของสคริปต์ ห้ามแก้)
- ห้ามแก้สคริปต์/สกิลนี้ระหว่างงาน, ห้ามเขียนไฟล์นอกโฟลเดอร์ run ของงาน

## รายงานกลับ

หลังรันเสร็จให้ตอบสั้นๆ ตามนี้ (อ่านจาก `result.json`, ไม่ต้องเดา):

- `status` (succeeded / failed) และ exit code
- ถ้าสำเร็จ: path ของ `*_40_Short_Final.mp4`, ความยาว, ความดังที่วัดได้ (ถ้าต้องการให้รัน `ffprobe` ดูได้ แต่ห้ามแก้ไฟล์)
- ถ้าล้มเหลว: ข้อความ `error` ตามตัวอักษร, ขั้นที่ล้ม (ดู `<final>.FAILED.json` → `stage`), และ `retry_safe`
- ไม่ต้องเขียนสรุปว่า "คุณภาพดี" — การ QC เป็นขั้นอื่น

## ทดสอบสกิล

```bash
cd <ราก repo> && "$PY" -m unittest discover -s .claude/skills/gg-short-reel-v1/scripts/tests -v
```

ต้องมี ffmpeg/ffprobe (ไม่มี = เทสต์ที่ใช้ ffmpeg ถูกข้าม) การทดสอบสร้างคลิปจำลองด้วย ffmpeg lavfi ไม่เรียกเครือข่ายหรือ API ที่เสียเงิน
ตัว music provider จริงยังไม่มี: เทสต์ใช้ provider ปลอมที่ส่งผ่านพารามิเตอร์ Python (`run(request_path, music_provider=...)`) เท่านั้น ไม่มี CLI flag สำหรับใส่ไฟล์เพลง
