// ===========================================================================
// FableNewsYT V2 — EPISODE DATA (pure TypeScript, no React)
// Everything episode-specific lives here; FableNewsYTV2.tsx is the engine.
// Times: `src` = seconds in avatar_source.mp4 (whisper spine). Beats marked
// `abs: true` are already in timeline seconds (teaser + sting). The engine maps
// src -> timeline with `mapMain()` below.
// ===========================================================================
import { WEB_RECTS, type WebRect } from "./fableNewsWeb";

export type Tone = "amber" | "mint" | "clay";
export interface CamKey { t: number; fy: number; z: number; fx?: number }
export interface Highlight { t: number; key?: string; rect?: WebRect; pad?: number; th?: string }
export interface Stat { t: number; big?: string; label: string; tone?: Tone }
export interface Gloss { t: number; term: string; th: string }
export interface ExplainItem { t: number; icon: string; text: string; tone?: Tone }
export interface Explain {
  title: string;
  sub?: string;
  layout: "flow" | "list" | "compare";
  left?: { title: string; icon: string; tone?: Tone };
  right?: { title: string; icon: string; tone?: Tone };
  items: ExplainItem[];
  footnote?: string;
}
export interface ChartBar { label: string; value: number; tone?: Tone; note?: string }
export interface Chart { title: string; sub?: string; bars: ChartBar[]; max?: number; unit?: string }
export interface TermLine { t: number; kind: "cmd" | "out" | "ok" | "warn" | "claude" | "add" | "del" | "dim"; text: string }
export interface Terminal { title: string; tag: string; lines: TermLine[] }
export interface NextTease { label?: string; items: string[]; tease?: string; t?: number; pill?: string }

export interface Beat {
  t: number;
  abs?: boolean;
  mode: "full" | "pip";
  media?: "web" | "broll" | "clip" | "typo" | "explain" | "chart" | "terminal" | "none";
  kicker?: string;
  // web
  file?: string;
  cssH?: number;
  cam?: CamKey[];
  hl?: Highlight[];
  // footage
  src?: string;
  from?: number;
  headline?: string;
  sub?: string;
  subT?: number;
  idx?: string;
  clipFit?: "cover" | "contain";
  hook?: boolean; // teaser typography (bigger)
  // typo
  typo?: "summary3" | "vs" | "final4" | "agenda" | "sting";
  // new stages
  explain?: Explain;
  chart?: Chart;
  terminal?: Terminal;
  // overlays
  stats?: Stat[];
  lower?: { title: string; sub: string; t?: number; dur?: number; tag?: string };
  next?: NextTease;
  gloss?: Gloss[];
}

// ---- Episode copy ---------------------------------------------------------
export const EPISODE = {
  assetDir: "fable-news",
  brand: "AI NEWS",
  dateLabel: "3 ก.ย. 2026",
  page: { domain: "anthropic.com", path: "/claude-fable-and-mythos-5-1" },
  captureLabel: "VERIFIED · จับภาพ 3 ก.ย. 2026",
  officialTag: "OFFICIAL · ANTHROPIC",
  previewTag: "PREVIEW",
  cta: { lead: "ลองใช้ได้เลยที่", text: "claude.ai" },
  sting: { eyebrow: "AI NEWS · SEPTEMBER 2026", titleA: "Claude Fable 5.1", amp: "&", titleB: "Mythos 5.1", sub: "เปิดตัวแล้ว · ข่าวเต็มใน 8 นาที" },
  endcard: {
    eyebrow: "AI NEWS · SEPTEMBER 2026",
    titleA: "Claude Fable 5.1",
    titleB: "Mythos 5.1",
    sub: "อ่านฉบับเต็ม · anthropic.com/claude-fable-and-mythos-5-1",
    cta: "ลองใช้ได้เลยที่ claude.ai",
    next: "ติดตามข่าว AI ย่อยง่ายทุกสัปดาห์ · กด Subscribe 🔔",
  },
  agendaLabel: "ใน 8 นาทีนี้",
  summary3Label: "สรุปง่าย ๆ",
  final4: { title: "Claude Fable 5.1", sub: "AI ที่ฉลาดที่สุดในโลกตอนนี้" },
  vs: {
    eyebrow: "AI ตัวเดียวกัน · ฉลาดเท่ากัน · ต่างกันที่ “ใครใช้ได้”",
    left: { title: "Fable 5.1", badge: "GENERALLY AVAILABLE", lines: ["ทุกคนใช้ได้เลย", "claude.ai · API", "Claude Code · Cowork"] },
    right: { title: "Mythos 5.1", badge: "TRUSTED ACCESS", lines: ["เฉพาะนักวิจัย · ผู้เชี่ยวชาญ", "สายวิทยาศาสตร์ · ไซเบอร์", "ที่ผ่านการตรวจสอบแล้วเท่านั้น"] },
    conclusion: "🔓 Mythos ปลดล็อคความสามารถที่ต้องใช้ความรับผิดชอบสูง",
  },
  thumbs: [
    { id: "A", lines: ["บั๊ก 1 ในล้าน", "5 ปีไม่มีใครหาเจอ"], accent: "Claude Fable 5.1 หาเจอ", accentTone: "amber" as Tone },
    { id: "B", lines: ["ฉลาดที่สุดในโลก", "แต่ถูกลง 25%"], accent: "Claude Fable 5.1", accentTone: "mint" as Tone },
    { id: "C", lines: ["Fable 5.1 vs Mythos 5.1", "ต่างกันตรงไหน?"], accent: "AI ตัวเดียวกัน", accentTone: "clay" as Tone },
  ],
};

// ---- Timeline (pre-lap teaser from the presenter's own lines) -------------
// Cut points snapped to silence with .claude/skills/Youtube-Web-News-Style01-V2/scripts/snap_cuts.py.
export const TIMELINE = {
  teaser: [
    { src: 117.4, end: 121.92 }, // "ไม่มีวิศวกรคนไหนหาสาเหตุเจอมาตลอด 4-5 ปี" (117.40 = dip between "ครั้ง" and "ไม่")
    { src: 125.74, end: 127.9 }, // "แต่พอลอง Claude Fable 5.1"
    { src: 132.1, end: 137.83 }, // "แล้วชี้ได้เลยว่าบั๊กอยู่ตรงไหน เป็นครั้งแรกในรอบ 5 ปีที่มีใครหาเจอค่ะ"
  ],
  stingDur: 2.6,
  mainSrcStart: 0.98, // skip "สวัสดีค่ะ"
  mainSrcEnd: 455.6, // last word end + 0.3 (VO_END of the source)
  endcardDur: 8.0,
};

