// ===========================================================================
// TripoGameNewsYT V2 — EPISODE DATA (pure TypeScript, no React)
// 4 AI Build a Game From Scratch & Tripo P2.0 3D Model Generation
// ===========================================================================
import { WEB_RECTS, type WebRect } from "./tripoGameWeb";

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
  assetDir: "tripoGameNews",
  brand: "AI GAME REPORT",
  dateLabel: "15 ก.ย. 2026",
  page: { domain: "developers.tripo3d.ai", path: "/tripo-3d-api" },
  captureLabel: "VERIFIED · จับภาพ 15 ก.ย. 2026",
  officialTag: "OFFICIAL · TRIPO 3D",
  previewTag: "SPECIAL REPORT",
  cta: { lead: "ทดลองสร้างโมเดล 3D ฟรีได้ที่", text: "tripo3d.ai" },
  sting: {
    eyebrow: "SPECIAL REPORT · SEPTEMBER 2026",
    titleA: "4 AI สร้างเกม",
    amp: "&",
    titleB: "Tripo P2.0",
    sub: "สร้างเกมจากศูนย์ · ไม่ต้องเขียนโค้ดแม้แต่บรรทัดเดียว",
  },
  endcard: {
    eyebrow: "AI SPECIAL REPORT · SEPTEMBER 2026",
    titleA: "4 AI สร้างเกม",
    titleB: "Tripo P2.0",
    sub: "ทดลองใช้งานได้ที่ · tripo3d.ai",
    cta: "กดติดตามเพื่อไม่พลาดข่าวสาร AI ใหม่ล่าสุด",
    next: "ติดตามเทคนิค AI ย่อยง่ายทุกสัปดาห์ · กด Subscribe 🔔",
  },
  agendaLabel: "ในคลิปนี้",
  summary3Label: "สรุป 4 ข้อคิดสำคัญ",
  final4: { title: "4 AI สร้างเกมจากศูนย์", sub: "ปฏิวัติการสร้างสื่อและเกมในยุค AI" },
  vs: {
    eyebrow: "การสร้างเกม: อดีต vs ยุค AI",
    left: { title: "ทีมงานแบบเดิม", badge: "TRADITIONAL", lines: ["ต้องใช้คนหลายฝ่าย", "ต้องฝึกทักษะเฉพาะทางหลายปี", "ใช้เวลาสร้างนานหลายเดือน"] },
    right: { title: "4 AI ทำงานเป็นทีม", badge: "AI ERA", lines: ["คนเดียวคุมงานเหมือนผู้กำกับ", "ไม่ต้องเขียนโค้ดเองแม้แต่บรรทัดเดียว", "สร้างเสร็จได้ในไม่กี่วัน"] },
    conclusion: "⚡ คิดเป็น สื่อสารเป็น ก็สร้างงานระดับมืออาชีพได้",
  },
  thumbs: [
    { id: "A", lines: ["4 AI สร้างเกม", "จากศูนย์ไม่ต้องเขียนโค้ด"], accent: "Tripo P2.0 ปั้น 3D", accentTone: "mint" as Tone },
    { id: "B", lines: ["มีทีมงาน 4 คน", "ทำงานแทนตลอด 24 ชม."], accent: "AI Game Dev", accentTone: "amber" as Tone },
    { id: "C", lines: ["ปั้น 3D ได้ในพริบตา", "คนไม่เป็นโค้ดก็ทำได้"], accent: "โอกาสใหม่ของทุกคน", accentTone: "clay" as Tone },
  ],
};

// ---- Timeline (pre-lap teaser from the presenter's own lines) -------------
export const TIMELINE = {
  teaser: [
    { src: 14.35, end: 20.88 }, // "วันนี้เราจะมาดูกันว่า มีคนใช้ AI ถึง 4 ตัว มาช่วยกันสร้างเกมขึ้นมาจากศูนย์เลย"
    { src: 20.88, end: 24.63 }, // "โดยที่เขาไม่ต้องเขียนโค้ดเองแม้แต่บรรทัดเดียว"
  ],
  stingDur: 2.6,
  mainSrcStart: 0.76, // skip "สวัสดีค่ะ"
  mainSrcEnd: 370.10, // last word end + 0.3
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
  { src: 0.76, title: "4 AI สร้างเกมจากศูนย์" },
  { src: 31.26, title: "AI แทนทีมงาน 4 คน" },
  { src: 81.62, title: "Tripo 3D ปั้นโมเดล" },
  { src: 129.60, title: "AI เขียนโค้ดระบบเกม" },
  { src: 171.58, title: "AI สร้างภาพและเสียง" },
  { src: 217.04, title: "ประโยชน์สำหรับทุกคน" },
  { src: 267.30, title: "ทักษะสำคัญในยุค AI" },
  { src: 307.54, title: "สรุป 4 ข้อคิดสำคัญ" },
  { src: 361.18, title: "ส่งท้าย & Subscribe" },
];

