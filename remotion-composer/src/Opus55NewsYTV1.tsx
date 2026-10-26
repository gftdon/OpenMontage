import React, { useEffect, useState } from "react";
import {
  OffthreadVideo,
  Img,
  Loop,
  Sequence,
  interpolate,
  spring,
  staticFile,
  continueRender,
  delayRender,
  useCurrentFrame,
  useVideoConfig,
  CalculateMetadataFunction,
} from "remotion";
import { CAPTION_PAGES } from "./opus55NewsCaptions";
import { WEB_CLIPS, WEB_RECTS, WebRect } from "./opus55NewsWeb";

// ===========================================================================
// Opus55NewsYTV1 — 16:9 AI-news report (1920x1080@25)
// Format "Youtube-YT-News-Style01-V1": the report subject is a YOUTUBE VIDEO
// (Anthropic — "Introducing Claude Opus 5.5"), not a web page.
// The left stage carries clips cut from the source video (museum cards +
// full-bleed footage) picked to match what the presenter says, stock b-roll
// with kinetic Thai headlines, and typography scenes — while one continuous
// avatar morphs between FULL-FRAME and a 9:16 anchor card on the right.
// Timing spine = whisper word timing (opus55NewsCaptions.ts), never the SRT.
// ===========================================================================

// ---- Design tokens --------------------------------------------------------
const NAVY = "#0B0E17";
const NAVY_2 = "#141A2B";
const CREAM = "#F5F1E8";
const CREAM_DIM = "rgba(245,241,232,0.62)";
const INK = "#1A1714";
const AMBER = "#F2B34C";
const AMBER_DEEP = "#D98E1F";
const CLAY = "#D97757";
const MINT = "#8FD6B4";
const GOLD = "#F59E0B"; // karaoke locked style
const GOLD_LIGHT = "#FDE68A";
const FONT = '"KanitX", "Kanit", system-ui, -apple-system, sans-serif';
const MONO = '"SF Mono", "JetBrains Mono", Menlo, monospace';

// ---- Timing ---------------------------------------------------------------
const VO_END_SEC = 299.0; // last whisper word end (298.68) + 0.3
const TOTAL_DURATION_SEC = 303.4; // + 4.4 s endcard
const MODE_BLEND_SEC = 0.55;

// ---- Episode config (swap per episode — every on-screen string lives here) --
const EPISODE = {
  assetDir: "opus55-news", // public/<assetDir>/{avatar_source.mp4, broll/, web/}
  brand: "AI TECH NEWS",
  dateLabel: "23 ก.ย. 2026",
  page: { domain: "youtube.com", path: "/watch?v=1f13Bl1sYkw" }, // browser chrome URL pill
  officialTag: "SOURCE · ANTHROPIC", // tag on `clip` beats
  cta: { lead: "อ่านรายละเอียดและทดลองใช้งานได้ที่", text: "anthropic.com/claude-opus-5-5" },
  endcard: {
    eyebrow: "AI TECH NEWS · SEPTEMBER 2026",
    titleA: "CLAUDE OPUS 5.5",
    titleB: "ฉลาดเท่าตัวท็อป · เร็วขึ้น · คุ้มค่า",
    sub: "ต้นฉบับ: Anthropic — Introducing Claude Opus 5.5",
    cta: "ข้อมูลเพิ่มเติม · anthropic.com",
  },
  summary3Label: "3 เสาหลัก Claude Opus 5.5",
  final4: { title: "สรุปประเด็นสำคัญ 4 ข้อ", sub: "Claude Opus 5.5 · ก้าวสำคัญของ AI ประสิทธิภาพสูงเพื่อทุกคน" },
  vs: {
    eyebrow: "เปรียบเทียบจุดเด่นสองค่ายยักษ์ใหญ่",
    left: {
      title: "ChatGPT (OpenAI)",
      badge: "GENERAL AI",
      lines: ["ฟีเจอร์หลากหลาย ครอบคลุมรอบด้าน", "เหมาะกับการสนทนาทั่วไป", "ฐานผู้ใช้งานกว้างขวางทั่วโลก"],
    },
    right: {
      title: "Claude Opus 5.5",
      badge: "DEEP WORK",
      lines: ["เขียนกระชับ ตรงประเด็น ไม่อ้อมค้อม", "เอาใจความสำคัญขึ้นก่อน (BLUF)", "ทำงานต่อเนื่องได้ดีแม้ใช้ทั้งวัน"],
    },
    conclusion: "💡 เลือกใช้ตามลักษณะงาน ไม่จำเป็นต้องเลือกแค่ตัวเดียว",
  },
};

// ---- Geometry -------------------------------------------------------------
const W = 1920;
const H = 1080;
const STAGE = { x: 80, y: 100, w: 1210, h: 840, r: 22 };
const CHROME_H = 46;
const VW = STAGE.w;
const VH = STAGE.h - CHROME_H;
const AV = { x: 1362, y: 96, w: 478, h: 850, r: 26 };
// presenter centre in the 1920x1080 source
const AV_CX = 960;
const AV_CY = 540;
const S0 = VW / 1100; // capture CSS px -> stage px at zoom 1

// ---- B-roll durations (public/<assetDir>/broll, 1080p25; yt_* = clips cut from the YouTube source) ----
const BROLL_DUR: Record<string, number> = {
  abstract: 30.0,
  ai_network: 30.0,
  brain: 10.0,
  chat_ai: 19.48,
  city_night: 22.36,
  coding: 14.96,
  cyber: 30.0,
  datacenter: 9.12,
  handshake: 11.48,
  office: 14.8,
  server_lights: 23.52,
  shopping: 10.0,
  trading: 8.0,
  typing: 12.16,
  warehouse: 20.44,
  // YouTube source clips
  yt_claude_logo: 4.0,
  yt_discover: 5.0,
  yt_elements: 8.0,
  yt_full_spot: 20.0,
  yt_horizon: 5.0,
  yt_opus_reveal: 5.0,
  yt_web_benchmarks: 20.0,
  yt_web_comm: 20.0,
  yt_web_hero: 20.0,
  yt_web_pricing: 20.0,
};

// ---- Beat model -----------------------------------------------------------
interface CamKey { t: number; fy: number; z: number; fx?: number }
interface Highlight { t: number; key?: string; rect?: WebRect; pad?: number }
interface Stat { t: number; big?: string; label: string; tone?: "amber" | "mint" | "clay" }