export interface Segment { src: number; end: number; dst: number; dur: number }
export function segments(): { teaser: Segment[]; teaserDur: number; stingStart: number; mainDst: number; main: Segment; voEnd: number; total: number } {
  let dst = 0;
  const teaser: Segment[] = TIMELINE.teaser.map((s) => {
    const seg = { src: s.src, end: s.end, dst, dur: s.end - s.src };
    dst += seg.dur;
    return seg;
  });
  const teaserDur = dst;
  const stingStart = dst;
  const mainDst = dst + TIMELINE.stingDur;
  const main: Segment = { src: TIMELINE.mainSrcStart, end: TIMELINE.mainSrcEnd, dst: mainDst, dur: TIMELINE.mainSrcEnd - TIMELINE.mainSrcStart };
  const voEnd = mainDst + main.dur;
  return { teaser, teaserDur, stingStart, mainDst, main, voEnd, total: voEnd + TIMELINE.endcardDur };
}
export const SEG = segments();
export const mapMain = (src: number): number => src - TIMELINE.mainSrcStart + SEG.mainDst;
// teaser-local helper: src time inside teaser segment i -> timeline seconds
export const mapTeaser = (i: number, src: number): number => SEG.teaser[i].dst + (src - SEG.teaser[i].src);

// ---- Chapters (src times) ---------------------------------------------------
export const CHAPTERS: { src: number; title: string }[] = [
  { src: 0.98, title: "เปิดตัว 2 รุ่นใหม่" },
  { src: 43.52, title: "เก่งขึ้นยังไง" },
  { src: 101.7, title: "เคสจริง 4 บริษัท" },
  { src: 191.72, title: "ราคา" },
  { src: 213.86, title: "งานวิจัยวิทยาศาสตร์" },
  { src: 335.98, title: "ปลอดภัยไหม?" },
  { src: 398.8, title: "Fable vs Mythos" },
  { src: 424.2, title: "สรุป + มุมไทย" },
];

// ---- B-roll durations (public/fable-news/broll) -----------------------------
export const BROLL_DUR: Record<string, number> = {
  abstract: 30, ai_network: 30, brain: 10, chat_ai: 19.48, city_night: 22.36,
  coding: 14.96, cyber: 30, datacenter: 9.12, dna: 8.32, handshake: 11.48,
  lab: 15.2, microscope: 8, molecule: 18.64, nipah: 4.96, office: 14.8,
  protein: 14.2, server_lights: 23.52, shopping: 10, trading: 8, typing: 12.16,
  venus: 30, venus_volcano: 15, warehouse: 20.44,
  // generated signature shots (Imagen + Kling) — durations patched after transcode
  gen_glitch: 5.04, gen_protein: 5.04, gen_ident: 5.04,
};

// ---- Rect helpers -----------------------------------------------------------
export const R = (k: string): WebRect => WEB_RECTS[k] || { x: 230, y: 0, w: 600, h: 40 };
export const rowRect = (includes: string): WebRect => {
  const k = Object.keys(WEB_RECTS).find(
    (kk) => kk.startsWith("table_row") && (WEB_RECTS[kk].text || "").includes(includes) && WEB_RECTS[kk].w > 0
  );
  return k ? WEB_RECTS[k] : { x: 110, y: 216, w: 880, h: 72 };
};
export const colRect = (includes: string, rowKey: WebRect): WebRect => {
  const k = Object.keys(WEB_RECTS).find(
    (kk) => kk.startsWith("table_col") && (WEB_RECTS[kk].text || "").includes(includes)
  );
  const c = k ? WEB_RECTS[k] : { x: 330, w: 170, y: 0, h: 0 };
  return { x: c.x, y: rowKey.y, w: c.w, h: rowKey.h };
};

// ---- Terminal demo (a real run replayed as a synthetic recording; paste verbatim outputs)
export const TERMINAL_DEMO: Terminal = {
  title: "claude — billing (Thai POS)",
  tag: "DEMO · Claude Code",
  // Real session on 2026-09-03 (scratch repo `billing`, Python 3.12): outputs below are verbatim.
  lines: [
    { t: 0.0, kind: "cmd", text: "pytest fails in this repo. Find the ROOT CAUSE (not a symptom patch), fix it, run the tests again." },
    { t: 0.9, kind: "dim", text: "$ pytest -q" },
    { t: 1.4, kind: "warn", text: "FAILED tests/test_billing.py::test_line_total_rounds_half_up - assert 1.12 == 1.13" },
    { t: 1.8, kind: "out", text: "1 failed, 2 passed in 0.02s" },
    { t: 2.4, kind: "claude", text: "ต้นตอ: round() ของ Python ปัดแบบ banker's rounding → 1.125 กลายเป็น 1.12 ไม่ใช่ 1.13 แบบบัญชี" },
    { t: 3.2, kind: "dim", text: "$ python -c \"print(round(1.125, 2))\"   →  1.12" },
    { t: 3.7, kind: "dim", text: "Edit billing.py" },
    { t: 4.0, kind: "del", text: "-    return round(qty * unit_price, 2)" },
    { t: 4.3, kind: "add", text: "+    return _satang(qty * unit_price)   # Decimal(...).quantize(\"0.01\", ROUND_HALF_UP)" },
    { t: 4.9, kind: "dim", text: "$ pytest -q" },
    { t: 5.5, kind: "ok", text: "3 passed in 0.00s" },
    { t: 6.2, kind: "claude", text: "แก้ที่ต้นตอ: ใช้ ROUND_HALF_UP ทุกจุดที่ปัดเศษ ไม่ได้แก้แค่เทสต์ให้ผ่าน" },
  ],
};

