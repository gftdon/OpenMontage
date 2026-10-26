// ===========================================================================
// Gpt6NewsYT V2 — EPISODE DATA (pure TypeScript, no React)
// Topic: Introducing GPT-6 Sol and Luna (OpenAI Announcement & Frontier AI for Everyone)
// ===========================================================================
import { WEB_RECTS, type WebRect } from "./gpt6NewsWeb";

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
  assetDir: "gpt6-sol-luna-news",
  brand: "AI NEWS",
  dateLabel: "23 ก.ย. 2026",
  page: { domain: "openai.com", path: "/index/introducing-gpt-6-sol-and-luna" },
  captureLabel: "VERIFIED · จับภาพ 23 ก.ย. 2026",
  officialTag: "OFFICIAL · OPENAI",
  previewTag: "PREVIEW",
  cta: { lead: "อ่านประกาศฉบับเต็มได้ที่", text: "openai.com" },
  sting: {
    eyebrow: "AI NEWS SPECIAL · 2026",
    titleA: "GPT-6 Sol",
    amp: "&",
    titleB: "GPT-6 Luna",
    sub: "OpenAI เปิดตัว 2 โมเดลใหม่ · ฉลาดขึ้น ถูกลง 50%",
  },
  endcard: {
    eyebrow: "AI NEWS · 2026",
    titleA: "GPT-6 Sol & Luna",
    titleB: "Frontier AI for Everyone",
    sub: "อ่านรายละเอียดเต็มที่ openai.com/index/introducing-gpt-6-sol-and-luna",
    cta: "เริ่มใช้งานได้แล้ววันนี้",
    next: "ติดตามข่าว AI ย่อยง่ายทุกสัปดาห์ · กด Subscribe 🔔",
  },
  agendaLabel: "ในคลิปนี้",
  summary3Label: "สรุปหัวใจสำคัญ",
  final4: { title: "GPT-6 Sol & Luna", sub: "ยุคใหม่ของ AI ที่ทุกคนเข้าถึงได้จริง" },
  vs: {
    eyebrow: "สรุปการเลือกใช้ · Sol vs Luna",
    left: {
      title: "GPT-6 Sol ☀️",
      badge: "SUPER CAR",
      lines: ["ตัวท็อป ฉลาดสุด แรงสุด", "งานซับซ้อน วิเคราะห์ธุรกิจ", "เขียนโค้ด งานที่ห้ามผิดพลาด"],
    },
    right: {
      title: "GPT-6 Luna 🌙",
      badge: "DAILY DRIVE",
      lines: ["ฉลาดเหมือนกัน เน้นคุ้มค่า", "เขียนอีเมล สรุปบทความ", "งานทั่วไปในชีวิตประจำวัน"],
    },
    conclusion: "💡 เลือกใช้ให้ตรงกับงาน หรือสลับกันเพื่อประสิทธิภาพสูงสุด",
  },
  thumbs: [
    { id: "A", lines: ["OpenAI เปิดตัว", "GPT-6 Sol & Luna"], accent: "ฉลาดขึ้น ถูกลง 50%", accentTone: "amber" as Tone },
    { id: "B", lines: ["Sol vs Luna", "ต่างกันยังไง?"], accent: "เลือกใช้ให้ถูกตัว", accentTone: "mint" as Tone },
    { id: "C", lines: ["AI เปลี่ยนชีวิต", "ไม่ใช่แค่สาย IT"], accent: "สรุปครบใน 7 นาที", accentTone: "clay" as Tone },
  ],
};

