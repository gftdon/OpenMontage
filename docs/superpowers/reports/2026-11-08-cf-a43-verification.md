# CF-A43 — V3 engine และ QC gates: รายงานตรวจรับ

วันที่: 2026-11-08
Branch: `cf-a43-yt-news-v3` · Base: `59b390d`
สถานะ: **ตรวจรับ CF-A43 engine/gates ผ่านแล้ว — มี final regression MP4; ยังไม่ merge/push**. การผ่านนี้ไม่ใช่ whole-video editorial QC หรืออนุมัติเผยแพร่.

## ขอบเขต

สร้าง `Youtube-YT-News-Style01-V3` ทั้ง `.claude/skills` และ `.agents/skills` โดยเก็บ V2 เดิมไว้ พร้อม composition ชื่อกลาง `YtNewsStyle01V3` และ caption helper ที่ track ใน branch ไม่พึ่ง source file ที่ untracked ใน checkout หลัก. `Root.tsx` เพิ่มเพียง import และ registration 2 บรรทัด. ไม่แก้ shared components/lib, package/lockfiles, AIOS preset, database หรือ dev server :3000.

Spec: `/Volumes/Ext_SS990Pro/Dev/ai-business-os-fable/docs/superpowers/specs/2026-11-08-video-qc-v2-design.md` §CF-A43, §4.
แผน: `docs/superpowers/plans/2026-11-08-cf-a43-yt-news-v3.md`.

## สิ่งที่เปลี่ยน

- ป้ายสถิติแยกแถวจาก headline, description และ subtitle; read text ≥28px, label ≥22px ใน safe area 5%.
- Source footage มี SOURCE/URL ตาม origin ราย beat; stock ไม่ติดเครดิตต้นทาง.
- Source full เป็น 1920×1080 `cover` จริง; source stage ใช้ `contain` เพื่อไม่ crop UI. มี stats rail ใน full layout.
- เอา dark wash ทั้งภาพออก ใช้พื้นรอง/gradient เฉพาะข้อความ; contrast เป็นค่าคำนวณของ palette บน backing ที่นิ่งแล้ว ไม่ใช่ผลวัดพิกเซลของทุกเฟรม.
- คง bounded avatar morph, stage slide/fade และ chip/lower-third/CTA entrance; hard cuts เฉพาะ approved punch.
- Hold ≤10s ตรวจจาก shot/media/layout ที่ render จริง. Overlay ปรากฏ/หายหรือเปลี่ยนข้อความไม่รีเซ็ต hold. Hard punch ของ avatar/source รีเซ็ตได้เมื่อ scale เปลี่ยน ≥15% หรือ visible crop เปลี่ยนชัดตาม threshold; raw fx/fy ที่ z=1 ไม่ถือเป็น cut. Stock/typo ไม่ใช้ punch.
- `captionLane` ต่อ beat สำหรับหลบ burned-in source text โดยผู้ตัดต่อดู contact sheet และตั้งค่าเอง; source ตัวอย่างใช้ top-left เพื่อไม่บังชื่อผู้พูดหรือใบหน้า.
- DOM gate วัด grapheme ink, field boxes, ancestor clipping, tagged opaque layer paint order, visible credit และ structural backing. ไม่มี production injection API.
- รายงาน gate มี schema/version, run ID, timestamps, source hashes, full-plan coverage และ artifacts แยกต่อ run. Subset เป็น diagnostic ไม่ใช่ acceptance; stale pass ถูกแทนด้วย running/failed ก่อนเริ่มงานใหม่.
- Audio mux ทำ loudnorm สองรอบ เป้า I −14 LUFS / TP −1.5 dBTP แล้ววัด AAC สุดท้าย ต้องอยู่ I −14±0.5 LUFS และ TP ≤−1 dBTP. โหมด analysis filter แยกจาก normalization mode ของ mix.

## คำตัดสินและ deviation ที่ต้องเก็บไว้