// ---- Beats (src seconds unless abs) -----------------------------------------
export const BEATS: Beat[] = [
  // ===== PRE-LAP TEASER (timeline seconds) ===================================
  {
    t: 0.0, abs: true, mode: "pip", media: "broll", src: "gen_glitch", hook: true,
    headline: "บั๊ก 1 ในล้าน", sub: "5 ปี ไม่มีใครหาเจอ", subT: 1.1, kicker: "เรื่องจริงจาก Millennium",
    stats: [{ t: 2.3, big: "4–5 ปี", label: "ไม่มีวิศวกรคนไหนหาสาเหตุเจอ", tone: "clay" }],
  },
  {
    t: SEG.teaser[1].dst, abs: true, mode: "pip", media: "web", file: "quote_02", kicker: "แต่พอลอง Claude Fable 5.1…",
    cam: [{ t: 0, fy: 168, z: 1.46, fx: 535 }, { t: 8, fy: 168, z: 1.56, fx: 535 }],
    hl: [
      { t: SEG.teaser[1].dst + 0.2, key: "q_mill_million", th: "บั๊กที่เกิดแค่ 1 ในล้านครั้ง ทีมอธิบายไม่ได้มา 4–5 ปี" },
      { t: mapTeaser(2, 132.3), key: "q_mill_first", th: "Claude Fable 5.1 คือตัวแรกที่หาเจอ" },
    ],
    stats: [{ t: mapTeaser(2, 134.5), big: "ครั้งแรกใน 5 ปี", label: "ที่มีใครหาบั๊กนี้เจอ" }],
  },
  { t: SEG.stingStart, abs: true, mode: "full", media: "none", typo: "sting" },

  // ===== MAIN (src seconds) ==================================================
  { t: 0.98, mode: "full", lower: { title: "ข่าวใหญ่วงการ AI", sub: "Anthropic เปิดตัว Claude Fable 5.1 & Mythos 5.1", t: 1.3, dur: 4.8 } },
  { t: 6.42, mode: "pip", media: "typo", typo: "agenda", src: "gen_ident", kicker: "5 เรื่องที่ต้องรู้" },
  {
    t: 13.34, mode: "pip", media: "web", file: "sec_hero", kicker: "เปิดตัว 2 รุ่นใหม่พร้อมกัน",
    cam: [{ t: 0, fy: 400, z: 1.0 }, { t: 6.5, fy: 380, z: 1.1 }],
    stats: [{ t: 14.7, label: "🏢 Anthropic · บริษัท AI ระดับโลก" }, { t: 18.2, big: "2 รุ่น", label: "เปิดตัวพร้อมกัน" }],
  },
  {
    t: 20.06, mode: "pip", media: "web", file: "sec_hero", kicker: "Claude Fable 5.1 · Claude Mythos 5.1",
    cam: [{ t: 0, fy: 370, z: 1.28 }, { t: 4, fy: 360, z: 1.36 }],
    stats: [{ t: 20.3, big: "Fable 5.1", label: "เวอร์ชันสำหรับทุกคน" }, { t: 22.6, big: "Mythos 5.1", label: "เวอร์ชันนักวิจัย", tone: "clay" }],
  },
  {
    t: 24.1, mode: "pip", media: "broll", src: "chat_ai", headline: "Claude คืออะไร?", sub: "AI ผู้ช่วยอัจฉริยะ", subT: 27.2, kicker: "รู้จัก Claude",
    stats: [{ t: 29.4, label: "💬 พิมพ์คุยได้" }, { t: 30.4, label: "🧑‍💼 สั่งงานได้" }, { t: 31.6, label: "🪄 เหมือนมีเลขาส่วนตัวที่ฉลาดมาก" }],
  },
  {
    t: 34.0, mode: "pip", media: "broll", src: "office", from: 1, headline: "ช่วยได้ทุกงาน", kicker: "รู้จัก Claude",
    stats: [{ t: 34.3, label: "✍️ เขียนงาน" }, { t: 35.5, label: "📊 วิเคราะห์ข้อมูล" }, { t: 37.2, label: "💻 เขียนโปรแกรม" }, { t: 39.0, label: "💡 คิดไอเดียธุรกิจ" }],
  },
  { t: 41.3, mode: "full", next: { label: "เก่งขึ้น 3 ข้อ", items: ["💻 เขียนโค้ด", "📄 งานความรู้", "🧠 แก้ปัญหายาก"], t: 41.8 } },
  // ---- 3 upgrades -------------------------------------------------------
  { t: 43.52, mode: "pip", media: "terminal", terminal: TERMINAL_DEMO, idx: "01", headline: "เขียนโค้ดเก่งที่สุดในโลก", kicker: "เก่งขึ้นยังไง · ข้อ 1" },
  {
    t: 51.0, mode: "pip", media: "web", file: "sec_table", kicker: "ผลทดสอบ Agentic coding",
    cam: [{ t: 0, fy: 300, z: 1.2 }, { t: 2.5, fy: 300, z: 1.24 }],
    hl: [
      { t: 51.2, rect: colRect("Fable 5.1", rowRect("Fable 5.1 Fable 5")) },
      { t: 51.9, rect: rowRect("Agentic coding Terminal"), th: "เขียนโค้ดแบบเอเจนต์ · ข้อสอบ Terminal-Bench 4.0" },
    ],
    stats: [{ t: 52.3, big: "55.8%", label: "Fable 5.1 · Terminal-Bench 4.0" }],
  },
  {
    t: 53.3, mode: "pip", media: "chart", kicker: "ชนะ AI ของทุกบริษัท", src: "gen_ident",
    chart: {
      title: "Terminal-Bench 4.0 · เขียนโค้ดแบบเอเจนต์", sub: "ยิ่งสูงยิ่งดี · ตัวเลขจาก anthropic.com", unit: "%", max: 70,
      bars: [
        { label: "Claude Fable 5.1", value: 55.8, tone: "amber", note: "Mythos 5.1 = 60.9%" },
        { label: "Claude Opus 5", value: 52.3 },
        { label: "Claude Fable 5", value: 42.0 },
        { label: "GPT-5.6 Sol · OpenAI", value: 37.3, tone: "clay" },
      ],
    },
    gloss: [{ t: 53.6, term: "Benchmark", th: "ข้อสอบมาตรฐาน ให้ AI ทุกตัวทำโจทย์เดียวกันแล้วเทียบคะแนน" }],
  },
  {
    t: 57.8, mode: "pip", media: "broll", src: "office", from: 5, idx: "02", headline: "งานความรู้ทั่วไป", kicker: "เก่งขึ้นยังไง · ข้อ 2",
    stats: [{ t: 60.4, label: "📄 วิเคราะห์เอกสาร" }, { t: 62.0, label: "📝 ทำรายงาน" }, { t: 63.9, label: "🧾 สรุปข้อมูล" }],
  },
  {
    t: 65.17, mode: "pip", media: "web", file: "quote_10", kicker: "ละเอียดขึ้น · แม่นยำขึ้น · อ่านง่ายขึ้น",
    cam: [{ t: 0, fy: 168, z: 1.46, fx: 535 }, { t: 7, fy: 168, z: 1.54, fx: 535 }],
    hl: [{ t: 69.5, key: "q_canva_writing", th: "อ่านเข้าใจง่ายขึ้น มีความหมายมากขึ้น" }],
    stats: [{ t: 65.6, label: "🗣️ Canva · Head of AI" }],
  },
  {
    t: 73.06, mode: "pip", media: "web", file: "quote_00", kicker: "งานยาวแค่ไหน ผลลัพธ์ก็ยังอ่านรู้เรื่อง",
    cam: [{ t: 0, fy: 168, z: 1.46, fx: 535 }, { t: 8, fy: 168, z: 1.54, fx: 535 }],
    hl: [{ t: 77.4, key: "q_js_readable", th: "ยังอ่านรู้เรื่อง แม้เป็นงานยาวหลายขั้นตอน" }],
    stats: [{ t: 73.5, label: "🗣️ Jane Street Capital" }],
  },
  { t: 82.2, mode: "pip", media: "broll", src: "brain", idx: "03", headline: "แก้ปัญหาที่ยากมาก ๆ", sub: "คิดลึก · หาต้นตอของปัญหา", subT: 86.5, kicker: "เก่งขึ้นยังไง · ข้อ 3" },
  {
    t: 85.78, mode: "pip", media: "web", file: "sec_millennium", kicker: "ไม่ใช่แค่แก้ที่ปลายเหตุ",
    cam: [{ t: 0, fy: 120, z: 1.56 }, { t: 12, fy: 120, z: 1.64 }],
    hl: [
      { t: 87.8, key: "mill_avoid", th: "ไม่ใช้ทางลัดที่ทำให้งานคุณภาพต่ำลง" },
      { t: 90.5, key: "mill_root", th: "แก้ที่ต้นตอของปัญหาซอฟต์แวร์" },
      { t: 96.0, key: "mill_none", th: "ไม่มีวิศวกร (หรือ AI ตัวไหน) อธิบายได้มาหลายปี" },
    ],
    stats: [{ t: 98.4, label: "🔎 Claude Fable 5.1 หาสาเหตุจริง ๆ" }],
  },
  { t: 101.7, mode: "full", next: { label: "เคสจริง 4 บริษัท", items: ["Millennium", "MongoDB", "Rakuten", "Shopify"], tease: "แล้วราคาล่ะ? อีกไม่ถึง 2 นาที", t: 102.4 } },
  // ---- customer stories -------------------------------------------------
  { t: 108.2, mode: "pip", media: "broll", src: "trading", idx: "CASE 1", headline: "Millennium", sub: "บริษัทการเงินระดับโลก", subT: 109.5, kicker: "ตัวอย่างจากบริษัทจริง" },
  {
    t: 111.56, mode: "pip", media: "web", file: "quote_02", kicker: "Millennium · บั๊กที่ไม่มีใครหาเจอ",
    cam: [{ t: 0, fy: 168, z: 1.46, fx: 535 }, { t: 12, fy: 168, z: 1.54, fx: 535 }],
    hl: [
      { t: 116.4, key: "q_mill_million", th: "บั๊กที่เกิดแค่ 1 ในล้านครั้ง" },
      { t: 121.0, key: "q_mill_years", th: "ทีมพยายามมา 4–5 ปี ก็ยังอธิบายไม่ได้" },
    ],
    stats: [{ t: 117.1, big: "1 ใน 1,000,000", label: "โอกาสเกิดบั๊ก" }, { t: 121.3, big: "4–5 ปี", label: "ไม่มีใครหาสาเหตุเจอ", tone: "clay" }],
  },
  {
    t: 125.62, mode: "pip", media: "broll", src: "coding", from: 6, headline: "แกะโค้ด · วิเคราะห์ crash", sub: "หาต้นตอที่ซ่อนอยู่ในระบบภายนอก", subT: 128.7, kicker: "Millennium",
    gloss: [{ t: 131.4, term: "crash", th: "โปรแกรมล่ม/ค้างกะทันหัน" }],
  },
  {
    t: 132.02, mode: "pip", media: "web", file: "quote_02", kicker: "Millennium · ครั้งแรกในรอบ 5 ปี",
    cam: [{ t: 0, fy: 168, z: 1.52, fx: 535 }, { t: 6, fy: 168, z: 1.6, fx: 535 }],
    hl: [{ t: 133.0, key: "q_mill_first", th: "Claude Fable 5.1 คือตัวแรกที่หาเจอ" }],
  },
  { t: 134.3, mode: "full", lower: { tag: "MILLENNIUM", title: "ครั้งแรกในรอบ 5 ปี", sub: "ที่มีใครหาบั๊กนี้เจอ", t: 134.6, dur: 3.4 } },
  { t: 138.7, mode: "pip", media: "broll", src: "datacenter", idx: "CASE 2", headline: "MongoDB", sub: "สร้าง prototype ระบบใหม่", subT: 140.5, kicker: "ตัวอย่างจากบริษัทจริง" },
  {
    t: 141.9, mode: "pip", media: "web", file: "quote_03", kicker: "MongoDB · ทำงานเองจนเสร็จ",
    cam: [{ t: 0, fy: 168, z: 1.46, fx: 535 }, { t: 5, fy: 168, z: 1.52, fx: 535 }],
    hl: [{ t: 145.4, key: "q_mongo_3days", th: "สร้างต้นแบบระบบที่ซับซ้อนเสร็จใน 3 วัน" }],
    gloss: [{ t: 143.4, term: "prototype", th: "ต้นแบบระบบ สร้างเพื่อทดลองก่อนทำของจริง" }],
    stats: [{ t: 146.1, big: "3 วัน", label: "สร้าง prototype เสร็จ" }],
  },
  {
    t: 146.8, mode: "pip", media: "explain", src: "gen_ident", kicker: "MongoDB · ทำงานเองข้ามคืน",
    explain: {
      title: "ทำงานเองข้ามคืน ไม่ต้องมีคนคอยดู", layout: "flow",
      items: [
        { t: 147.0, icon: "🌙", text: "สั่งงานตอนเย็น" },
        { t: 148.4, icon: "🤖", text: "AI ทำงานเองหลายชั่วโมง" },
        { t: 150.1, icon: "🌅", text: "ตื่นเช้ามา งานเสร็จ" },
        { t: 152.3, icon: "📝", text: "พร้อมสรุปว่าทำอะไรไปบ้าง" },
      ],
    },
  },
  { t: 155.7, mode: "pip", media: "broll", src: "microscope", idx: "CASE 3", headline: "Rakuten", sub: "ตรวจสอบงานวิจัยทางคลินิก", subT: 157.5, kicker: "ตัวอย่างจากบริษัทจริง" },
  {
    t: 160.1, mode: "pip", media: "web", file: "quote_07", kicker: "Rakuten · เจอสิ่งที่ AI อื่นมองข้าม",
    cam: [{ t: 0, fy: 168, z: 1.46, fx: 535 }, { t: 7, fy: 168, z: 1.52, fx: 535 }],
    hl: [{ t: 162.9, key: "q_rak_three", th: "AI ตัวอื่นอีก 3 ตัว ตรวจแล้วว่าผ่าน" }],
    stats: [{ t: 163.2, big: "AI 3 ตัว", label: "ตรวจแล้วบอกว่า “ผ่าน”", tone: "clay" }],
  },
  {
    t: 167.0, mode: "pip", media: "explain", src: "gen_ident", kicker: "Rakuten · ใครเจอจุดบกพร่อง?",
    explain: {
      title: "งานวิจัยชิ้นเดียวกัน ตรวจ 4 ครั้ง", layout: "compare",
      left: { title: "AI อีก 3 ตัว: “ผ่าน”", icon: "✅✅✅", tone: "clay" },
      right: { title: "Fable 5.1: เจอจุดบกพร่อง", icon: "⚠️", tone: "amber" },
      items: [
        { t: 170.6, icon: "🧪", text: "แล้วยังเสนอสมมติฐานใหม่" },
        { t: 173.7, icon: "⏱️", text: "เปิดทิศทางวิจัยใหม่ ภายในบ่ายเดียว" },
      ],
    },
  },
  { t: 176.3, mode: "pip", media: "broll", src: "warehouse", idx: "CASE 4", headline: "Shopify", sub: "ทำงานยาว ๆ ได้ดีมาก", subT: 178.8, kicker: "ตัวอย่างจากบริษัทจริง" },
  {
    t: 179.9, mode: "pip", media: "web", file: "quote_17", kicker: "Shopify · ทำงานหลายชั่วโมงไม่หลุดประเด็น",
    cam: [{ t: 0, fy: 168, z: 1.46, fx: 535 }, { t: 12, fy: 168, z: 1.54, fx: 535 }],
    hl: [{ t: 181.4, key: "q_shop_long", th: "งานยาว ๆ ที่ปล่อยให้ทำเองโดยไม่มีคนดู" }],
    stats: [{ t: 183.1, label: "⏱️ ปล่อยทำงานหลายชั่วโมง" }, { t: 185.0, label: "🗒️ จดบันทึกเอง · จัดลำดับเอง" }, { t: 188.5, label: "▶️ ทำต่อจากจุดที่ค้างไว้" }],
  },
  // ---- pricing ----------------------------------------------------------
  {
    t: 191.72, mode: "pip", media: "web", file: "sec_cost", kicker: "ราคา · ถูกลงกว่าเดิม",
    cam: [{ t: 0, fy: 330, z: 1.2 }, { t: 3.5, fy: 380, z: 1.2 }, { t: 7.5, fy: 880, z: 1.05 }, { t: 16, fy: 880, z: 1.1 }],
    hl: [{ t: 194.5, key: "cost_25", th: "ค่าใช้จ่ายลดลงราว 25% เทียบกับ Fable 5" }, { t: 202.0, key: "cost_45", th: "งานหนัก ๆ ประหยัดได้ถึงราว 45%" }],
    stats: [{ t: 198.3, big: "−25%", label: "งานทั่วไป", tone: "mint" }, { t: 206.1, big: "−45%", label: "งานหนัก / agentic", tone: "mint" }],
  },
  { t: 208.1, mode: "pip", media: "typo", typo: "summary3", src: "gen_ident", kicker: "สรุปง่าย ๆ" },
  { t: 213.86, mode: "full", next: { label: "เรื่องที่น่าทึ่งที่สุด", items: ["💊 ออกแบบยา ดีกว่ามนุษย์ 10×", "🪐 แผนที่ดาวศุกร์ใหม่", "🧬 วิจัยชีววิทยาเร็วขึ้น 2.5×"], t: 214.4 } },
  // ---- science ----------------------------------------------------------
  { t: 219.4, mode: "pip", media: "broll", src: "lab", headline: "งานวิจัยวิทยาศาสตร์", sub: "อาจเปลี่ยนโลกไปเลย", subT: 223.2, kicker: "เรื่องที่น่าทึ่งที่สุด" },
  {
    t: 225.9, mode: "pip", media: "web", file: "sec_science", idx: "01", kicker: "① การออกแบบยา",
    cam: [{ t: 0, fy: 130, z: 1.1 }, { t: 4, fy: 300, z: 1.22 }, { t: 8, fy: 330, z: 1.22 }],
    hl: [{ t: 227.6, key: "sci_title", th: "การออกแบบโมเลกุล" }],
  },
  { t: 233.96, mode: "pip", media: "broll", src: "gen_protein", headline: "โปรตีนจับเป้าหมายในร่างกาย", sub: "เหมือนกุญแจที่ต้องเข้ากับแม่กุญแจพอดี", subT: 238.0, kicker: "① การออกแบบยา" },
  { t: 240.74, mode: "pip", media: "clip", src: "nipah", headline: "Claude Mythos 5.1 ออกแบบโปรตีน", sub: "ที่มา: anthropic.com — โปรตีนที่ Claude ออกแบบ (สีส้ม) จับเป้าหมาย (สีเทา)", subT: 245.6, kicker: "① การออกแบบยา" },
  { t: 247.5, mode: "pip", media: "broll", src: "lab", from: 7, headline: "ทดสอบในห้องแล็บจริง", sub: "ผลปรากฏว่า…", subT: 251.0, kicker: "① การออกแบบยา" },
  {
    t: 253.6, mode: "pip", media: "web", file: "sec_science", kicker: "ก้าวกระโดดในวงการยา",
    cam: [{ t: 0, fy: 470, z: 1.32 }, { t: 14, fy: 490, z: 1.38 }],
    hl: [
      { t: 254.9, key: "sci_10x", th: "จับได้แน่นกว่าแบบที่ดีที่สุดถึง 10 เท่า" },
      { t: 257.6, key: "sci_50", th: "สำเร็จเกือบ 50% จาก 12 เป้าหมาย" },
      { t: 261.3, key: "sci_1015", th: "ปกติวงการนี้สำเร็จแค่ 10–15%" },
    ],
    stats: [{ t: 255.3, big: "10×", label: "จับได้ดีกว่าของมนุษย์", tone: "mint" }, { t: 257.8, big: "~50%", label: "อัตราสำเร็จ", tone: "mint" }, { t: 261.4, big: "10–15%", label: "ปกติทั่วไป", tone: "clay" }],
    gloss: [{ t: 264.5, term: "ก้าวกระโดด", th: "จากสำเร็จ 10–15% เป็นเกือบ 50% = ดีขึ้น 3–5 เท่าในก้าวเดียว" }],
  },
  { t: 268.0, mode: "pip", media: "broll", src: "venus", idx: "02", headline: "แผนที่ดาวศุกร์ใหม่", sub: "จากข้อมูลยาน NASA Magellan เมื่อ 30 ปีก่อน", subT: 272.0, kicker: "② แผนที่ดาวศุกร์" },
  {
    t: 276.37, mode: "pip", media: "clip", src: "venus_volcano", clipFit: "cover", headline: "ภูเขาไฟบนดาวศุกร์", sub: "ที่มา: anthropic.com — แผนที่ความสูงใหม่ที่ Claude สร้าง", subT: 283.0, kicker: "② แผนที่ดาวศุกร์",
    stats: [{ t: 279.7, big: "10–20 km", label: "ความละเอียดแผนที่เดิม", tone: "clay" }, { t: 288.0, big: "2–3 km", label: "แผนที่ใหม่", tone: "mint" }],
  },
  {
    t: 289.73, mode: "pip", media: "web", file: "sec_venus", kicker: "② แผนที่ดาวศุกร์ · แจกฟรีทั่วโลก",
    cam: [{ t: 0, fy: 190, z: 1.26 }, { t: 12, fy: 230, z: 1.3 }],
    hl: [
      { t: 290.6, key: "venus_25", th: "แม่นยำขึ้นถึง 25%" },
      { t: 294.2, key: "venus_release", th: "เปิดให้ทุกคนดาวน์โหลดแผนที่นี้" },
      { t: 296.2, key: "venus_cc", th: "ภายใต้สัญญาอนุญาต Creative Commons" },
    ],
    gloss: [{ t: 296.4, term: "Creative Commons", th: "สัญญาอนุญาตที่ให้ทุกคนนำไปใช้ฟรีได้" }],
    stats: [{ t: 291.0, big: "+25%", label: "แม่นยำขึ้นกว่าเดิม", tone: "mint" }, { t: 296.7, label: "🌍 แจกฟรี · Creative Commons" }],
  },
  { t: 302.1, mode: "pip", media: "broll", src: "dna", idx: "03", headline: "งานวิจัยชีววิทยา", sub: "วิเคราะห์ยีน · โปรตีน", subT: 304.5, kicker: "③ ชีววิทยา" },
  {
    t: 305.78, mode: "pip", media: "explain", src: "server_lights", kicker: "③ ชีววิทยา · ทำไมช้าและแพง",
    explain: {
      title: "ทำไมงานวิจัยชีววิทยาถึงช้าและแพง", layout: "flow",
      items: [
        { t: 306.0, icon: "🧬", text: "รันโมเดล AI วิเคราะห์ยีน/โปรตีน" },
        { t: 308.4, icon: "🖥️", text: "ต้องใช้ GPU ระดับสูง → ช้า · แพง" },
        { t: 310.2, icon: "🧑‍💻", text: "Claude เข้าไปปรับโค้ดให้เร็วขึ้น" },
      ],
    },
  },
  {
    t: 311.48, mode: "pip", media: "web", file: "sec_compbio", kicker: "Claude ปรับแต่งโค้ดของโมเดล",
    cam: [{ t: 0, fy: 150, z: 1.36 }, { t: 6, fy: 170, z: 1.42 }],
    hl: [
      { t: 312.5, key: "bio_slow", th: "ความเร็วของโมเดลจึงเป็นคอขวดของงานวิจัย" },
      { t: 315.8, key: "bio_kernels", th: "เขียน GPU kernel เอง + เก็บผลลัพธ์ระหว่างทางไว้ใช้ซ้ำ" },
    ],
    gloss: [{ t: 316.0, term: "GPU kernel", th: "โค้ดชิ้นเล็กที่สั่งการ์ดจอโดยตรง ให้คำนวณเร็วขึ้น" }],
  },
  {
    t: 317.86, mode: "pip", media: "web", file: "bio_chart_0", cssH: 724, kicker: "เร็วขึ้น · ถูกลง",
    cam: [{ t: 0, fy: 330, z: 1.08 }, { t: 7, fy: 350, z: 1.14 }],
    stats: [{ t: 319.9, big: "2.5×", label: "เร็วขึ้นสูงสุด", tone: "mint" }, { t: 322.8, big: "−30–60%", label: "ลดค่าใช้จ่าย", tone: "mint" }],
  },
  {
    t: 325.06, mode: "pip", media: "web", file: "sec_compbio", kicker: "จากเป็นสัปดาห์ → ไม่กี่วัน",
    cam: [{ t: 0, fy: 330, z: 1.4 }, { t: 10, fy: 350, z: 1.46 }],
    hl: [
      { t: 326.4, key: "bio_weeks", th: "ปกติทีมวิศวกรต้องใช้เวลาเป็นสัปดาห์" },
      { t: 331.5, key: "bio_open", th: "เตรียมเปิดซอร์สโค้ดนี้ให้ใช้ฟรีเร็ว ๆ นี้" },
    ],
    stats: [{ t: 327.6, big: "สัปดาห์ → วัน", label: "งานทีมวิศวกร" }, { t: 333.3, label: "🔓 เปิดโค้ดให้ทุกคนใช้ฟรี" }],
  },
  { t: 335.98, mode: "full", next: { label: "ปลอดภัยไหม?", items: ["🛡️ ทดสอบก่อนปล่อย", "🔒 ข้อมูลอยู่กับบริษัทคุณ", "⚖️ Fable vs Mythos ต่างกันยังไง"], t: 336.6 } },
  // ---- safety -----------------------------------------------------------
  {
    t: 341.12, mode: "pip", media: "web", file: "sec_safety", kicker: "ความปลอดภัย",
    cam: [{ t: 0, fy: 120, z: 1.1 }, { t: 3, fy: 300, z: 1.24 }, { t: 6, fy: 320, z: 1.24 }],
    hl: [{ t: 343.8, key: "safety_testing", th: "ทดสอบความเสี่ยงอย่างเข้มข้นหลายด้าน" }],
  },
  {
    t: 347.16, mode: "pip", media: "broll", src: "cyber", headline: "ทดสอบเข้มข้นก่อนปล่อย", kicker: "ความปลอดภัย",
    stats: [{ t: 349.0, label: "🛡️ ความปลอดภัยไซเบอร์" }, { t: 352.3, label: "🧬 ป้องกันการสร้างอาวุธชีวภาพ" }, { t: 355.6, label: "🎭 ป้องกันคนร้ายหลอก AI" }],
  },
  {
    t: 357.08, mode: "pip", media: "web", file: "sec_cyber", kicker: "ตรวจสอบโดยทีมภายใน + ผู้เชี่ยวชาญภายนอก",
    cam: [{ t: 0, fy: 200, z: 1.4 }, { t: 7, fy: 220, z: 1.46 }],
    hl: [
      { t: 358.9, key: "cyber_external", th: "จ้างองค์กรภายนอก 2 แห่งมาทดสอบ" },
      { t: 360.6, key: "cyber_gray", th: "Gray Swan · บริษัททดสอบความปลอดภัย AI" },
      { t: 362.2, key: "cyber_jailbreak", th: "การหลอก AI ให้ทำผิดกฎ ระดับร้ายแรง" },
    ],
    gloss: [{ t: 362.4, term: "jailbreak", th: "การหลอกล่อให้ AI ข้ามกฎความปลอดภัย" }],
  },
  {
    t: 364.19, mode: "pip", media: "web", file: "sec_efs", kicker: "Enterprise Frontier Safeguards",
    cam: [{ t: 0, fy: 120, z: 1.4 }, { t: 5, fy: 150, z: 1.46 }, { t: 12, fy: 160, z: 1.46 }],
    hl: [
      { t: 364.4, key: "efs_title", th: "ระบบป้องกันสำหรับองค์กร" },
      { t: 369.6, key: "efs_store", th: "ลูกค้าเก็บข้อมูลบนคลาวด์ของตัวเอง ไม่ใช่ระบบของ Anthropic" },
    ],
    stats: [{ t: 373.9, big: "ไม่เก็บ", label: "Anthropic", tone: "mint" }, { t: 374.7, big: "ไม่เห็น", label: "ข้อมูลของคุณ", tone: "mint" }, { t: 375.4, big: "ไม่แตะ", label: "เลย", tone: "mint" }],
  },
  {
    t: 376.5, mode: "pip", media: "explain", src: "server_lights", from: 8, kicker: "Enterprise Frontier Safeguards",
    explain: {
      title: "ข้อมูลบริษัทคุณอยู่ที่ไหน?", layout: "compare",
      left: { title: "แบบทั่วไป: ข้อมูลไปอยู่ที่ระบบ AI", icon: "☁️", tone: "clay" },
      right: { title: "EFS: ข้อมูลอยู่ในระบบบริษัทคุณเอง", icon: "🏢", tone: "mint" },
      items: [
        { t: 377.6, icon: "🚫", text: "Anthropic ไม่เก็บ · ไม่เห็น · ไม่แตะ" },
        { t: 379.2, icon: "🔒", text: "ปลอดภัยสำหรับข้อมูลธุรกิจ" },
      ],
    },
  },
  {
    t: 381.2, mode: "pip", media: "web", file: "sec_precise", kicker: "ลดการบล็อกผิดพลาด",
    cam: [{ t: 0, fy: 130, z: 1.26 }, { t: 5, fy: 150, z: 1.3 }],
    hl: [{ t: 383.0, key: "precise_benign", th: "บล็อกคำถามปกติน้อยลง" }],
    stats: [{ t: 383.6, label: "🚫 ระบบเดิมเข้มเกินไป · บล็อกคำถามปกติ" }],
  },
  {
    t: 386.84, mode: "pip", media: "web", file: "sec_precise", kicker: "รุ่นนี้แก้แล้ว",
    cam: [{ t: 0, fy: 400, z: 1.3 }, { t: 11, fy: 420, z: 1.34 }],
    hl: [
      { t: 390.6, key: "precise_60", th: "แทรกแซงน้อยลงราว 60% ต่อเซสชัน" },
      { t: 393.4, key: "precise_85", th: "บล็อกคำถามปกติน้อยลง 85%" },
    ],
    stats: [{ t: 390.8, big: "−60%", label: "บล็อกผิดพลาด · งานไซเบอร์", tone: "mint" }, { t: 393.6, big: "−85%", label: "บล็อกผิดพลาด · งานชีววิทยา", tone: "mint" }],
  },
  { t: 398.8, mode: "full", next: { label: "Fable 5.1 vs Mythos 5.1", items: ["🟰 AI ตัวเดียวกัน ฉลาดเท่ากัน", "🔓 ต่างกันที่ “ใครใช้ได้”"], t: 399.4 } },
  // ---- Fable vs Mythos --------------------------------------------------
  {
    t: 402.9, mode: "pip", media: "web", file: "sec_trusted", kicker: "Fable 5.1 vs Mythos 5.1",
    cam: [{ t: 0, fy: 140, z: 1.26 }, { t: 5, fy: 150, z: 1.3 }],
    hl: [{ t: 403.9, key: "trusted_identical", th: "Mythos 5.1 คือตัวเดียวกับ Fable 5.1 แต่ผ่อนปรนกว่า สำหรับคน/องค์กรที่ผ่านการตรวจสอบ" }],
    stats: [{ t: 404.2, big: "AI ตัวเดียวกัน", label: "ฉลาดเท่ากัน" }],
  },
  { t: 407.97, mode: "pip", media: "typo", typo: "vs", src: "gen_ident", from: 1, kicker: "Fable 5.1 vs Mythos 5.1" },
  { t: 424.2, mode: "full" },
  { t: 426.31, mode: "pip", media: "typo", typo: "final4", src: "city_night", kicker: "สรุปสุดท้าย" },
  {
    t: 434.32, mode: "pip", media: "explain", src: "city_night", from: 9, kicker: "มุมไทย 🇹🇭",
    explain: {
      title: "สำหรับคนไทย ใช้ได้เลยวันนี้", layout: "list",
      items: [
        { t: 434.7, icon: "🌐", text: "claude.ai บนเว็บ + แอป iOS / Android" },
        { t: 437.2, icon: "🆓", text: "แผนฟรี มีให้ใช้" },
        { t: 439.6, icon: "💳", text: "Pro $20/เดือน ≈ ฿660" },
        { t: 442.0, icon: "🇹🇭", text: "พิมพ์คุยภาษาไทยได้เลย" },
      ],
      footnote: "ราคา: claude.com/pricing · อัตรา ฿33.2/USD (3 ก.ย. 2026)",
    },
  },
  { t: 446.4, mode: "full", next: { pill: "แล้วเจอกันคลิปหน้า", items: ["🔔 กด Subscribe · ข่าว AI ย่อยง่ายทุกสัปดาห์"], t: 452.0 } },
];

