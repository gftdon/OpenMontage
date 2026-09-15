// ===========================================================================
// AiAgencyNewsYT V2 — EPISODE DATA (pure TypeScript, no React)
// Topic: AI News in 10 mins: 10% chance AI kills all humans & $1M AI Agency Playbook
// ===========================================================================
import { WEB_RECTS, type WebRect } from "./aiAgencyWeb";

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
  assetDir: "ai-agency-news",
  brand: "AI NEWS",
  dateLabel: "14 ก.ย. 2026",
  page: { domain: "aiautomationsociety.ai", path: "/opaa-ads-optin" },
  captureLabel: "VERIFIED · จับภาพ 14 ก.ย. 2026",
  officialTag: "AI AGENCY · PLAYBOOK",
  previewTag: "PREVIEW",
  cta: { lead: "ดูเพลย์บุ๊กฉบับเต็มได้ที่", text: "aiautomationsociety.ai" },
  sting: {
    eyebrow: "AI NEWS SPECIAL · 2026",
    titleA: "AI 10% Risk",
    amp: "&",
    titleB: "AI Agency",
    sub: "วิเคราะห์ความเสี่ยง 10% พร้อมโอกาสสร้างรายได้เอเจนซี่",
  },
  endcard: {
    eyebrow: "AI NEWS · 2026",
    titleA: "AI Risk 10%",
    titleB: "& AI Agency",
    sub: "อย่านั่งกลัว แต่จงเรียนรู้เพื่อคว้าโอกาส",
    cta: "ติดตามข่าวสาร AI ย่อยง่ายทุกสัปดาห์",
    next: "กด Subscribe 🔔 เพื่อไม่พลาดเทรนด์ AI ล่าสุด",
  },
  agendaLabel: "ในคลิปนี้",
  summary3Label: "สรุปใจความสำคัญ",
  final4: { title: "ก้าวสู่ยุค AI อย่างมั่นใจ", sub: "เปลี่ยนความกลัวเป็นความรู้และโอกาสสร้างรายได้" },
  vs: {
    eyebrow: "เปรียบเทียบแนวคิด · AI ยุคใหม่",
    left: { title: "AI ในอดีต", badge: "BASIC TOOL", lines: ["แค่ตอบคำถามง่าย ๆ", "ช่วยพิมพ์ข้อความสั้น", "ต้องสั่งงานทีละอย่าง"] },
    right: { title: "AI ปัจจุบัน", badge: "AI AGENT", lines: ["เขียนโค้ด วาดรูป แต่งเพลง", "ทำงานอัตโนมัติตลอด 24 ชม.", "สร้างโมเดลธุรกิจ AI Agency"] },
    conclusion: "💡 AI เป็นเครื่องมือ เหมือนมีด — เรียนรู้วิธีใช้เพื่อสร้างคุณค่า",
  },
  thumbs: [
    { id: "A", lines: ["AI เสี่ยง 10% ?", "จริงหรือแค่ขู่!"], accent: "วิเคราะห์ข่าว AI", accentTone: "mint" as Tone },
    { id: "B", lines: ["ไม่ต้องเขียนโค้ด", "ทำ AI Agency ได้"], accent: "โอกาสธุรกิจ $1M", accentTone: "amber" as Tone },
    { id: "C", lines: ["4 สเต็ปเตรียมตัว", "ก่อนโดน AI แย่งงาน"], accent: "สรุปครบในคลิปเดียว", accentTone: "clay" as Tone },
  ],
};