// ---- Timeline (pre-lap teaser from presenter's own lines) -----------------
export const TIMELINE = {
  teaser: [
    { src: 55.54, end: 63.50 }, // "แต่คราวนี้ OpenAI ไม่ได้ออกมาแค่ตัวเดียวนะคะ เขาออกมาสองตัวเลย ก็คือ Sol กับ Luna ค่ะ"
    { src: 146.41, end: 151.82 }, // "เพื่อให้เราเลือกใช้ได้ตรงกับความต้องการ ไม่ต้องจ่ายแพงเกินจำเป็นค่ะ"
  ],
  stingDur: 2.6,
  mainSrcStart: 0.70, // skip "สวัสดีค่ะ"
  mainSrcEnd: 414.0, // end of Line 99 ("บาย ๆ")
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
  { src: 0.70, title: "เปิดตัว GPT-6 Sol & Luna" },
  { src: 76.48, title: "Sol vs Luna ต่างกันยังไง" },
  { src: 151.64, title: "4 ด้านที่เก่งขึ้นก้าวกระโดด" },
  { src: 221.90, title: "ประโยชน์กับคนทั่วไป" },
  { src: 288.78, title: "วิธีเลือกใช้ให้คุ้มค่า" },
  { src: 334.40, title: "อนาคต AI กับทุกคน" },
  { src: 382.56, title: "สรุปส่งท้าย" },
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
  title: "codex — gpt-6-sol reasoning benchmark",
  tag: "DEMO · OpenAI GPT-6 Sol",
  lines: [
    { t: 0.0, kind: "cmd", text: "$ codex run --model gpt-6-sol 'optimize high-concurrency token processing'" },
    { t: 0.9, kind: "dim", text: "Analyzing system architecture across 12 microservices..." },
    { t: 1.6, kind: "claude", text: "GPT-6 Sol: Root cause identified. Stream buffer lock contention." },
    { t: 2.3, kind: "del", text: "-    while not queue.empty(): process(queue.get())" },
    { t: 2.7, kind: "add", text: "+    for batch in chunked(queue.drain(), 512): process_bulk(batch)" },
    { t: 3.5, kind: "ok", text: "PASS: 47 tools verified on AutomationBench (Score 33.2%)" },
    { t: 4.2, kind: "dim", text: "Cost per task: $0.27 (vs $2.97 Claude Opus 5 — 9% cost)" },
  ],
};

// ---- Benchmark Chart --------------------------------------------------------
export const CHART_BENCH: Chart = {
  title: "AutomationBench: AI Agents Workflow",
  sub: "ความสามารถในการทำงานจริง 47 เครื่องมือ (ยิ่งสูงยิ่งดี)",
  unit: "%",
  max: 40,
  bars: [
    { label: "GPT-6 Sol (xhigh)", value: 33.2, tone: "amber", note: "อันดับ 1 · ต้นทุน $0.27" },
    { label: "Claude Fable 5.1", value: 31.4, tone: "mint", note: "31.4%" },
    { label: "GPT-6 Astra (low)", value: 30.3, tone: "mint", note: "30.3%" },
    { label: "Claude Opus 5 (max)", value: 26.9, tone: "clay", note: "ต้นทุนสูงกว่า 11x" },
  ],
};

// ---- Explain Cards ----------------------------------------------------------
export const EXPLAIN_CARS: Explain = {
  title: "เปรียบเทียบรถยนต์: ซูเปอร์คาร์ vs รถใช้งานทั่วไป",
  sub: "เลือกเครื่องมือให้เหมาะกับเป้าหมาย ไม่ต้องจ่ายแพงเกินจำเป็น",
  layout: "compare",
  left: { title: "GPT-6 Sol (ซูเปอร์คาร์)", icon: "🏎️", tone: "amber" },
  right: { title: "GPT-6 Luna (รถใช้งานทุกวัน)", icon: "🚗", tone: "mint" },
  items: [
    { t: 134.5, icon: "⚡", text: "Sol: เร็ว แรง วิ่งบนสนามแข่ง (งานซับซ้อน/วิจัย)", tone: "amber" },
    { t: 137.0, icon: "⛽", text: "Luna: ขับสบาย ประหยัดน้ำมัน วิ่งได้ทุกวัน (งานทั่วไป)", tone: "mint" },
    { t: 140.0, icon: "🎯", text: "ไม่จำเป็นต้องใช้ซูเปอร์คาร์ไปซื้อของที่ตลาด", tone: "mint" },
  ],
  footnote: "OpenAI พัฒนา 2 โมเดล เพื่อตอบโจทย์ทุกระดับงบประมาณ",
};

export const EXPLAIN_MULTIMODAL: Explain = {
  title: "ความสามารถข้ามสื่อ (Multimodal Full-Stack)",
  sub: "เข้าใจโลกและทำงานร่วมกันได้ใกล้เคียงมนุษย์มากที่สุด",
  layout: "list",
  items: [
    { t: 207.5, icon: "💬", text: "ข้อความ: จัดการภาษาและบริบทซับซ้อนได้อย่างเป็นธรรมชาติ" },
    { t: 211.5, icon: "🖼️", text: "รูปภาพ: มองเห็น วิเคราะห์ภาพ และสร้างสรรค์กราฟิก" },
    { t: 213.5, icon: "🎙️", text: "เสียง & วิดีโอ: รับฟัง โต้ตอบ และเข้าใจภาพเคลื่อนไหว" },
    { t: 217.0, icon: "🌐", text: "ข้ามสื่อลื่นไหล: ผสมผสานทุกประสาทสัมผัสในการแก้ปัญหา" },
  ],
};

