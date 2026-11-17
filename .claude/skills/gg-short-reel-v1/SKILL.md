---
name: gg-short-reel-v1
description: ใช้เมื่อ AIOS สั่งขั้น edit_short ของงาน G&G Short Reel (request.json kind=edit_short, aspect 9:16, ผลลัพธ์ *_40_Short_Final.mp4) — รันสคริปต์เดียวที่ตัดต่อคลิป AI + ข้อความบนจอ + เสียงเพลงที่ขั้น music ของ AIOS สร้างไว้ แล้วเขียน result.json เอง
---

# gg-short-reel-v1

ขั้น `edit_short` ของงาน G&G Short Reel (Instagram Reel 9:16) ทำด้วยสคริปต์ที่ทำงานแบบ deterministic ตัวเดียว
สคริปต์อ่าน `request.json` ของ AIOS, ต่อคลิปที่ขั้น `ai_clip` สร้างไว้, ใส่ข้อความบนจอ, ผสมเพลงพื้นหลัง (ไฟล์เพลงจากขั้น `music` ของ AIOS), ตรวจความดัง/ความยาว
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
  - **exit 2** (อ่าน request/envelope ไม่ได้) และ **exit 3** (เขียน receipt ไม่สำเร็จ — รวมกรณีรอ `.result.lock` ของ run dir ไม่ได้: สคริปต์รอสูงสุด 30 วินาที (ไม่เกินเวลาที่เหลือของงาน ขั้นต่ำ 1 วินาที) แล้วเลิกโดยไม่รอซ้ำ และลบ final ของตัวเองที่เพิ่งสร้าง) = สคริปต์อาจไม่มี `result.json` เลย → ดู "ถ้าไม่มี result.json" ด้านล่าง
  - **exit 4** = `result.json` มี receipt สถานะสิ้นสุด (succeeded/failed) ของ correlation เดียวกันอยู่แล้ว สคริปต์ไม่เขียนทับและไม่แตะไฟล์ใดเลย (รวมไฟล์ final ที่ receipt `succeeded` ชี้อยู่ — แม้ receipt นั้นโผล่ขึ้นระหว่างที่สคริปต์กำลังรัน การเขียน receipt ใช้ no-clobber link จึงไม่มีช่วงให้เขียนทับ)
    → **หยุด** รายงานตาม receipt ที่มีอยู่ ห้ามรันซ้ำ ห้ามแก้ไฟล์
- ใช้ ffmpeg/ffprobe ที่ `/opt/homebrew/bin` ฟอนต์ Kanit-Bold หาจาก `GG_SHORT_FONT` → `remotion-composer/public/fonts/` ของ repo → checkout หลัก

## สิ่งที่สคริปต์ทำ (อ่านเพื่อเข้าใจผล ไม่ต้องทำเอง)

