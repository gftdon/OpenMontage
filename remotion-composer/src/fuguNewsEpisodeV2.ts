// ===========================================================================
// FuguNewsYT V2 — EPISODE DATA (pure TypeScript, no React)
// Sakana AI Launches Fugu Max and Fugu Ultra v2 for Cheaper, Stronger Multi-Agent Orchestration
// ===========================================================================
import { WEB_RECTS, type WebRect } from "./fuguNewsWeb";

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
  assetDir: "fugu-news",
  brand: "AI NEWS",
  dateLabel: "11 ก.ย. 2026",
  page: { domain: "marktechpost.com", path: "/sakana-ai-fugu-max-ultra-v2" },
  captureLabel: "VERIFIED · จับภาพ 11 ก.ย. 2026",
  officialTag: "OFFICIAL · SAKANA AI",
  previewTag: "PREVIEW",
  cta: { lead: "อ่านรายงานฉบับเต็มได้ที่", text: "marktechpost.com" },
  sting: {
    eyebrow: "AI NEWS · SEPTEMBER 2026",
    titleA: "Sakana AI Fugu",
    amp: "&",
    titleB: "Ultra v2",
    sub: "เปิดตัวแล้ว · ระบบ Multi-Agent ประหยัดกว่าเดิม 40-60%",
  },
  endcard: {
    eyebrow: "AI NEWS · SEPTEMBER 2026",
    titleA: "Sakana AI Fugu",
    titleB: "Ultra v2",
    sub: "อ่านฉบับเต็ม · marktechpost.com",
    cta: "ติดตามข่าวสาร AI ล่าสุด",
    next: "ติดตามข่าว AI ย่อยง่ายทุกสัปดาห์ · กด Subscribe 🔔",
  },
  agendaLabel: "ในคลิปนี้",
  summary3Label: "สรุปง่าย ๆ",
  final4: { title: "Fugu Max & Ultra v2", sub: "ก้าวสำคัญของ Multi-Agent Orchestration" },
  vs: {
    eyebrow: "สถาปัตยกรรมเดียวกัน · ต่างกันที่เป้าหมาย",
    left: { title: "Fugu Max", badge: "COST EFFICIENCY", lines: ["เน้นประหยัดต้นทุน", "$2/$6 ต่อ 1M tokens", "ส่งงานให้โมเดลขนาดเล็ก"] },
    right: { title: "Fugu Ultra v2", badge: "MAX CAPABILITY", lines: ["เน้นความแม่นยำสูงสุด", "ทำคะแนน 48.3 บน Chartography", "ใช้โมเดลระดับท็อปทำงานร่วมกัน"] },
    conclusion: "⚡ ปฏิวัติการใช้งาน AI ในองค์กรให้คุ้มค่าที่สุด",
  },
  thumbs: [
    { id: "A", lines: ["AI 2 ตัวใหม่", "ประหยัดกว่า 60%"], accent: "Sakana AI เปิดตัว Fugu", accentTone: "mint" as Tone },
    { id: "B", lines: ["Multi-Agent", "ทำงานแทนคนทั้งทีม"], accent: "Fugu Max & Ultra v2", accentTone: "amber" as Tone },
    { id: "C", lines: ["ชนะ AI ระดับโลก", "แต่ถูกลงครึ่งราคา"], accent: "Fugu Ultra v2", accentTone: "clay" as Tone },
  ],
};