// ---- Timeline (pre-lap teaser from the presenter's own lines) -------------
export const TIMELINE = {
  teaser: [
    { src: 12.04, end: 15.31 }, // "มีผู้เชี่ยวชาญด้าน AI หลายคนออกมาพูดว่า ตอนนี้ AI มีโอกาสประมาณ 10% ที่จะเป็นอันตรายต่อมนุษย์ทั้งหมด"
    { src: 78.57, end: 80.89 }, // "ตอนนี้มีคนจำนวนมากที่ใช้ AI สร้างรายได้ โดยเฉพาะสิ่งที่เรียกว่า AI Agency หรือเอเจนซี่ AI"
    { src: 95.56, end: 96.99 }, // "ธุรกิจแบบนี้ไม่จำเป็นต้องเขียนโค้ดเป็นก็ทำได้ค่ะ"
  ],
  stingDur: 2.6,
  mainSrcStart: 1.19, // skip "สวัสดีค่ะ"
  mainSrcEnd: 182.50, // last word end + 0.2
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
  { src: 1.19, title: "บทนำข่าว AI วันนี้" },
  { src: 8.80, title: "ความเสี่ยง AI 10%" },
  { src: 28.36, title: "AI ฉลาดขึ้นเร็วมาก" },
  { src: 43.32, title: "เกี่ยวอะไรกับชีวิตเรา" },
  { src: 74.19, title: "โอกาสธุรกิจ AI Agency" },
  { src: 100.58, title: "2 เครื่องมือ AI สำคัญ" },
  { src: 122.82, title: "4 วิธีเตรียมตัวรับมือ" },
  { src: 156.60, title: "สรุปและก้าวต่อไป" },
];

// ---- B-roll durations ------------------------------------------------------
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

// ---- Terminal demo (a real business automation session) --------------------
export const TERMINAL_DEMO: Terminal = {
  title: "n8n workflow --run ai-business-automations",
  tag: "DEMO · 24/7 AI Automation",
  lines: [
    { t: 0.0, kind: "cmd", text: "trigger: webhook.listen('new_customer_inquiry')" },
    { t: 0.8, kind: "dim", text: "→ Incoming lead from online store..." },
    { t: 1.4, kind: "claude", text: "AI Agent: parsing customer intent & checking inventory" },
    { t: 2.2, kind: "out", text: "✓ Auto-reply email drafted & sent in 0.8s" },
    { t: 2.9, kind: "out", text: "✓ Stock updated in database & receipt generated" },
    { t: 3.6, kind: "out", text: "✓ Delivery alert dispatched to logistics team" },
    { t: 4.3, kind: "dim", text: "Human intervention required: 0 min | Uptime: 24/7/365" },
    { t: 5.0, kind: "ok", text: "Automation complete — working 24 hours without vacation" },
  ],
};

// ---- Charts & Explains -----------------------------------------------------
export const CHART_OPPORTUNITY: Chart = {
  title: "อัตราความเร็วในการทำงานด้วย AI",
  sub: "ประหยัดเวลาและเพิ่มผลผลิตก้าวกระโดด (เท่า เทียบกับทำมือ)",
  unit: "x เท่า",
  max: 10,
  bars: [
    { label: "ตอบอีเมล & บริการลูกค้า", value: 8.0, tone: "mint", note: "อัตโนมัติ 24/7" },
    { label: "ตรวจเช็กสต็อก & ออกบิล", value: 6.5, tone: "mint", note: "ลดข้อผิดพลาด" },
    { label: "สรุปรายงาน & ประชุม", value: 5.0, tone: "amber", note: "ประหยัด 80% เวลา" },
    { label: "ช่วยเขียนโค้ด & วิเคราะห์", value: 4.0, tone: "clay", note: "เร็วขึ้น 4 เท่า" },
  ],
};

export const EXPLAIN_RISK: Explain = {
  title: "ประเมินความเสี่ยง AI 10% vs การเตรียมตัว",
  sub: "มองความเป็นจริงอย่างมีเหตุผล ไม่ตื่นตระหนก",
  layout: "compare",
  left: { title: "ความเสี่ยงระยะยาว", icon: "⚠️", tone: "clay" },
  right: { title: "การเตรียมพร้อม", icon: "🛡️", tone: "mint" },
  items: [
    { t: 18.28, icon: "📉", text: "ตัวเลข 10% เป็นการประเมินระยะยาว ไม่ใช่จะเกิดพรุ่งนี้", tone: "amber" },
    { t: 21.03, icon: "🚗", text: "เหมือนสถิติการขับรถที่มีความเสี่ยง แต่เรามีเข็มขัดนิรภัย", tone: "mint" },
    { t: 25.03, icon: "⚙️", text: "บอกให้เราระวัง วางกฎเกณฑ์ และควบคุมระบบให้รัดกุม", tone: "mint" },
  ],
  footnote: "ที่มา: บทวิเคราะห์ความปลอดภัย AI และ Dario Amodei (Anthropic)",
};