1. ตรวจ request: `schema 1`, `kind edit_short`, `aspect 9:16`, output เดียวที่ลงท้าย `_40_Short_Final.mp4`
2. หา input ตามชื่อไฟล์ ไม่ใช่ตามลำดับ: `manifest.json` ใน `*_20_Clips`, `*_00_Script.txt` และเพลง `*_30_Music.mp3` ใน input role `music`; ตรวจ `run_id` ของ manifest, seq 1..N ต่อเนื่อง, ไฟล์คลิปอยู่ในโฟลเดอร์งานและอยู่ใน input, และ `originality.json` ที่ผ่านด่านกันลอกตรงกับ hash ของสคริปต์
3. ต่อคลิป (ใช้ video stream แรกเท่านั้น, ทิ้งเสียงต้นทาง, ช็อตต่อทิ้งเฟรมแรก) เป็น 1080×1920, 30 fps คงที่, H.264
4. ใส่ข้อความ `on_screen_text` ด้วยฟอนต์ Kanit-Bold ใน safe zone ของ Instagram (x 90–990, y 210–1600) — ตัดอักขระที่ฟอนต์ไม่มีกลิฟ (อีโมจิ/สัญลักษณ์) ออกก่อน ไม่วาดเป็นกล่องว่าง; รายการที่เหลือว่างจะถูกตัดทิ้ง และ stderr บอก `on_screen_text[i]` ที่ลบ (ไม่เปลี่ยน receipt)
5. อ่านเพลงจาก input role `music` (ขั้น `music` ของ AIOS สร้างและจ่ายเงินไปแล้ว — สคริปต์ไม่เรียกเครือข่ายและไม่เรียก API ที่เสียเงิน)
   ไฟล์ต้องอยู่ในโฟลเดอร์งาน, อยู่ใน `files` ของ input, ไม่ว่าง, มี audio stream และ **ยาวไม่น้อยกว่าวิดีโอ** (สั้นกว่า = ล้มเหลว ไม่ลูปเพลง)
   ตัดเพลงให้ยาวเท่าวิดีโอ, fade-in 0.1 วินาที, fade-out 1.2 วินาที, ปรับความดัง −14 LUFS (เป้า true peak −2 dBTP) แล้วตรวจไฟล์สุดท้ายซ้ำจริง (เกณฑ์: −14±1 LUFS, TP ≤ −1 dBTP)
   (เพลงที่ peak สูงจนปรับด้วย gain เฉยๆ ไม่ถึงเป้า สคริปต์ใช้ gain + peak limiter แทน)
   หลัง mux สคริปต์วัดไฟล์จริงซ้ำ: ถ้าความดังถูกแต่ true peak ใกล้เกณฑ์เกิน (> −1.2 dBTP เพราะ AAC encode ดัน peak ขึ้น) จะสร้างเพลงใหม่ด้วย peak target ที่ต่ำลงแล้ว mux ซ้ำ (สูงสุด 4 รอบ) — ด่านตรวจสุดท้ายยังเป็นเกณฑ์เดิม
6. ตรวจความยาว 10–90 วินาที, ไม่เขียนทับไฟล์เดิม (เขียน `.partial.mp4` แล้วค่อยย้ายเข้าที่)
7. ล้มเหลว → ลบไฟล์ครึ่งๆ กลางๆ, เขียน `<final>.FAILED.json` และ receipt `status: failed` พร้อม `retry_safe`

## ถ้าไม่มี result.json (exit 2 หรือ 3)

สคริปต์เขียน receipt ไม่ได้ในสองกรณีนี้ (envelope พัง / disk เขียนไม่ได้ / มีโพรเซสอื่นถือ `.result.lock` ค้าง) ถ้าไม่มี `result.json` AIOS จะรอจนหมดเวลา — ให้ agent เขียน receipt ล้มเหลวเอง **ครั้งเดียว** ตาม runtime instruction ในข้อความสั่งงาน:

1. ตรวจก่อนว่า `result.json` ยัง **ไม่มี** (`[ -e <result_path> ]`) — ถ้ามีอยู่แล้ว (ไม่ว่าสถานะอะไร) **ห้ามเขียนอะไรทั้งสิ้น** ให้รายงานตามที่มี
2. อ่าน `request.json` แล้วคัดลอก `schema`, `task_id`, `step_id`, `run_id`, `dispatch_id`, `target` **ตรงตัวอักษร** (ห้ามเดา/สร้าง ID — ถ้า request.json อ่านไม่ได้จนคัดลอกไม่ได้ ให้รายงานแล้วหยุด)
3. เขียน JSON นี้ไปที่ `result_path` (ต้องอยู่โฟลเดอร์เดียวกับ `request.json`; ถ้าไม่ใช่ ให้รายงานแล้วหยุด):
   `{ <correlation 6 ฟิลด์>, "status": "failed", "error": "<เหตุผลเฉพาะเจาะจง: exit code + บรรทัด stderr ของสคริปต์>", "retry_safe": true, "outputs": [] }`
   — `retry_safe` เป็น `true` เสมอเพราะสกิลนี้ไม่ทำงานที่เสียเงิน