interface Beat {
  t: number;
  mode: "full" | "pip";
  media?: "web" | "broll" | "clip" | "typo" | "none";
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
  // typo
  typo?: "summary3" | "vs" | "final4";
  // overlays
  stats?: Stat[];
  lower?: { title: string; sub: string; t?: number; dur?: number };
}

const tone = (t?: "amber" | "mint" | "clay") => {
  if (t === "mint") return MINT;
  if (t === "clay") return CLAY;
  return AMBER;
};

// ---- Beat sheet: 299s VO mapped line-by-line to whisper --------------------
const BEATS: Beat[] = [
  // =========================================================================
  // Part 1: Cold Open & Hook (0.00 - 37.20)
  // =========================================================================
  // L1-L4: Cold Open (full frame with breaking lower third)
  {
    t: 0.0,
    mode: "full",
    lower: {
      title: "Anthropic เปิดตัว Claude Opus 5.5",
      sub: "ฉลาดเท่าตัวท็อป Fable 5.1 · เร็วกว่าเดิม · ประหยัดต้นทุน 40%",
      t: 1.2,
      dur: 8.0,
    },
  },
  // L5-L8 (11.82 - 30.04): Morph to PiP -> AI คืออะไร
  {
    t: 11.82,
    mode: "pip",
    media: "broll",
    src: "ai_network",
    kicker: "หลายคนอาจสงสัย: AI คืออะไร?",
    headline: "AI = โปรแกรมคอมพิวเตอร์ที่ฉลาด",
    sub: "คิด วิเคราะห์ เขียน และตอบคำถามแทนเราได้",
    subT: 16.04,
    stats: [
      { t: 17.9, label: "🤖 ผู้ช่วยส่วนตัวอัจฉริยะ" },
      { t: 21.1, label: "💡 คิด · วิเคราะห์ · เขียน" },
      { t: 26.0, label: "📱 ในมือถือและคอมพิวเตอร์" },
    ],
  },
  // L9-L11 (30.04 - 37.20): Open Loop - สรุป 3 เสาหลักที่กำลังจะเจาะลึก
  {
    t: 30.04,
    mode: "pip",
    media: "typo",
    typo: "summary3",
    src: "abstract",
    kicker: "Claude Opus 5.5 พิเศษยังไง · 3 เสาหลัก",
  },
  // Brief full-frame turn before diving into Part 2
  { t: 37.20, mode: "full" },

  // =========================================================================
  // Part 2: เรื่องที่ 1 · ความฉลาด (39.00 - 81.00)
  // =========================================================================
  // L12-L14 (39.00 - 50.28): ความฉลาดเทียบเท่า Fable 5.1 -> clip official web benchmarks
  {
    t: 39.00,
    mode: "pip",
    media: "clip",
    src: "yt_web_benchmarks",
    clipFit: "contain",
    idx: "01",
    kicker: "เรื่องที่ 1 · ความฉลาดระดับแนวหน้า",
    headline: "ฉลาดเทียบเท่า Claude Fable 5.1",
    sub: "โมเดลที่ฉลาดที่สุดของ Anthropic ในปัจจุบัน",
    subT: 45.44,
  },
  // L15-L18 (50.28 - 63.40): พนักงานที่เก่งที่สุด -> office broll
  {
    t: 50.28,
    mode: "pip",
    media: "broll",
    src: "office",
    kicker: "เปรียบเทียบในที่ทำงาน",
    headline: "เหมือนมีพนักงานหัวกะทิ 2 คน",
    sub: "ทำงานเก่งเท่ากัน แต่คนใหม่เร็วกว่าและสื่อสารชัดเจนกว่า",
    subT: 57.55,
    stats: [
      { t: 54.04, big: "2 เท่า", label: "พนักงานหัวกะทิในทีม", tone: "mint" },
      { t: 58.3, label: "⚡ ทำงานเร็วกว่า" },
      { t: 59.6, label: "🎯 สื่อสารชัดเจนกว่า" },
    ],
  },
  // L19-L23 (63.40 - 81.00): สไตล์การสื่อสาร ชัดเจน เอาประเด็นขึ้นก่อน -> web comm clip
  {
    t: 63.40,
    mode: "pip",
    media: "clip",
    src: "yt_web_comm",
    clipFit: "contain",
    kicker: "สไตล์การตอบคำถามแบบใหม่",
    headline: "เอาใจความสำคัญขึ้นมาก่อน",
    sub: "ไม่ต้องอ่านยาว ๆ ได้คำตอบที่ตรงประเด็นทันที",
    subT: 68.82,
  },

  // =========================================================================
  // Part 3: เรื่องที่ 2 · ความเร็วและประสิทธิภาพ (81.00 - 125.64)
  // =========================================================================
  // L24: Full frame turn (81.00 - 83.42)
  { t: 81.00, mode: "full" },
  // L25-L28 (83.42 - 101.84): ความเร็วเหนือกว่า Opus 5 -> city_night broll
  {
    t: 83.42,
    mode: "pip",
    media: "broll",
    src: "city_night",
    idx: "02",
    kicker: "เรื่องที่ 2 · ความเร็วที่เพิ่มขึ้น",
    headline: "เร็วกว่ารุ่น Opus 5 อย่างเห็นได้ชัด",
    sub: "ถามปุ๊บ ตอบปั๊บ คำตอบมาไวขึ้นเหมือนสั่งอาหารแล้วได้เสิร์ฟทันที",
    subT: 94.50,
    stats: [
      { t: 86.2, big: "+30%", label: "เร็วกว่า Opus 5 เดิม", tone: "mint" },
      { t: 96.2, label: "⚡ คำตอบมาเร็วขึ้นมาก" },
    ],
  },
  // L29-L33 (101.84 - 125.64): Efficient & ประหยัดต้นทุน -> pricing clip
  {
    t: 101.84,
    mode: "pip",
    media: "clip",
    src: "yt_web_pricing",
    clipFit: "contain",
    kicker: "ประสิทธิภาพ & ความคุ้มค่า",
    headline: "ประหยัดพลังงาน · ต้นทุนลดลง 40%",
    sub: "Efficient ทำงานได้ดีเท่าเดิม แต่ค่าใช้จ่ายถูกลงและลื่นไหล",
    subT: 111.64,
  },

  // =========================================================================
  // Part 4: เรื่องที่ 3 · เหมาะกับการทำงานยาว ๆ (125.64 - 164.82)
  // =========================================================================
  // L34-L36: Full frame pivot (125.64 - 132.96)
  { t: 125.64, mode: "full" },
  // L37-L40 (132.96 - 147.48): สมมติทำงานกับ AI ทั้งวัน -> typing broll
  {
    t: 132.96,
    mode: "pip",
    media: "broll",
    src: "typing",
    idx: "03",
    kicker: "เรื่องที่ 3 · การทำงานยาวทั้งวัน",
    headline: "Long Sessions · ทำงานได้ตลอดวัน",
    sub: "ไม่หลุดประเด็น แม้คุยต่อเนื่องหลายชั่วโมง",
    subT: 141.3,
    stats: [
      { t: 135.0, big: "ทั้งวัน", label: "ทำงานร่วมกับ AI ต่อเนื่อง", tone: "mint" },
      { t: 143.9, label: "🎯 ตอบตรงประเด็นเสมอ" },
    ],
  },
  // L41-L44 (147.48 - 164.82): ออกแบบมาให้ทำงานร่วมกับเราได้ดี -> YouTube official full spot
  {
    t: 147.48,
    mode: "pip",
    media: "clip",
    src: "yt_full_spot",
    clipFit: "cover",
    kicker: "ออกแบบมาเพื่อการทำงานจริง",
    headline: "ผู้ช่วยที่ไม่มีวันเหนื่อย",
    sub: "จัดลำดับข้อมูลสำคัญให้เราเห็นก่อนเสมอ",
    subT: 154.9,
  },

  // =========================================================================
  // Part 5: ประโยชน์สำหรับคนทั่วไป (164.82 - 213.30)
  // =========================================================================
  // L45-L48: Full frame pivot (164.82 - 175.92)
  { t: 164.82, mode: "full" },
  // L49-L52 (175.92 - 189.28): คนทำธุรกิจ -> trading broll
  {
    t: 175.92,
    mode: "pip",
    media: "broll",
    src: "trading",
    idx: "ธุรกิจ",
    kicker: "กลุ่มที่ 1 · คนทำธุรกิจ & ค้าขาย",
    headline: "อีเมลลูกค้า · แคปชั่นขาย · วางแผน",
    sub: "ช่วยคิดไอเดียและคอนเทนต์การตลาดครบวงจร",
    subT: 183.54,
    stats: [
      { t: 182.1, label: "📧 เขียนอีเมลหาลูกค้า" },
      { t: 184.3, label: "🛍️ เขียนโพสต์ขายของ" },
      { t: 187.2, label: "📈 ช่วยวางแผนการตลาด" },
    ],
  },
  // L53-L56 (189.28 - 200.42): พนักงานออฟฟิศ -> handshake broll
  {
    t: 189.28,
    mode: "pip",
    media: "broll",
    src: "handshake",
    idx: "ออฟฟิศ",
    kicker: "กลุ่มที่ 2 · พนักงานออฟฟิศ",
    headline: "สรุปเอกสาร · รายงาน · แปลภาษา",
    sub: "ย่อเอกสารยาวเหลือประเด็นสำคัญ และช่วยเตรียม Presentation",
    subT: 194.78,
    stats: [
      { t: 192.0, label: "📄 สรุปเอกสารยาว" },
      { t: 195.5, label: "📝 เขียนรายงาน & แปลภาษา" },
      { t: 198.9, label: "📊 เตรียม Presentation" },
    ],
  },
  // L57-L60 (200.42 - 213.30): นักเรียน นักศึกษา -> source yt_elements (nature, art, science)
  {
    t: 200.42,
    mode: "pip",
    media: "clip",
    src: "yt_elements",
    clipFit: "contain",
    idx: "นักเรียน",
    kicker: "กลุ่มที่ 3 · นักเรียน & นักศึกษา",
    headline: "อธิบายเรื่องยากให้เข้าใจง่าย",
    sub: "ตรวจการบ้าน หาข้อมูลรายงาน ไม่ว่าจะทำอาชีพไหนก็ใช้ได้",
    subT: 206.20,
  },

  // =========================================================================
  // Part 6: เปรียบเทียบกับ ChatGPT (213.30 - 253.56)
  // =========================================================================
  // L61-L67 (213.30 - 233.58): Typo VS Scene (ChatGPT vs Claude)
  {
    t: 213.30,
    mode: "pip",
    media: "typo",
    typo: "vs",
    src: "abstract",
    kicker: "เปรียบเทียบ: ChatGPT vs Claude Opus 5.5",
  },
  // L68-L73 (233.58 - 253.56): จุดเด่น Claude: เขียนกระชับ ตรงประเด็น ไม่อ้อมค้อม -> coding broll
  {
    t: 233.58,
    mode: "pip",
    media: "broll",
    src: "coding",
    kicker: "จุดเด่นที่แตกต่างของ Claude",
    headline: "เขียนกระชับ · ตรงประเด็น · ไม่อ้อมค้อม",
    sub: "ให้ข้อมูลสำคัญก่อน ทำงานเสถียรในเซสชันยาว และประหยัดทรัพยากร",
    subT: 240.22,
    stats: [
      { t: 236.6, label: "🎯 ชัดเจน กระชับ ไม่อ้อมค้อม" },
      { t: 242.5, label: "⏳ เสถียรในงานยาว" },
      { t: 245.1, big: "ประหยัด", label: "เร็วและคุ้มค่าทรัพยากร", tone: "mint" },
    ],
  },

  // =========================================================================
  // Part 7: สรุปภาพรวม & ปิดท้าย (253.56 - 298.68)
  // =========================================================================
  // L74-L78 (253.56 - 269.32): Typo Final4 Scene
  {
    t: 253.56,
    mode: "pip",
    media: "typo",
    typo: "final4",
    src: "abstract",
    from: 8,
    kicker: "สรุป 4 ประเด็นสำคัญของ Claude Opus 5.5",
  },
  // L79-L84 (269.32 - 289.60): YouTube official Claude logo clip!
  {
    t: 269.32,
    mode: "pip",
    media: "clip",
    src: "yt_claude_logo",
    clipFit: "cover",
    kicker: "ก้าวสำคัญของวงการ AI เพื่อทุกคน",
    headline: "AI ช่วยให้ชีวิตสะดวกขึ้นเยอะมาก",
    sub: "ไม่ว่าเรื่องงาน เรื่องเรียน หรือเรื่องส่วนตัว AI ช่วยได้หมด",
    subT: 281.8,
  },
  // L85-L87 (289.60 - 298.68): Outro Full Frame + CTA Chip
  {
    t: 289.60,
    mode: "full",
    lower: {
      title: "กด Like · Share · Subscribe",
      sub: "เพื่อไม่พลาดการอัปเดตเทคโนโลยี AI ล่าสุดทุกสัปดาห์",
      t: 292.5,
      dur: 6.5,
    },
  },
];

