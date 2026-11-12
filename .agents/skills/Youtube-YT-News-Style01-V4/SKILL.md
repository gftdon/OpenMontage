---
name: Youtube-YT-News-Style01-V4
description: Use when editing a Thai 16:9 YouTube AI/technology news episode from presenter MP4, SRT and YouTube source footage, or repairing overlapping chips, misleading source chrome, long visual holds or low loudness in the YT News format. Not for web articles or vertical Shorts.
---

# Youtube YT News Style01 V3

ใช้ pipeline เดิมที่อนุมัติแล้ว V3 เป็น engine + hard gates ไม่ใช่การรับรองสคริปต์หรือ B-roll ว่าตรงเรื่อง ห้ามแก้ V2 หรือ preset ใน production โดยพลการ

## เริ่มตอนใหม่

1. สร้าง `projects/<slug>/` และ `remotion-composer/public/<mediaDir>/` ใหม่ เก็บ artifacts ตาม pipeline ของ repo อ่าน `references/yt-source.md` ก่อนตัดต้นทาง
2. Copy `assets/YtNewsStyle01V4.reference.tsx` ไป `remotion-composer/src/<CompId>.tsx` และ `assets/ytNewsStyle01V4Captions.reference.ts` ไป helper ชื่อใหม่ เปลี่ยน export/import, `EPISODE.assetDir`, config, BEATS, caption pages, duration และ registration ใน Root ให้ครบ **ไม่ import helper ของตอนเก่า**
3. Reference ใช้ fixture ตอนเดิมเพื่อทดสอบเท่านั้น ต้องแทนข้อความ/เวลา/captions/media ของตอนใหม่ทั้งหมด Copy fonts/media เข้า public จริง อย่า symlink public
4. อ่าน `references/v3-contract.md` และ `references/broll-freshness.md` ก่อนใช้ภาพ ทุก `broll/clip/typo` ต้องมี src ชัดเจน เก็บ media enum นี้เพื่อไม่หลบ ledger parser

## สัญญาภาพและข้อความ

- 1920×1080 @25fps; safe area 5% = x96–1824, y54–1026 รวม topbar, caption, lower-third, CTA
- ข้อความอ่าน ≥28px; label/pill ≥22px ขนาดที่วัดหลัง transform ห้ามย่อจนหลุดเกณฑ์
- headline, description, stat rail, caption แยก lane ไม่วาง chip ทับหัวข้อหรือซับ
- `origin:'source'` ใช้เฉพาะ src ชื่อ `yt_...`; `origin:'stock'` ต้องไม่เป็น yt_ ป้าย SOURCE/URL/chrome มีเฉพาะ source; source เต็มจอต้องมีเครดิตที่มองเห็น
- ไม่มี dark wash คลุม footage ทั้ง stage ใช้ gradient เฉพาะใต้ข้อความ Source UI และตำแหน่ง pixel สำคัญต้องเห็นชัด Source full ต้องเป็น footage background เต็ม 1920×1080 แบบ cover ไม่ใช่ contain/letterbox; text/credit/stats อยู่ safe overlays
- ใช้ `layout:'full'` เพื่อแสดง source ในพื้นที่หลัก หรือ `layout:'stage'` คู่ avatar; `mode:'full'` คือ avatar เต็มพื้นที่
- visual hold ทุกแบบ ≤10s รวม avatar/typo และ adjacent-identical beats ห้ามซอย beat เหมือนเดิมหลอก gate Overlayทุกชนิด (lower/chip/CTA/kicker/headline/cardที่ซ้อนshotเดิม) โผล่/หาย/เปลี่ยนข้อความไม่reset hold และไม่มีminimum dwell; resetเฉพาะshot/mediaจริง, layoutจริง, approvedhardpunch หรือ primary typo cardที่เปลี่ยนเนื้อหาจริง punch อนุญาตเฉพาะ avatar/source footage ห้าม stock/typo; stock ยาวให้ตัดกลับ avatar หรือเปลี่ยนภาพจริง ส่วน typo ใช้ `cards:[{t,lines}]` ที่เนื้อหาเปลี่ยนจริง `punch:[{t,z,fx,fy}]` เป็น hard step ทันที: scale ratio เปลี่ยน ≥15% หรือ ตำแหน่ง visible viewport เปลี่ยน ≥0.15 ของกรอบ (left=fx×(1−1/z), top=fy×(1−1/z)) จึงเริ่ม hold ใหม่ Slow zoom/Ken Burns (`cam`) ไม่ใช่ cut
- ดู source contactsheet ก่อนตั้ง `captionLane:'top'|'bottom'` ราย beat หาก source full มี burned lower-third ให้ย้ายซับไป top-left lane (x116, max650, y248; wrap) ที่ไม่ชน topbar/chrome/credit/headline/chips Gate ไม่ทำ OCR และไม่รับรอง burned-in text เอง ต้องบันทึกการดู contactsheet/flag ไว้
- Full footage text ทุก field ต้องมี localized dark backing จริง (local background alpha≥.9 และกรอบครอบ ink, shared visibility ancestry) Structural presence proxy ไม่ตัด shared entrance fade เพราะ cumulative opacityต่ำ; cumulative field opacityยังคุมvisibility และ missing/invisible/uncovered backingต้องfail ค่าcontrastเป็นcalculated paletteบนbackingตอนsettled ไม่ใช่pixelmeasurement; sharedfadeกับภาพอาจลดcontrastจริง ไม่ได้อ้างว่าคงcontrastทุกtransition
- ใช้ backing เพื่อให้ cream/amber/mint contrast≥4.5:1 บนพื้นรอง; ห้าม dark wash ทั้งภาพ
- endcard ≤5s, CTA คำถามสั้นหนึ่งประโยค; reference audio/script ยังเป็น regression ไม่ใช่ editorial approval