1. Lead อนุญาตให้นำ stock เดิมมาใช้เป็น regression episode; freshness ใช้ ledger แยก ห้ามเขียน ledger หลัก. Semantic B-roll เป็น CF-A44 และไม่อ้างว่าคลิปนี้ผ่าน whole-video editorial QC.
2. Candidate แรกเปลี่ยน morph/crossfade/spring เป็น hard-cut-only โดยไม่ได้ขออนุมัติ. Lead ปฏิเสธ; คืน bounded motion ก่อนตรวจรับ. หลักฐาน candidate นั้นไม่ใช่ผลสุดท้าย.
3. Candidate full layout แรกทำภาพต้นทางเล็กลงเพราะ contain ในกล่องเตี้ย. Reviewer พบและ Lead ยืนยัน true full-bleed; แก้เป็นเต็ม 1920×1080 พร้อม safe text/credit/stats overlays.
4. Candidate แรก punch typography ทำให้ข้อความถูกตัด. Lead จำกัด punch เฉพาะ avatar/source; typography เปลี่ยนการ์ดหลักจริงแทน.
5. Lead ยืนยัน overlay ทุกชนิดไม่รีเซ็ต hold; ไม่เพิ่ม minimum dwell.
6. Pixel-freeze analysis หลัง render เป็น advisory ไม่ใช่ gate แทน BEATS. Missing pytest เป็นข้อจำกัด environment เดิมที่ Lead อนุญาตให้รายงานแยก.

## หลักฐานก่อนแก้และ regression

ฐานหลักฐาน local (ไม่ commit media):
`projects/v261107-001-yt-news-v3-test/qc/`

| หลักฐาน | ผลที่สังเกตได้ |
|---|---|
| `baseline-layout/` | Actual legacy stills 0:09/1:29 FAIL รวม 40 issues รวม Q1 overlap |
| `layout-all/report.json` | Rejected candidate 700 samples FAIL 35 typography clipping issues |
| `final-layout/cancelled-historical.json` | ยุติรอบที่หมดประโยชน์หลัง code/schema เปลี่ยน เก็บ partial evidence; ไม่ใช่ acceptance |
| `repair-negative-ready/negative-results.json` | Opaque image ที่ pointer-events:none, hidden credit, stock URL และ Thai clipping ถูกจับ |
| `crash-stale/report.json` | Failed run ไม่เหลือ stale pass |
| `polish-negative-proof/thai-ink-only-proof.json` | Range y300..360 อยู่ใน clip box แต่ ink y299.3999977 เกิน ~0.6px; rangeInside/inkOutside/caught เป็น true |
| `caption-left-focused/` | ภาพจริงซับ top-left ไม่บังตาหรือชื่อผู้พูด และไม่มี chip box เปล่าก่อนข้อความ |
| `b1-red-actual/report.json` | backing false rejection ที่ 1199/1241/1408 และ avatar บัง URL ที่ 1199 |
| `b1-green-actual/report.json` | Focused 7 frames หลังแก้ผ่าน diagnostic; complete=false/pass=false ถูกต้อง |
| `b1-negative/negative-results.json` | Negative cases ยังจับได้ รวม missing backing และ ink-only clipping |

Main ตรวจ hash 9 ไฟล์ใน `b1-green-actual/report.json` ตรงกับ source ก่อนเริ่ม full-plan run.

## Fresh checks โดย main

คำสั่งรันจาก worktree:

```bash
python3 -m unittest discover -s .claude/skills/Youtube-YT-News-Style01-V3/scripts/tests
node --test .claude/skills/Youtube-YT-News-Style01-V3/scripts/tests/*.test.mjs
python3 -I .claude/skills/Youtube-YT-News-Style01-V3/scripts/lint_beats.py remotion-composer/src/YtNewsStyle01V3.tsx
```

