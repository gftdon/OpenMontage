# CF-A44 — Verification และ handoff

**สถานะ: ผ่าน implementation/regression acceptance ตามขอบเขตที่ Lead อนุมัติ พร้อมส่ง branch; ไม่ใช่ production ship หรือ whole-video editorial approval**

ตรวจเสร็จ 2026-11-09 (เวลาเครื่อง). Session `ai-business-os-fable-3`.

## ผลส่งมอบ

- Worktree: `/Volumes/Ext_SS990Pro/Dev/openMontage-worktrees/cf-a44-yt-news-v3-broll`
- Branch: `cf-a44-yt-news-v3-broll`, base `fe63994` (CF-A43)
- Project: `projects/v261107-001-yt-news-v3-broll-test` — ต่อไปเรียก `PROJECT`
- **MP4 ล่าสุด: `PROJECT/renders/final-v2.mp4`**
- H.264 **1920×1080, 25fps, 341.000s**; AAC **48kHz stereo**; **124,867,189 bytes**
- SHA256: `93aee44046958ab2f82cf56c01feebdb66891e048eaee95002b92b44b86ea53e`
- Main วัด encoded MP4 ซ้ำ: **−14.02 LUFS / −1.53 dBTP / LRA 2.4 — PASS**
- Pass2 normalization **linear**, warnings ว่าง; `analysis_filter_mode` ในรายงานวัดเสียงไม่ใช่ mode ของ pass2
- Stills ล่าสุด: `PROJECT/renders/stills-v2/{009s,089s,144s,251s,253s}.png`
- Transition evidence จาก MP4 ล่าสุด:
  - `PROJECT/renders/transitions-v2/morph-89-six-frames.jpg`
  - `PROJECT/renders/transitions-v2/morph-89-detail.jpg`
  - `PROJECT/renders/transitions-v2/source-transitions.jpg`
  - `PROJECT/renders/transitions-v2/source-fadeout-transitions.jpg`

`renders/final.mp4` SHA `17f14e4843c23f9836c292b1c0e1190b805055a39df1cfe2d913f8bdbb113ba5` คือ candidate ก่อนแก้ artifact ไม่ใช่ไฟล์ส่งมอบล่าสุด เก็บไว้เป็นหลักฐาน ไม่ overwrite.

## Acceptance ล่าสุด

| Check | ผล | หลักฐาน |
|---|---|---|
| Python tests | 151/151 ผ่าน ไม่มี skip เมื่อระบุ actual report | คำสั่งด้านล่าง |
| Node tests | 75/75 ผ่าน | รวม temporal/endcard/negative fixtures |
| Full TypeScript | 11 baseline errors เดิม; V3 ไม่มี error | `PROJECT/qc/main-full-tsc.log` และ worker reruns |
| BEATS/hold | 44 beats ผ่าน; hold≤10s, endcard≤5s | `PROJECT/qc/main-beats-lint.json` |
| Full semantic plan | 22 cutaways, all overlapping cues, manifest/hash/duration reconciliation ผ่าน | `PROJECT/qc/phase-c/integration-inputs.json` |
| Within-episode identity | ไม่มี 60s repeat/loop violations | Phase C usage checks + fresh `prepare_rows` |
| Relevance | **22/22 verified**, 8 score2 / 14 score1 warning / 0 fail / 0 unverified | Latest cache-linked report ด้านล่าง |
| AI illustration | score1 + `readable_text:false` | `ai_layout_draft_final-250.96` |
| Full DOM | **953/953**, complete=true, pass=true, issues=[] | `PROJECT/qc/phase-d/full-dom-v4-temporal/report.json` |
| Continuous temporal gate | **36 windows / 647 frames**, complete=true, issues=[] | `temporalSweep` ใน full DOM report |
| Final encoded audio | −14.02 LUFS, −1.53 dBTP, LRA2.4 | `PROJECT/qc/main-final-v2-audio.json` |
| Playback | seek 13 จุด readyState4/error null; playback เดินจริง | `PROJECT/qc/playwright-final-v2-playback.json` |
| Hygiene | สอง skill mirrors ตรงกัน; diff check ผ่าน; reference ต่างเฉพาะ assetDir placeholder | ตรวจใหม่ก่อน commit |

Full DOM run ID: `bb4e2661-f224-43cd-b127-ec191df5d232`. Main ตรวจ source hashes ทุกไฟล์ตรงก่อน render; ต้องไม่ใช้ report เก่าหลังแก้ input.