// ---- Timeline (pre-lap teaser from the presenter's own lines) -------------
export const TIMELINE = {
  teaser: [
    { src: 11.99, end: 19.92 }, // "บริษัท Sakana AI ได้เปิดตัว AI ตัวใหม่ 2 ตัว ชื่อว่า Fugu Max กับ Fugu Ultra v2 ค่ะ"
    { src: 183.67, end: 186.90 }, // "มันทำคะแนนได้ถึง 48.3 คะแนน"
  ],
  stingDur: 2.6,
  mainSrcStart: 0.86, // skip "สวัสดีค่ะ"
  mainSrcEnd: 202.90, // last word end + 0.3
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
  { src: 0.86, title: "เปิดตัว 2 รุ่นใหม่" },
  { src: 23.74, title: "Multi-Agent คืออะไร" },
  { src: 79.30, title: "วาทยกร Orchestrator" },
  { src: 113.54, title: "Fugu Max สายประหยัด" },
  { src: 148.66, title: "ราคา $2 / $6 Tokens" },
  { src: 174.78, title: "Fugu Ultra v2 ตัวท็อป" },
  { src: 191.36, title: "เทียบ AI ชั้นนำของโลก" },
];

// ---- B-roll durations (public/fugu-news/broll) ------------------------------
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

// ---- Terminal demo (a real orchestration session) -------------------------
export const TERMINAL_DEMO: Terminal = {
  title: "curl -s api.sakana.ai/v1/chat/completions",
  tag: "DEMO · Fugu Orchestrator",
  lines: [
    { t: 0.0, kind: "cmd", text: "curl -X POST https://api.sakana.ai/v1/chat/completions -d '{\"model\":\"fugu-max\",\"query\":\"Analyze quarterly report and calculate profit margins\"}'" },
    { t: 0.8, kind: "dim", text: "→ Fugu Orchestrator: analyzing task complexity..." },
    { t: 1.4, kind: "claude", text: "TRINITY Coordinator: [Thinker role assigned] → breakdown query into 3 subtasks" },
    { t: 2.2, kind: "out", text: "1. Data Extraction → Nemotron 8B ($0.002) [Lean Worker]" },
    { t: 2.9, kind: "out", text: "2. Margin Computation → Python Exec Env [Specialized Tool]" },
    { t: 3.6, kind: "out", text: "3. Synthesis & QA → Fugu Verifier [Verifier role]" },
    { t: 4.3, kind: "dim", text: "Tokens: 1,420 in / 380 out | Total cost: $0.0051 (vs $0.028 on frontier model)" },
    { t: 5.0, kind: "ok", text: "HTTP 200 OK — Fugu Max routed across 3 models seamlessly in 1.4s" },
  ],
};

// ---- Charts & Explains -----------------------------------------------------
export const CHART_PRICING: Chart = {
  title: "ราคา Output Tokens ($ ต่อ 1 ล้านโทเค็น)",
  sub: "ยิ่งต่ำยิ่งประหยัด · ตัวเลขจาก Sakana AI / MarkTechPost",
  unit: "$",
  max: 18,
  bars: [
    { label: "Fugu Max", value: 6.0, tone: "mint", note: "ถูกที่สุด" },
    { label: "Kimi K3", value: 10.0, note: "+66%" },
    { label: "GPT-5.6 Terra", value: 12.0, note: "+100%" },
    { label: "Sonnet 5", value: 15.0, note: "+150%" },
  ],
};

export const CHART_BENCHMARK: Chart = {
  title: "คะแนน Chartography (Visual Reasoning)",
  sub: "ยิ่งสูงยิ่งฉลาด · การคิดวิเคราะห์ข้อมูลซับซ้อน",
  unit: "pts",
  max: 60,
  bars: [
    { label: "Fugu Ultra v2", value: 48.3, tone: "mint", note: "อันดับ 1 ในโลก" },
    { label: "Fable 5", value: 29.5 },
    { label: "Opus 5", value: 27.3 },
  ],
};

export const EXPLAIN_MULTI_AGENT: Explain = {
  title: "Multi-Agent คืออะไร?",
  sub: "แนวคิดการให้ AI หลายตัวทำงานร่วมกันเป็นทีม",
  layout: "flow",
  items: [
    { t: 52.8, icon: "👤", text: "Agent = ผู้ช่วย AI ที่เชี่ยวชาญเฉพาะเรื่อง", tone: "mint" },
    { t: 56.5, icon: "👥", text: "Multi-Agent = AI หลายตัวแบ่งหน้าที่กันทำ", tone: "amber" },
    { t: 62.4, icon: "🏢", text: "เหมือนทีมเลขา: จัดตาราง · วิเคราะห์ · ทำเอกสาร", tone: "clay" },
    { t: 70.0, icon: "🎯", text: "ส่งผลลัพธ์ที่แม่นยำและเสร็จไวกว่าทำคนเดียว" },
  ],
  footnote: "สถาปัตยกรรมแห่งอนาคตที่ก้าวข้ามขีดจำกัดของโมเดลเดี่ยว",
};