- Main final run หลัง render: Python **22/22**, Node **23/23**, BEATS **37** ผ่าน exit 0. รวม actual overhang before/after regression และ backing shared-fade/negative cases.
- Main คำนวณ MP4 SHA-256 เองตรงกับ packet: `ee62ab51ca76c8f9c731d19ed7dd09779f679d28f9c11f829386434676b15902`. คำสั่ง hash รอบแรกใช้ `hashlib.file_digest` ที่ Python เดิมไม่มี จึงเปลี่ยนเป็น streaming SHA-256 และรันผ่าน (verification-command compatibility ไม่ใช่ product failure).
- Scoped TypeScript main run: exit 0 ด้วย target ES2020, module ESNext, moduleResolution bundler, strict, react-jsx, esModuleInterop, skipLibCheck และสองไฟล์ V3.
- Full TypeScript main run: exit 2, **11 diagnostics เดิม** ด้านล่าง ไม่มี V3 diagnostics.
- Main final run ตรวจ `git diff --check` ผ่าน, V2/shared diff ว่าง, mirrors ตรงกัน; Root diff เป็น 2 additions เท่านั้น. Main full tsc เทียบ log แบบ exact โดย normalize Root line offset +1: diagnostics ทั้ง 11 ตรง baseline ไม่มี error ใหม่.
- Repo pytest: ผู้ลงมือพยายามรันแล้ว environment ไม่มี `pytest` (`No module named pytest`); **ไม่ได้อ้างว่า repo-wide suite ผ่าน**. ไม่มีการติดตั้ง/เปลี่ยน dependencies เพื่อแก้นอก scope.
- `remotion-composer/package.json` ไม่มี test/eslint script; build script เดิม render `Explainer` ไม่ใช่ V3. งานนี้ตรวจ V3 ด้วย actual Remotion bundling/render แทน.

### Baseline TypeScript ที่ Lead อนุมัติให้คงไว้

| ไฟล์ | บรรทัดปัจจุบัน | Error |
|---|---|---|
| AiAgencyNewsYTV2.tsx | 230,253 | TS2349 getWebRect object not callable |
| FuguNewsYTV2.tsx | 230,253 | TS2349 เหมือนกัน |
| TripoGameNewsYTV2.tsx | 230,253 | TS2349 เหมือนกัน |
| KaraokeOverlayV2.tsx | 69 | TS2344 props ไม่มี Record index signature |
| V260821Reel.tsx | 11 | TS2344 เหมือนกัน |
| Root.tsx | 733,742,755 | TS2322 component/metadata generic mismatch เดิม; ขยับ +1 จาก import |

## การตรวจอิสระ

ใช้ deep-reasoner read-only ทั้ง branch และ targeted re-reviews. Finding ที่ปิดแล้ว: full layout ไม่เต็มจอ, ineffective crop reset, hidden metadata reset, subset/stale report provenance, hardcoded CTA/dead configuration, audio mode provenance, opaque/Thai ink measurement และ hidden credits. Delta review ปิด hold policy/caption lane/Thai ink proof; B1 backing fade และ URL paint order พิสูจน์ด้วย actual RED→GREEN และ negative fixtures โดยไม่ลด gate.

## การตรวจเต็มและไฟล์ส่งมอบ