Actual relevance call report/table:
- `PROJECT/qc/relevance-full-jxl9wzuc/report.json`
- `PROJECT/qc/relevance-full-jxl9wzuc/relevance-table.md`

Latest composition-linked cache refresh:
- `PROJECT/qc/relevance-final-v2-e1dy0j9q/report.json`
- `verification_status:verified` ทั้ง aggregate และทุก row, complete/pass=true, paid_enabled=false; journal ไม่เปลี่ยน
- Refresh หลังแก้ overlays ใช้ภาพ/cue/crop เดิม จึงไม่เรียก paid rescore

## เนื้อหาการเปลี่ยน

### Source-first B-roll

- 44 BEATS / 22 cutaways: source6ช่วง, stock15รายการ (ใหม่10 / same-episode reuse5), AI1ภาพ
- Query/selection rationale ผูกกับบทพูดในแต่ละช่วง ไม่ใช้ชื่อไฟล์เป็นหลักฐานความเกี่ยวข้อง
- พบของเดิมชื่อหลอกความหมาย: `photo_studio_lights` เป็นตลาดน้ำ, `architect_concept_draft` เป็น abstract network, `graphic_designer_ui` เป็น keyboard, `fine_oil_painter` เป็นคนกับผงสี, `hourglass_sand_time` เป็น countdown
- `yt_api_docs` มี presenter+logo ไม่ใช่ API docs UI จึงเปลี่ยนออก
- Main ดู previews 68 ภาพก่อนเลือก stock; stable Pixabay IDs, raw hashes และ public post-transcode hashes/duration บันทึกแยก
- Source cuts ใหม่6ช่วงมี source SHA/ranges/output SHA; ไม่มีช่วง source overlap ภายใน60s
- Lead อนุมัติ **same-episode reuse** IDs `27706/98143/152728/137265/1006` เพราะ re-render `V261107_001` ตอนเดิมที่ยังไม่เผยแพร่ ไม่อ้างว่า fresh ทั่วระบบและไม่ใช้เป็นข้อยกเว้นกับ episode ใหม่
- Isolated ledger ไม่เขียน main ledger; within-episode60s gate ยังใช้ตามเดิม
- Pixabay1643 เดิมได้ valid score0 จริงและถูกเปลี่ยนออก ผล0ยังอยู่ใน outcome ledger ไม่แปลงเป็น unverified

### Timing และซับไทย

- Existing word timing เป็น spine เดียวของ captions และ semantic plan; vendor SRT เป็น reference เท่านั้น
- Exact script คงคำ/whitespace/timestamps; แยก display spacing ออกจาก source ไม่เว้นวรรคทุกคำไทยและไม่ตัดกลาง ICU word
- Quantity+unit เป็น no-break pair ตาม list ไม่ใช่ semantic parser ทั่วไป
- Algorithm `a44-exact-icu-start-5`, 151 pages / 810 chunks / loss0; helper hash `d868cffe4911c31e72c1082fe7a71713b4a69a9f3090541f88b77d743bd563de`
- Karaoke switch อิง word START; คง Gold Glow และ timing เดิม
- Avatar bytes AIOS/original/A43 ตรงกัน; mux ไม่ trim/speed/offset
- Local ASR เฉพาะ6–14sและ86–96s ใช้ cached model ไม่มี download/API: phrase deltas +.06/+.06 และ+.08/−.22s ภายใน±.3s. Individual word tails ต่างได้ .44–.46s จึงไม่อ้าง whole-episode/word-level sync ผ่าน
- แก้ inherited root-level Loop ให้ cutaway ใช้ beat-local Sequence; avatar ยัง global เพื่อคง lip-sync

### Gate และ transition repairs