export const EXPLAIN_EVERYDAY: Explain = {
  title: "GPT-6 ช่วยชีวิตทุกคนในครอบครัว",
  sub: "ไม่ใช่แค่คนทำงาน IT แต่มีประโยชน์กับชีวิตประจำวันจริง",
  layout: "list",
  items: [
    { t: 270.5, icon: "🍳", text: "สูตรอาหาร & วางแผนมื้อสุขภาพจากวัตถุดิบในตู้เย็น" },
    { t: 274.0, icon: "🔧", text: "วิธีแก้ปัญหาในบ้านและซ่อมแซมสิ่งของเบื้องต้น" },
    { t: 277.5, icon: "🩺", text: "ขอคำแนะนำเรื่องสุขภาพเบื้องต้นอย่างมีหลักการ" },
    { t: 281.0, icon: "🤖", text: "เสมือนมีผู้ช่วยส่วนตัวที่รู้รอบด้าน พร้อมช่วย 24 ชม." },
  ],
};

export const EXPLAIN_THAI: Explain = {
  title: "มุมไทย: โอกาสครั้งสำคัญของคนไทย",
  sub: "ต้นทุนลดลง 50% ปลดล็อกการใช้งาน AI ทั่วประเทศ",
  layout: "flow",
  items: [
    { t: 372.0, icon: "💸", text: "ลดต้นทุน 50%: นักพัฒนา & SME ไทยใช้ AI โมเดลระดับโลกได้ถูกลงครึ่งหนึ่ง" },
    { t: 374.5, icon: "⚡", text: "ภาษาไทยลื่นไหล: เข้าใจบริบท วัฒนธรรม และภาษาไทยได้แม่นยำยิ่งขึ้น" },
    { t: 377.5, icon: "📱", text: "ใช้ง่ายผ่านแชท: แค่พิมพ์คุยเหมือนเพื่อน ไม่ต้องมีความรู้เทคนิค" },
  ],
  footnote: "ข้อมูลอ้างอิง: openai.com/index/introducing-gpt-6-sol-and-luna",
};