// Typo scene word times (src)
export const AGENDA = [
  { t: 6.6, text: "เก่งขึ้นยังไง", icon: "💻" },
  { t: 7.5, text: "เคสจริง 4 บริษัท", icon: "🏢" },
  { t: 8.4, text: "ราคา", icon: "💸" },
  { t: 9.3, text: "งานวิจัยวิทยาศาสตร์", icon: "🔬" },
  { t: 10.3, text: "ปลอดภัย + Fable vs Mythos", icon: "🛡️" },
];
export const SUMMARY3 = [{ t: 209.5, text: "ฉลาดขึ้น", icon: "🧠" }, { t: 210.5, text: "เก่งขึ้น", icon: "🚀" }, { t: 211.7, text: "ถูกลง", icon: "💸" }];
export const FINAL4 = [{ t: 428.3, text: "ฉลาดที่สุดในโลก", icon: "🧠" }, { t: 430.2, text: "ใช้งานง่าย", icon: "✨" }, { t: 431.4, text: "ราคาถูกลง", icon: "💸" }, { t: 432.6, text: "ปลอดภัยมากขึ้น", icon: "🛡️" }];
// vs card: each line lands on its word (left = Fable, right = Mythos)
export const VS = { fableT: 408.8, mythosT: 410.6, subT: 420.0, leftLines: [409.1, 409.6, 409.9], rightLines: [412.7, 414.6, 416.8] };
export const CTA_T = 448.7;