1. Full DOM รอบแรก457เฟรมพบ typo ถูก avatar บัง6จุดที่1870/2870/3594. เลื่อน typo entrance หลัง full-avatar morph0.55s โดยคง motion และ threshold เดิม; negative actual frames → focused46ผ่าน → full457ผ่าน
2. Lead พบ empty headline gradient ทับ avatar ใน MP4089s แม้ gateเดิมผ่าน เพราะ gateเดิมตรวจเฉพาะ text occlusion. Mainดู6เฟรมยืนยัน12เฟรม/.48s และ trace ถึง headline/sub backing z30 ที่ทับ avatar z20
3. แก้ headline/backing/stat entrance ให้รอทั้ง morph และ fade-out ด้วย booleanเดียว;ไม่เลื่อน source credit/AIlabel/caption/media
4. เพิ่ม temporal check ใน **default full DOM**: ทุก actual frame ใน rect-changing windows รวม reverse, actual paint order, visible background/gradient รวม untagged elements และพื้นที่ว่างนอก glyph/padding. ไม่มี name exemption
5. 25fps: 7เฟรม/.28sผ่าน, 8เฟรม/.32s fail; clean frame reset, missing/duplicate/invalid measurement fail closed, dirtyชนปลายwindowเป็น unbounded
6. Gateใหม่จับ chromeแถบยาว .44–.48s จึงเปลี่ยนพื้นหลังให้หุ้ม URL+padding ตาม Lead โดยคงเวลา URL/credit
7. Gateจับ fade-out108.64/171.8เพิ่มอย่างละ12เฟรม/.48s จึงขยาย panel-delay condition ให้ครอบ `from.opacity>to.opacity`
8. ปิด review P2: รวมพื้นที่ disjoint empty regions ต่อ candidate/frame ก่อนเทียบ1500px²; negative3384px²ที่แต่ละชิ้นเล็กกว่า1500ต้อง fail
9. Full953รอบหนึ่งหยุดที่ endcard ด้วย `missing avatar measurement`: แก้ QC-only expected endcard absence เป็น explicit N/A/avatar:null. Missing active avatar หรือ N/Aในsweepยังfail; endcard fieldsยังครบ. Actual8412/8413/8524ผ่านก่อน full953ล่าสุดผ่าน

เก็บ failed runs/negative fixtures ไว้ ไม่ลด thresholds หรือซ่อน failures. Reference composition กับ engine ตรงกันยกเว้น `EPISODE.assetDir` placeholder.

Temporal limitation: identityจาก DOM path อาจเปลี่ยนถ้ามี siblingใหม่แทรกกลางwindowในอนาคต; episodeนี้ไม่มีเงื่อนไขนั้น (review P3). Paint-order เป็น geometry/sample-point evidence ไม่ใช่ full pixel semantic comparison.

## Source และ inherited editorial limitations

- Legacy AIOS taskไม่มี `source/source.json`;ใช้ fallbackที่ระบุ provenance
- Original `assets/ytsource/transcript.txt` มี14 timed English lines /1545bytes SHA `2c7c37761db7635579a090246dfbd2e029eb2d2401aee3033f5522007a3bc1d3`
- `chapters.txt` เป็น title/duration header104bytes ไม่ใช่ transcript. เคยอ้างสลับจาก parallel Read แล้วแก้ชื่อให้ถูก ไม่มีหลักฐานไฟล์ถูกเปลี่ยน
- Transcriptจบ91.28s แต่ sourcecontainer86.994s จึงคง local-unverified-transcript ไม่ใช้ timestamp เป็น cut authority
- ไม่แก้ audio/script เดิมตาม Lead แต่เอา graphics/stat claims ที่ต้นทางไม่ยืนยันออก: 50%, 6วินาที และ10→5. “เร็วขึ้น50%”ไม่เท่ากับเวลาลดครึ่งหนึ่งโดยทั่วไป
- Exact karaoke ยังตามเสียงเดิม จึงยังมี inherited factual limitations; relevance ไม่ใช่ fact-check และผลนี้ไม่ใช่ whole-video QC>90 หรืออนุมัติเผยแพร่
- Internal QC copy เช่น “รอ relevance…” และ placeholder ถูกย้ายออกจากข้อความบนจอไป metadata; subtitleบนจอเป็นข้อความสำหรับผู้ชม

## ค่าใช้จ่ายและ recovery

**Actual billing ไม่ทราบ/null**. ทุก failureนับ attempt; ไม่ reset/refund และไม่มี automatic retry.