export const EXPLAIN_COMPARE: Explain = {
  title: "สรุปเปรียบเทียบ Fugu 2 รุ่น",
  sub: "เลือกใช้ให้ตรงกับงานและงบประมาณ",
  layout: "compare",
  left: { title: "Fugu Max", icon: "💰", tone: "mint" },
  right: { title: "Fugu Ultra v2", icon: "🚀", tone: "clay" },
  items: [
    { t: 194.5, icon: "🎯", text: "เป้าหมาย: ประหยัดต้นทุนสูงสุด vs ศักยภาพสูงสุด" },
    { t: 196.5, icon: "💵", text: "ราคา: $2/$6 ต่อ 1M tokens vs ราคาตามโมเดลท็อป" },
    { t: 198.5, icon: "🧠", text: "งานที่เหมาะ: งานทั่วไป/ออฟฟิศ vs วิจัย/โค้ดดิ้งลึก" },
  ],
  footnote: "เชื่อมต่อผ่าน OpenAI-compatible API เดียวกันทั้งสองโมเดล",
};

// ---- BEATS (src times; mapped to timeline by mapMain) ---------------------
export const BEATS: Beat[] = [
  // ===== TEASER (abs: true, timeline seconds) =============================
  {
    t: 0.0, abs: true, mode: "pip", media: "broll", src: "gen_ident", hook: true,
    kicker: "AI NEWS · EXCLUSIVE", headline: "Sakana AI เปิดตัว 2 โมเดลใหม่",
    sub: "Fugu Max & Fugu Ultra v2", subT: 1.5,
    stats: [{ t: 0.5, big: "2 โมเดล", label: "Fugu Max & Ultra v2", tone: "mint" }],
  },
  {
    t: SEG.teaser[1].dst, abs: true, mode: "pip", media: "broll", src: "gen_glitch", hook: true,
    kicker: "BENCHMARK RECORD", headline: "ทำคะแนนสถิติโลก 48.3",
    sub: "บนแบบทดสอบ Chartography", subT: SEG.teaser[1].dst + 1.0,
    stats: [{ t: SEG.teaser[1].dst + 0.3, big: "48.3", label: "คะแนน Chartography", tone: "mint" }],
  },
  // STING at timeline sec
  { t: SEG.stingStart, abs: true, mode: "full", typo: "sting" },

  // ===== MAIN EPISODE (src times in avatar_source.mp4) =====================
  // ---- 1. OPEN & AGENDA (L2..L8: 0.86 - 20.98s) ---------------------------
  {
    t: 0.86, mode: "full", typo: "agenda",
    lower: { title: "ข่าวเทคโนโลยีวันนี้", sub: "Sakana AI เปิดตัว Fugu Max & Ultra v2", dur: 5.0 },
  },
  {
    t: 11.08, mode: "pip", media: "web", file: "sec_hero", kicker: "Sakana AI · เปิดตัว 2 โมเดลใหม่",
    cam: [{ t: 0, fy: 80, z: 1.25 }, { t: 4, fy: 100, z: 1.30 }],
    hl: [
      { t: 12.1, rect: WEB_RECTS.hero_title, th: "Sakana AI เปิดตัว Fugu Max และ Fugu Ultra v2 ระบบ Multi-Agent อัจฉริยะ" },
      { t: 16.4, rect: WEB_RECTS.intro_routes, th: "เชื่อมโยงโมเดลหลายตัวผ่าน 1 API เดียวกัน" },
    ],
    stats: [{ t: 13.5, big: "2 โมเดล", label: "Fugu Max & Ultra v2", tone: "mint" }],
  },
  {
    t: 19.76, mode: "full",
    next: { label: "หัวข้อที่จะเล่า", items: ["Multi-Agent คืออะไร", "วาทยกร Orchestrator", "Fugu Max สายประหยัด", "Fugu Ultra v2 ตัวท็อป"], t: 20.2 },
  },

  // ---- 2. MULTI-AGENT & ORCHESTRATOR (L11..L40: 23.74 - 113.54s) ---------
  {
    t: 23.74, mode: "pip", media: "broll", src: "chat_ai", kicker: "การใช้ AI ทั่วไป",
    headline: "AI รูปแบบเดิม", sub: "ถามไป แล้ว AI ตอบกลับมา", subT: 27.9,
    stats: [{ t: 25.4, label: "💬 ChatGPT / Gemini" }, { t: 28.0, label: "⚡ คำถาม 1 ข้อ → คำตอบ 1 ข้อ" }],
  },
  {
    t: 32.14, mode: "pip", media: "broll", src: "ai_network", kicker: "AI ยุคใหม่",
    headline: "ทำงานหลายอย่างพร้อมกัน", sub: "ค้นหาข้อมูล · วิเคราะห์ตัวเลข · เขียนรายงาน", subT: 38.3,
    stats: [{ t: 38.4, label: "🔍 ค้นหาข้อมูล" }, { t: 40.0, label: "📊 วิเคราะห์ตัวเลข" }],
  },
  {
    t: 42.69, mode: "pip", media: "broll", src: "coding", kicker: "ระบบอัตโนมัติ",
    headline: "ส่งงานเสร็จในคราวเดียว", sub: "รายงานสรุปและอีเมลส่งถึงมือทันที", subT: 44.8,
    stats: [{ t: 44.8, label: "⚡ สรุปผลและส่งอีเมลทันที" }],
  },
  {
    t: 50.29, mode: "pip", media: "explain", kicker: "แนวคิดสำคัญ", explain: EXPLAIN_MULTI_AGENT,
    stats: [{ t: 51.3, big: "Multi-Agent", label: "ทีมผู้ช่วย AI ร่วมมือกัน", tone: "mint" }],
  },
  {
    t: 60.90, mode: "full",
    next: { label: "ลองนึกภาพตาม", items: ["เลขาจัดตาราง", "เลขาวิเคราะห์ตัวเลข", "เลขาเขียนเอกสาร"], t: 61.5 },
  },
  {
    t: 66.89, mode: "pip", media: "broll", src: "office", from: 1, kicker: "การแบ่งงานเป็นทีม",
    headline: "หัวหน้าเลขาคุมงาน", sub: "คอยแจกจ่ายงานให้คนที่เก่งที่สุด", subT: 73.1,
    stats: [{ t: 73.5, label: "👩‍💼 หัวหน้าเลขาแจกงาน" }],
  },
  {
    t: 79.30, mode: "pip", media: "web", file: "sec_orchestration", kicker: "หลักการ Orchestration",
    cam: [{ t: 0, fy: 120, z: 1.25 }, { t: 4, fy: 150, z: 1.30 }],
    hl: [
      { t: 81.2, rect: WEB_RECTS.orch_models, th: "Fugu ทำหน้าที่เป็นโมเดลสมอง ออกแบบ Workflow อัตโนมัติ" },
      { t: 85.0, rect: WEB_RECTS.orch_scaffold, th: "สร้างโครงสร้างเอเจนต์แบบ On-the-fly ตามคำสั่ง" },
    ],
    stats: [{ t: 81.9, big: "Orchestrator", label: "วาทยกรคุมวงดนตรี AI", tone: "mint" }],
  },
  {
    t: 94.68, mode: "pip", media: "terminal", kicker: "ระบบเบื้องหลัง", terminal: TERMINAL_DEMO,
    headline: "การกระจายงานอัตโนมัติ",
  },
  {
    t: 106.0, mode: "full",
    next: { label: "ถัดไป ▶", items: ["Fugu Max ($2/$6)", "Fugu Ultra v2 (48.3 pts)"], tease: "ประหยัดกว่าเดิม 40-60%", t: 107.0 },
  },

  // ---- 3. FUGU MAX & COST-EFFICIENCY (L41..L60: 113.54 - 174.78s) --------
  {
    t: 113.54, mode: "pip", media: "web", file: "sec_fugu_max", kicker: "โมเดลที่ 1 · Fugu Max",
    cam: [{ t: 0, fy: 80, z: 1.25 }, { t: 4, fy: 100, z: 1.30 }, { t: 8, fy: 120, z: 1.32 }],
    hl: [
      { t: 117.9, rect: WEB_RECTS.max_leanest, th: "ส่งงานให้โมเดลที่เล็กที่สุดที่ยังแก้ปัญหานั้นได้สำเร็จ" },
      { t: 121.0, rect: WEB_RECTS.max_nemotron, th: "เชื่อมต่อกับ NVIDIA Nemotron และ Open-weights อื่น ๆ" },
    ],
    stats: [{ t: 119.0, big: "Fugu Max", label: "เน้นความคุ้มค่าสูงสุด", tone: "mint" }],
  },
  {
    t: 125.18, mode: "pip", media: "web", file: "sec_fugu_max", kicker: "การเลือกโมเดลตามระดับงาน",
    cam: [{ t: 0, fy: 120, z: 1.28 }, { t: 4, fy: 150, z: 1.32 }],
    hl: [
      { t: 126.6, rect: WEB_RECTS.max_leanest, th: "ส่งงานให้โมเดลที่เล็กที่สุดที่ยังแก้ปัญหานั้นได้สำเร็จ" },
    ],
    stats: [
      { t: 130.0, label: "🤖 งานง่าย → AI ตัวเล็กราคาถูก" },
      { t: 135.2, label: "🧠 งานยาก → AI ตัวใหญ่ราคาแพง" },
    ],
  },
  {
    t: 139.16, mode: "pip", media: "broll", src: "handshake", kicker: "หลักการประหยัดต้นทุน",
    headline: "เลือกคนให้เหมาะกับงาน", sub: "งานง่ายใช้น้องฝึกงาน · งานยากใช้ผู้จัดการ", subT: 141.7,
    stats: [{ t: 142.0, label: "📑 ถ่ายเอกสาร → น้องฝึกงาน" }, { t: 146.0, label: "💡 ไม่จำเป็นต้องจ้างผู้จัดการ" }],
  },
  {
    t: 148.66, mode: "pip", media: "web", file: "sec_fugu_max", kicker: "ราคาค่าบริการ · Fugu Max",
    cam: [{ t: 0, fy: 260, z: 1.30 }, { t: 4, fy: 290, z: 1.35 }],
    hl: [
      { t: 152.0, rect: WEB_RECTS.max_pricing, th: "อินพุต $2 / ล้านโทเค็น · เอาต์พุต $6 / ล้านโทเค็น" },
      { t: 156.9, rect: WEB_RECTS.max_lower, th: "ราคาเอาต์พุตถูกลง 40% ถึง 60% เมื่อเทียบกับโมเดลท็อป" },
    ],
    stats: [
      { t: 154.1, big: "$2 / $6", label: "ต่อ 1M Tokens (In/Out)", tone: "mint" },
      { t: 160.1, big: "-40% ถึง -60%", label: "ประหยัดกว่า Sonnet 5", tone: "amber" },
    ],
  },
  {
    t: 161.56, mode: "pip", media: "chart", kicker: "เปรียบเทียบราคา Output Tokens", src: "gen_ident", chart: CHART_PRICING,
  },
  {
    t: 171.0, mode: "full",
    next: { label: "ถัดไป ▶", items: ["Fugu Ultra v2", "คะแนน 48.3 สถิติโลก"], tease: "ฉลาดที่สุดบน Chartography", t: 171.5 },
  },

  // ---- 4. FUGU ULTRA V2 & CAPABILITY (L61..L70: 174.78 - 202.60s) --------
  {
    t: 174.78, mode: "pip", media: "web", file: "sec_fugu_ultra", kicker: "โมเดลที่ 2 · Fugu Ultra v2",
    cam: [{ t: 0, fy: 60, z: 1.25 }, { t: 4, fy: 90, z: 1.30 }],
    hl: [
      { t: 176.5, rect: WEB_RECTS.ultra_targets, th: "เน้นงานคิดวิเคราะห์ซับซ้อน งานวิจัย และเขียนโปรแกรมเต็มระบบ" },
    ],
    stats: [{ t: 178.0, big: "Ultra v2", label: "ศักยภาพระดับสูงสุด", tone: "clay" }],
  },
  {
    t: 183.84, mode: "pip", media: "chart", kicker: "ผลทดสอบ Chartography", src: "gen_ident", chart: CHART_BENCHMARK,
  },
  {
    t: 193.86, mode: "pip", media: "explain", kicker: "สรุปเปรียบเทียบ", explain: EXPLAIN_COMPARE,
  },
  {
    t: 201.0, mode: "full",
    next: { label: "ติดตามข่าว AI", items: ["กด Subscribe 🔔", "อัปเดตข่าวทุกวัน"], pill: "SUBSCRIBE 🔔", t: 201.5 },
  },
];