// Typo scene word times
const SUMMARY3 = [
  { t: 30.7, text: "1 · ฉลาดเท่าตัวท็อป Fable 5.1", icon: "🧠" },
  { t: 33.4, text: "2 · ทำงานเร็วกว่า & ต้นทุนลด 40%", icon: "⚡" },
  { t: 35.3, text: "3 · เขียนกระชับ เหมาะกับงานยาว", icon: "🎯" },
];

const FINAL4 = [
  { t: 254.4, text: "1 · ฉลาดเทียบเท่ารุ่นท็อป (Fable 5.1)", icon: "🧠" },
  { t: 257.0, text: "2 · สื่อสารชัดเจน เอาใจความขึ้นก่อน", icon: "🎯" },
  { t: 260.0, text: "3 · เร็วกว่าเดิม & ประหยัดต้นทุน 40%", icon: "⚡" },
  { t: 264.7, text: "4 · ทุกคนเข้าถึงได้ ไม่ต้องรู้โค้ด", icon: "✨" },
];

const VS = { fableT: 220.34, mythosT: 223.80, subT: 230.48 };
const CTA_T = 292.5;

// ---- Fonts ----------------------------------------------------------------
let fontReady: Promise<void> | null = null;
function ensureFonts(): Promise<void> {
  if (!fontReady) {
    const defs: [string, number][] = [
      ["fonts/Kanit-ExtraBold.ttf", 800],
      ["fonts/Kanit-Bold.ttf", 700],
    ];
    fontReady = Promise.all(
      defs.map(async ([path, weight]) => {
        const ff = new FontFace("KanitX", `url(${staticFile(path)})`, { weight: String(weight) });
        await ff.load();
        (document as any).fonts.add(ff);
      })
    ).then(() => undefined);
  }
  return fontReady;
}
const useThaiFonts = () => {
  const [handle] = useState(() => delayRender("thai-fonts"));
  useEffect(() => {
    ensureFonts().then(() => continueRender(handle)).catch(() => continueRender(handle));
  }, [handle]);
};