export const BROLL_DUR: Record<string, number> = {
  abstract: 30.00,
  ai_network: 30.00,
  brain: 10.00,
  coding: 14.96,
  cyber: 30.00,
  gaming: 24.16,
  gen_glitch: 5.04,
  gen_ident: 5.04,
  gladiator: 10.04,
  office: 14.80,
  shopping: 10.00,
  studio: 8.00,
  typing: 12.16,
};

// ---- Terminal demo (Tripo CLI & Agent Workflow) -----------------------------
export const TERMINAL_DEMO: Terminal = {
  title: "npx tripo-cli generate --prompt \"Gladiator warrior\"",
  tag: "DEMO · CLAUDE CODE & TRIPO CLI",
  lines: [
    { t: 0.0, kind: "cmd", text: "npx tripo-cli generate --prompt \"Gladiator warrior with shield\" --pbr" },
    { t: 0.8, kind: "dim", text: "→ Connecting to Tripo API v3 (Developers SDK)..." },
    { t: 1.5, kind: "claude", text: "Tripo P2.0: Generating high-fidelity 3D mesh (12,450 polygons)" },
    { t: 2.2, kind: "out", text: "Auto-rigging skeleton & 100+ motion presets applied [OK]" },
    { t: 3.0, kind: "out", text: "PBR materials: BaseColor, Normal, Roughness, Metalness 8K" },
    { t: 3.8, kind: "ok", text: "Exported: gladiator_hero.glb (Ready for Game Engine)" },
    { t: 4.5, kind: "cmd", text: "claude \"Write player controller script with jump & sprint physics\"" },
    { t: 5.2, kind: "out", text: "AI Programmer generated 180 lines of game logic in 2.1s" },
    { t: 6.0, kind: "ok", text: "Game Build Succeeded: 60 FPS verified without human code" },
  ],
};

// ---- Charts & Explains -----------------------------------------------------
export const CHART_PRODUCTION_TIME: Chart = {
  title: "ระยะเวลาในการสร้างเกมต้นแบบ (Prototype)",
  sub: "เปรียบเทียบการทำงานแบบเดิมกับ 4 AI · ประหยัดเวลา 98%",
  unit: "วัน",
  max: 100,
  bars: [
    { label: "ทีมคนทั่วไป", value: 90.0, note: "3 เดือน" },
    { label: "เขียนโค้ดเอง", value: 45.0, note: "1.5 เดือน" },
    { label: "ปั้น 3D มือ", value: 30.0, note: "1 เดือน" },
    { label: "4 AI ร่วมมือกัน", value: 1.0, tone: "mint", note: "เสร็จใน 1 วัน" },
  ],
};

export const EXPLAIN_AI_TEAM: Explain = {
  title: "ทีมงาน AI 4 คน ทำหน้าที่อะไรบ้าง?",
  sub: "แต่ละตัวเชี่ยวชาญคนละด้าน ทำตามคำสั่งตลอด 24 ชม.",
  layout: "flow",
  items: [
    { t: 55.5, icon: "🗿", text: "1. Tripo P2.0: ปั้นโมเดล 3D และตัวละครเกม", tone: "mint" },
    { t: 58.5, icon: "💻", text: "2. Coding AI: เขียนโค้ดระบบวิ่ง กระโดด ควบคุม", tone: "amber" },
    { t: 61.5, icon: "🎨", text: "3. Image AI: วาดฉากหลัง ป่าไม้ ภูเขา ท้องฟ้า", tone: "clay" },
    { t: 64.5, icon: "🎵", text: "4. Audio AI: สร้างเสียงดาบฟัน เอฟเฟกต์ และดนตรี" },
  ],
  footnote: "รวมกัน 4 ตัวเหมือนมีสตูดิโอสร้างเกมครบวงจร โดยไม่ต้องจ้างคนเพิ่ม",
};