export const EXPLAIN_EVOLUTION: Explain = {
  title: "วิวัฒนาการก้าวกระโดดของ AI",
  sub: "จากแชทบอทตอบคำถาม สู่เอเจนต์ลงมือทำงานจริง",
  layout: "flow",
  items: [
    { t: 32.97, icon: "💬", text: "2-3 ปีก่อน: ตอบคำถามข้อความง่าย ๆ", tone: "clay" },
    { t: 34.19, icon: "🎨", text: "ปัจจุบัน: เขียนโค้ด วาดรูป แต่งเพลง ออกแบบ", tone: "amber" },
    { t: 35.59, icon: "🧠", text: "ก้าวถัดไป: วิเคราะห์ข้อมูลซับซ้อน + ตัดสินใจแทนมนุษย์", tone: "mint" },
  ],
  footnote: "พัฒนาการที่รวดเร็วทำให้ผู้เชี่ยวชาญต้องทบทวนการควบคุม",
};

export const EXPLAIN_HEALTH_BIZ: Explain = {
  title: "ประโยชน์ของ AI ในชีวิตจริง",
  sub: "AI ไม่ได้มีแค่ด้านน่ากลัว แต่ช่วยสร้างคุณค่ามหาศาล",
  layout: "list",
  items: [
    { t: 62.21, icon: "🩺", text: "การแพทย์: ช่วยแพทย์วินิจฉัยโรคได้แม่นยำและรวดเร็วขึ้น", tone: "mint" },
    { t: 64.00, icon: "🌾", text: "เกษตรกรรม: ช่วยเกษตรกรดูแลพืชผลและคาดการณ์ผลผลิต", tone: "amber" },
    { t: 65.50, icon: "📚", text: "การศึกษา: ช่วยครูออกแบบบทเรียนให้เหมาะกับเด็กแต่ละคน", tone: "mint" },
    { t: 67.20, icon: "💼", text: "ธุรกิจขนาดย่อม: ทำงานเสร็จเร็วขึ้นโดยไม่ต้องเพิ่มคน", tone: "amber" },
  ],
  footnote: "แทนที่จะกลัว เราควรเรียนรู้วิธีใช้ให้เกิดประโยชน์สูงสุด",
};

export const EXPLAIN_AGENCY_ROLE: Explain = {
  title: "AI Agency คืออะไร?",
  sub: "ธุรกิจรับติดตั้งและตั้งค่าระบบ AI ให้องค์กร",
  layout: "compare",
  left: { title: "ช่างไฟฟ้า", icon: "⚡", tone: "amber" },
  right: { title: "AI Agency", icon: "🤖", tone: "mint" },
  items: [
    { t: 83.88, icon: "🏠", text: "ช่างไฟฟ้า: ติดตั้งระบบไฟในบ้าน ลูกค้าไม่ต้องต่อสายไฟเอง", tone: "amber" },
    { t: 85.51, icon: "🏢", text: "AI Agency: ติดตั้งระบบ AI ให้ธุรกิจ ลูกค้าใช้งานได้ทันที", tone: "mint" },
    { t: 95.37, icon: "✨", text: "ไม่ต้องเขียนโค้ด! มีเครื่องมือสำเร็จรูป แค่ลากวางก็ใช้งานได้", tone: "mint" },
  ],
  footnote: "บริการยอดนิยม: แชทบอทตอบลูกค้า · ระบบนัดหมาย · สรุปรายงาน",
};