4. เขียนด้วย temp file ในโฟลเดอร์เดียวกันแล้ว link เข้าที่แบบไม่ทับ: `ln <tmp> <result_path> && rm <tmp>` — ถ้า `ln` ล้มเพราะ `result_path` มีอยู่แล้ว **ห้ามเขียนทับเด็ดขาด** ให้ลบ tmp (`rm <tmp>`) แล้วรายงานตามที่มี (ห้ามใช้ `mv`/`cp`/`>` ลงบน `result.json`) — ห้ามเขียนตรงลง `result.json`
5. ห้ามทำอย่างอื่นเพิ่ม (ไม่รันสคริปต์ซ้ำ ไม่สร้างไฟล์ final)

## ข้อห้าม

- **ห้ามเขียนหรือแก้ `result.json` เอง** — สคริปต์เป็นเจ้าของไฟล์นี้ (เขียนแบบ atomic พร้อม correlation ครบ)
  ข้อยกเว้นเดียว: สคริปต์จบด้วย exit 2 หรือ 3 **และ** ไม่มี `result.json` เลย — ดูหัวข้อ "ถ้าไม่มี result.json" ด้านบน
- **ห้ามตัดต่อ/แก้วิดีโอด้วยมือ** ห้าม ffmpeg เพิ่มเอง ห้ามสร้างหรือ copy ไฟล์ `*_40_Short_Final.mp4` ด้วยวิธีอื่น
- **ห้ามหา/สร้าง/แทนเพลงเอง**: เพลงมาจาก input role `music` (ขั้น `music` ของ AIOS) เท่านั้น — ห้ามใช้ stock/Pixabay/ไฟล์เพลงที่หามาเอง/
  เครื่องมือสร้างเพลงใน repo/ดาวน์โหลดจากเครือข่าย และห้ามลูปหรือต่อเพลงให้ยาวขึ้น ถ้า receipt บอกว่าเพลงไม่มี (`ต้องมี input role music`,
  `ไม่พบไฟล์ *_30_Music.mp3`, ไฟล์ว่าง, ไม่มี audio) หรือสั้นกว่าวิดีโอ (`เพลงสั้นกว่าวิดีโอ (X วิ < Y วิ)`) ให้ **รายงานตามข้อความนั้นแล้วหยุด** —
  ห้ามพยายามแก้เอง (ต้องรันขั้น `music` ของ AIOS ใหม่) ความล้มเหลวพวกนี้ `retry_safe: true` เพราะสคริปต์ไม่เสียเงินเลย
- **ข้อความบนวิดีโอต้องเป็นภาษาอังกฤษ (อักษรละติน) เท่านั้น**: ถ้า `on_screen_text[i].text` มีอักษรที่ไม่ใช่ละติน (เช่น ไทย ญี่ปุ่น ซีริลลิก) สคริปต์จะล้มที่ขั้น `script` ก่อนตัดต่อ/ทำเพลงใดๆ — receipt `failed`, `retry_safe: true`
  ข้อความ `ต้องเป็นภาษาอังกฤษเท่านั้น (พบอักษรที่ไม่ใช่ละติน "...")` → **รายงานตามข้อความนั้นแล้วหยุด** ห้ามแปลหรือแก้สคริปต์/`on_screen_text` เอง (ต้องให้ขั้น script ของ AIOS สร้างใหม่)
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
เทสต์สร้างไฟล์เพลง mp3 จำลองในโฟลเดอร์ขั้น `music` (CLI ใช้ `FileMusicProvider` อ่านจาก input เสมอ); บางเทสต์ส่ง provider ปลอมผ่านพารามิเตอร์ Python (`run(request_path, music_provider=...)`) ไม่มี CLI flag สำหรับใส่ไฟล์เพลง และมีเทสต์ยืนยันว่ารันทั้งงานได้โดยไม่เปิด socket