Bounded motion คง avatar rect morph ภายใน media boxes, stage slide/fade และ spring opacity+translate 6px ของ chip/lower-third/CTA ไม่มี scale ย่อข้อความหรือ overshoot ออก lane Hard cut ใช้เฉพาะ punch-in ที่อนุญาต

## QC gates ก่อนส่งงาน (hard fail)

ให้ `SKILL=.claude/skills/Youtube-YT-News-Style01-V4` และรันจาก root worktree ของ episode

```bash
python3 "$SKILL/scripts/lint_beats.py" remotion-composer/src/<CompId>.tsx --report projects/<slug>/qc/beats.json
node "$SKILL/scripts/qc_layout.mjs" <CompId> projects/<slug>/qc/layout remotion-composer
node "$SKILL/scripts/render_episode.mjs" remotion-composer <CompId> projects/<slug>/renders/visual.mp4
bash "$SKILL/scripts/mux_av.sh" projects/<slug>/renders/visual.mp4 remotion-composer/public/<mediaDir>/avatar_source.mp4 projects/<slug>/assets/audio/bed.mp3 projects/<slug>/renders/final.mp4 <TOTAL_SEC> <VO_END_SEC>
python3 "$SKILL/scripts/measure_loudness.py" projects/<slug>/renders/final.mp4 --report projects/<slug>/qc/final-audio.json
```

Report schema v2 มี runId/timestamps/composition/source hashes/full-plan และ requested frames; subset มีเพียง diagnosticPass แต่ acceptance pass=false, complete=false เสมอ Crash จะ invalidate report เก่าและเขียน failed state; hashes รวม Root/index/lint ด้วย และเก็บ PNG/JSON ใน runs/<runId> ใหม่ทุกครั้งไม่ปนรอบเก่า

DOM runner ใช้ actual-video renderStill + font-ready delayRender + onBrowserLog เก็บ field boxes + Range rects + canvas Thai grapheme ink extents, clip ancestors และ tagged opaque occluders ด้วย browser paint-order (รวม pointer-events:none) ทุก beat/transition/settled/middle/last frame, caption page centers, punch cuts, lower-third/CTA ไม่มี surrogate และไม่มี private seek API ขาด log/font/frame/geometry = FAIL; ไม่มี exemption ซ่อนข้อความชนกัน ตัวอย่าง `--frames 225,2225,4300` ใช้ debug เท่านั้น **ไม่ใช่ acceptance แทน full plan**

เสียงใช้ mix ducking เดิม → pass1 → pass2 loudnorm I=-14 TP=-1.5 LRA=20 → 48k AAC → วัด final MP4 ต้องได้ −14±0.5 LUFS และ TP≤−1 dBTP เก็บ `<final>.audio/{pass1,pass2,final}.json` เป้าของ filter ไม่ใช่ผลที่วัด `analysis_filter_mode` ใน final report เป็น mode ของเครื่องมือวัด ไม่ใช่ delivered normalization; pass2.json เก็บ delivered mode และ warning เมื่อ fallback เป็น dynamic

Production freshness ยังใช้ `check_broll.py` และ ledger เดิม: ภาพแต่ละไฟล์ใช้หนึ่ง beat, stock ใหม่ต่อ episode และ old cap 2 อ่านรายละเอียด freshness reference ห้ามอ้างว่าการใช้ media regression เดิมเป็นของใหม่ ห้ามเขียน main ledger จาก test project

## A44 — offline-first semantic assets และ current paid admission

อ่าน `references/v3-contract.md` ส่วน **A44 current paid-admission contract** ก่อนใช้ `source_context.py`, `broll_plan.py`, `gen_stills.py`, `score_relevance.py`, `batch_relevance.py`. ใช้ source-first → AI abstract → stock พร้อมเหตุผลทุก rejected tier; validator ยืนยัน linkage ไม่ใช่ semantic proof. Stock fetch รับ `--plan ... --context ...` เพื่อใช้ query ราย beat แทน global keyword และต้องใช้ isolated ledger ของ project ห้าม copy main ledger. หลัง transcode ใช้ public `_manifest.json` ที่ writer คำนวณ hash/duration จริง ไม่เติม SHA มือ.

