# Production B-roll freshness (inherited V2 gate)

ทุก `src` ของ beat `broll`/`clip` ปรากฏได้ไม่เกินหนึ่ง beat (ยกเว้น source clip เดียวกันที่ช่วง `[from, from+shown)` ไม่ซ้อนกัน — กฎ S10 ของ engine) Source clips ใช้ prefix `yt_` และต้องตัดจากวิดีโอต้นฉบับของตอนนี้ (`cut_clips.sh` เขียน `_cuts.json`) (กฎ stock ด้านล่างสืบทอดจาก V2: stock fresh = ดาวน์โหลดสำหรับตอนนี้ด้วย `fetch_broll` พร้อม manifest/raw hash ที่ตรง และไม่ซ้ำเนื้อหากับตอนอื่น; stock เก่าที่อนุมัติแล้วไม่เกินสองไฟล์; การเปลี่ยนชื่อไฟล์ไม่ทำให้ของเก่าเป็นของใหม่ — แต่ **ใน V4 `fetch_broll.py` มีแค่โหมด `--music` โหมด footage ทุกแบบ exit 3** จึงไม่มี stock ใหม่ให้เข้า manifest และ footage ที่ไม่ใช่ source ล้ม `stock-not-allowed` เสมอ)

ใช้ slug และ `assetDir` ใหม่ทุกตอน ห้าม copy คลัง B-roll ของตอนอื่นมาใช้จริง เลือก query จากบรรทัดที่พูดในตอนนี้ และ source UI มาก่อน ความตรงของภาพกับคำพูด (semantic/vision) เป็นขั้นแยก ความไม่ซ้ำไม่ได้พิสูจน์ความตรง

**โหมดไม่มีคนดู (V4):** ห้าม stock/AI footage ทุกกรณี (`stock-not-allowed` ใน `lint_content.py`; `relevance.json` ไม่ใช่หลักฐานและ verdict ไม่ทำให้ผ่าน — ดู `v5-contract.md` ส่วน "Unattended policy") ตอนนั้นไม่มี stock และ `check_broll.py` มีหน้าที่แค่ยืนยันว่า source clip ไม่ซ้ำ/ไม่ปลอมชื่อ ห้ามรัน `fetch_broll.py` เพื่อ "หาของมาเติม" (ใช้ได้เฉพาะ `--music` ขั้น 9 ของ SKILL.md)

ledger ความไม่ซ้ำนี้คุม **footage** เท่านั้น เพลงประกอบ (`fetch_broll.py --music`) อยู่นอกขอบเขต: bed ซ้ำข้ามตอนได้ เพราะเจ้าของเลือกเพลงช่องไว้ใน `scripts/music_library.json` (ไฟล์ใน `music_library/`) และคำสั่งใช้คลังนี้ก่อนและที่เดียวเมื่อรายการมีเพลง (ไม่ติดต่อ Pixabay) — สิ่งที่ห้ามคือ agent copy bed เอง (จากงานอื่นหรือจากคลัง) ไม่ใช่การที่ bed มาจากคลัง ตอนส่งมอบ finalize (ภายใน record `mux`) ผ่านเฉพาะ bed ที่ sidecar เป็น `music_library` และ sha256 อยู่ในรายการที่ล็อกไว้ โดยไฟล์ต้องอยู่ใต้ `$P/assets/audio/`

ใน V4 beats อยู่ใน `artifacts/episode.json` (field `beats`; ตาราง `brollDur` อยู่ในไฟล์เดียวกัน) ไม่ใช่ `BEATS` ใน TSX

Production command (รันเมื่อได้รับอนุญาตให้เขียน ledger เท่านั้น; `episode.json` เป็น positional แรก — ส่ง `.tsx` = exit 2; `--media-dir`, `--manifest` และ `--cuts` บังคับ; exit 0 = ผ่าน, 1 = พบการซ้ำ/ผิดกฎ, 2 = อินพุตผิด):

```bash
$PY "$SKILL/scripts/check_broll.py projects/<slug>/artifacts/episode.json \
  --media-dir <assetDir> --manifest projects/<slug>/assets/broll/_manifest.json \
  --cuts projects/<slug>/artifacts/_cuts.json --public-root remotion-composer/public \
  --projects-root projects --ledger projects/_broll_ledger.json
```

`--manifest` คือ `_manifest.json` ที่ writer (`fetch_broll.py` / `transcode_broll.sh`) เขียน ห้ามเขียนมือ ใน V4 ไม่มี stock จึงไม่มีไฟล์นี้ ให้ข้าม `check_broll.py` แล้วจดในรายงานขั้นตอนว่า "ไม่มี stock" (source clip ถูกคุมซ้ำโดย `lint_content.py` `source-reuse` และ `frame_checks.py` `shot-reuse` อยู่แล้ว) `--usage-report <file>` เป็นตัวเลือก (รายงาน identity ใต้ผิว) `--max-old 0..2` จำกัดจำนวน stock เก่า (ค่าเริ่ม 2)

(เฉพาะ ledger/โปรเจกต์เก่าที่มี stock — V4 ไม่มี) เมื่อได้รับอนุญาตให้เขียน ledger และมี stock: บันทึกการใช้ด้วย `broll_ledger.py record <assetDir> --episode projects/<slug>/artifacts/episode.json [--manifest ...]` (ใช้ `--episode`; `--composition` เป็น error ใน V4) และ coverage/cache ของ `broll_plan.py`/`batch_relevance.py`/`score_relevance.py` ผูกกับ `episode_sha256` ของ `episode.json` (อ่านผ่าน `--beats <episode.json>`)

Checker seed ledger ที่เลือกเองอัตโนมัติ สำหรับ regression test ให้ใช้ ledger/project/public root แยก ห้ามชี้ test ไปที่ ledger หลัก stock เก่าจาก regression ถือว่า "เก่า" เสมอ: gate ของ engine ผ่านไม่ได้แปลว่า freshness ผ่าน ห้ามลดเพดานหรือปลอม fetch manifest เพื่ออ้างว่า fresh ห้ามเขียน ledger จริงจากโปรเจกต์ทดสอบ และห้ามเขียน ledger หลักก่อนส่งมอบได้รับอนุญาต