| ลำดับ | งาน/ผล | Usage | Reserved USD |
|---|---|---|---:|
|1|Imagen4 failed_or_ambiguous; causeเดิมUNKNOWN|ไม่มี|.06|
|2|Gemini3.8 CLI relevance failed_or_ambiguous|ไม่มี|.02784|
|3|Gemini3.1 image ได้ภาพแต่มีคำlight จึง exclude; MAX_TOKENS|prompt178/candidates1547/total1725; IMAGE1120+427ไม่แจกแจง|.10|
|4|Native relevance wire ผ่าน; Pixabay1643ได้0|input1198/candidate39/thought168/output207|.0047385|
|5|Final image draft layout สำเร็จ|prompt276/candidates1540/total1816; IMAGE1120+420ไม่แจกแจง|.13|
|6–27|Native relevance actual22cutawaysผ่าน|input26373/outputรวมthinking4128|.10425975|

**ยอดสำรองรวม USD0.42683825; 27attempts = image3 + relevance24.** Image capใช้ครบ3แล้ว. Conservative estimate ตาม usage/maximum image-output rate โดยคงยอดสำรองของสองattemptแรกที่unknownรวม **USD0.3102215**; ไม่ใช่ยอดบิล.

- Recovery1 เปลี่ยนจาก Imagen4ที่ live GET404/listไม่มี เป็น native Gemini ตามอนุมัติ. เก็บ2attemptsเดิมเท่าเดิม. Call3 outputเกินcap1536ไป11และแจกแจงไม่ครบจึงSTOPตามกติกาขณะนั้น
- Leadอนุมัติ recovery2 + settlement: call3คิด `(1547×60+178×.5)/1M = .092909` อยู่ในreserve.10;ไม่ลดreservationและไม่เขียนทับattemptเดิม
- Config SHA `1405c75aa896141257139ef5e3ee998869f52da399da0604fb017e126c618fd1`: imagecap3/input14000/max2048/reserve.13; relevance45/max1024/LOW;หยุดเมื่อreserved+nextcall≥1.95 และ strict<2
- Final image gateต้องมี real post-recovery2 relevance usage receipt ก่อน; call4ผ่านจึงเรียกcall5ได้เพียงครั้งสุดท้าย
- Call5 conservative estimate `(1540×60+276×.5)/1M = .092538`; original image SHA `24e2403b32f66df9644ef30dc388506a73e284e50149af1a9bc87bdfe9c74f46`. Providerส่งJPEGแต่artifactชื่อ.png;ffmpegdecodeได้
- ทุก paid payloadใหม่ผ่าน countTokens exactmodel/body ด้วย keyเดิมในmemory/header, timeout90s;ไม่ใส่keyในfiles/logs
- Journal: `PROJECT/artifacts/broll-costs.json`; approvalsแยกไฟล์ `approved-budget-recovery1.json`, `approved-budget-recovery2.json`; historical snapshots/events/settlementเก็บครบ
- Raw usage evidence: `qc/recovery-precheck/native-image-response-ta1qskiq/`, `qc/recovery2-preview/native-relevance-response-x90f7pya/`, `qc/final-image-response-h781t9zb/`, `qc/relevance-full-jxl9wzuc/`

## Unattended และขอบเขตส่งมอบ

Leadรับ **agent-guided V3 flow**; paid lifecycle/AIOS consumerอยู่ ticket **CF-A55** ไม่แก้นอก scope.

- Source/stock toolsใช้ได้; paidทุกrunต้องexplicitapprovalและMain-injected transport. ห้ามcopyjournal/recovery/approvalของepisodeนี้ไปเปิดgateให้episodeอื่น
- Native final-image gateของconfigนี้ผูกpost-recovery2 receipt จึงไม่อ้างfresh-project one-command paid pipelineพร้อมใช้
- Noapproval tests6กรณียืนยันไม่มีpaid/reservation. `generate` APIคืนstockfallbackwarning แต่ nativeprovider `gen_stills --execute` CLIคืนSTOP_PAID/exit0และ **ไม่เลือกstock/sourceให้อัตโนมัติ** ผู้ควบคุมflowต้องเลือกเอง
- Scorerไม่มีrunnerคืนunverified ไม่ใช่hardfailure;known0/readable-text rejectionยังhardfail
- เพิ่ม `verification_status: verified|unverified|failed` ทุกcueและaggregate โดยderiveจากverdictไม่เชื่อcachelabelเก่า. AIverifiedต้องreadable_textfalse;aggregateverifiedต้องfullnonemptycoverageครบทุกrow
- คงlegacy `pass`/`acceptance`/exitcodeเพื่อcompat: `pass:true` อาจหมายถึงnonblockingขณะที่verification_status=unverified. **Consumerต้องอ่านverification_status ไม่อ่านpassอย่างเดียว**
- Engine lint/DOM/render/muxยังไม่consume relevance reportอัตโนมัติ. ยืนยันtool-boundary tests ไม่ใช่ unattended edit_long end-to-end;consumerintegrationอยู่CF-A55