`scripts/broll_config.json` เป็น authority ของ provider/model/rates/caps/token limits; อ่านไฟล์จริงทุกครั้ง ไม่ใช้ค่าจาก historical B1/recovery1. Snapshot ปัจจุบันคือ image attempts3, relevance45 รวมประวัติทั้งหมด; admission ต้อง SUM+reservation <USD1.95 และ <USD2. ใช้ native generateContent ทั้งสองชนิด โดย FREE countTokens ของ request bytes/model/config/key identity เดียวกันก่อน reserve/generate ทุก request ใหม่; ไม่มี automatic retry. CLI เป็น offline preview โดย default; Main เท่านั้นที่อนุมัติ recovery และ inject live transports/key จาก memory โดยไม่ log credentials. Approval ต้องมี `config_sha256` จาก `broll_costs.config_sha256()` ครอบ config ทุกค่า; approval เดิมไม่ใช่สิทธิ์เริ่ม call ใหม่.

Image คิด candidate+thought output ทั้งหมดที่ maximum output rate แม้ modality breakdown ไม่ครบ; `actual_usd:null` ไม่ใช่ billingศูนย์. Calls ล้ม/คลุมเครือยังนับ attempt, ไม่ refund; usage ไม่ทราบ/ไม่สอดคล้องหรือ estimateเกิน reserve => durable STOP_PAID ทุกชนิดข้าม process. Image output-cap overrunที่ยังอยู่ใน reserveบันทึก warning ตาม current contract ไม่เหมารวมเป็น STOP. Budget/rate/auth unavailable => unverified + warning/stock fallback แต่ valid score0 ยัง hard fail. Known score0 ผูก identity+context+intersecting cue IDs ไม่หายเมื่อเปลี่ยน frame/crop; AI ต้องใช้ schemaที่มี `readable_text:boolean` และ true ปฏิเสธแม้ relevanceผ่าน. ห้าม autoexpand/model switch/ตั้ง key; batch acceptanceต้องเป็น full unchanged PreparedRows ไม่ใช่ caller complete=True หรือ focused subset.

Unattended AIOS `edit_long` ที่ไม่มี approval: ปิด AI image แล้วเลือก source/stockตามหลักฐาน; relevance ที่ยังตรวจไม่ได้เป็น `unverified` พร้อม warning ไม่ fabricate scoreและไม่ใช้เพียงเหตุนี้ failทั้งคลิป. Known score0 หรือ AI readable_text rejection ยังคง hard fail. `batch_relevance` report pass:false หมายถึง verificationยังไม่ established ไม่ใช่ hard failureเสมอ; แยก coverage/unverified/failures และ CLI exitให้ชัด. Consumer **ต้องอ่าน `verification_status` ไม่ใช่ `pass` เพียงอย่างเดียว**: `verified` คือ valid verdictครบfullcoverage, `unverified` คือยังไม่มีหลักฐานพอ, `failed` คือ known rejectionหรือstructuralerror. ระดับrow score1แม้warningยังverified; AIต้องreadable_textfalse. Diagnostic/plainrowsไม่verifiedระดับaggregate. Fieldใหม่นี้deriveจากverdictปัจจุบัน ไม่เชื่อlabelในcacheเก่า; pass/exit/acceptanceเดิมคงไว้เพื่อcompatibility. Agent-guided handoffเท่านั้นในงานนี้; AIOS consumer/paid lifecycle integration เป็น separate ticket CF-A55 ไม่อ้างว่า production unattended wiringพร้อมแล้ว.

Caption start-5 จับคู่ quantity+unit แบบ list เท่านั้น ไม่ใช่ semantic parser; timing ใช้ word START และคง exact script/timestamps. Cutaway Loop เป็น beat-local Sequence; avatar ยังคง global. ต้อง fresh full DOM หลังเปลี่ยน helper/timing ก่อน whole render; focused144s เป็น diagnostic เท่านั้น.

## เมื่อไม่ผ่าน

หยุดส่งมอบ แก้ beat/layout/mix แล้วรัน gate นั้นและ full acceptance ใหม่ เก็บ negative/baseline evidence ไว้ ห้ามลด threshold หรือซ่อน log เพื่อให้ผ่าน ส่ง final MP4, stills, reports, commands/exit codes, limitations ให้ผู้ตรวจอิสระ ห้ามกล่าวว่า whole-video QC ผ่านจาก engine gates อย่างเดียว (hook, accuracy และ semantic B-roll ต้องตรวจแยก)

## Regression และ tests

`V261107_001` เป็น baseline ที่มี Q1 chip overlap, stock chrome, holds ยาว และเสียงต่ำ Unit negative fixtures + actual baseline still ต้อง fail ก่อน V3 ผ่าน ใช้ `evals/evals.json` เป็น scenario การซ่อม ไม่ใช่คะแนน QC รับรอง

```bash
python3 -m unittest discover -s "$SKILL/scripts/tests"
node --test "$SKILL"/scripts/tests/*.test.mjs
```