// ---- Typo scenes (src times) -----------------------------------------------
export const AGENDA = [
  { t: 12.6, text: "Sakana AI", icon: "🏢" },
  { t: 16.4, text: "Fugu Max", icon: "💰" },
  { t: 17.6, text: "Fugu Ultra v2", icon: "🚀" },
  { t: 154.1, text: "$2/$6 Tokens", icon: "💸" },
  { t: 185.3, text: "48.3 Benchmark", icon: "🏆" },
];

export const SUMMARY3 = [
  { t: 117.9, text: "Fugu Max เน้นคุ้มค่า", icon: "💰" },
  { t: 154.1, text: "ราคา $2/$6 ต่อล้าน", icon: "💸" },
  { t: 185.3, text: "Ultra v2 สถิติโลก 48.3", icon: "🏆" },
];

export const FINAL4 = [
  { t: 194.5, text: "Multi-Agent ล้ำหน้า", icon: "👥" },
  { t: 196.5, text: "วาทยกรคุมงานอัตโนมัติ", icon: "🎼" },
  { t: 198.5, text: "ประหยัดต้นทุน 40-60%", icon: "💸" },
  { t: 200.5, text: "เชื่อมผ่าน 1 API ทันที", icon: "⚡" },
];

export const VS = {
  fableT: 117.9,
  mythosT: 176.5,
  subT: 194.5,
  leftLines: [118.5, 121.2, 130.0],
  rightLines: [178.0, 183.8, 193.8],
};

export const CTA_T = 201.0;

// Marquee numbers: the music bed dips right before these (src seconds)
export const MUSIC_DIPS = [11.9, 117.9, 153.6, 184.2, 198.5];

// ---- Timeline-space views (what the engine and audio scripts consume) ------
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
export const VS_TL = {
  fableT: mapMain(VS.fableT),
  mythosT: mapMain(VS.mythosT),
  subT: mapMain(VS.subT),
  leftLines: VS.leftLines.map(mapMain),
  rightLines: VS.rightLines.map(mapMain),
};
export const CTA_TL = mapMain(CTA_T);
export const CHAPTERS_TL = CHAPTERS.map((c) => ({ ...c, t: mapMain(c.src) }));
export const VO_END_TL = SEG.voEnd;
export const TOTAL_TL = SEG.total;

export const R = {
  row: (rectKey: string) => WEB_RECTS[rectKey] ?? { x: 89, y: 100, w: 550, h: 44 },
};