export const EXPLAIN_DIRECTOR: Explain = {
  title: "เราคือผู้กำกับหนัง (Director Model)",
  sub: "สั่งงานด้วยความคิด ไม่ต้องลงมือทำทางเทคนิคเอง",
  layout: "list",
  items: [
    { t: 71.2, icon: "🎬", text: "ไม่ต้องถือกล้องเอง · ไม่ต้องแต่งหน้าเอง", tone: "amber" },
    { t: 74.2, icon: "🗣️", text: "แค่บอกว่าอยากได้ฉากแบบไหน ทีมงานไปจัดการให้", tone: "mint" },
    { t: 78.4, icon: "⚡", text: "AI ทำหน้าที่เป็นทีมงานคอยซัพพอร์ตความคิดเรา", tone: "clay" },
  ],
  footnote: "เปลี่ยนจากการลงแรง ทำงานซ้ำซาก มาเป็นผู้นำทางความคิดและการสร้างสรรค์",
};

export const EXPLAIN_USE_CASES: Explain = {
  title: "ใครได้ประโยชน์จากเทคโนโลยีนี้บ้าง?",
  sub: "ไม่ได้จำกัดแค่คนทำเกม ประยุกต์ได้กับทุกสายงาน",
  layout: "list",
  items: [
    { t: 239.5, icon: "🛍️", text: "ขายของออนไลน์: ภาพสินค้า 3 มิติ หมุนดูได้ 360°", tone: "mint" },
    { t: 247.2, icon: "📚", text: "ครูและอาจารย์: สื่อการสอน 3D จำลองเห็นภาพเข้าใจง่าย", tone: "amber" },
    { t: 254.6, icon: "📐", text: "นักออกแบบ: สร้างโมเดลต้นแบบ Prototype ในไม่กี่นาที", tone: "clay" },
    { t: 261.0, icon: "📱", text: "ครีเอเตอร์: สร้างภาพ แอนิเมชัน และวิดีโอลงโซเชียล" },
  ],
  footnote: "เปิดโอกาสให้ทุกคนสร้างสื่อคุณภาพสูงได้ด้วยตนเอง",
};

export const EXPLAIN_FUTURE_SKILLS: Explain = {
  title: "ทักษะที่สำคัญที่สุดในยุค AI",
  sub: "จากทักษะทางเทคนิค สู่ทักษะการคิดและการสื่อสาร",
  layout: "compare",
  left: { title: "ยุคเดิม (Past)", icon: "⚙️", tone: "clay" },
  right: { title: "ยุค AI (Future)", icon: "💡", tone: "mint" },
  items: [
    { t: 289.8, icon: "🎯", text: "ต้องเรียนรู้โค้ดลึก vs รู้ว่าอยากได้อะไรและสั่ง AI ให้ตรงจุด" },
    { t: 294.2, icon: "🗣️", text: "ทักษะเทคนิคเฉพาะด้าน vs ทักษะการคิดวิเคราะห์และการสื่อสาร" },
    { t: 299.9, icon: "🚀", text: "ทำงานตามกรอบจำกัด vs คนคิดเป็นสร้างงานได้ทุกรูปแบบ" },
  ],
  footnote: "โอกาสที่เปิดกว้างสำหรับทุกคนที่ไม่หยุดเรียนรู้สิ่งใหม่",
};

export const EXPLAIN_MUM_THAI: Explain = {
  title: "มุมไทย: เริ่มต้นใช้งาน Tripo 3D",
  sub: "เครื่องมือสร้างโมเดลสามมิติด้วย AI สำหรับคนไทย",
  layout: "list",
  items: [
    { t: 348.8, icon: "🌐", text: "ใช้งานง่ายผ่านเบราว์เซอร์ที่เว็บไซต์ tripo3d.ai", tone: "mint" },
    { t: 351.5, icon: "🎁", text: "สมัครใหม่รับฟรี 300 Credits ทดลองปั้นโมเดลได้ทันที", tone: "amber" },
    { t: 354.8, icon: "📦", text: "Export ไฟล์ .GLB / .FBX / .USDZ นำไปใช้ใน Unity, Unreal, Blender ได้เลย", tone: "clay" },
  ],
  footnote: "รองรับคำสั่งภาษาอังกฤษ และนำไปต่อยอดได้ในทุกอุตสาหกรรมสร้างสรรค์",
};