// ---- Helpers --------------------------------------------------------------
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const easeInOutCos = (p: number) => (1 - Math.cos(Math.PI * clamp01(p))) / 2;
const easeOutCubic = (p: number) => 1 - Math.pow(1 - clamp01(p), 3);
const springIn = (frame: number, fps: number, damping = 16, stiffness = 130) =>
  spring({ frame: Math.max(0, frame), fps, config: { damping, stiffness } });

function pipProgress(t: number): number {
  let p = BEATS[0].mode === "pip" ? 1 : 0;
  for (let i = 1; i < BEATS.length; i++) {
    const b = BEATS[i];
    const target = b.mode === "pip" ? 1 : 0;
    if (t >= b.t) {
      const local = (t - b.t) / MODE_BLEND_SEC;
      p = local >= 1 ? target : p + (target - p) * easeInOutCos(local);
    } else break;
  }
  return p;
}

// ===========================================================================
// Stage components: Footage (broll), Clip (museum card), Typo
// ===========================================================================
const BrowserChrome: React.FC = () => {
  return (
    <div
      style={{
        height: CHROME_H,
        background: NAVY_2,
        borderBottom: "1px solid rgba(245,241,232,0.12)",
        display: "flex",
        alignItems: "center",
        padding: "0 18px",
        gap: 14,
        zIndex: 20,
      }}
    >
      <div style={{ display: "flex", gap: 7 }}>
        <div style={{ width: 11, height: 11, borderRadius: "50%", background: "#FF5F56" }} />
        <div style={{ width: 11, height: 11, borderRadius: "50%", background: "#FFBD2E" }} />
        <div style={{ width: 11, height: 11, borderRadius: "50%", background: "#27C93F" }} />
      </div>
      <div
        style={{
          flex: 1,
          maxWidth: 620,
          background: "rgba(245,241,232,0.06)",
          border: "1px solid rgba(245,241,232,0.14)",
          borderRadius: 8,
          height: 28,
          display: "flex",
          alignItems: "center",
          padding: "0 12px",
          gap: 8,
        }}
      >
        <span style={{ fontSize: 13, color: MINT }}>🔒</span>
        <span style={{ fontFamily: MONO, fontSize: 13, color: CREAM_DIM }}>
          {EPISODE.page.domain}
        </span>
        <span style={{ fontFamily: MONO, fontSize: 13, color: CREAM }}>
          {EPISODE.page.path}
        </span>
      </div>
    </div>
  );
};

const Footage: React.FC<{
  src: string;
  from?: number;
  beatStart: number;
  beatEnd: number;
  t: number;
  fps: number;
}> = ({ src, from = 0, beatStart, beatEnd, t, fps }) => {
  const dur = BROLL_DUR[src] || 10;
  const local = t - beatStart + from;
  const loopFrames = Math.max(1, Math.floor(dur * fps) - 2);

  return (
    <Loop durationInFrames={loopFrames}>
      <OffthreadVideo
        muted
        src={staticFile(`${EPISODE.assetDir}/broll/${src}.mp4`)}
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
      />
    </Loop>
  );
};