// ---- Beats (src seconds unless abs) -----------------------------------------
export const BEATS: Beat[] = [
  // ===== PRE-LAP TEASER (timeline seconds) ===================================
  {
    t: 0.0, abs: true, mode: "pip", media: "broll", src: "gen_glitch", hook: true,
    headline: "OpenAI เปิดตัว 2 รุ่นใหม่!", sub: "GPT-6 Sol & GPT-6 Luna", subT: 1.2, kicker: "BREAKING NEWS",
    stats: [{ t: 2.2, big: "2 โมเดล", label: "ครอบคลุมทุกระดับการใช้งาน", tone: "amber" }],
  },
  {
    t: 4.5, abs: true, mode: "pip", media: "web", file: "sec_hero", kicker: "ก้าวกระโดดครั้งสำคัญ",
    cam: [{ t: 0, fy: 380, z: 1.1 }, { t: 3.4, fy: 360, z: 1.2 }],
    hl: [{ t: 4.8, key: "hero_title", th: "เปิดตัว GPT-6 Sol และ Luna อย่างเป็นทางการ" }],
  },
  {
    t: SEG.teaser[1].dst, abs: true, mode: "pip", media: "web", file: "sec_pricing", kicker: "คุ้มค่า ไม่ต้องจ่ายแพงเกินจำเป็น",
    cam: [{ t: 0, fy: 200, z: 1.2 }, { t: 5.0, fy: 220, z: 1.3 }],
    hl: [{ t: SEG.teaser[1].dst + 0.5, key: "price_reduction", th: "ลดราคา API ลง 50% ทันที" }],
    stats: [{ t: SEG.teaser[1].dst + 1.2, big: "ถูกลง 50%", label: "ประหยัดต้นทุนมหาศาล", tone: "mint" }],
  },
  { t: SEG.stingStart, abs: true, mode: "full", media: "none", typo: "sting" },

  // ===== MAIN INTRO (src seconds) ============================================
  {
    t: 0.70, mode: "full",
    lower: { title: "OpenAI ข่าวใหญ่ระดับโลก", sub: "เปิดตัว GPT-6 Sol & Luna · ยุคใหม่ของ AI สำหรับทุกคน", t: 1.2, dur: 4.6 },
  },
  { t: 6.00, mode: "pip", media: "typo", typo: "agenda", src: "gen_ident", kicker: "ในคลิปนี้" },
  {
    t: 13.00, mode: "pip", media: "broll", src: "ai_network", headline: "ก้าวกระโดดครั้งสำคัญ", sub: "AI ที่ฉลาดและเข้าใจชีวิตเรามากขึ้น", subT: 15.0, kicker: "ภาพรวมข่าวใหญ่",
    stats: [{ t: 15.5, label: "🏢 OpenAI ค่าย AI อันดับ 1 ของโลก" }],
  },
  {
    t: 20.00, mode: "pip", media: "broll", src: "office", headline: "เข้าใจง่าย แม้ไม่เก่ง IT", kicker: "สรุปให้ฟังครบจบ",
    stats: [{ t: 21.0, label: "✨ สรุปให้ฟังภาษาง่าย ๆ" }, { t: 23.5, label: "💡 นำไปปรับใช้ได้ทันที" }],
  },

  // ===== CHAPTER 1: เปิดตัว GPT-6 Sol & Luna (src 25.78 to 76.48) =============
  {
    t: 25.78, mode: "full",
    next: { label: "2 โมเดลรุ่นใหม่", items: ["☀️ Sol: ตัวท็อป ฉลาดสุด แรงสุด", "🌙 Luna: ตัวคุ้มค่า ประหยัดกว่า"], t: 26.5 },
  },
  {
    t: 31.50, mode: "pip", media: "broll", src: "chat_ai", headline: "จาก ChatGPT สู่ GPT-6", sub: "สมองกลรุ่นใหม่ล่าสุดที่ฉลาดกว่าเดิม", subT: 34.5, kicker: "วิวัฒนาการ AI",
    stats: [{ t: 34.0, label: "💬 พิมพ์คุย ตอบคำถาม" }, { t: 37.0, label: "🧠 ช่วยคิดไอเดียและวิเคราะห์" }],
    gloss: [{ t: 32.0, term: "ChatGPT", th: "แชทบอท AI ยอดนิยมของ OpenAI" }],
  },
  {
    t: 43.86, mode: "pip", media: "web", file: "sec_hero", kicker: "สมองรุ่นใหม่ล่าสุด",
    cam: [{ t: 0, fy: 380, z: 1.0 }, { t: 7.0, fy: 360, z: 1.15 }],
    hl: [{ t: 45.0, key: "hero_title", th: "GPT-6 คือสมอง AI เจเนอเรชันใหม่ล่าสุด" }],
    stats: [{ t: 46.5, big: "GPT-6", label: "สมองรุ่นใหม่ล่าสุด" }],
  },
  {
    t: 51.36, mode: "pip", media: "broll", src: "abstract", headline: "เหมือน iPhone 15 สู่ 16", sub: "อัปเกรดประสิทธิภาพครั้งใหญ่รอบด้าน", subT: 53.5, kicker: "เปรียบเทียบง่าย ๆ",
  },
  {
    t: 59.30, mode: "pip", media: "web", file: "sec_hero", kicker: "เปิดตัว 2 ตัวพร้อมกัน",
    cam: [{ t: 0, fy: 600, z: 1.2 }, { t: 8.0, fy: 620, z: 1.3 }],
    hl: [
      { t: 60.5, key: "hero_sol", th: "Sol = พระอาทิตย์ (ตัวแรงที่สุด)" },
      { t: 62.0, key: "hero_luna", th: "Luna = พระจันทร์ (ตัวคุ้มค่าที่สุด)" },
    ],
    stats: [{ t: 64.0, big: "Sol ☀️", label: "พระอาทิตย์" }, { t: 66.0, big: "Luna 🌙", label: "พระจันทร์", tone: "mint" }],
  },
  {
    t: 69.34, mode: "full",
    next: { label: "หัวข้อถัดไป", items: ["☀️ Sol เหมาะกับใคร", "🌙 Luna คุ้มค่ายังไง", "📊 ผลทดสอบจริง"], t: 70.0 },
  },

  // ===== CHAPTER 2: Sol vs Luna ต่างกันยังไง (src 76.48 to 151.64) ===========
  {
    t: 76.48, mode: "pip", media: "web", file: "sec_professional", kicker: "GPT-6 Sol: ตัวท็อป ฉลาดที่สุด",
    cam: [{ t: 0, fy: 220, z: 1.1 }, { t: 7.0, fy: 240, z: 1.2 }],
    hl: [{ t: 79.5, key: "prof_title", th: "Sol ถูกออกแบบมาเพื่องานระดับมืออาชีพ" }],
    stats: [{ t: 80.5, big: "Sol ☀️", label: "ตัวท็อป ฉลาดสุด แรงสุด" }],
  },
  {
    t: 84.08, mode: "pip", media: "broll", src: "trading", headline: "งานคิดซับซ้อน แม่นยำสูง", sub: "วิเคราะห์ข้อมูลธุรกิจจำนวนมาก", subT: 86.5, kicker: "ความสามารถ Sol",
    stats: [{ t: 87.0, label: "📊 วิเคราะห์ข้อมูลธุรกิจซับซ้อน" }, { t: 90.5, label: "📑 รายงานวิจัยอ้างอิงหลายแหล่ง" }],
  },
  {
    t: 95.83, mode: "pip", media: "terminal", terminal: TERMINAL_DEMO, kicker: "เขียนโค้ดซับซ้อน",
  },
  {
    t: 100.74, mode: "pip", media: "broll", src: "server_lights", headline: "เหมือนรถซูเปอร์คาร์", sub: "แรง เร็ว ประสิทธิภาพสูง ของดีแลกกับราคาที่สูงขึ้น", subT: 103.5, kicker: "Sol ☀️ ซูเปอร์คาร์",
    stats: [{ t: 106.0, big: "Supercar", label: "แรงและเร็วที่สุด", tone: "clay" }],
  },
  {
    t: 110.42, mode: "pip", media: "web", file: "sec_pricing", kicker: "GPT-6 Luna: ฉลาด เน้นคุ้มค่า",
    cam: [{ t: 0, fy: 300, z: 1.25 }, { t: 8.0, fy: 300, z: 1.35 }],
    hl: [
      { t: 114.0, key: "price_luna", th: "Luna: ค่าใช้จ่ายเพียง $0.10 ต่อ 1M tokens" },
      { t: 117.0, key: "price_reduction", th: "ราคาลดลง 50% เทียบกับรุ่นก่อน" },
    ],
    stats: [{ t: 115.0, big: "Luna 🌙", label: "เน้นความคุ้มค่า", tone: "mint" }],
    gloss: [{ t: 111.0, term: "API Pricing", th: "ค่าบริการคิดตามจำนวนคำ/โทเค็นที่ใช้" }],
  },
  {
    t: 121.14, mode: "pip", media: "broll", src: "typing", headline: "เหมาะกับงานทั่วไปในชีวิต", sub: "ช่วยเขียนอีเมล สรุปบทความ ตอบคำถาม", subT: 123.5, kicker: "งานประจำวันของ Luna",
    stats: [
      { t: 122.0, label: "✉️ ช่วยเขียนอีเมล" },
      { t: 124.0, label: "📝 สรุปบทความยาว ๆ" },
      { t: 126.0, label: "🛍️ คิดแคปชั่นขายของ" },
      { t: 128.5, label: "💬 ตอบคำถามลูกค้า" },
    ],
  },
  {
    t: 133.94, mode: "pip", media: "explain", kicker: "เปรียบเทียบรถยนต์", explain: EXPLAIN_CARS,
  },
  {
    t: 143.36, mode: "pip", media: "typo", typo: "vs", src: "cyber", kicker: "สรุปการเลือกใช้",
  },
  {
    t: 149.00, mode: "full",
    next: { label: "หัวข้อต่อไป", items: ["🎯 เข้าใจบริบท", "🧠 ใช้เหตุผล", "💡 ความคิดสร้างสรรค์", "🌐 มัลติโมดอล"], t: 149.5 },
  },

  // ===== CHAPTER 3: 4 ด้านที่เก่งขึ้นก้าวกระโดด (src 151.64 to 221.90) ======
  {
    t: 151.64, mode: "pip", media: "broll", src: "brain", headline: "เก่งขึ้นกว่าเดิมยังไง?", sub: "จาก GPT-4 สู่ GPT-6 ก้าวกระโดดหลายขั้น", subT: 154.5, kicker: "การก้าวกระโดด",
    stats: [{ t: 158.0, label: "🤖 จากเดิมมี GPT-4" }, { t: 163.0, big: "ก้าวกระโดด", label: "พัฒนาขึ้นรอบด้าน", tone: "amber" }],
  },
  {
    t: 166.76, mode: "pip", media: "web", file: "sec_professional", kicker: "ข้อ 1: ความเข้าใจบริบท",
    cam: [{ t: 0, fy: 200, z: 1.15 }, { t: 8.0, fy: 220, z: 1.25 }],
    hl: [{ t: 169.0, key: "prof_benchmark", th: "ถามยาว ซับซ้อน หลายเงื่อนไข ไม่ตอบผิดประเด็น" }],
    stats: [{ t: 173.0, big: "แม่นยำขึ้น", label: "ไม่ตอบหลงประเด็น", tone: "mint" }],
  },
  {
    t: 175.91, mode: "pip", media: "chart", chart: CHART_BENCH, kicker: "ข้อ 2: การใช้เหตุผล (AutomationBench)",
  },
  {
    t: 184.48, mode: "pip", media: "broll", src: "abstract", headline: "ข้อ 3: ความคิดสร้างสรรค์", sub: "เนื้อหา ไอเดียการตลาด แผนงาน หลากหลายใช้ได้จริง", subT: 187.5, kicker: "ความคิดสร้างสรรค์",
    stats: [{ t: 189.0, label: "🎨 ไอเดียการตลาดแปลกใหม่" }, { t: 193.0, label: "📈 ออกแบบแผนงานใช้ได้จริง" }],
  },
  {
    t: 196.01, mode: "pip", media: "web", file: "sec_hero", kicker: "ผลลัพธ์หลากหลาย & ใช้ได้จริง",
    cam: [{ t: 0, fy: 240, z: 1.15 }, { t: 8.0, fy: 260, z: 1.25 }],
    hl: [{ t: 198.0, key: "hero_subtitle", th: "นำความฉลาดระดับแนวหน้ามาสู่การทำงานทุกวัน" }],
    stats: [{ t: 200.0, big: "ใช้ได้จริง", label: "ผลลัพธ์น่าสนใจและหลากหลาย", tone: "mint" }],
  },
  {
    t: 206.96, mode: "pip", media: "explain", kicker: "ข้อ 4: มัลติโมดอลเต็มรูปแบบ", explain: EXPLAIN_MULTIMODAL,
  },
  {
    t: 218.00, mode: "full",
    next: { label: "ประโยชน์กับทุกคน", items: ["🛍️ แม่ค้าออนไลน์", "🎓 นักศึกษา", "💼 พนักงานออฟฟิศ", "🏡 ครอบครัว"], t: 218.5 },
  },

  // ===== CHAPTER 4: ประโยชน์กับคนทั่วไป (src 221.90 to 288.78) ===============
  {
    t: 221.90, mode: "pip", media: "broll", src: "city_night", headline: "AI ไม่ใช่แค่เรื่องคน IT", sub: "แต่มีประโยชน์กับทุกคนในชีวิตประจำวัน", subT: 224.5, kicker: "AI เพื่อทุกคน",
  },
  {
    t: 233.82, mode: "pip", media: "broll", src: "shopping", headline: "แม่ค้าออนไลน์ 🛍️", sub: "เขียนแคปชั่น ตอบแชท คิดโปรโมชัน", subT: 235.5, kicker: "กลุ่มที่ 1: แม่ค้าออนไลน์",
    stats: [
      { t: 236.5, label: "✍️ บรรยายสินค้าน่าสนใจ" },
      { t: 240.5, label: "🤖 ตอบแชทลูกค้าอัตโนมัติ" },
      { t: 243.0, label: "🎉 คิดโปรโมชันกระตุ้นยอด" },
    ],
  },
  {
    t: 245.68, mode: "pip", media: "broll", src: "lab", headline: "นักเรียน นักศึกษา 🎓", sub: "อธิบายเรื่องยาก สรุปหนังสือ ฝึกภาษา", subT: 247.5, kicker: "กลุ่มที่ 2: นักเรียน นักศึกษา",
    stats: [
      { t: 248.5, label: "📚 อธิบายบทเรียนที่ไม่เข้าใจ" },
      { t: 251.5, label: "📖 สรุปหนังสือเล่มหนาเหลือไม่กี่หน้า" },
      { t: 254.5, label: "🗣️ ฝึกสนทนาภาษาอังกฤษ" },
    ],
  },
  {
    t: 257.42, mode: "pip", media: "broll", src: "office", headline: "พนักงานออฟฟิศ 💼", sub: "ร่างอีเมล พรีเซนต์ วิเคราะห์ยอดขาย", subT: 259.5, kicker: "กลุ่มที่ 3: คนทำงานออฟฟิศ",
    stats: [
      { t: 261.0, label: "📧 ร่างอีเมลติดต่อธุรกิจ" },
      { t: 263.5, label: "📊 ทำพรีเซนเทชันและวิเคราะห์ยอด" },
      { t: 266.5, big: "ประหยัดเวลา", label: "จากหลาย ชม. เหลือไม่กี่นาที", tone: "mint" },
    ],
  },
  {
    t: 270.00, mode: "pip", media: "explain", kicker: "ผู้ช่วยทุกคนในบ้าน", explain: EXPLAIN_EVERYDAY,
  },
  {
    t: 280.56, mode: "pip", media: "broll", src: "ai_network", headline: "ผู้ช่วยส่วนตัว 24 ชั่วโมง", sub: "รู้รอบด้าน พร้อมช่วยตลอด ไม่มีวันหยุด", subT: 283.0, kicker: "ผู้ช่วย 24 ชม.",
    stats: [{ t: 282.5, big: "24 ชั่วโมง", label: "พร้อมดูแลไม่มีวันหยุด", tone: "amber" }],
  },
  {
    t: 286.00, mode: "full",
    next: { label: "จะเลือกใช้ยังไงดี?", items: ["🌙 งานทั่วไป ใช้ Luna", "☀️ งานยาก ใช้ Sol", "🔄 สลับกันเพื่อความคุ้ม"], t: 286.5 },
  },

  // ===== CHAPTER 5: วิธีเลือกใช้ให้คุ้มค่า (src 288.78 to 334.40) =============
  {
    t: 288.78, mode: "pip", media: "web", file: "sec_pricing", kicker: "ควรเลือกใช้ตัวไหนดี?",
    cam: [{ t: 0, fy: 200, z: 1.15 }, { t: 8.0, fy: 220, z: 1.25 }],
    hl: [{ t: 291.0, key: "pricing_title", th: "พิจารณาตามลักษณะงานและงบประมาณ" }],
    stats: [{ t: 294.0, label: "🎯 ดูที่ลักษณะงานของเราเป็นหลัก" }],
  },
  {
    t: 297.74, mode: "pip", media: "broll", src: "typing", headline: "งานทั่วไป: เลือก Luna 🌙", sub: "เขียนข้อความ สรุปข้อมูล ตอบคำถาม ประหยัดกว่า", subT: 300.5, kicker: "Luna: สบายกระเป๋า",
    stats: [{ t: 302.0, big: "คุ้มค่ามาก", label: "งานประจำวันใช้ Luna เพียงพอ", tone: "mint" }],
  },
  {
    t: 309.70, mode: "pip", media: "broll", src: "coding", headline: "งานแม่นยำสูง: เลือก Sol ☀️", sub: "วิเคราะห์ซับซ้อน งานมืออาชีพ ห้ามผิดพลาด", subT: 312.5, kicker: "Sol: มืออาชีพ แม่นยำสูง",
    stats: [{ t: 314.0, big: "แม่นยำสูงสุด", label: "งานวิจัยและวิเคราะห์ขั้นสูง", tone: "amber" }],
  },
  {
    t: 322.48, mode: "pip", media: "broll", src: "server_lights", headline: "เทคนิค: ใช้สลับกันได้!", sub: "งานเบาใช้ Luna · งานหนักใช้ Sol คุ้มค่าและฉลาดที่สุด", subT: 325.5, kicker: "กลยุทธ์การใช้งาน",
    stats: [
      { t: 326.5, label: "🌙 งานเบาใช้ Luna" },
      { t: 329.5, label: "☀️ งานหนักใช้ Sol" },
      { t: 332.0, big: "คุ้มค่าสุด", label: "ประหยัดเงิน + ได้งานดีสุด", tone: "mint" },
    ],
  },
  {
    t: 332.50, mode: "full",
    next: { label: "ภาพใหญ่ของวงการ", items: ["🌍 ยุค AI สำหรับทุกคน", "📱 เหมือนยุคสมาร์ทโฟน", "💡 มุมมองประเทศไทย"], t: 333.0 },
  },

  // ===== CHAPTER 6: อนาคต AI กับทุกคน (src 334.40 to 382.56) =================
  {
    t: 334.40, mode: "pip", media: "broll", src: "datacenter", headline: "ภาพใหญ่ของวงการ AI", sub: "OpenAI ออก 2 รุ่น กำลังบอกอะไรเรา?", subT: 337.5, kicker: "อนาคตของ AI",
    stats: [{ t: 341.0, label: "🚀 เข้าสู่ยุคที่ทุกคนเข้าถึง AI ได้" }],
  },
  {
    t: 345.32, mode: "pip", media: "web", file: "sec_hero", kicker: "ทุกคนเข้าถึง AI ได้แล้ว",
    cam: [{ t: 0, fy: 200, z: 1.1 }, { t: 8.0, fy: 220, z: 1.2 }],
    hl: [{ t: 348.0, key: "hero_subtitle", th: "ไม่ใช่แค่บริษัทใหญ่ แต่คนธรรมดาก็ใช้ได้" }],
  },
  {
    t: 358.22, mode: "pip", media: "broll", src: "city_night", headline: "เหมือนยุคสมาร์ทโฟน", sub: "ตอนแรกคิดว่าไม่จำเป็น แต่วันนี้ขาดไม่ได้", subT: 361.0, kicker: "การเปลี่ยนแปลงครั้งใหญ่",
    stats: [{ t: 363.0, label: "📱 สมาร์ทโฟนในวันวาน" }, { t: 367.0, label: "🤖 AI ในอนาคตอันใกล้" }],
  },
  {
    t: 371.60, mode: "pip", media: "explain", kicker: "มุมมองประเทศไทย", explain: EXPLAIN_THAI,
  },
  {
    t: 380.00, mode: "full",
    next: { label: "สรุปส่งท้าย", items: ["☀️ Sol ตัวแรง", "🌙 Luna ตัวคุ้ม", "🔔 กด Subscribe"], t: 380.5 },
  },

  // ===== CHAPTER 7: สรุปส่งท้าย (src 382.56 to 414.00) ========================
  {
    t: 382.56, mode: "pip", media: "typo", typo: "summary3", src: "gen_ident", kicker: "สรุปสั้น ๆ อีกครั้ง",
  },
  {
    t: 395.18, mode: "pip", media: "typo", typo: "final4", src: "cyber", kicker: "GPT-6 Sol & Luna",
  },
  {
    t: 404.76, mode: "full",
    next: { pill: "ขอบคุณสำหรับการรับชม", items: ["👍 กดไลก์", "↗️ กดแชร์", "🔔 กดติดตามช่องของเรา"], t: 406.0 },
  },
];