// ---- BEATS (src times; mapped to timeline by mapMain) ---------------------
export const BEATS: Beat[] = [
  // ===== TEASER (abs: true, timeline seconds) =============================
  {
    t: 0.0, abs: true, mode: "pip", media: "broll", src: "gen_ident", hook: true,
    kicker: "AI GAME REPORT · EXCLUSIVE", headline: "4 AI ร่วมมือสร้างเกมจากศูนย์",
    sub: "ไม่ต้องเขียนโค้ดแม้แต่บรรทัดเดียว", subT: 1.5,
    stats: [{ t: 0.5, big: "4 AI", label: "ทำงานร่วมกันเป็นทีม", tone: "mint" }],
  },
  {
    t: SEG.teaser[1].dst, abs: true, mode: "pip", media: "broll", src: "cyber", hook: true,
    kicker: "NO CODE GAME DEV", headline: "เปลี่ยนคำสั่งเป็นเกมจริง",
    sub: "Tripo 3D & AI Coding Agent", subT: SEG.teaser[1].dst + 0.8,
    stats: [{ t: SEG.teaser[1].dst + 0.3, big: "0 โค้ด", label: "สร้างเกมได้ทันที", tone: "mint" }],
  },
  // STING at timeline sec
  { t: SEG.stingStart, abs: true, mode: "full", typo: "sting" },

  // ===== MAIN EPISODE (src times in avatar_source.mp4) =====================
  // ---- 1. OPEN & AGENDA (L2..L12: 0.76 - 31.26s) --------------------------
  {
    t: 0.76, mode: "full", typo: "agenda",
    lower: { title: "รายงานพิเศษวันนี้", sub: "เมื่อ 4 AI ช่วยกันสร้างเกมจากศูนย์", dur: 5.0 },
  },
  {
    t: 4.18, mode: "pip", media: "broll", src: "gaming", kicker: "คำถามยอดฮิต",
    headline: "อยากสร้างเกมสักเกม?", sub: "แต่เขียนโปรแกรมไม่เป็นเลย จะทำได้ไหม?", subT: 6.96,
    stats: [{ t: 7.5, label: "🎮 อยากทำเกม" }, { t: 9.37, label: "❌ เขียนโค้ดไม่เป็น" }],
  },
  {
    t: 10.48, mode: "pip", media: "broll", src: "gladiator", kicker: "คำตอบในยุคนี้",
    headline: "ทำได้แล้วในยุคนี้!", sub: "มีคนใช้ AI ถึง 4 ตัว สร้างเกมขึ้นมาจากศูนย์", subT: 14.52,
    stats: [{ t: 14.52, big: "4 AI", label: "ช่วยกันสร้างเกมขึ้นมา", tone: "mint" }],
  },
  {
    t: 20.88, mode: "pip", media: "broll", src: "coding", kicker: "ความมหัศจรรย์",
    headline: "ไม่ต้องเขียนโค้ดเอง", sub: "แม้แต่บรรทัดเดียว เกิดขึ้นจริงแล้ว", subT: 24.60,
    stats: [{ t: 22.62, label: "⚡ Zero Code Development" }],
  },
  {
    t: 29.20, mode: "full",
    next: { label: "หัวข้อที่จะเล่า", items: ["AI แทนทีมงาน 4 คน", "Tripo 3D ปั้นโมเดล", "AI เขียนโค้ดเกม", "ทุกคนสร้างงานได้"], t: 29.5 },
  },

  // ---- 2. OVERVIEW: AI TEAM (L13..L26: 31.26 - 81.62s) -------------------
  {
    t: 31.26, mode: "pip", media: "broll", src: "office", kicker: "ภาพรวมการสร้างเกม",
    headline: "การสร้างเกมแบบเดิม", sub: "ต้องใช้คนหลายฝ่าย ใช้เวลาและทักษะสูง", subT: 34.60,
    stats: [
      { t: 38.30, label: "🎨 คนออกแบบตัวละคร" },
      { t: 43.28, label: "💻 คนเขียนโปรแกรม" },
      { t: 44.80, label: "🔊 คนทำเสียงและเอฟเฟกต์" },
    ],
  },
  {
    t: 50.02, mode: "pip", media: "broll", src: "ai_network", kicker: "การเปลี่ยนแปลง",
    headline: "AI ทำงานแทนเกือบทั้งหมด", sub: "เหมือนมีทีมงาน 4 คน พร้อมทำตามคำสั่ง", subT: 55.24,
    stats: [{ t: 55.24, big: "4 ทีมงาน", label: "พร้อมรับคำสั่งตลอด 24 ชม.", tone: "mint" }],
  },
  {
    t: 58.08, mode: "pip", media: "explain", kicker: "การแบ่งหน้าที่", explain: EXPLAIN_AI_TEAM,
    stats: [{ t: 59.5, big: "Full Studio", label: "ทีมพัฒนาเกมครบวงจร", tone: "amber" }],
  },
  {
    t: 68.14, mode: "pip", media: "explain", kicker: "บทบาทใหม่ของเรา", explain: EXPLAIN_DIRECTOR,
    stats: [{ t: 69.5, big: "Director", label: "เราเป็นผู้กำกับหนัง", tone: "mint" }],
  },
  {
    t: 78.32, mode: "full",
    next: { label: "ต่อไป ▶", items: ["Tripo 3D AI ปั้นโมเดล", "ปั้นมังกร ดาบวิเศษ ในพริบตา"], t: 78.8 },
  },

  // ---- 3. TRIPO 3D MODELING (L27..L40: 81.62 - 129.60s) -----------------
  {
    t: 81.62, mode: "pip", media: "web", file: "sec_hero", kicker: "AI ตัวที่ 1 · โมเดลสามมิติ",
    cam: [{ t: 0, fy: 80, z: 1.25 }, { t: 4, fy: 110, z: 1.30 }],
    hl: [
      { t: 86.59, rect: WEB_RECTS.hero_title, th: "Build End-to-End AI 3D Workflows with Tripo API" },
      { t: 91.31, rect: WEB_RECTS.hero_sub, th: "Power 3D generation, processing, rigging, and animation" },
    ],
    stats: [{ t: 88.48, big: "Tripo 3D", label: "AI สร้างโมเดลสามมิติ", tone: "mint" }],
    gloss: [{ t: 86.59, term: "3D Model", th: "โมเดลสามมิติ" }],
  },
  {
    t: 96.58, mode: "pip", media: "web", file: "sec_text_to_3d", kicker: "การทำงานของ Tripo",
    cam: [{ t: 0, fy: 100, z: 1.25 }, { t: 4, fy: 140, z: 1.30 }],
    hl: [
      { t: 97.26, rect: WEB_RECTS.pipe_title, th: "Any Image. Any Prompt. Instant 3D." },
      { t: 101.48, rect: WEB_RECTS.text_to_3d, th: "พิมพ์ข้อความบอกสิ่งที่ต้องการ AI จะปั้นโมเดล 3D ให้ทันที" },
      { t: 107.42, rect: WEB_RECTS.mesh_seconds, th: "Production-ready mesh in seconds" },
    ],
    stats: [{ t: 104.60, big: "ช่างปั้นส่วนตัว", label: "สั่งปั้นมังกรหรือดาบวิเศษได้ทันที", tone: "mint" }],
  },
  {
    t: 112.74, mode: "pip", media: "web", file: "sec_use_cases", kicker: "Tripo P2.0 เวอร์ชันล่าสุด",
    cam: [{ t: 0, fy: 100, z: 1.25 }, { t: 4, fy: 150, z: 1.30 }],
    hl: [
      { t: 115.88, rect: WEB_RECTS.cases_title, th: "Use Cases Powered by Tripo" },
      { t: 118.21, rect: WEB_RECTS.cases_gaming, th: "Rapidly generate high-quality 3D assets at scale" },
      { t: 125.92, rect: WEB_RECTS.cases_animation, th: "Bring cinematic characters and scenes to life" },
    ],
    stats: [{ t: 118.21, big: "P2.0", label: "ละเอียด สวยงาม เหมาะทำเกมและแอนิเมชัน", tone: "mint" }],
    gloss: [{ t: 118.21, term: "Tripo P2.0", th: "AI ปั้น 3D ยุคใหม่" }],
  },
  {
    t: 127.36, mode: "full",
    next: { label: "ต่อไป ▶", items: ["AI เขียนโค้ดระบบเกม", "ทำให้ตัวละครวิ่ง กระโดด ควบคุมได้"], t: 127.8 },
  },

  // ---- 4. CODING AI (L41..L52: 129.60 - 171.58s) -------------------------
  {
    t: 129.60, mode: "pip", media: "web", file: "sec_agent_cli", kicker: "AI ตัวที่ 2 · เขียนโค้ดเกม",
    cam: [{ t: 0, fy: 90, z: 1.25 }, { t: 4, fy: 130, z: 1.30 }],
    hl: [
      { t: 131.39, rect: WEB_RECTS.agent_title, th: "One prompt to connect your Agent to Tripo" },
      { t: 134.03, rect: WEB_RECTS.agent_copy, th: "Copy the prompt into Codex, Claude Code or Cursor" },
      { t: 147.16, rect: WEB_RECTS.agent_beginner, th: "Beginner-friendly — no coding skills required" },
    ],
    stats: [{ t: 133.02, big: "Coding AI", label: "ผู้ช่วยเขียนโปรแกรมระบบเกม", tone: "mint" }],
  },
  {
    t: 139.60, mode: "pip", media: "broll", src: "coding", kicker: "หน้าที่ของโค้ด",
    headline: "ทำให้ตัวละครขยับได้", sub: "กดปุ่มวิ่ง กระโดด ควบคุมการเล่นเกม", subT: 143.12,
    stats: [{ t: 143.12, label: "🏃 วิ่งได้" }, { t: 143.93, label: "🦘 กระโดดได้" }],
  },
  {
    t: 148.60, mode: "pip", media: "terminal", kicker: "การทำงานจริง", terminal: TERMINAL_DEMO,
    headline: "พิมพ์บอก AI จัดการให้เสร็จ",
  },
  {
    t: 161.28, mode: "pip", media: "chart", kicker: "ลดเวลาสร้างงาน", chart: CHART_PRODUCTION_TIME,
    stats: [{ t: 162.08, big: "1 วัน", label: "จากเดิมต้องใช้เวลาหลายเดือน", tone: "mint" }],
  },
  {
    t: 168.38, mode: "full",
    next: { label: "ต่อไป ▶", items: ["AI ตัวที่ 3 สร้างภาพฉากหลัง", "AI ตัวที่ 4 สร้างเสียงและดนตรี"], t: 168.8 },
  },

  // ---- 5. IMAGE & AUDIO AI (L53..L65: 171.58 - 217.04s) ------------------
  {
    t: 171.58, mode: "pip", media: "broll", src: "studio", kicker: "AI ตัวที่ 3 · สร้างภาพและฉาก",
    headline: "AI สร้างภาพพื้นหลัง", sub: "ป่าไม้ ภูเขา ท้องฟ้า หรือฉากในเมือง", subT: 179.44,
    stats: [{ t: 175.08, big: "Image AI", label: "วาดภาพฉากหลังและสิ่งแวดล้อม", tone: "mint" }],
  },
  {
    t: 184.10, mode: "pip", media: "broll", src: "cyber", kicker: "ภาพที่ไม่ซ้ำใคร",
    headline: "พิมพ์บอกบรรยากาศที่ต้องการ", sub: "ไม่ต้องจ้างนักวาด ได้ภาพที่เป็นของเรา 100%", subT: 189.36,
    stats: [{ t: 194.28, label: "✨ เอกลักษณ์ของเราเอง 100%" }],
  },
  {
    t: 196.50, mode: "pip", media: "broll", src: "abstract", kicker: "AI ตัวที่ 4 · เสียงและดนตรี",
    headline: "เสียงเอฟเฟกต์ & เพลงประกอบ", sub: "เสียงดาบฟัน เสียงระเบิด เพลงประกอบฉากต่อสู้", subT: 204.04,
    stats: [{ t: 200.92, big: "Audio AI", label: "สร้าง Sound Effects และดนตรี", tone: "mint" }],
  },
  {
    t: 210.16, mode: "pip", media: "broll", src: "office", kicker: "พลังของการรวมตัว",
    headline: "ทีมสร้างเกมครบวงจร", sub: "ไม่ต้องจ้างใครเลยสักคนเดียว", subT: 214.48,
    stats: [{ t: 211.54, big: "ครบวงจร", label: "4 AI ประสานงานกันสมบูรณ์แบบ", tone: "mint" }],
  },
  {
    t: 214.48, mode: "full",
    next: { label: "ต่อไป ▶", items: ["เรื่องนี้เกี่ยวอะไรกับเรา?", "ประโยชน์ต่อคนทั่วไปและทุกอาชีพ"], t: 215.0 },
  },

  // ---- 6. RELEVANCE TO EVERYONE (L66..L80: 217.04 - 267.30s) -------------
  {
    t: 217.04, mode: "pip", media: "broll", src: "brain", kicker: "คำถามสำคัญ",
    headline: "ถ้าเราไม่ได้อยากสร้างเกมล่ะ?", sub: "เทคโนโลยีนี้ยังมีประโยชน์กับเราไหม?", subT: 222.42,
    stats: [{ t: 227.00, big: "มีประโยชน์มาก", label: "สร้างอย่างอื่นได้มากมาย", tone: "mint" }],
  },
  {
    t: 228.72, mode: "pip", media: "broll", src: "shopping", kicker: "การประยุกต์ใช้งาน",
    headline: "AI สร้างเกมทั้งเกมได้", sub: "ก็สร้างงานรูปแบบอื่นได้เหมือนกัน", subT: 235.02,
    stats: [{ t: 235.02, label: "🚀 ประยุกต์ได้ไม่จำกัด" }],
  },
  {
    t: 238.22, mode: "pip", media: "explain", kicker: "ใครได้ประโยชน์บ้าง?", explain: EXPLAIN_USE_CASES,
    stats: [{ t: 239.5, big: "ทุกสายงาน", label: "ขายของ · การศึกษา · ออกแบบ · คอนเทนต์", tone: "amber" }],
  },
  {
    t: 259.62, mode: "pip", media: "broll", src: "studio", kicker: "การทำคอนเทนต์",
    headline: "ช่วยทำภาพ วิดีโอ เสียง", sub: "สร้างสรรค์ผลงานลงโซเชียลได้ครบถ้วน", subT: 263.78,
    stats: [{ t: 265.67, label: "📱 ทำคอนเทนต์ลงโซเชียล" }],
  },
  {
    t: 264.80, mode: "full",
    next: { label: "ต่อไป ▶", items: ["ทักษะที่สำคัญที่สุดในยุค AI", "การคิดและการสื่อสาร"], t: 265.2 },
  },

  // ---- 7. SKILLS OF THE FUTURE (L81..L92: 267.30 - 307.54s) --------------
  {
    t: 267.30, mode: "pip", media: "broll", src: "typing", kicker: "สิ่งที่น่าทึ่งที่สุด",
    headline: "AI ลดอุปสรรคลงไปมาก", sub: "ไม่จำเป็นต้องฝึกฝนเทคนิคนานหลายปีเหมือนก่อน", subT: 275.54,
    stats: [{ t: 282.46, big: "ลดอุปสรรค", label: "ไม่จำเป็นต้องเก่งทุกเรื่อง", tone: "mint" }],
  },
  {
    t: 284.17, mode: "pip", media: "explain", kicker: "ทักษะแห่งอนาคต", explain: EXPLAIN_FUTURE_SKILLS,
    stats: [{ t: 290.44, big: "Thinking", label: "ทักษะการคิดและการสื่อสาร", tone: "mint" }],
    gloss: [{ t: 287.44, term: "Prompting", th: "การสื่อสารสั่งงาน AI" }],
  },
  {
    t: 299.96, mode: "pip", media: "broll", src: "gaming", kicker: "โอกาสครั้งใหญ่",
    headline: "คนที่คิดเป็น สื่อสารเป็น", sub: "สร้างงานได้ทุกรูปแบบ นี่คือโอกาสของทุกคน", subT: 304.38,
    stats: [{ t: 305.32, big: "โอกาสเปิดกว้าง", label: "สำหรับทุกคนในยุคนี้", tone: "amber" }],
  },
  {
    t: 304.38, mode: "full",
    next: { label: "ต่อไป ▶", items: ["สรุป 4 ข้อคิดสำคัญ", "มุมไทย: ทดลองใช้ Tripo 3D ฟรี"], t: 304.8 },
  },

  // ---- 8. SUMMARY & MUM THAI (L93..L110: 307.54 - 370.10s) ----------------
  {
    t: 307.54, mode: "pip", media: "typo", typo: "vs", kicker: "สรุปเปรียบเทียบ",
    stats: [{ t: 309.93, big: "สรุป 4 ข้อ", label: "สิ่งที่เราได้เรียนรู้ในวันนี้", tone: "mint" }],
  },
  {
    t: 327.38, mode: "pip", media: "web", file: "sec_formats_pricing", kicker: "การนำไปใช้งานจริง",
    cam: [{ t: 0, fy: 60, z: 1.25 }, { t: 4, fy: 100, z: 1.30 }],
    hl: [
      { t: 329.40, rect: WEB_RECTS.formats_title, th: "Multi-Format Output: GLB, FBX, OBJ, USDZ" },
      { t: 337.26, rect: WEB_RECTS.formats_list, th: "นำไปต่อยอดได้ในทุกเอนจินและโปรแกรม 3D" },
    ],
    stats: [{ t: 332.30, big: "Multi-Format", label: "GLB · FBX · OBJ · USDZ", tone: "mint" }],
  },
  {
    t: 344.28, mode: "pip", media: "explain", kicker: "มุมไทย", explain: EXPLAIN_MUM_THAI,
    stats: [{ t: 351.48, big: "300 Credits", label: "ทดลองสร้างโมเดล 3D ฟรี", tone: "mint" }],
  },
  {
    t: 356.88, mode: "pip", media: "broll", src: "brain", kicker: "เปิดใจเรียนรู้",
    headline: "AI ออกแบบมาให้ใช้ง่าย", sub: "ไม่ต้องกลัวว่าจะยากเกินไป เริ่มต้นได้ทันที", subT: 360.14,
    stats: [{ t: 358.90, label: "💡 ใช้ง่ายสำหรับทุกคน" }],
  },
  {
    t: 361.18, mode: "full",
    next: { label: "ขอบคุณสำหรับการรับชม", items: ["กดไลก์ 👍", "กดแชร์ ↗️", "กด Subscribe 🔔"], pill: "🔔 กดติดตามช่อง", t: 363.90 },
  },
];