const FootageStage: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, beatEnd, t, fps }) => {
  const local = t - beat.t;
  const enter = springIn(Math.round(local * fps), fps, 14, 110);
  const subSpring = beat.subT ? springIn(Math.round((t - beat.subT) * fps), fps, 16, 110) : 0;

  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      {beat.src ? <Footage src={beat.src} from={beat.from || 0} beatStart={beat.t} beatEnd={beatEnd} t={t} fps={fps} /> : null}
      <div style={{ position: "absolute", inset: 0, background: "linear-gradient(180deg, rgba(11,14,23,0.3) 0%, rgba(11,14,23,0.85) 100%)" }} />
      <div style={{ position: "absolute", left: 40, right: 40, bottom: 40, zIndex: 10 }}>
        {beat.idx ? (
          <div style={{ display: "inline-block", background: AMBER, color: NAVY, padding: "4px 12px", borderRadius: 6, fontSize: 16, fontWeight: 800, marginBottom: 12 }}>
            {beat.idx}
          </div>
        ) : null}
        {beat.headline ? (
          <div
            style={{
              fontSize: 48, fontWeight: 800, color: CREAM, lineHeight: 1.15,
              opacity: enter, transform: `translateY(${(1 - enter) * 16}px)`,
              textShadow: "0 4px 16px rgba(0,0,0,0.6)",
            }}
          >
            {beat.headline}
          </div>
        ) : null}
        {beat.sub && beat.subT && t >= beat.subT ? (
          <div
            style={{
              fontSize: 28, fontWeight: 700, color: AMBER, marginTop: 12, lineHeight: 1.3,
              opacity: subSpring, transform: `translateY(${(1 - subSpring) * 12}px)`,
            }}
          >
            {beat.sub}
          </div>
        ) : null}
      </div>
    </div>
  );
};