export const EXPLAIN_PREPARE_4: Explain = {
  title: "4 ขั้นตอนเตรียมตัวรับมือยุค AI",
  sub: "วิธีปรับตัวสำหรับทุกคน ไม่จำเป็นต้องเป็นคนสาย IT",
  layout: "flow",
  items: [
    { t: 131.08, icon: "1️⃣", text: "เริ่มเรียนรู้: รู้ว่า AI ทำอะไรได้ เหมือนตอนหัดใช้สมาร์ทโฟน", tone: "amber" },
    { t: 136.39, icon: "2️⃣", text: "ลองใช้จริง: ใช้ ChatGPT ช่วยเขียนอีเมล สรุปบทความ คิดไอเดีย", tone: "mint" },
    { t: 142.54, icon: "3️⃣", text: "ติดตามข่าว: อัปเดตสม่ำเสมอ เทคโนโลยีเปลี่ยนแปลงเร็วมาก", tone: "amber" },
    { t: 148.27, icon: "4️⃣", text: "อย่ากลัว: AI เหมือนมีด ใช้ถูกวิธีทำอาหาร ใช้ผิดบาดมือ", tone: "mint" },
  ],
  footnote: "คนที่เรียนรู้เร็ว จะเป็นผู้ได้เปรียบในโลกยุคใหม่",
};