// ---- Typo scenes (src times) -----------------------------------------------
export const AGENDA = [
  { t: 14.52, text: "4 AI สร้างเกม", icon: "🎮" },
  { t: 55.24, text: "AI แทนทีมงาน", icon: "👥" },
  { t: 88.48, text: "Tripo 3D ปั้นโมเดล", icon: "🗿" },
  { t: 129.60, text: "AI เขียนโค้ด", icon: "💻" },
  { t: 217.04, text: "โอกาสของทุกคน", icon: "🚀" },
];

export const SUMMARY3 = [
  { t: 88.48, text: "Tripo 3D ปั้นโมเดล", icon: "🗿" },
  { t: 129.60, text: "AI เขียนโค้ดระบบเกม", icon: "💻" },
  { t: 289.72, text: "ทักษะคิดและสื่อสาร", icon: "💡" },
];

export const FINAL4 = [
  { t: 309.93, text: "1. AI ทำงานร่วมเป็นทีม", icon: "👥" },
  { t: 317.61, text: "2. สร้างเกมได้ไม่ต้องรู้โค้ด", icon: "🎮" },
  { t: 327.38, text: "3. มีประโยชน์กับทุกคน", icon: "🌍" },
  { t: 339.38, text: "4. ทักษะคิดและสั่ง AI", icon: "💡" },
];

export const VS = {
  fableT: 307.54,
  mythosT: 314.78,
  subT: 322.14,
  leftLines: [308.28, 311.51, 317.61],
  rightLines: [319.60, 323.86, 325.48],
};

export const CTA_T = 361.18;

// Marquee numbers: the music bed dips right before these (src seconds)
export const MUSIC_DIPS = [14.52, 55.24, 88.48, 129.60, 171.58, 217.04, 289.72, 307.54];

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
