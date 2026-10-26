// ===========================================================================
// Haiku55NewsYT V2 — EPISODE DATA (pure TypeScript, no React)
// Topic: Introducing Claude Haiku 5.5 (Anthropic Announcement)
// ===========================================================================
import { WEB_RECTS, type WebRect } from "./haiku55V2Web";

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
  assetDir: "haiku55_v2",
  brand: "AI NEWS",
  dateLabel: "7 ต.ค. 2026",
  page: { domain: "anthropic.com", path: "/claude-haiku-5-5" },
  captureLabel: "VERIFIED · จับภาพ 9 ต.ค. 2026",
  officialTag: "OFFICIAL · ANTHROPIC",
  previewTag: "PREVIEW",
  cta: { lead: "อ่านประกาศฉบับเต็มได้ที่", text: "anthropic.com/claude-haiku-5-5" },
  sting: {
    eyebrow: "AI NEWS SPECIAL · 2026",
    titleA: "Claude",
    amp: "Haiku",
    titleB: "5.5",
    sub: "Anthropic เปิดตัวโมเดลเล็กตัวใหม่ · เร็วสุด ฉลาดสุด ประหยัด 75%",
  },
  endcard: {
    eyebrow: "AI NEWS · 2026",
    titleA: "Claude Haiku 5.5",
    titleB: "Fastest & Cheapest AI",
    sub: "อ่านรายละเอียดฉบับเต็มที่ anthropic.com/claude-haiku-5-5",
    cta: "เปิดใช้งานแล้ววันนี้บนทุกคลาวด์",
    next: "ติดตามข่าวสารเทคโนโลยี AI เข้าใจง่าย · กด Subscribe 🔔",
  },
  agendaLabel: "ในคลิปนี้",
  summary3Label: "สรุปหัวใจสำคัญ",
  final4: { title: "Claude Haiku 5.5", sub: "เทคโนโลยีระดับโลก ในราคาที่ทุกคนจับต้องได้" },
  vs: {
    eyebrow: "สรุปการเปรียบเทียบ · AI รุ่นใหญ่ vs Claude Haiku 5.5",
    left: {
      title: "AI รุ่นใหญ่ (อาจารย์ใหญ่) 🎓",
      badge: "DEEP THINKER",
      lines: ["รู้ลึก รู้เยอะ วิเคราะห์ซับซ้อน", "ตัวใหญ่และคิดช้ากว่า", "เหมาะกับงานวิจัย ออกแบบระบบ"],
    },
    right: {
      title: "Claude Haiku 5.5 ⚡",
      badge: "FAST RUNNER",
      lines: ["เร็วที่สุด ประหยัดที่สุด 75%", "ตอบทันที ไม่ต้องรอนาน", "เหมาะกับงาน High-Volume ทุกวัน"],
    },
    conclusion: "💡 แนะนำ: ใช้ Haiku 5.5 เป็นหัวหอกงานประจำวัน และเป็น Subagent ช่วยโมเดลใหญ่",
  },
  thumbs: [
    { id: "A", lines: ["Anthropic เปิดตัว", "Claude Haiku 5.5"], accent: "เร็วสุด ประหยัดสุด 75%", accentTone: "amber" as Tone },
    { id: "B", lines: ["AI น้องเล็กสุดฉลาด", "เปลี่ยนชีวิตเรายังไง?"], accent: "ไม่ใช่แค่โปรแกรมเมอร์", accentTone: "mint" as Tone },
    { id: "C", lines: ["เจาะลึก Haiku 5.5", "สรุปจบใน 7 นาที"], accent: "ฉลาดล้ำ ราคาจับต้องได้", accentTone: "clay" as Tone },
  ],
};