// ---- BEATS -----------------------------------------------------------------
export const BEATS: Beat[] = [
  // ===== TEASER (pre-lap at timeline seconds) ==============================
  {
    t: 0, abs: true, mode: "pip", media: "broll", src: "gen_glitch", hook: true,
    kicker: "AI EXTINCTION RISK", headline: "โอกาส 10% อันตรายต่อมนุษย์",
    sub: "ผู้เชี่ยวชาญเตือนความเสี่ยง AI ยุคใหม่", subT: 0.8,
    stats: [{ t: 0.4, big: "10%", label: "โอกาสความเสี่ยงของ AI", tone: "clay" }],
  },
  {
    t: SEG.teaser[1].dst, abs: true, mode: "pip", media: "broll", src: "handshake", hook: true,
    kicker: "NEW OPPORTUNITY", headline: "โอกาสธุรกิจ AI Agency",
    sub: "สร้างรายได้ยุคใหม่ด้วยระบบ AI", subT: SEG.teaser[1].dst + 0.6,
    stats: [{ t: SEG.teaser[1].dst + 0.3, big: "AI Agency", label: "โมเดลธุรกิจมาแรง", tone: "mint" }],
  },
  {
    t: SEG.teaser[2].dst, abs: true, mode: "pip", media: "broll", src: "coding", hook: true,
    kicker: "NO CODE NEEDED", headline: "ไม่ต้องเขียนโค้ดเป็นก็ทำได้",
    sub: "ใช้เครื่องมือง่าย ลากวางได้ทันที", subT: SEG.teaser[2].dst + 0.4,
    stats: [{ t: SEG.teaser[2].dst + 0.2, big: "No-Code", label: "เริ่มต้นได้ทุกคน", tone: "mint" }],
  },

  // STING at timeline sec
  { t: SEG.stingStart, abs: true, mode: "full", typo: "sting" },

  // ===== MAIN EPISODE (src times in avatar_source.mp4) =====================
  // ---- 1. OPEN & AGENDA (1.19 - 8.80s) ------------------------------------
  {
    t: 1.19, mode: "full", typo: "agenda",
    lower: { title: "ข่าว AI ย่อยง่าย", sub: "10% Risk & โอกาสธุรกิจ AI Agency", dur: 5.0 },
  },

  // ---- 2. PART 1: 10% RISK & RAPID PROGRESS (8.80 - 43.32s) ---------------
  {
    t: 8.80, mode: "pip", media: "web", file: "sec_dario", kicker: "ประเด็นความปลอดภัย AI",
    cam: [{ t: 0, fy: 30, z: 1.22 }, { t: 4, fy: 60, z: 1.26 }],
    hl: [
      { t: 11.05, rect: WEB_RECTS.dario_title, th: "Dario Amodei (CEO Anthropic) บทความ We Must Pace the Frontier" },
    ],
    stats: [{ t: 13.41, big: "10%", label: "โอกาสความเสี่ยงต่อมนุษย์", tone: "clay" }],
  },
  {
    t: 18.28, mode: "pip", media: "explain", kicker: "การประเมินระยะยาว", explain: EXPLAIN_RISK,
    stats: [{ t: 19.88, big: "Long-term", label: "การประเมินความเสี่ยงระยะยาว", tone: "amber" }],
  },
  {
    t: 28.36, mode: "pip", media: "broll", src: "ai_network", kicker: "พัฒนาการก้าวกระโดด",
    headline: "AI ฉลาดขึ้นเร็วมาก", sub: "เร็วกว่าที่หลายคนคาดการณ์ไว้", subT: 30.10,
    stats: [{ t: 28.5, label: "⚡ พัฒนาการเร็วกว่าที่คาดไว้" }],
  },
  {
    t: 32.97, mode: "pip", media: "explain", kicker: "ความสามารถ AI ปัจจุบัน", explain: EXPLAIN_EVOLUTION,
    stats: [{ t: 34.2, label: "💻 เขียนโค้ด · วาดรูป · แต่งเพลง" }],
  },
  {
    t: 37.04, mode: "pip", media: "broll", src: "server_lights", kicker: "ความท้าทายยุคใหม่",
    headline: "ความเร็วในการพัฒนา", sub: "เราจะควบคุมมันได้จริงไหมในอนาคต", subT: 40.92,
    stats: [{ t: 40.9, big: "Control?", label: "โจทย์ใหญ่เรื่องการควบคุม", tone: "clay" }],
  },

  // ---- 3. PART 2: RELATION TO OUR LIVES (43.32 - 74.19s) -------------------
  {
    t: 43.32, mode: "full",
    next: { label: "หัวข้อถัดไป ▶", items: ["AI ในชีวิตประจำวัน", "ประโยชน์ 4 สายอาชีพ", "โอกาสธุรกิจ AI Agency"], tease: "AI Agency สร้างรายได้", t: 44.5 },
  },
  {
    t: 49.82, mode: "pip", media: "broll", src: "chat_ai", kicker: "AI รอบตัวเรา",
    headline: "AI ในชีวิตประจำวัน", sub: "ค้นหาข้อมูล · แชทบอท · แอปธนาคาร", subT: 55.40,
    stats: [
      { t: 52.0, label: "📱 มือถือค้นหาข้อมูล" },
      { t: 54.0, label: "💬 แชทบอทบริการลูกค้า" },
      { t: 56.0, label: "💳 ระบบวิเคราะห์การใช้จ่าย" },
    ],
  },
  {
    t: 58.76, mode: "pip", media: "broll", src: "office", kicker: "มุมมองเชิงบวก",
    headline: "ประโยชน์มหาศาล", sub: "ยกระดับคุณภาพชีวิตและประสิทธิภาพการทำงาน", subT: 60.5,
  },
  {
    t: 62.21, mode: "pip", media: "explain", kicker: "ผลกระทบเชิงบวก", explain: EXPLAIN_HEALTH_BIZ,
    stats: [{ t: 62.5, label: "🩺 หมอ · 🌾 เกษตรกร · 📚 ครู · 💼 ธุรกิจ" }],
  },
  {
    t: 69.74, mode: "full",
    next: { label: "ข้อคิดสำคัญ", items: ["อย่ากลัวจนไม่กล้าทำอะไร", "เปลี่ยนความกลัวเป็นโอกาส", "เริ่มเรียนรู้เพื่อสร้างรายได้"], t: 70.5 },
  },

  // ---- 4. PART 3: AI AGENCY BUSINESS (74.19 - 100.58s) --------------------
  {
    t: 74.19, mode: "pip", media: "broll", src: "trading", kicker: "โอกาสทางธุรกิจ",
    headline: "สร้างรายได้ด้วย AI", sub: "โอกาสใหม่สำหรับคนที่เริ่มเรียนรู้ก่อน", subT: 76.5,
    stats: [{ t: 77.0, big: "AI Agency", label: "ธุรกิจเอเจนซี่ AI ยุคใหม่", tone: "mint" }],
  },
  {
    t: 79.72, mode: "pip", media: "web", file: "sec_hero", kicker: "โมเดลธุรกิจ AI Agency",
    cam: [{ t: 0, fy: 60, z: 1.25 }, { t: 4, fy: 90, z: 1.30 }],
    hl: [
      { t: 80.0, rect: WEB_RECTS.hero_title, th: "เพลย์บุ๊กสร้าง AI Agency สู่รายได้กว่า $1,000,000 ต่อปี" },
    ],
    stats: [{ t: 80.5, big: "$1M+", label: "ศักยภาพธุรกิจ AI Agency", tone: "mint" }],
  },
  {
    t: 83.88, mode: "pip", media: "explain", kicker: "บทบาทของ AI Agency", explain: EXPLAIN_AGENCY_ROLE,
  },
  {
    t: 87.28, mode: "pip", media: "web", file: "sec_modules", kicker: "บริการยอดนิยม",
    cam: [{ t: 0, fy: 80, z: 1.26 }, { t: 4, fy: 110, z: 1.30 }],
    hl: [
      { t: 88.0, rect: WEB_RECTS.mod_opp, th: "โอกาสในตลาด: ธุรกิจต้องการระบบอัตโนมัติ" },
    ],
    stats: [
      { t: 88.5, label: "🛍️ แชทบอทตอบลูกค้า" },
      { t: 90.0, label: "🏥 คลินิกระบบนัดหมาย" },
      { t: 92.0, label: "📊 ระบบสรุปรายงานเร็วขึ้น" },
    ],
  },
  {
    t: 95.37, mode: "pip", media: "broll", src: "coding", kicker: "ความง่ายในการเริ่มต้น",
    headline: "ไม่ต้องเขียนโค้ดเป็น!", sub: "เครื่องมือสำเร็จรูป ลากวาง กดคลิกไม่กี่ที", subT: 97.5,
    stats: [{ t: 95.8, big: "No-Code", label: "สร้างระบบได้ด้วยการลากวาง", tone: "mint" }],
  },

  // ---- 5. PART 4: AI TOOLS (100.58 - 122.82s) -----------------------------
  {
    t: 100.58, mode: "full",
    next: { label: "2 เครื่องมือเด็ด ▶", items: ["แปลงเสียงเป็นข้อความ", "ระบบทำงานอัตโนมัติ 24 ชม."], tease: "เหมือนมีพนักงาน 24 ชม.", t: 101.5 },
  },
  {
    t: 104.07, mode: "pip", media: "broll", src: "typing", kicker: "เครื่องมือที่ 1",
    headline: "แปลงเสียงเป็นข้อความ", sub: "แค่พูดออกไป AI จะพิมพ์ให้ทันที ไม่ต้องนั่งพิมพ์", subT: 106.0,
    stats: [{ t: 105.0, label: "🎙️ Voice-to-Text ประหยัดเวลาพิมพ์" }],
  },
  {
    t: 110.21, mode: "pip", media: "terminal", kicker: "เครื่องมือที่ 2", terminal: TERMINAL_DEMO,
    headline: "ระบบทำงานอัตโนมัติ",
  },
  {
    t: 117.50, mode: "pip", media: "broll", src: "warehouse", kicker: "พนักงาน 24 ชั่วโมง",
    headline: "ทำงานให้เราตลอด 24 ชม.", sub: "ไม่ต้องนอน ไม่ต้องพัก ไม่ต้องลาหยุด", subT: 119.5,
    stats: [{ t: 118.0, big: "24/7", label: "ไม่มีวันหยุด ทำงานแม่นยำ", tone: "mint" }],
  },

  // ---- 6. PART 5: HOW TO PREPARE (122.82 - 156.60s) ------------------------
  {
    t: 122.82, mode: "full",
    next: { label: "4 วิธีเตรียมตัว ▶", items: ["1. เริ่มเรียนรู้ AI", "2. ลองใช้ในชีวิตประจำวัน", "3. ติดตามข่าว AI", "4. อย่ากลัว AI"], tease: "AI เหมือน 'มีด'", t: 124.0 },
  },
  {
    t: 125.64, mode: "pip", media: "explain", kicker: "กลยุทธ์การปรับตัว", explain: EXPLAIN_PREPARE_4,
  },
  {
    t: 136.39, mode: "pip", media: "broll", src: "chat_ai", kicker: "การใช้งานจริง",
    headline: "ลองใช้ ChatGPT ในงานประจำ", sub: "ช่วยเขียนอีเมล · ช่วยสรุปบทความ · ช่วยคิดไอเดีย", subT: 139.64,
    stats: [{ t: 137.5, label: "💡 ลองใช้ AI ในชีวิตประจำวัน" }],
  },
  {
    t: 142.54, mode: "pip", media: "broll", src: "datacenter", kicker: "อัปเดตสม่ำเสมอ",
    headline: "ติดตามข่าว AI อยู่เสมอ", sub: "สิ่งที่เป็นเรื่องใหม่วันนี้ จะเป็นเรื่องธรรมดาในวันหน้า", subT: 146.03,
    stats: [{ t: 143.0, label: "📰 เทคโนโลยีพัฒนาเร็วมาก" }],
  },
  {
    t: 148.27, mode: "pip", media: "broll", src: "cyber", kicker: "มุมมองที่ถูกต้อง",
    headline: "AI เป็นเครื่องมือ เหมือน 'มีด'", sub: "ใช้ถูกวิธีช่วยทำอาหารอร่อย ใช้ผิดอาจบาดมือ", subT: 151.18,
    stats: [{ t: 149.0, big: "เครื่องมือ", label: "อยู่ที่คนนำไปใช้", tone: "mint" }],
  },

  // ---- 7. PART 6: SUMMARY & CLOSING (156.60 - 182.50s) ---------------------
  {
    t: 156.60, mode: "pip", media: "chart", kicker: "สรุปภาพรวม", chart: CHART_OPPORTUNITY,
  },
  {
    t: 168.12, mode: "full", typo: "final4",
    lower: { title: "บทสรุปสำหรับทุกคน", sub: "คนที่เรียนรู้ AI เร็ว จะได้เปรียบในโลกยุคใหม่", dur: 6.0 },
  },
  {
    t: 174.97, mode: "full",
    next: { pill: "🔔 กดติดตามช่องเพื่อรับข่าว AI ทุกสัปดาห์", items: ["ขอบคุณที่รับชมนะคะ"], t: 176.0 },
  },

  // ---- 8. ENDCARD (182.50s+) ----------------------------------------------
  { t: SEG.voEnd, abs: true, mode: "full", typo: "final4" },
];