- [x] Fresh full-plan DOM gate `qc/acceptance-layout-v2/report.json`: run `8a989131-261f-4578-9fbd-412845b6e74c`, **695/695 samples**, complete=true, pass=true, issues=[]; main อ่านรายงานและคำนวณ source hashes 9 ไฟล์ซ้ำแล้วตรงทั้งหมด. รอบก่อน `acceptance-layout` ตก 29 headline-backing issues จาก glyph ยื่นซ้าย ~0.90px; แก้ horizontal padding 12px จริง ไม่ผ่อน gate และเก็บ actual before/after regression.
- [x] Full 341s 1080p serial render, concurrency 1; ไม่รันคู่กับ allDOM. `renders/final.mp4` ขนาด **135,803,863 bytes**, H.264 1920×1080 25fps; AAC 48kHz stereo.
- [x] Two-pass mux mode **linear**, ไม่มี warning. Main วัด encoded MP4 ซ้ำ: **I −14.02 LUFS / TP −1.53 dBTP / LRA 2.4 — PASS**. รายงาน `qc/main-final-audio.json`; pass1/pass2/final อยู่ `renders/final.audio/`. Main ffprobe ยืนยัน duration **341.000s**.
- [x] Delivery stills `renders/stills/009s.png`, `089s.png`, `172s.png` จาก full acceptance run/hash เดียวกัน.
- [x] Playwright MCP เปิด MP4 จริง, seek 9/89/172/56.2/58.84/339s สำเร็จและ playback 88→90s เดินจริง; video readyState=4/error=null, console errors=0. ดู screenshots actual final `qc/browser-*.png` รวมจุดแก้ overlap/source-safe subtitles/endcard. Browser ปิดแล้ว, local HTTP server ของ main port31843 หยุดด้วย TaskStop; ไม่แตะ :3000. Python HTTP server ไม่รองรับ seek ตามต้องการจึงโหลด MP4 เป็น browser Blob ก่อน seek; ไม่ได้แก้ตัววิดีโอ. การทดสอบ browser muted: ไม่อ้างว่าฟังเสียงด้วยหูแล้ว, เสียงตรวจด้วย ffmpeg final loudness.
- [x] Fresh final checks / git hygiene ผ่านตามข้างบน; commit เฉพาะ pathspec ของ CF-A43 โดยไม่มี merge/push.

Test project เก็บหลักฐาน historical bundles/stills รวมประมาณ **14.93 GiB**; ไม่ลบเองเพราะใช้ audit/rollback. ไม่มี Node render/QC ของผู้ลงมือค้างตามตรวจล่าสุด; Remotion child PID ไม่ได้เก็บรายตัวจึงไม่อ้างว่า inventory process ครบทุกตัว. ผู้ลงมือปิด renderer browser ผ่าน finally และ main ปิด Playwright browser/server ของตนแล้ว.

## ปัญหา render ที่เกิดขึ้น

รอบแรกที่รันคู่กับ allDOM ล้มที่ frame 668 ด้วย browser per-frame timeout 33s. หลังแยกงาน minirange 650–680 ผ่านที่ concurrency 1 และ timeout เดิม. ข้อมูลนี้สนับสนุนสมมติฐาน resource contention แต่ไม่พิสูจน์เหตุเชิงสาเหตุ; ไม่สรุปว่ามี code exception หรือแก้ด้วยการเพิ่ม timeout. Final render ต้องรันเดี่ยวแบบ background.

## ข้อจำกัดที่ไม่ควรปิดบัง

- DOM gate ไม่ OCR ข้อความที่ฝังอยู่ใน source video และไม่ตรวจ semantic B-roll/ข้อเท็จจริงสคริปต์/การแบ่งคำซับ. ต้องตรวจ contact sheet แล้วตั้ง source-safe caption lane.
- Opaque-layer coverage ใช้ authored tags และ paint-order observations; layer ใหม่ต้องติด tag ตาม contract.
- Structural backing presence ไม่ใช่ pixel-contrast measurement; contrast ที่รายงานเป็นค่าคำนวณสำหรับ palette และ backing ในสภาวะ settled.
- Sampling ครอบคลุมแผน beats/transitions/caption pages/overlays ไม่ได้แปลว่าตรวจทุกเฟรมของ MP4.
- Episode ใช้ stock/script/captions เดิมเพื่อทดสอบ engine ไม่ใช่วิดีโอที่ได้รับอนุมัติเผยแพร่.
- ไม่มี merge/push/deploy และไม่มีการเปลี่ยน AIOS preset.