// Typo scene word times (src)
export const AGENDA = [
  { t: 13.5, text: "มันคืออะไรกันแน่", icon: "❓" },
  { t: 14.8, text: "ทำอะไรได้บ้าง", icon: "⚡" },
  { t: 16.5, text: "ประโยชน์กับชีวิตเรา", icon: "💡" },
  { t: 21.5, text: "เข้าใจง่าย ไม่ใช่สาย IT", icon: "✨" },
  { t: 28.0, text: "เจาะลึก Sol & Luna", icon: "☀️" },
];
export const SUMMARY3 = [
  { t: 385.3, text: "Sol ตัวแรง ฉลาดสุด", icon: "☀️" },
  { t: 389.8, text: "Luna ตัวคุ้มค่า", icon: "🌙" },
  { t: 393.8, text: "ราคาถูกลง 50%", icon: "💸" },
];
export const FINAL4 = [
  { t: 396.2, text: "AI รุ่นใหม่ล่าสุด", icon: "🚀" },
  { t: 399.1, text: "ชีวิตเราง่ายขึ้น", icon: "✨" },
  { t: 401.6, text: "เรื่องงาน & เรื่องเรียน", icon: "💼" },
  { t: 403.1, text: "เรื่องส่วนตัวในชีวิต", icon: "🏡" },
];
export const VS = {
  fableT: 323.0,
  mythosT: 327.4,
  subT: 331.2,
  leftLines: [323.2, 324.8, 325.5],
  rightLines: [327.6, 328.6, 330.0],
};
export const CTA_T = 405.0;

// Marquee numbers: the music bed dips right before these (src seconds)
export const MUSIC_DIPS = [28.0, 79.5, 114.0, 175.9, 233.8, 384.5];

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