// ---- Timeline (pre-lap teaser from presenter's own lines) -----------------
export const TIMELINE = {
  teaser: [
    { src: 89.05, end: 98.04 }, // "นี่คือ AI ขนาดเล็กที่เร็วที่สุด ประหยัดค่าใช้จ่ายที่สุด และมีความสามารถสูงที่สุดเท่าที่พวกเขาเคยสร้างมาเลยค่ะ"
    { src: 279.67, end: 285.06 }, // "งานที่มีปริมาณเยอะมาก ๆ แต่ต้องการจ่ายเงินให้น้อยที่สุด ค่ะ"
  ],
  stingDur: 2.6,
  mainSrcStart: 0.87, // skip "สวัสดีค่ะ"
  mainSrcEnd: 409.80, // end of line 149
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
export const mapTeaser = (i: number, src: number): number => SEG.teaser[i].dst + (src - SEG.teaser[i].src);

// ---- Chapters (src times) ---------------------------------------------------
export const CHAPTERS: { src: number; title: string }[] = [
  { src: 0.87, title: "เกริ่นนำ AI ยุคใหม่" },
  { src: 42.06, title: "รู้จัก Claude Haiku 5.5" },
  { src: 109.64, title: "เร็วและประหยัดที่สุด" },
  { src: 190.12, title: "3 งานเด่นในชีวิตจริง" },
  { src: 267.22, title: "งาน High-Volume & ธุรกิจ" },
  { src: 335.58, title: "อนาคต AI ที่ทุกคนจับต้องได้" },
  { src: 399.45, title: "สรุปส่งท้าย" },
];

// ---- B-roll durations -------------------------------------------------------
export const BROLL_DUR: Record<string, number> = {
  abstract: 30.0,
  ai_network: 30.0,
  brain: 10.0,
  chat_ai: 19.48,
  city_night: 22.36,
  coding: 14.96,
  cyber: 30.0,
  datacenter: 9.12,
  dna: 8.32,
  gen_glitch: 5.04,
  gen_ident: 5.04,
  gen_protein: 5.04,
  handshake: 11.48,
  lab: 15.2,
  microscope: 8.0,
  molecule: 18.64,
  nipah: 4.96,
  office: 14.8,
  protein: 14.2,
  server_lights: 23.52,
  shopping: 10.0,
  trading: 8.0,
  typing: 12.16,
  venus: 30.0,
  venus_volcano: 15.0,
  warehouse: 20.44,
};

// ---- Rect helpers -----------------------------------------------------------
export const R = (k: string): WebRect => WEB_RECTS[k] || { x: 295, y: 100, w: 500, h: 40 };

// ---- Terminal Demo ----------------------------------------------------------
export const TERMINAL_DEMO: Terminal = {
  title: "claude-haiku-5-5 — subagent document compaction",
  tag: "DEMO · Anthropic Claude Haiku 5.5",
  lines: [
    { t: 0.0, kind: "cmd", text: "$ claude run --model claude-haiku-5-5 'summarize financial-report.pdf --bullets'" },
    { t: 0.6, kind: "dim", text: "Reading 48 pages (12,450 tokens)... Latency: 180ms" },
    { t: 1.2, kind: "claude", text: "Claude Haiku 5.5: Financial summary extracted in 0.42s" },
    { t: 1.8, kind: "add", text: "+ Q3 Revenue: $4.2B (+18% YoY) | Net Margin: 24.5%" },
    { t: 2.4, kind: "add", text: "+ Operating Cost: -12% via automated AI pipelines" },
    { t: 3.0, kind: "ok", text: "PASS: 48 pages compacted | Token cost: $0.0012 (-75% vs Haiku 4.5)" },
    { t: 3.6, kind: "dim", text: "Subagent completed task. Ready for next query." },
  ],
};

// ---- Benchmark Chart --------------------------------------------------------
export const CHART_BENCH: Chart = {
  title: "Computer Use: OSWorld 2.1 Benchmark",
  sub: "ความสามารถในการสั่งการคอมพิวเตอร์ทำงานอัตโนมัติ (ยิ่งสูงยิ่งดี)",
  unit: "%",
  max: 100,
  bars: [
    { label: "Claude Haiku 5.5", value: 72.4, tone: "amber", note: "ก้าวกระโดดจากรุ่นเดิม 4.6x" },
    { label: "GPT-6 Luna", value: 48.9, tone: "mint", note: "48.9%" },
    { label: "Claude Haiku 4.5", value: 15.7, tone: "clay", note: "รุ่นก่อนหน้า (15.7%)" },
  ],
};

// ---- Explain Cards ----------------------------------------------------------
export const EXPLAIN_PROFESSOR: Explain = {
  title: "เปรียบเทียบ AI: อาจารย์ใหญ่ vs น้องเล็กสุดปราดเปรียว",
  sub: "จัดวางผู้ช่วยให้เหมาะสมกับเนื้องาน ไม่ต้องจ่ายแพงเกินจำเป็น",
  layout: "compare",
  left: { title: "AI รุ่นใหญ่ (อาจารย์ใหญ่)", icon: "🎓", tone: "clay" },
  right: { title: "Claude Haiku 5.5 (น้องเล็ก)", icon: "⚡", tone: "mint" },
  items: [
    { t: 71.5, icon: "🧠", text: "รุ่นใหญ่: รู้ลึก รู้เยอะ คิดรอบด้าน แต่คิดช้าและค่าใช้จ่ายสูง", tone: "clay" },
    { t: 74.5, icon: "⚡", text: "Haiku 5.5: ปราดเปรียว ว่องไว ตอบสนองทันทีในเสี้ยววินาที", tone: "mint" },
    { t: 77.0, icon: "🤝", text: "ทำงานคู่กัน: ให้ Haiku 5.5 เป็น Subagent ช่วยจัดการงานซ้ำ ๆ", tone: "mint" },
  ],
  footnote: "Anthropic ออกแบบ Haiku 5.5 เพื่อประหยัดต้นทุนเฉลี่ย 75%",
};

export const EXPLAIN_3TASKS: Explain = {
  title: "3 งานเด่นในชีวิตจริงของ Claude Haiku 5.5",
  sub: "ตัวเล็กแค่นี้ แต่ช่วยขับเคลื่อนงานจริงได้อย่างทรงพลัง",
  layout: "list",
  items: [
    { t: 191.0, icon: "📑", text: "จัดการข้อมูลกองโต: สรุปเอกสาร รายงาน หรือคู่มือยาว ๆ ในเสี้ยววินาที" },
    { t: 193.0, icon: "💬", text: "ตอบคำถามลูกค้า: แอดมินร้านค้าออนไลน์ 24 ชม. สุภาพ ไม่เคยบ่นเหนื่อย" },
    { t: 195.0, icon: "💼", text: "จัดระเบียบชีวิต & งาน: ช่วยร่างอีเมล แปลภาษา และสรุปค่าใช้จ่ายจากบิล" },
  ],
  footnote: "ตอบโจทย์ทั้งชีวิตประจำวัน ธุรกิจส่วนตัว และคนทำงานทั่วไป",
};

export const EXPLAIN_THAI: Explain = {
  title: "มุมมองประเทศไทย: คนไทยได้ประโยชน์อะไร?",
  sub: "เทคโนโลยีระดับโลก ในราคาที่ทุกคนจับต้องได้",
  layout: "list",
  items: [
    { t: 373.0, icon: "🛍️", text: "พ่อค้าแม่ค้าออนไลน์: ติดตั้ง AI ตอบแชทลูกค้าตลอด 24 ชม. ด้วยต้นทุนนิดเดียว" },
    { t: 375.0, icon: "📱", text: "แอปมือถือไทย: แอปช้อปปิ้ง ธนาคาร แปลภาษา จะฉลาดขึ้นอย่างก้าวกระโดด" },
    { t: 377.0, icon: "🇹🇭", text: "เข้าใจภาษาไทยสละสลวย: ช่วยตรวจคำผิด เรียบเรียงประโยค และร่างอีเมล" },
    { t: 379.0, icon: "💡", text: "ฟรีแลนซ์ & SME: มีผู้ช่วยอัจฉริยะนั่งข้างกาย ย่นเวลางานครึ่งวันเหลือนิดเดียว" },
  ],
  footnote: "เปิดโอกาสให้ธุรกิจไทยเติบโตด้วยเทคโนโลยี AI ในงบประมาณที่คุ้มค่า",
};

// ---- Beats (src times) -----------------------------------------------------
const BEATS_SRC: Beat[] = [
  // ===== TEASER (Pre-lap cuts from presenter's own lines) ====================
  {
    t: 0,
    abs: true,
    mode: "pip",
    media: "broll",
    src: "gen_glitch",
    hook: true,
    headline: "AI ขนาดเล็กที่เร็วที่สุด ⚡",
    sub: "ประหยัดค่าใช้จ่ายที่สุด เท่าที่เคยสร้างมา",
    subT: 2.0,
    kicker: "ANNOUNCEMENT · CLAUDE HAIKU 5.5",
    stats: [{ t: 1.5, big: "เร็วที่สุด", label: "Fastest Model", tone: "amber" }, { t: 4.5, big: "ประหยัดสุด", label: "Lowest Cost", tone: "mint" }],
  },
  {
    t: mapTeaser(1, 279.67),
    abs: true,
    mode: "pip",
    media: "broll",
    src: "abstract",
    hook: true,
    headline: "High-Volume & Cost-Sensitive 📊",
    sub: "งานปริมาณเยอะมาก แต่จ่ายเงินให้น้อยที่สุด",
    subT: mapTeaser(1, 281.5),
    kicker: "REVOLUTIONARY PRICING",
    stats: [{ t: mapTeaser(1, 280.5), big: "75%", label: "ประหยัดต้นทุนกว่าเดิม", tone: "amber" }],
  },
  {
    t: SEG.stingStart,
    abs: true,
    mode: "full",
    typo: "sting",
  },

  // ===== CHAPTER 1: เกริ่นนำ AI ยุคใหม่ (src 0.87 to 42.06) ==================
  {
    t: 0.87,
    mode: "full",
    lower: { title: "เทคโนโลยี AI กำลังก้าวข้ามไปอีกขั้น", sub: "และขยับเข้ามาใกล้ชีวิตประจำวันของเราทุกคน", t: 1.2, dur: 7.0, tag: "AI NEWS 2026" },
  },
  {
    t: 11.44,
    mode: "pip",
    media: "broll",
    src: "server_lights",
    headline: "AI ดูไกลตัวและราคาแพง?",
    sub: "เหมือนมีไว้ให้แค่โปรแกรมเมอร์ หรือบริษัทยักษ์ใหญ่เขาใช้กันเท่านั้น",
    subT: 13.5,
    kicker: "ภาพจำเดิมของ AI",
    stats: [{ t: 14.0, label: "💻 มีแต่ศัพท์เทคนิคชวนปวดหัว" }, { t: 16.5, label: "💰 ดูเหมือนค่าใช้จ่ายสูง" }],
  },
  {
    t: 20.12,
    mode: "pip",
    media: "broll",
    src: "ai_network",
    headline: "แต่วันนี้ ทุกอย่างกำลังจะเปลี่ยนไป ✨",
    sub: "เทคโนโลยี AI เพิ่งก้าวข้ามไปอีกขั้น ขยับเข้ามาใกล้ชีวิตเราทุกคน",
    subT: 22.5,
    kicker: "จุดเปลี่ยนครั้งสำคัญ",
    stats: [{ t: 23.0, big: "ก้าวข้าม", label: "พัฒนาขึ้นอีกระดับ", tone: "mint" }],
  },
  {
    t: 28.70,
    mode: "pip",
    media: "typo",
    typo: "agenda",
    src: "city_night",
    kicker: "ประเด็นสำคัญในคลิปนี้",
  },
  {
    t: 37.96,
    mode: "full",
    next: { label: "ประเด็นถัดไป", items: ["⚡ น้องเล็ก Claude Haiku 5.5", "🏎️ เร็วติดสปีด มอเตอร์ไซค์ด่วน", "💸 ประหยัดต้นทุน 75%", "📱 มีผลกับแอปมือถือ"], t: 38.5 },
  },

  // ===== CHAPTER 2: รู้จัก Claude Haiku 5.5 (src 42.06 to 109.64) ============
  {
    t: 42.06,
    mode: "pip",
    media: "broll",
    src: "city_night",
    headline: "Anthropic ผู้พัฒนา Claude 🌐",
    sub: "บริษัทเทคโนโลยีระดับโลก ประกาศเปิดตัว AI ตัวใหม่ล่าสุด",
    subT: 45.0,
    kicker: "ผู้พัฒนาแถวหน้า",
    stats: [{ t: 45.5, label: "🏢 บริษัท Anthropic" }, { t: 48.0, label: "🤖 ผู้พัฒนาโมเดล Claude" }],
  },
  {
    t: 51.22,
    mode: "pip",
    media: "web",
    file: "sec_hero",
    kicker: "เปิดตัว Claude Haiku 5.5",
    cam: [{ t: 0, fy: 380, z: 1.15 }, { t: 8.0, fy: 410, z: 1.25 }],
    hl: [{ t: 52.0, key: "hero_title", th: "เปิดตัว Claude Haiku 5.5 โมเดลเล็กตัวใหม่" }],
    stats: [{ t: 53.0, big: "Haiku 5.5", label: "น้องเล็กสุดฉลาด", tone: "amber" }],
    gloss: [{ t: 52.5, term: "Haiku 5.5", th: "โมเดลขนาดเล็กสายความเร็วและประหยัดจาก Anthropic" }],
  },
  {
    t: 65.46,
    mode: "pip",
    media: "broll",
    src: "brain",
    headline: "AI ในโลกเหมือนมีหลายขนาด",
    sub: "เปรียบเหมือนผู้ช่วยส่วนตัวที่มีบทบาทและขนาดต่างกัน",
    subT: 68.0,
    kicker: "มุมมองผู้ช่วยส่วนตัว",
    stats: [{ t: 69.5, label: "🎓 รุ่นใหญ่: อาจารย์รอบรู้" }, { t: 73.0, label: "⚡ รุ่นเล็ก: น้องเล็กปราดเปรียว" }],
  },
  {
    t: 70.98,
    mode: "pip",
    media: "explain",
    kicker: "เปรียบเทียบผู้ช่วย AI",
    explain: EXPLAIN_PROFESSOR,
  },
  {
    t: 82.53,
    mode: "pip",
    media: "web",
    file: "sec_hero",
    kicker: "เล็กแต่เก่งที่สุดเท่าที่เคยมีมา",
    cam: [{ t: 0, fy: 700, z: 1.2 }, { t: 8.0, fy: 740, z: 1.3 }],
    hl: [
      { t: 86.2, key: "hero_sub", th: "โมเดลเล็กที่เร็วที่สุด ประหยัดที่สุด และเก่งที่สุด" },
      { t: 89.2, key: "hero_fastest", th: "เร็วที่สุดเท่าที่เคยสร้างมา" },
      { t: 93.5, key: "hero_75", th: "ประหยัดต้นทุนกว่าเดิม 75%" },
    ],
    stats: [{ t: 89.5, big: "เร็วสุด", label: "Fastest Model", tone: "mint" }, { t: 93.0, big: "ถูกลง 75%", label: "75% Cheaper", tone: "amber" }],
    gloss: [{ t: 83.5, term: "Small Model", th: "โมเดลขนาดกะทัดรัด ประมวลผลไว กินพลังงานต่ำ" }],
  },
  {
    t: 97.98,
    mode: "pip",
    media: "broll",
    src: "abstract",
    headline: "เหมือนเด็กอัจฉริยะ ⚡",
    sub: "วิ่งไวมาก ถามอะไรก็ตอบทันที ไม่ต้องเสียเวลายืนคิดนาน ๆ",
    subT: 100.5,
    kicker: "ความปราดเปรียว",
    stats: [{ t: 101.0, label: "⚡ ถามปุ๊บตอบปั๊บ" }, { t: 104.5, label: "⏳ ไม่ต้องรอคอย" }],
  },
  {
    t: 106.50,
    mode: "full",
    next: { label: "หัวข้อต่อไป", items: ["🛵 มอเตอร์ไซค์ส่งของด่วน", "📉 ค่าไฟ-ค่าเซิร์ฟเวอร์ลดฮวบ", "📱 มีผลกับแอปในมือถือ", "🎁 ผู้ใช้ได้ใช้บริการราคาถูก"], t: 107.0 },
  },

  // ===== CHAPTER 3: เร็วและประหยัดที่สุด (src 109.64 to 190.12) =============
  {
    t: 109.64,
    mode: "pip",
    media: "broll",
    src: "typing",
    headline: "เร็ว & ประหยัด เกี่ยวอะไรกับเรา?",
    sub: "ทำไมผู้ใช้งานทั่วไปถึงได้ประโยชน์โดยตรง",
    subT: 112.5,
    kicker: "ประโยชน์ที่จับต้องได้",
  },
  {
    t: 119.88,
    mode: "pip",
    media: "broll",
    src: "office",
    headline: "AI รุ่นใหญ่บางครั้งต้องนั่งรอ ⏳",
    sub: "กดถามอะไรไป ต้องรอให้ระบบค่อย ๆ คิด ค่อย ๆ พิมพ์ทีละประโยค",
    subT: 123.0,
    kicker: "ความเร็วที่ต่างกัน",
    stats: [{ t: 124.0, label: "⏳ รุ่นใหญ่ต้องรอพิมพ์ทีละคำ" }],
  },
  {
    t: 131.61,
    mode: "pip",
    media: "broll",
    src: "chat_ai",
    headline: "ดั่งมอเตอร์ไซค์ส่งของด่วน 🛵",
    sub: "พร้อมซิ่งส่งคำตอบให้ทันที กระพริบตาแค่ทีสองทีคำตอบก็โผล่แล้ว",
    subT: 134.5,
    kicker: "ความเร็ว Haiku 5.5",
    stats: [{ t: 135.0, big: "Instant", label: "ตอบไวในพริบตา", tone: "mint" }],
  },
  {
    t: 143.50,
    mode: "pip",
    media: "web",
    file: "sec_pricing",
    kicker: "จุดเด่นสำคัญ: ความประหยัด",
    cam: [{ t: 0, fy: 220, z: 1.2 }, { t: 8.0, fy: 250, z: 1.3 }],
    hl: [
      { t: 144.5, key: "price_cache_reads", th: "Cache Reads เพียง $0.01 ต่อ 1M tokens" },
      { t: 147.5, key: "price_input", th: "Input Token เพียง $0.10" },
    ],
    stats: [{ t: 145.0, big: "ประหยัด 75%", label: "ต้นทุนลดลงมหาศาล", tone: "amber" }],
    gloss: [{ t: 144.0, term: "Cache Reads", th: "การดึงข้อมูลเดิมที่ระบบจำไว้ ทำให้ประหยัดค่าใช้จ่ายได้สูงสุด" }],
  },
  {
    t: 151.02,
    mode: "pip",
    media: "broll",
    src: "datacenter",
    headline: "เบื้องหลังมีต้นทุนมหาศาล ⚡",
    sub: "ค่าไฟ ค่าเซิร์ฟเวอร์ แต่ Haiku 5.5 ถูกออกแบบมาให้กินพลังงานน้อยมาก",
    subT: 154.5,
    kicker: "ลดภาระระบบ",
    stats: [{ t: 155.0, label: "📉 ลดค่าไฟฟ้าและเซิร์ฟเวอร์" }, { t: 158.0, label: "🌱 ประหยัดพลังงานเป็นเลิศ" }],
  },
  {
    t: 165.92,
    mode: "pip",
    media: "broll",
    src: "shopping",
    headline: "แอปพลิเคชันมือถือจะฉลาดขึ้น 📱",
    sub: "แอปช้อปปิ้ง ธนาคาร แปลภาษา สามารถใส่ AI เก่ง ๆ ได้โดยไม่ต้องแบกต้นทุนแพง",
    subT: 169.5,
    kicker: "ประโยชน์สู่มือถือ",
    stats: [{ t: 170.0, label: "🛍️ แอปช้อปปิ้งออนไลน์" }, { t: 173.0, label: "🏦 แอปธนาคารและการเงิน" }, { t: 176.0, label: "🌐 แอปแปลภาษาแบบเรียลไทม์" }],
  },
  {
    t: 181.23,
    mode: "pip",
    media: "broll",
    src: "handshake",
    headline: "ผู้ใช้อย่างเราได้ประโยชน์เต็ม ๆ",
    sub: "ได้ใช้บริการดี ๆ ฟรี หรือในราคาที่ถูกลงมากอย่างที่ไม่เคยมีมาก่อน",
    subT: 184.0,
    kicker: "ประโยชน์ต่อทุกคน",
    stats: [{ t: 184.5, big: "ฟรี & ถูกลง", label: "ผลลัพธ์เพื่อผู้ใช้งาน", tone: "mint" }],
  },
  {
    t: 187.50,
    mode: "full",
    next: { label: "ประเด็นถัดไป", items: ["📑 จัดการข้อมูลกองโต", "💬 แอดมินตอบแชท 24 ชม.", "💼 ช่วยงานเอกสารและบิล", "⚡ สรุปเร็วเสี้ยววินาที"], t: 188.0 },
  },

  // ===== CHAPTER 4: 3 งานเด่นในชีวิตจริง (src 190.12 to 267.22) =============
  {
    t: 190.12,
    mode: "pip",
    media: "explain",
    kicker: "3 บทบาทสำคัญ",
    explain: EXPLAIN_3TASKS,
  },
  {
    t: 197.16,
    mode: "pip",
    media: "broll",
    src: "typing",
    headline: "งานที่ 1: จัดการข้อมูลกองโต 📑",
    sub: "เอกสารยาวเป็นสิบหน้า กฎหมาย รายงานการประชุม ที่เห็นแล้วไม่อยากอ่าน",
    subT: 201.0,
    kicker: "สรุปข้อมูลอัตโนมัติ",
    stats: [{ t: 202.0, label: "📑 สรุปเอกสารยาวหลายสิบหน้า" }, { t: 206.0, label: "⚖️ กฎหมาย รายงาน คู่มือ" }],
  },
  {
    t: 210.54,
    mode: "pip",
    media: "terminal",
    terminal: TERMINAL_DEMO,
    kicker: "การทำงานจริงแบบ Subagent",
  },
  {
    t: 221.20,
    mode: "pip",
    media: "broll",
    src: "shopping",
    headline: "งานที่ 2: ตอบคำถามลูกค้า 💬",
    sub: "ลูกค้าทักมาตอนตีสองตีสาม Haiku 5.5 เป็นแอดมินตอบแชทสุภาพ ไม่เคยบ่นเหนื่อย",
    subT: 224.5,
    kicker: "แอดมินตอบแชท 24 ชม.",
    stats: [{ t: 226.0, big: "24/7", label: "ตอบลูกค้าไม่หยุดพัก", tone: "mint" }, { t: 231.0, label: "🌙 ตอบไวแม้ตอนตีสองตีสาม" }],
  },
  {
    t: 241.36,
    mode: "pip",
    media: "broll",
    src: "coding",
    headline: "งานที่ 3: จัดระเบียบชีวิต & งาน 💼",
    sub: "เขียนอีเมลสมัครงาน ร่างข้อความทักทายลูกค้า แปลภาษา หรือดึงตัวเลขจากบิลใบเสร็จ",
    subT: 245.0,
    kicker: "ผู้ช่วยส่วนตัวอเนกประสงค์",
    stats: [
      { t: 248.0, label: "✉️ เขียนอีเมลสมัครงาน" },
      { t: 251.5, label: "🤝 ร่างข้อความทักลูกค้า" },
      { t: 254.5, label: "🇬🇧 แปลไทยเป็นอังกฤษสละสลวย" },
      { t: 258.5, label: "🧾 สรุปค่าใช้จ่ายจากบิล" },
    ],
  },
  {
    t: 264.50,
    mode: "full",
    next: { label: "หัวข้อถัดไป", items: ["🏢 High-Volume คืองานแบบไหน", "🏪 ร้านค้าเปิดระบบ 24 ชม.", "💼 ประโยชน์กับฟรีแลนซ์", "📊 ทดสอบความฉลาดจริง"], t: 265.0 },
  },

  // ===== CHAPTER 5: งาน High-Volume & ธุรกิจ (src 267.22 to 335.58) ============
  {
    t: 267.22,
    mode: "pip",
    media: "web",
    file: "sec_hero",
    kicker: "High-Volume & Cost-Sensitive",
    cam: [{ t: 0, fy: 480, z: 1.2 }, { t: 8.0, fy: 520, z: 1.3 }],
    hl: [{ t: 273.7, key: "hero_tasks", th: "ออกแบบสำหรับงานปริมาณเยอะมาก แต่ต้องการจ่ายเงินให้น้อยที่สุด" }],
    stats: [{ t: 274.0, big: "High Volume", label: "งานปริมาณเยอะมหาศาล", tone: "amber" }, { t: 277.0, big: "Cost Sensitive", label: "คุมค่าใช้จ่ายได้ดีเยี่ยม", tone: "mint" }],
    gloss: [{ t: 274.0, term: "High-volume", th: "งานที่มีการเรียกใช้ซ้ำ ๆ วันละหลายพันหรือหลายล้านครั้ง" }],
  },
  {
    t: 284.94,
    mode: "pip",
    media: "broll",
    src: "warehouse",
    headline: "ร้านค้าออนไลน์ข้อความหลักพัน 🛍️",
    sub: "ตอบได้เป็นหมื่นคนพร้อมกันในพริบตาเดียว โดยเสียค่าบริการเพียงแค่นิดเดียว",
    subT: 288.0,
    kicker: "ขยายธุรกิจอย่างไร้กังวล",
    stats: [{ t: 289.0, big: "10,000+", label: "ตอบพร้อมกันในพริบตา", tone: "mint" }, { t: 294.0, label: "💸 กำไรไม่หมดไปกับค่าระบบ" }],
  },
  {
    t: 300.14,
    mode: "pip",
    media: "chart",
    chart: CHART_BENCH,
    kicker: "ผลการทดสอบคะแนนจริง",
  },
  {
    t: 311.44,
    mode: "pip",
    media: "broll",
    src: "office",
    headline: "สำหรับคนทำงาน & ฟรีแลนซ์ 💼",
    sub: "เสมือนมีผู้ช่วยส่วนตัวมานั่งข้าง ๆ คอยเช็กคำผิด เรียบเรียงประโยค ค้นหาข้อมูล",
    subT: 315.0,
    kicker: "ผู้ช่วยคนทำงาน",
    stats: [{ t: 317.0, label: "✍️ ช่วยเช็กคำผิด เรียบเรียงประโยค" }, { t: 321.0, label: "⏱️ งานครึ่งวันเสร็จในไม่กี่นาที" }],
  },
  {
    t: 329.50,
    mode: "pip",
    media: "broll",
    src: "city_night",
    headline: "มีเวลาพักผ่อนและครอบครัวมากขึ้น 🏡",
    sub: "เมื่อ AI ช่วยย่นระยะเวลาการทำงาน คุณก็มีเวลาเหลือไปใช้ชีวิตได้อย่างมีความสุข",
    subT: 332.0,
    kicker: "คุณภาพชีวิตที่ดีกว่า",
    stats: [{ t: 332.5, big: "คุณภาพชีวิต", label: "มีเวลาให้ตัวเอง & ครอบครัว", tone: "mint" }],
  },
  {
    t: 334.00,
    mode: "full",
    next: { label: "ช่วงสรุปภาพรวม", items: ["🚪 เปิดประตูสู่เทคโนโลยีโลก", "📞 คอลเซ็นเตอร์ยุคใหม่เข้าใจเรา", "🇹🇭 มุมมองประเทศไทย", "🔔 ติดตามข่าวสารคลิปหน้า"], t: 334.5 },
  },

  // ===== CHAPTER 6: อนาคต AI ที่ทุกคนจับต้องได้ (src 335.58 to 399.45) =======
  {
    t: 335.58,
    mode: "pip",
    media: "broll",
    src: "ai_network",
    headline: "ไม่ใช่แค่เรื่องของคนไอทีอีกต่อไป 🚀",
    sub: "แต่มันคือการเปิดประตูให้เทคโนโลยีที่ฉลาดล้ำ ลงมาอยู่ในจุดที่เข้าถึงง่ายและรวดเร็ว",
    subT: 339.0,
    kicker: "อนาคตของทุกคน",
    stats: [{ t: 341.0, label: "🚪 เปิดประตูเทคโนโลยีสู่ทุกคน" }, { t: 345.0, label: "⚡ ราคาจับต้องได้ ทำงานรวดเร็ว" }],
  },
  {
    t: 348.66,
    mode: "pip",
    media: "web",
    file: "sec_pricing",
    kicker: "ราคาที่ใคร ๆ ก็จ่ายไหว",
    cam: [{ t: 0, fy: 320, z: 1.15 }, { t: 8.0, fy: 350, z: 1.25 }],
    hl: [{ t: 350.0, key: "pricing_title", th: "ราคาเริ่มต้นเพียง $0.01 ต่อล้านโทเค็น" }],
    stats: [{ t: 351.0, big: "จ่ายไหว", label: "ต้นทุนต่ำที่สุด", tone: "mint" }],
  },
  {
    t: 357.94,
    mode: "pip",
    media: "broll",
    src: "chat_ai",
    headline: "คอลเซ็นเตอร์ที่ไม่ใช่เสียงหุ่นยนต์ทื่อ ๆ 📞",
    sub: "เข้าใจความรู้สึก ตอบคำถามได้ทันทีโดยไม่ต้องรอสายนาน",
    subT: 361.5,
    kicker: "บริการอัจฉริยะ",
    stats: [{ t: 362.0, big: "เข้าใจจริง", label: "รับรู้อารมณ์และความรู้สึก", tone: "mint" }, { t: 366.5, label: "📞 ไม่ต้องรอสายเสียงสัญญาณยาวนาน" }],
  },
  {
    t: 372.68,
    mode: "pip",
    media: "explain",
    kicker: "มุมมองประเทศไทย",
    explain: EXPLAIN_THAI,
  },
  {
    t: 382.00,
    mode: "pip",
    media: "typo",
    typo: "vs",
    src: "cyber",
    kicker: "สรุปการเลือกใช้งาน",
  },
  {
    t: 390.52,
    mode: "pip",
    media: "web",
    file: "sec_availability",
    kicker: "พร้อมใช้งานแล้ววันนี้",
    cam: [{ t: 0, fy: 150, z: 1.1 }, { t: 7.0, fy: 180, z: 1.2 }],
    hl: [{ t: 391.0, key: "avail_all", th: "พร้อมใช้งานแล้วบน AWS, Google Cloud, Azure และ Claude Platform" }],
    stats: [{ t: 392.0, big: "Available", label: "พร้อมใช้งานทั่วโลก", tone: "mint" }],
  },
  {
    t: 396.30,
    mode: "full",
    next: { pill: "สรุปส่งท้าย", items: ["⚡ Claude Haiku 5.5", "💸 ประหยัดต้นทุน 75%", "👍 ฝากกดไลก์ & แชร์", "🔔 กด Subscribe ช่องของเรา"], t: 397.0 },
  },

  // ===== CHAPTER 7: สรุปส่งท้าย (src 399.45 to 409.80) ========================
  {
    t: 399.45,
    mode: "pip",
    media: "typo",
    typo: "final4",
    src: "gen_ident",
    kicker: "Claude Haiku 5.5",
  },
  {
    t: 406.00,
    mode: "full",
    next: { pill: "ขอบคุณสำหรับการรับชม", items: ["👍 กดไลก์", "↗️ กดแชร์", "🔔 กดติดตามช่องของเรา"], t: 407.0 },
  },
];

// Typo scene word times (src)
export const AGENDA = [
  { t: 29.5, text: "น้องเล็กสุดฉลาด", icon: "⚡" },
  { t: 32.0, text: "เร็วและประหยัด 75%", icon: "💸" },
  { t: 34.5, text: "3 งานเด่นชีวิตจริง", icon: "📑" },
  { t: 37.0, text: "ปฏิวัติงาน High-Volume", icon: "📊" },
  { t: 39.5, text: "อนาคต AI สู่ทุกคน", icon: "🌐" },
];
export const SUMMARY3 = [
  { t: 382.5, text: "น้องเล็กสุดฉลาด", icon: "⚡" },
  { t: 385.0, text: "ประหยัดต้นทุน 75%", icon: "💸" },
  { t: 387.5, text: "ทุกคนจับต้องได้", icon: "🌐" },
];
export const FINAL4 = [
  { t: 400.0, text: "เร็วที่สุดในโมเดลเล็ก", icon: "⚡" },
  { t: 402.0, text: "ประหยัดพลังงาน 75%", icon: "💸" },
  { t: 404.0, text: "เหมาะกับงาน High-Volume", icon: "📈" },
  { t: 405.5, text: "ชีวิตประจำวันง่ายขึ้น", icon: "✨" },
];
export const VS = {
  fableT: 382.5,
  mythosT: 385.5,
  subT: 388.5,
  leftLines: [383.0, 384.0, 385.0],
  rightLines: [386.0, 387.0, 388.0],
};
export const CTA_T = 403.4;

// Marquee numbers: the music bed dips right before these (src seconds)
export const MUSIC_DIPS = [37.5, 88.5, 143.0, 210.0, 273.0, 350.0, 400.0];

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
export const BEATS_TL: Beat[] = BEATS_SRC.map(shiftBeat).sort((a, b) => a.t - b.t);
export const AGENDA_TL = AGENDA.map((x) => ({ ...x, t: mapMain(x.t) }));
export const SUMMARY3_TL = SUMMARY3.map((x) => ({ ...x, t: mapMain(x.t) }));
export const FINAL4_TL = FINAL4.map((x) => ({ ...x, t: mapMain(x.t) }));
export const VS_TL = { fableT: mapMain(VS.fableT), mythosT: mapMain(VS.mythosT), subT: mapMain(VS.subT), leftLines: VS.leftLines.map(mapMain), rightLines: VS.rightLines.map(mapMain) };
export const CTA_TL = mapMain(CTA_T);
export const CHAPTERS_TL = CHAPTERS.map((c) => ({ ...c, t: mapMain(c.src) }));
export const VO_END_TL = SEG.voEnd;
export const TOTAL_TL = SEG.total;