const ClipStage: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, beatEnd, t, fps }) => {
  const local = t - beat.t;
  const enter = springIn(Math.round(local * fps), fps, 14, 110);
  const dur = (beat.src && BROLL_DUR[beat.src]) || 10;
  const loopFrames = Math.max(1, Math.floor(dur * fps) - 2);
  const fit = beat.clipFit || "contain";
  const subSpring = beat.subT ? springIn(Math.round((t - beat.subT) * fps), fps, 16, 110) : 0;

  return (
    <div style={{ position: "absolute", inset: 0, background: fit === "contain" ? "#EDE8DD" : NAVY_2, display: "flex", flexDirection: "column" }}>
      <div style={{ flex: 1, position: "relative", overflow: "hidden", margin: fit === "contain" ? 28 : 0, borderRadius: fit === "contain" ? 16 : 0, background: "#000" }}>
        <Loop durationInFrames={loopFrames}>
          <OffthreadVideo
            muted
            src={staticFile(`${EPISODE.assetDir}/broll/${beat.src}.mp4`)}
            style={{ width: "100%", height: "100%", objectFit: fit }}
          />
        </Loop>
        {/* official source badge */}
        <div style={{ position: "absolute", top: 16, left: 18, background: "rgba(11,14,23,0.78)", color: CREAM, padding: "6px 14px", borderRadius: 8, fontSize: 15, fontWeight: 800, letterSpacing: 1.2, border: "1px solid rgba(245,241,232,0.18)" }}>
          {EPISODE.officialTag}
        </div>
      </div>
      {beat.headline ? (
        <div style={{ padding: "0 36px 26px 36px", zIndex: 10 }}>
          <div style={{ fontSize: 38, fontWeight: 800, color: fit === "contain" ? INK : CREAM, lineHeight: 1.2, opacity: enter, transform: `translateY(${(1 - enter) * 12}px)` }}>
            {beat.headline}
          </div>
          {beat.sub && beat.subT && t >= beat.subT ? (
            <div style={{ fontSize: 24, fontWeight: 700, color: fit === "contain" ? AMBER_DEEP : AMBER, marginTop: 6, opacity: subSpring, transform: `translateY(${(1 - subSpring) * 8}px)` }}>
              {beat.sub}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};

// ===========================================================================
// Typography stages (summary3 / vs / final4)
// ===========================================================================
const Summary3Stage: React.FC<{ beat: Beat; t: number; fps: number }> = ({ beat, t, fps }) => {
  return (
    <div style={{ position: "absolute", inset: 0, background: NAVY_2, padding: "80px 70px", display: "flex", flexDirection: "column", justifyContent: "center", gap: 32 }}>
      <div style={{ fontSize: 44, fontWeight: 800, color: AMBER, letterSpacing: 1 }}>{EPISODE.summary3Label}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        {SUMMARY3.map((item, idx) => {
          if (t < item.t) return null;
          const s = springIn(Math.round((t - item.t) * fps), fps, 14, 120);
          return (
            <div
              key={idx}
              style={{
                display: "flex", alignItems: "center", gap: 24, background: "rgba(245,241,232,0.06)",
                border: "1px solid rgba(245,241,232,0.12)", borderRadius: 16, padding: "20px 28px",
                opacity: s, transform: `translateX(${(1 - s) * 30}px)`,
              }}
            >
              <span style={{ fontSize: 38 }}>{item.icon}</span>
              <span style={{ fontSize: 36, fontWeight: 700, color: CREAM }}>{item.text}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const VsStage: React.FC<{ beat: Beat; t: number; fps: number }> = ({ beat, t, fps }) => {
  const cfg = EPISODE.vs;
  const sLeft = t >= VS.fableT ? springIn(Math.round((t - VS.fableT) * fps), fps, 15, 110) : 0;
  const sRight = t >= VS.mythosT ? springIn(Math.round((t - VS.mythosT) * fps), fps, 15, 110) : 0;
  const sSub = t >= VS.subT ? springIn(Math.round((t - VS.subT) * fps), fps, 15, 110) : 0;

  return (
    <div style={{ position: "absolute", inset: 0, background: NAVY_2, padding: "50px 50px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
      <div style={{ fontSize: 32, fontWeight: 800, color: AMBER, letterSpacing: 0.5 }}>{cfg.eyebrow}</div>
      <div style={{ display: "flex", gap: 24, flex: 1, margin: "20px 0" }}>
        {/* Left card */}
        <div
          style={{
            flex: 1, background: "rgba(217,119,87,0.10)", border: "1.5px solid rgba(217,119,87,0.35)", borderRadius: 20,
            padding: "26px 28px", display: "flex", flexDirection: "column", gap: 16,
            opacity: sLeft, transform: `translateY(${(1 - sLeft) * 24}px)`,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: 26, fontWeight: 800, color: CREAM }}>{cfg.left.title}</span>
            <span style={{ background: CLAY, color: NAVY, fontSize: 14, fontWeight: 800, padding: "3px 10px", borderRadius: 6 }}>{cfg.left.badge}</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {cfg.left.lines.map((l, i) => (
              <div key={i} style={{ fontSize: 22, fontWeight: 600, color: CREAM_DIM, lineHeight: 1.3 }}>• {l}</div>
            ))}
          </div>
        </div>
        {/* Right card */}
        <div
          style={{
            flex: 1, background: "rgba(143,214,180,0.10)", border: "1.5px solid rgba(143,214,180,0.35)", borderRadius: 20,
            padding: "26px 28px", display: "flex", flexDirection: "column", gap: 16,
            opacity: sRight, transform: `translateY(${(1 - sRight) * 24}px)`,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: 26, fontWeight: 800, color: CREAM }}>{cfg.right.title}</span>
            <span style={{ background: MINT, color: NAVY, fontSize: 14, fontWeight: 800, padding: "3px 10px", borderRadius: 6 }}>{cfg.right.badge}</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {cfg.right.lines.map((l, i) => (
              <div key={i} style={{ fontSize: 22, fontWeight: 600, color: CREAM_DIM, lineHeight: 1.3 }}>• {l}</div>
            ))}
          </div>
        </div>
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: CREAM, background: "rgba(245,241,232,0.06)", padding: "14px 20px", borderRadius: 12, opacity: sSub }}>
        {cfg.conclusion}
      </div>
    </div>
  );
};

const Final4Stage: React.FC<{ beat: Beat; t: number; fps: number }> = ({ beat, t, fps }) => {
  const cfg = EPISODE.final4;
  return (
    <div style={{ position: "absolute", inset: 0, background: NAVY_2, padding: "50px 60px", display: "flex", flexDirection: "column", justifyContent: "center", gap: 24 }}>
      <div>
        <div style={{ fontSize: 44, fontWeight: 800, color: AMBER }}>{cfg.title}</div>
        <div style={{ fontSize: 22, fontWeight: 600, color: CREAM_DIM, marginTop: 4 }}>{cfg.sub}</div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {FINAL4.map((item, idx) => {
          if (t < item.t) return null;
          const s = springIn(Math.round((t - item.t) * fps), fps, 14, 120);
          return (
            <div
              key={idx}
              style={{
                display: "flex", alignItems: "center", gap: 20, background: "rgba(245,241,232,0.07)",
                border: "1px solid rgba(245,241,232,0.14)", borderRadius: 14, padding: "16px 24px",
                opacity: s, transform: `translateX(${(1 - s) * 24}px)`,
              }}
            >
              <span style={{ fontSize: 32 }}>{item.icon}</span>
              <span style={{ fontSize: 28, fontWeight: 700, color: CREAM }}>{item.text}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const TypoStage: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, beatEnd, t, fps }) => {
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      {beat.src ? <Footage src={beat.src} from={beat.from || 0} beatStart={beat.t} beatEnd={beatEnd} t={t} fps={fps} /> : null}
      <div style={{ position: "absolute", inset: 0, background: "rgba(11,14,23,0.88)" }} />
      {beat.typo === "summary3" ? <Summary3Stage beat={beat} t={t} fps={fps} /> : null}
      {beat.typo === "vs" ? <VsStage beat={beat} t={t} fps={fps} /> : null}
      {beat.typo === "final4" ? <Final4Stage beat={beat} t={t} fps={fps} /> : null}
    </div>
  );
};

// ===========================================================================
// Overlays: TopBar, LowerThird, StatChips, CtaChip, Captions, Endcard
// ===========================================================================
const TopBar: React.FC<{ beat: Beat; t: number; fps: number; p: number }> = ({ beat, t, fps, p }) => {
  const kSpring = springIn(Math.round((t - beat.t) * fps), fps, 14, 120);
  return (
    <div style={{ position: "absolute", left: 80, right: 80, top: 32, display: "flex", alignItems: "center", gap: 14, zIndex: 40 }}>
      <div style={{ background: AMBER, color: NAVY, padding: "6px 16px", borderRadius: 10, fontSize: 18, fontWeight: 800, letterSpacing: 0.8 }}>
        {EPISODE.brand}
      </div>
      <div style={{ fontSize: 16, fontWeight: 700, color: CREAM_DIM, letterSpacing: 0.5 }}>{EPISODE.dateLabel}</div>
      {p > 0.4 && beat.kicker ? (
        <div
          style={{
            marginLeft: 8, background: "rgba(242,179,76,0.18)", color: AMBER, border: "1px solid rgba(242,179,76,0.4)",
            padding: "5px 14px", borderRadius: 8, fontSize: 16, fontWeight: 700,
            opacity: kSpring, transform: `scale(${0.9 + 0.1 * kSpring})`,
          }}
        >
          {beat.kicker}
        </div>
      ) : null}
    </div>
  );
};

const LowerThird: React.FC<{ beat: Beat; t: number; fps: number }> = ({ beat, t, fps }) => {
  const l = beat.lower;
  if (!l) return null;
  const start = beat.t + (l.t ?? 0.5);
  const dur = l.dur ?? 5.5;
  if (t < start || t >= start + dur) return null;
  const local = t - start;
  const enter = springIn(Math.round(local * fps), fps, 14, 110);
  const exit = local > dur - 0.5 ? clamp01((dur - local) / 0.5) : 1;

  return (
    <div
      style={{
        position: "absolute", left: 80, bottom: 120, zIndex: 40,
        opacity: enter * exit, transform: `translateY(${(1 - enter) * 20}px)`,
      }}
    >
      <div style={{ display: "inline-block", background: CLAY, color: CREAM, fontSize: 15, fontWeight: 800, padding: "4px 12px", borderRadius: 6, letterSpacing: 1, marginBottom: 8 }}>
        BREAKING NEWS
      </div>
      <div style={{ fontSize: 52, fontWeight: 800, color: CREAM, textShadow: "0 4px 20px rgba(0,0,0,0.7)" }}>
        {l.title}
      </div>
      <div style={{ fontSize: 24, fontWeight: 600, color: AMBER, marginTop: 6, textShadow: "0 2px 10px rgba(0,0,0,0.7)" }}>
        {l.sub}
      </div>
    </div>
  );
};

const StatChips: React.FC<{ beat: Beat; t: number; fps: number; onLight?: boolean }> = ({ beat, t, fps, onLight }) => {
  const stats = beat.stats || [];
  return (
    <div style={{ position: "absolute", left: STAGE.x + 36, bottom: H - STAGE.y - STAGE.h + 28, display: "flex", gap: 14, zIndex: 25, flexWrap: "wrap", maxWidth: STAGE.w - 72 }}>
      {stats.map((st, i) => {
        if (t < st.t) return null;
        const s = springIn(Math.round((t - st.t) * fps), fps, 14, 130);
        return (
          <div
            key={i}
            style={{
              background: onLight ? "rgba(20,26,43,0.88)" : "rgba(11,14,23,0.85)",
              border: `1.5px solid ${tone(st.tone)}`,
              borderRadius: 12, padding: "8px 18px", display: "flex", alignItems: "baseline", gap: 10,
              boxShadow: "0 10px 30px rgba(0,0,0,0.45)",
              opacity: s, transform: `translateY(${(1 - s) * 14}px) scale(${0.9 + 0.1 * s})`,
            }}
          >
            {st.big ? (
              <span style={{ fontSize: 28, fontWeight: 800, color: tone(st.tone), fontFamily: MONO }}>{st.big}</span>
            ) : null}
            <span style={{ fontSize: 20, fontWeight: 700, color: CREAM }}>{st.label}</span>
          </div>
        );
      })}
    </div>
  );
};

const CtaChip: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  if (t < CTA_T || t >= VO_END_SEC) return null;
  const s = springIn(Math.round((t - CTA_T) * fps), fps, 14, 120);
  return (
    <div
      style={{
        position: "absolute", left: 80, bottom: 130, zIndex: 45,
        background: "rgba(11,14,23,0.92)", border: `2px solid ${AMBER}`, borderRadius: 16,
        padding: "16px 26px", display: "flex", alignItems: "center", gap: 14,
        boxShadow: "0 16px 40px rgba(0,0,0,0.6), 0 0 30px rgba(242,179,76,0.25)",
        opacity: s, transform: `translateY(${(1 - s) * 18}px)`,
      }}
    >
      <span style={{ fontSize: 30 }}>✨</span>
      <div>
        <div style={{ fontSize: 20, fontWeight: 600, color: CREAM_DIM }}>{EPISODE.cta.lead}</div>
        <div style={{ fontSize: 32, fontWeight: 800, color: AMBER }}>{EPISODE.cta.text}</div>
      </div>
    </div>
  );
};

const CaptionLane: React.FC<{ t: number; fps: number }> = ({ t }) => {
  if (t >= VO_END_SEC) return null;
  const page = CAPTION_PAGES.find((p) => t >= p.start && t < p.end);
  if (!page) return null;

  return (
    <div
      style={{
        position: "absolute", left: 0, right: 0, bottom: 26, zIndex: 50,
        display: "flex", justifyContent: "center", pointerEvents: "none",
      }}
    >
      <div
        style={{
          background: "rgba(11,14,23,0.78)", padding: "10px 28px", borderRadius: 16,
          backdropFilter: "blur(8px)", border: "1px solid rgba(245,241,232,0.12)",
          display: "flex", gap: 10, maxWidth: 1500, flexWrap: "wrap", justifyContent: "center",
          boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
        }}
      >
        {page.words.map((w, idx) => {
          const isSpoken = t >= w.s;
          return (
            <span
              key={idx}
              style={{
                fontFamily: FONT, fontSize: 36, fontWeight: 800,
                color: isSpoken ? GOLD : CREAM,
                textShadow: isSpoken ? `0 0 16px ${GOLD}, 0 0 28px ${GOLD_LIGHT}` : "0 2px 8px rgba(0,0,0,0.8)",
                transition: "color 0.08s ease, text-shadow 0.08s ease",
              }}
            >
              {w.w}
            </span>
          );
        })}
      </div>
    </div>
  );
};

const ProgressBar: React.FC<{ totalFrames: number }> = ({ totalFrames }) => {
  const frame = useCurrentFrame();
  const pct = clamp01(frame / totalFrames) * 100;
  return (
    <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 4, background: "rgba(245,241,232,0.15)", zIndex: 60 }}>
      <div style={{ width: `${pct}%`, height: "100%", background: `linear-gradient(90deg, ${AMBER}, ${MINT})` }} />
    </div>
  );
};

const Endcard: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  const local = t - VO_END_SEC;
  const s1 = springIn(Math.round(local * fps), fps, 14, 110);
  const s2 = springIn(Math.round((local - 0.4) * fps), fps, 14, 110);

  return (
    <div
      style={{
        position: "absolute", inset: 0, background: NAVY, zIndex: 100,
        display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", gap: 28,
      }}
    >
      <div style={{ fontSize: 22, fontWeight: 800, color: AMBER, letterSpacing: 2, opacity: s1, transform: `translateY(${(1 - s1) * 12}px)` }}>
        {EPISODE.endcard.eyebrow}
      </div>
      <div style={{ fontSize: 80, fontWeight: 800, color: CREAM, lineHeight: 1.1, textAlign: "center", opacity: s1, transform: `translateY(${(1 - s1) * 20}px)` }}>
        <div>{EPISODE.endcard.titleA}</div>
        <div style={{ color: AMBER }}>{EPISODE.endcard.titleB}</div>
      </div>
      <div style={{ width: 160 * s1, height: 5, background: `linear-gradient(90deg, ${CLAY}, ${AMBER})`, borderRadius: 3 }} />
      <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 28, color: CREAM_DIM, opacity: s2, transform: `translateY(${(1 - s2) * 14}px)` }}>
        {EPISODE.endcard.sub}
      </div>
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 40, color: NAVY, background: AMBER, padding: "10px 34px", borderRadius: 18, opacity: s2, transform: `translateY(${(1 - s2) * 14}px)`, boxShadow: `0 16px 40px rgba(242,179,76,0.35)` }}>
        {EPISODE.endcard.cta}
      </div>
    </div>
  );
};

// ===========================================================================
// Root composition
// ===========================================================================
export type Opus55NewsYTV1Props = { durationSec?: number };

export const calculateOpus55NewsYTV1Metadata: CalculateMetadataFunction<Opus55NewsYTV1Props> = ({ props }) => {
  const fps = 25;
  const durationSec = props.durationSec || TOTAL_DURATION_SEC;
  return { durationInFrames: Math.ceil(durationSec * fps), fps, width: W, height: H };
};

export const Opus55NewsYTV1: React.FC<Opus55NewsYTV1Props> = ({ durationSec = TOTAL_DURATION_SEC }) => {
  useThaiFonts();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const totalFrames = Math.ceil(durationSec * fps);

  let beatIdx = 0;
  for (let i = 0; i < BEATS.length; i++) if (t >= BEATS[i].t) beatIdx = i;
  const beat = BEATS[beatIdx];
  const beatEndOf = (i: number) => (i + 1 < BEATS.length ? BEATS[i + 1].t : VO_END_SEC);

  // avatar morph: full-frame <-> right anchor card (uniform scale, no distortion)
  const p = pipProgress(t);
  const cardX = interpolate(p, [0, 1], [0, AV.x]);
  const cardY = interpolate(p, [0, 1], [0, AV.y]);
  const cardW = interpolate(p, [0, 1], [W, AV.w]);
  const cardH = interpolate(p, [0, 1], [H, AV.h]);
  const radius = interpolate(p, [0, 1], [0, AV.r]);
  const scale = interpolate(p, [0, 1], [1, AV.h / 1080]);
  const cx = interpolate(p, [0, 1], [960, AV_CX]);
  const cy = interpolate(p, [0, 1], [540, AV_CY]);
  const innerLeft = -(cx - cardW / scale / 2) * scale;
  const innerTop = -(cy - cardH / scale / 2) * scale;
  const stageOpacity = interpolate(p, [0, 0.6, 1], [0, 0.9, 1]);
  const stageSlide = interpolate(p, [0, 1], [-40, 0]);

  const showEndcard = t >= VO_END_SEC;
  const bgDrift = Math.sin(t * 0.25) * 30;

  return (
    <div style={{ width: W, height: H, position: "relative", overflow: "hidden", backgroundColor: NAVY, fontFamily: FONT }}>
      {/* ===== backdrop ===== */}
      <div style={{ position: "absolute", inset: 0, background: `linear-gradient(180deg, ${NAVY_2} 0%, ${NAVY} 100%)` }} />
      <div style={{ position: "absolute", inset: 0, backgroundImage: "radial-gradient(rgba(245,241,232,0.075) 1.2px, transparent 1.2px)", backgroundSize: "28px 28px", opacity: stageOpacity }} />
      <div style={{ position: "absolute", left: -200 + bgDrift, top: -260, width: 900, height: 900, borderRadius: "50%", background: `radial-gradient(circle, rgba(242,179,76,0.16), transparent 62%)`, opacity: stageOpacity }} />
      <div style={{ position: "absolute", right: -260 - bgDrift, bottom: -380, width: 1000, height: 1000, borderRadius: "50%", background: `radial-gradient(circle, rgba(217,119,87,0.16), transparent 62%)`, opacity: stageOpacity }} />

      {/* ===== LEFT STAGE ===== */}
      <div
        style={{
          position: "absolute", left: STAGE.x + stageSlide, top: STAGE.y, width: STAGE.w, height: STAGE.h,
          borderRadius: STAGE.r, overflow: "hidden", opacity: stageOpacity, zIndex: 10,
          background: NAVY_2, border: "1px solid rgba(245,241,232,0.14)",
          boxShadow: "0 30px 80px rgba(0,0,0,0.55), 0 0 0 1px rgba(0,0,0,0.4)",
        }}
      >
        {BEATS.map((b, i) => {
          if (b.mode !== "pip" || !b.media || b.media === "none") return null;
          const bStart = b.t;
          const bEnd = beatEndOf(i);
          if (t < bStart || t >= bEnd + 0.45) return null;
          const fadeIn = clamp01((t - bStart) / 0.35);
          return (
            <div key={`m${i}`} style={{ position: "absolute", inset: 0, opacity: fadeIn, zIndex: i }}>
              {b.media === "broll" ? <FootageStage beat={b} beatEnd={bEnd} t={t} fps={fps} /> : null}
              {b.media === "clip" ? <ClipStage beat={b} beatEnd={bEnd} t={t} fps={fps} /> : null}
              {b.media === "typo" ? <TypoStage beat={b} beatEnd={bEnd} t={t} fps={fps} /> : null}
            </div>
          );
        })}
      </div>

      {/* stat / info chips over the stage */}
      {!showEndcard && beat.mode === "pip" ? <StatChips beat={beat} t={t} fps={fps} onLight={beat.media === "web"} /> : null}

      {/* ===== AVATAR (continuous, morphs full <-> anchor card) ===== */}
      <Sequence from={0} durationInFrames={Math.ceil(VO_END_SEC * fps) + 10} layout="none">
        <div
          style={{
            position: "absolute", left: cardX, top: cardY, width: cardW, height: cardH,
            borderRadius: radius, overflow: "hidden", zIndex: 30, backgroundColor: NAVY,
            border: p > 0.2 ? `2px solid rgba(245,241,232,${0.16 * p})` : "none",
            boxShadow: p > 0.2 ? `0 30px 80px rgba(0,0,0,${0.6 * p}), 0 0 40px rgba(242,179,76,${0.18 * p})` : "none",
          }}
        >
          <div style={{ position: "absolute", left: innerLeft, top: innerTop, width: 1920 * scale, height: 1080 * scale }}>
            <OffthreadVideo muted src={staticFile(`${EPISODE.assetDir}/avatar_source.mp4`)} style={{ width: "100%", height: "100%" }} />
          </div>
          {/* legibility vignette for lower-thirds/captions in full frame */}
          <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 300, background: "linear-gradient(180deg, transparent, rgba(11,14,23,0.55))", opacity: 1 - p, pointerEvents: "none" }} />
          {/* subtle anchor-card foot gradient */}
          <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 120, background: "linear-gradient(180deg, transparent, rgba(11,14,23,0.35))", opacity: p, pointerEvents: "none" }} />
        </div>
      </Sequence>

      {/* ===== Overlays ===== */}
      {!showEndcard ? <TopBar beat={beat} t={t} fps={fps} p={p} /> : null}
      {!showEndcard ? <LowerThird beat={beat} t={t} fps={fps} /> : null}
      <CtaChip t={t} fps={fps} />
      <ProgressBar totalFrames={totalFrames} />
      <CaptionLane t={t} fps={fps} />
      {showEndcard ? <Endcard t={t} fps={fps} /> : null}
    </div>
  );
};