// Marquee numbers: the music bed dips right before these (src seconds)
export const MUSIC_DIPS = [117.1, 146.1, 198.3, 255.3, 319.9, 393.6];

// ---- Timeline-space views (what the engine and the audio scripts consume) ----
const shiftBeat = (b: Beat): Beat => {
  if (b.abs) return b;
  const M = mapMain;
  return {
    ...b,
    t: M(b.t),
    subT: b.subT === undefined ? undefined : M(b.subT),
    hl: b.hl?.map((h) => ({ ...h, t: M(h.t) })),
    stats: b.stats?.map((s) => ({ ...s, t: M(s.t) })),
    gloss: b.gloss?.map((g) => ({ ...g, t: M(g.t) })),
    lower: b.lower ? { ...b.lower, t: b.lower.t === undefined ? undefined : M(b.lower.t) } : undefined,
    next: b.next ? { ...b.next, t: b.next.t === undefined ? undefined : M(b.next.t) } : undefined,
    explain: b.explain ? { ...b.explain, items: b.explain.items.map((it) => ({ ...it, t: M(it.t) })) } : undefined,
  };
};
export const BEATS_TL: Beat[] = BEATS.map(shiftBeat).sort((a, b) => a.t - b.t);
export const AGENDA_TL = AGENDA.map((x) => ({ ...x, t: mapMain(x.t) }));
export const SUMMARY3_TL = SUMMARY3.map((x) => ({ ...x, t: mapMain(x.t) }));
export const FINAL4_TL = FINAL4.map((x) => ({ ...x, t: mapMain(x.t) }));
export const VS_TL = { fableT: mapMain(VS.fableT), mythosT: mapMain(VS.mythosT), subT: mapMain(VS.subT), leftLines: VS.leftLines.map(mapMain), rightLines: VS.rightLines.map(mapMain) };
export const CTA_TL = mapMain(CTA_T);
export const CHAPTERS_TL = CHAPTERS.map((c) => ({ ...c, t: mapMain(c.src) }));
export const VO_END_TL = SEG.voEnd;
export const TOTAL_TL = SEG.total;