// ---- Overlays / Typo timings (src seconds) ---------------------------------
export const AGENDA = [
  { t: 1.5, text: "ความเสี่ยง AI 10%", icon: "⚠️" },
  { t: 3.5, text: "ใกล้ตัวเราแค่ไหน", icon: "📱" },
  { t: 4.8, text: "โอกาสธุรกิจ AI Agency", icon: "💼" },
  { t: 6.0, text: "2 เครื่องมือเด็ด", icon: "🛠️" },
  { t: 7.2, text: "4 วิธีเตรียมตัว", icon: "🚀" },
];

export const SUMMARY3 = [
  { t: 13.4, text: "ประเมินความเสี่ยง AI 10%", icon: "⚠️" },
  { t: 77.0, text: "โอกาสธุรกิจ AI Agency", icon: "💼" },
  { t: 131.0, text: "เริ่มเรียนรู้เร็ว = ได้เปรียบ", icon: "🚀" },
];

export const FINAL4 = [
  { t: 168.5, text: "AI พัฒนาเร็วมาก ทั้งน่าตื่นเต้นและต้องระวัง", icon: "⚡" },
  { t: 170.5, text: "เปิดโอกาสใหม่มหาศาล ทั้งงานและธุรกิจ", icon: "💼" },
  { t: 172.5, text: "อย่านั่งกลัว ลุกขึ้นมาเรียนรู้และเริ่มใช้", icon: "🚀" },
  { t: 174.5, text: "คนที่เรียนรู้เร็ว คือคนที่ได้เปรียบในยุคใหม่", icon: "🏆" },
];

export const VS = {
  fableT: 32.97,
  mythosT: 79.72,
  subT: 168.12,
  leftLines: [34.2, 35.6, 37.0],
  rightLines: [83.9, 87.3, 95.4],
};

export const CTA_T = 175.0;

// Marquee numbers: the music bed dips right before these (src seconds)
export const MUSIC_DIPS = [13.4, 28.3, 79.7, 95.3, 110.2, 148.2, 168.1];

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