## Playback / audio provenance

- `PROJECT/qc/playwright-final-v2-playback.json`: seek9/23.8/48.2/88.7/88.9/89.1/89.5/108.9/144/172.1/251/253/339s ทั้งหมดreadyState4/errornull;play88.5→90.575894sจริง;แยกqualityobservation2007frames/0dropped
- Screenshot `PROJECT/qc/playwright-final-v2-88_9s.png`;Mainเปิดดู artifactหาย. Console0errors. Browser tab/localserverของงานปิดแล้ว
- Playbackเป็นsmokeไม่ใช่ดูทุกวินาทีหรือรับรองlip-syncทั้งตอน
- Bed/VO ใช้ของA43เดิมจากactualmuxinvocationในtranscript ไม่เดาเพลง. `PROJECT/qc/audio-input-provenance.json`: bedSHA `0e18b14e4a49bc2003dc8a9d6a4b418b84cafd2503c570284c524f66473ed24e`, avatarSHA `eea798e90edb7db325ed162e23785a0f566b7c1fd5faffc4f4bceafeca31bf25`;mux341/336.5/bedvolume.22

## คำสั่ง verification สำคัญ

```bash
ROOT=/Volumes/Ext_SS990Pro/Dev/openMontage-worktrees/cf-a44-yt-news-v3-broll
PROJECT="$ROOT/projects/v261107-001-yt-news-v3-broll-test"
S="$ROOT/.claude/skills/Youtube-YT-News-Style01-V3/scripts"
MORPH_QC_REPORT="$PROJECT/qc/morph-89-review/green/report.json" \
  python3 -m unittest discover -s "$S/tests" -p 'test_*.py'
node --test "$S"/tests/*.test.mjs
python3 -I "$S/lint_beats.py" "$ROOT/remotion-composer/src/YtNewsStyle01V3.tsx"
node "$S/qc_layout.mjs" YtNewsStyle01V3 "$PROJECT/qc/phase-d/full-dom-v4-temporal" \
  "$ROOT/remotion-composer" --artifacts "$PROJECT/artifacts"
node "$S/render_episode.mjs" "$ROOT/remotion-composer" YtNewsStyle01V3 \
  "$PROJECT/renders/phase-d-visual-v2.mp4"
bash "$S/mux_av.sh" "$PROJECT/renders/phase-d-visual-v2.mp4" \
  "$ROOT/remotion-composer/public/ytNewsV3BrollTest/avatar_source.mp4" \
  "$PROJECT/assets/audio/bed.mp3" "$PROJECT/renders/final-v2.mp4" 341 336.5 0.22
python3 -I "$S/measure_loudness.py" "$PROJECT/renders/final-v2.mp4" \
  --report "$PROJECT/qc/main-final-v2-audio.json"
```

คำสั่งคือprovenanceของรอบที่รันแล้ว หากรันซ้ำให้ใช้outputใหม่เพื่อเก็บหลักฐานเดิม. FullDOMและfullrenderรันตามลำดับไม่ซ้อนกัน.

## Repository hygiene และ handoff

- เปลี่ยนเฉพาะ V3 mirrors, neutral V3 composition/helper และ task plan/report;ไม่แก้V2/sharedengine/Root/packages/lockfiles/main/A43
- Narrowtranscodefix:แก้ls/mp4/webm+pipefailที่ทำให้mp4-onlyหยุดก่อนffmpeg พร้อมtestsmp4/webm/both/missing/empty/spacefilename
- Fulltsc11baseline: AiAgencyNewsYTV2/FuguNewsYTV2/TripoGameNewsYTV2อย่างละ2, KaraokeOverlayV2, V260821Reel และRoot3;ไม่มีV3error ไม่ซ่อนหรือแก้ไฟล์อื่น
- Commitเฉพาะtaskpaths;node_modules symlinkและignoredmedia/public/evidenceไม่commit. Worktree/project/A43เก็บไว้
- ไม่merge/push/deploy/เปลี่ยนAIOSpreset/DB/เผยแพร่. Motion taskให้Leadจัดการเมื่อรับhandoff
