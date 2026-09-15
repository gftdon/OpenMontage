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
import { CAPTION_PAGES } from "./tripoGameCaptions";
import { WEB_CLIPS, WEB_RECTS, WebRect } from "./tripoGameWeb";

// ===========================================================================
// TripoYTNewsV1 — 16:9 AI-news report (1920x1080@25)
// Format "Youtube-YT-News-Style01-V1": the report subject is a YOUTUBE VIDEO
// (RemakeBench — "I let 4 AI Build this Game From Scratch"), not a web page.
// The left stage carries clips cut from the source video (museum cards +
// full-bleed footage) picked to match what the presenter says, stock b-roll
// with kinetic Thai headlines, and typography scenes — while one continuous
// avatar morphs between FULL-FRAME and a 9:16 anchor card on the right.
// Timing spine = whisper word timing (tripoGameCaptions.ts), never the SRT.
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
const VO_END_SEC = 370.1; // last whisper word end (369.76) + 0.3
const TOTAL_DURATION_SEC = 374.5; // + 4.4 s endcard
const MODE_BLEND_SEC = 0.55;

// ---- Episode config (swap per episode — every on-screen string lives here) --
const EPISODE = {
  assetDir: "tripoGameNews", // public/<assetDir>/{avatar_source.mp4, broll/, web/}
  brand: "AI GAME NEWS",
  dateLabel: "15 ก.ย. 2026",
  page: { domain: "youtube.com", path: "/watch?v=GBo8XjZJVis" }, // browser chrome URL pill
  officialTag: "SOURCE · REMAKEBENCH", // tag on `clip` beats
  cta: { lead: "ทดลองสร้างโมเดล 3D ฟรีได้ที่", text: "tripo3d.ai" },
  endcard: {
    eyebrow: "AI GAME NEWS · SEPTEMBER 2026",
    titleA: "4 AI สร้างเกม",
    titleB: "จากศูนย์",
    sub: "ต้นฉบับ: RemakeBench — I let 4 AI Build this Game From Scratch",
    cta: "ทดลอง Tripo ฟรี · tripo3d.ai",
  },
  summary3Label: "สรุปง่าย ๆ",
  final4: { title: "สรุปวันนี้ 4 ข้อ", sub: "4 AI สร้างเกมจากศูนย์ · ไม่ต้องเขียนโค้ด" },
  vs: {
    eyebrow: "ทักษะที่สำคัญที่สุดในยุคนี้",
    left: { title: "ยุคก่อน AI", badge: "BEFORE", lines: ["ต้องมีทักษะก่อน", "ต้องเรียน ต้องฝึก", "บางอย่างใช้เวลาหลายปี"] },
    right: { title: "ยุค AI", badge: "NOW", lines: ["ไม่ต้องเก่งทุกอย่าง", "รู้ว่าอยากได้อะไร", "รู้วิธีสั่ง AI ให้ทำ"] },
    conclusion: "💡 ทักษะสำคัญที่สุด = การคิด และ การสื่อสาร",
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
// presenter centre in the 1920x1080 source (face is slightly left of centre)
const AV_CX = 940;
const AV_CY = 540;
const S0 = VW / 1100; // capture CSS px -> stage px at zoom 1

// ---- B-roll durations (public/<assetDir>/broll, 1080p25; yt_* = clips cut from the YouTube source) ----
const BROLL_DUR: Record<string, number> = {
  abstract: 30.0, ai_network: 30.0, brain: 10.0, coding: 14.96, cyber: 30.0,
  gaming: 24.16, gen_glitch: 5.04, gen_ident: 5.04, gladiator: 10.04,
  office: 14.8, shopping: 10.0, studio: 8.0, typing: 12.16,
  // YouTube source clips (RemakeBench — GBo8XjZJVis), cut + transcoded 1080p25
  yt_fight: 11.08, yt_pipeline: 24.08, yt_refart: 26.12, yt_tripo_home: 19.12,
  yt_tripo_model: 18.08, yt_rig: 24.08, yt_gameplay: 13.08, yt_audio: 18.08,
  yt_judge: 22.12, yt_clay: 21.12, yt_arena: 22.12, yt_rounds: 20.08,
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
  file?: string; // e.g. "sec_hero" | "quote_02" | "chart_1"
  cssH?: number; // capture CSS height when not in WEB_CLIPS
  cam?: CamKey[];
  hl?: Highlight[];
  // footage
  src?: string; // broll key
  from?: number;
  headline?: string;
  sub?: string;
  subT?: number;
  idx?: string;
  clipFit?: "cover" | "contain"; // `clip` beats: cover for full-bleed footage, contain for light renders
  // typo
  typo?: "summary3" | "vs" | "final4";
  // overlays
  stats?: Stat[];
  lower?: { title: string; sub: string; t?: number; dur?: number };
}

const R = (k: string): WebRect => WEB_RECTS[k] || { x: 230, y: 0, w: 600, h: 40 };
const rowRect = (includes: string): WebRect => {
  const k = Object.keys(WEB_RECTS).find(
    (kk) => kk.startsWith("table_row") && (WEB_RECTS[kk].text || "").includes(includes) && WEB_RECTS[kk].w > 0
  );
  return k ? WEB_RECTS[k] : { x: 110, y: 216, w: 880, h: 72 };
};
const colRect = (includes: string, rowKey: WebRect): WebRect => {
  const k = Object.keys(WEB_RECTS).find(
    (kk) => kk.startsWith("table_col") && (WEB_RECTS[kk].text || "").includes(includes)
  );
  const c = k ? WEB_RECTS[k] : { x: 330, w: 170, y: 0, h: 0 };
  return { x: c.x, y: rowKey.y, w: c.w, h: rowKey.h };
};

const BEATS: Beat[] = [
  // ---- cold open (full frame) ------------------------------------------
  { t: 0.0, mode: "full", lower: { title: "4 AI ช่วยกันสร้างเกมจากศูนย์", sub: "ไม่ต้องเขียนโค้ดแม้แต่บรรทัดเดียว — เรื่องจริงที่เกิดขึ้นแล้ว", t: 1.2, dur: 6.5 } },
  {
    t: 10.48, mode: "pip", media: "broll", src: "yt_fight", kicker: "คำตอบคือ…ได้แล้วในยุคนี้",
    headline: "AI 4 ตัว สร้างเกมทั้งเกม", sub: "จากศูนย์ — ไม่ต้องเขียนโค้ดเอง", subT: 12.77,
    stats: [{ t: 14.52, big: "4 AI", label: "ช่วยกันสร้างเกมจากศูนย์", tone: "mint" }],
  },
  {
    t: 20.88, mode: "pip", media: "clip", src: "yt_pipeline", clipFit: "contain", kicker: "ไม่ต้องเขียนโค้ดแม้แต่บรรทัดเดียว",
    headline: "pipeline สร้างเกมด้วย AI ล้วน ๆ", sub: "ที่มา: คลิปต้นฉบับ RemakeBench", subT: 24.6,
  },
  { t: 29.2, mode: "full" },
  // ---- overview: ทีมงาน 4 คน --------------------------------------------
  {
    t: 31.26, mode: "pip", media: "broll", src: "office", kicker: "ภาพรวมการสร้างเกม",
    headline: "การสร้างเกมแบบเดิม", sub: "ต้องใช้คนหลายฝ่าย แต่ละส่วนใช้ทักษะเฉพาะทาง", subT: 34.6,
    stats: [{ t: 38.3, label: "🎨 คนออกแบบตัวละคร" }, { t: 43.28, label: "💻 คนเขียนโปรแกรม" }, { t: 44.8, label: "🔊 คนทำเสียงและเอฟเฟกต์" }],
  },
  {
    t: 50.02, mode: "pip", media: "broll", src: "yt_pipeline", from: 10, kicker: "ตอนนี้ AI ทำแทนได้เกือบทั้งหมด",
    headline: "เหมือนมีทีมงาน 4 คน", sub: "พร้อมทำตามคำสั่งเราตลอดเวลา", subT: 55.24,
    stats: [{ t: 55.24, big: "4 ทีมงาน", label: "พร้อมรับคำสั่ง 24 ชม.", tone: "mint" }],
  },
  {
    t: 58.08, mode: "pip", media: "broll", src: "ai_network", kicker: "การแบ่งหน้าที่",
    headline: "AI 4 ตัว คนละหน้าที่", sub: "เราแค่บอกว่าอยากได้อะไร AI ก็ไปทำให้", subT: 64.5,
    stats: [{ t: 59.5, label: "🗿 ปั้นโมเดล 3D" }, { t: 61.0, label: "💻 เขียนโค้ด" }, { t: 62.6, label: "🎨 วาดภาพฉาก" }, { t: 64.2, label: "🎵 เสียงและดนตรี" }],
  },
  {
    t: 68.14, mode: "pip", media: "broll", src: "studio", kicker: "บทบาทใหม่ของเรา",
    headline: "เราคือผู้กำกับหนัง", sub: "ไม่ต้องถือกล้องเอง ไม่ต้องแต่งหน้าเอง", subT: 71.2,
    stats: [{ t: 74.2, label: "🗣️ แค่บอกว่าอยากได้ฉากแบบไหน" }, { t: 78.0, label: "⚡ ทีมงาน AI ไปจัดการให้" }],
  },
  { t: 78.32, mode: "full" },
  // ---- AI ตัวที่ 1: Tripo 3D ---------------------------------------------
  {
    t: 81.62, mode: "pip", media: "clip", src: "yt_tripo_home", clipFit: "cover", idx: "AI 1", kicker: "AI ตัวที่ 1 · โมเดลสามมิติ",
    headline: "Tripo — AI ปั้นโมเดล 3D", sub: "บอกหน้าตาที่อยากได้ มันปั้นให้เลย", subT: 91.31,
    stats: [{ t: 88.48, big: "Tripo", label: "AI สร้างโมเดลสามมิติ", tone: "mint" }],
  },
  {
    t: 96.58, mode: "pip", media: "clip", src: "yt_tripo_model", clipFit: "cover", kicker: "เหมือนมีช่างปั้นส่วนตัว",
    headline: "พิมพ์บอก แล้วได้โมเดล 3D", sub: "อยากได้มังกร มันก็ปั้นมังกรให้", subT: 104.6,
    stats: [{ t: 107.42, label: "🐉 มังกร" }, { t: 110.0, label: "🗡️ ดาบวิเศษ" }],
  },
  {
    t: 112.74, mode: "pip", media: "clip", src: "yt_rig", clipFit: "cover", kicker: "หมุนดูได้รอบด้านเหมือนของจริง",
    headline: "Tripo P2.0", sub: "ละเอียดและสวยงามกว่าเดิมเยอะ", subT: 118.21,
    stats: [{ t: 115.88, big: "P2.0", label: "เวอร์ชันล่าสุด", tone: "mint" }, { t: 125.92, label: "🎮 เกม · แอนิเมชัน · งานออกแบบ" }],
  },
  { t: 127.36, mode: "full" },
  // ---- AI ตัวที่ 2: เขียนโค้ด ---------------------------------------------
  {
    t: 129.6, mode: "pip", media: "broll", src: "coding", idx: "AI 2", kicker: "AI ตัวที่ 2 · เขียนโค้ด",
    headline: "ทำให้เกมทำงานได้", sub: "ถ้าโมเดล 3D คือตัวละคร โค้ดคือสิ่งที่ทำให้ขยับได้", subT: 133.02,
    stats: [{ t: 136.0, big: "Coding AI", label: "ช่วยเขียนโปรแกรมระบบเกม", tone: "mint" }],
  },
  {
    t: 139.6, mode: "pip", media: "broll", src: "yt_gameplay", kicker: "โค้ดคืออะไร",
    headline: "วิ่งได้ กระโดดได้", sub: "กดปุ่มแล้วตัวละครทำตาม — นั่นคือโค้ด", subT: 143.12,
    stats: [{ t: 143.12, label: "🏃 วิ่งได้" }, { t: 143.93, label: "🦘 กระโดดได้" }],
  },
  {
    t: 148.6, mode: "pip", media: "broll", src: "typing", kicker: "คนที่ไม่เคยเขียนโปรแกรมเลย",
    headline: "พิมพ์บอก AI ก็เขียนให้หมด", sub: "อยากให้กดปุ่มแล้ววิ่งไปข้างหน้า บอกแค่นั้น", subT: 155.0,
    stats: [{ t: 158.0, label: "✅ AI เขียนคำสั่งให้ครบ" }],
  },
  {
    t: 161.28, mode: "pip", media: "clip", src: "yt_judge", clipFit: "cover", kicker: "แต่ก่อนต้องเรียนหลายเดือน",
    headline: "ตอนนี้ไม่กี่นาที", sub: "ที่มา: คลิปต้นฉบับ — AI ตรวจคุณภาพงานของตัวเอง", subT: 168.38,
    stats: [{ t: 168.38, big: "ไม่กี่นาที", label: "จากเดิมหลายเดือน", tone: "mint" }],
  },
  // ---- AI ตัวที่ 3 + 4: ภาพและเสียง ---------------------------------------
  {
    t: 171.58, mode: "pip", media: "clip", src: "yt_refart", clipFit: "contain", idx: "AI 3", kicker: "AI ตัวที่ 3 · สร้างภาพ",
    headline: "วาดฉากหลังให้ทั้งเกม", sub: "ป่าไม้ ภูเขา ท้องฟ้า หรือฉากในเมือง", subT: 179.44,
    stats: [{ t: 175.08, big: "Image AI", label: "สร้างภาพพื้นหลังและฉาก", tone: "mint" }],
  },
  {
    t: 184.1, mode: "pip", media: "broll", src: "cyber", kicker: "พิมพ์บอกบรรยากาศที่อยากได้",
    headline: "ไม่ต้องจ้างนักวาด", sub: "ได้ภาพที่ไม่เหมือนใคร เป็นของเราเอง 100%", subT: 189.36,
    stats: [{ t: 194.28, label: "✨ เอกลักษณ์ของเราเอง 100%" }],
  },
  {
    t: 196.5, mode: "pip", media: "clip", src: "yt_audio", clipFit: "cover", idx: "AI 4", kicker: "AI ตัวที่ 4 · เสียงและดนตรี",
    headline: "เอฟเฟกต์และเพลงประกอบ", sub: "เสียงดาบฟัน เสียงระเบิด เพลงฉากต่อสู้", subT: 204.04,
    stats: [{ t: 200.92, big: "Audio AI", label: "สร้างเสียงและดนตรี", tone: "mint" }],
  },
  {
    t: 210.16, mode: "pip", media: "broll", src: "office", from: 7, kicker: "รวม 4 ตัวเข้าด้วยกัน",
    headline: "ทีมสร้างเกมครบวงจร", sub: "โดยไม่ต้องจ้างใครเลยสักคนเดียว", subT: 214.48,
    stats: [{ t: 211.54, big: "ครบวงจร", label: "4 AI ทำงานเป็นทีม", tone: "mint" }],
  },
  { t: 217.04, mode: "full" },
  // ---- เกี่ยวอะไรกับเรา ---------------------------------------------------
  {
    t: 222.42, mode: "pip", media: "broll", src: "brain", kicker: "คำถามที่สำคัญที่สุด",
    headline: "ถ้าไม่ได้อยากสร้างเกมล่ะ?", sub: "เทคโนโลยีนี้ยังมีประโยชน์กับเราไหม", subT: 225.5,
    stats: [{ t: 227.0, big: "มีประโยชน์มาก", label: "คำตอบ", tone: "mint" }],
  },
  {
    t: 228.72, mode: "pip", media: "clip", src: "yt_arena", clipFit: "cover", kicker: "ไม่ได้จำกัดแค่การสร้างเกม",
    headline: "สร้างอย่างอื่นได้เหมือนกัน", sub: "ที่มา: คลิปต้นฉบับ — โคลอสเซียมที่ AI สร้าง", subT: 235.02,
  },
  {
    t: 239.5, mode: "pip", media: "broll", src: "shopping", kicker: "ขายของออนไลน์",
    headline: "ภาพสินค้า 3 มิติสวย ๆ", sub: "AI ก็ทำให้ได้", subT: 243.0,
    stats: [{ t: 239.5, label: "🛍️ ขายของออนไลน์" }],
  },
  {
    t: 247.2, mode: "pip", media: "broll", src: "typing", from: 6, kicker: "ทุกอาชีพใช้ได้",
    headline: "ครู · นักออกแบบ · ครีเอเตอร์", sub: "สื่อการสอน 3D · ต้นแบบในไม่กี่นาที · คอนเทนต์โซเชียล", subT: 250.0,
    stats: [{ t: 247.2, label: "📚 ครู — สื่อการสอน 3D" }, { t: 254.6, label: "📐 นักออกแบบ — ต้นแบบไว" }, { t: 261.0, label: "📱 ครีเอเตอร์ — คอนเทนต์ครบ" }],
  },
  { t: 264.8, mode: "full" },
  // ---- ทักษะยุค AI ---------------------------------------------------------
  {
    t: 267.3, mode: "pip", media: "broll", src: "gaming", kicker: "สิ่งที่น่าทึ่งที่สุดของยุคนี้",
    headline: "AI ลดอุปสรรคเรื่องทักษะ", sub: "เมื่อก่อนต้องเรียนก่อน ฝึกก่อน — บางอย่างหลายปี", subT: 272.0,
    stats: [{ t: 282.46, big: "ลดอุปสรรค", label: "ไม่จำเป็นต้องเก่งทุกอย่าง", tone: "mint" }],
  },
  { t: 284.17, mode: "pip", media: "typo", typo: "vs", src: "abstract", kicker: "ทักษะที่สำคัญที่สุดในยุคนี้" },
  { t: 304.38, mode: "full" },
  // ---- สรุป -----------------------------------------------------------------
  { t: 307.54, mode: "pip", media: "typo", typo: "final4", src: "abstract", from: 12, kicker: "สรุป 4 ข้อคิดสำคัญ" },
  {
    t: 345.0, mode: "pip", media: "clip", src: "yt_rounds", clipFit: "contain", kicker: "เรื่องจริงจากคลิปต้นฉบับ",
    headline: "AI ปรับเกมถึง 95 รอบ", sub: "ที่มา: คลิปต้นฉบับ RemakeBench", subT: 348.0,
    stats: [{ t: 348.8, big: "95 รอบ", label: "ปรับปรุงจนกว่าจะสมบูรณ์", tone: "mint" }],
  },
  {
    t: 351.5, mode: "pip", media: "broll", src: "brain", from: 5, kicker: "ลองเปิดใจเรียนรู้",
    headline: "AI ออกแบบมาให้ใช้ง่าย", sub: "ไม่ต้องกลัวว่ามันจะยากเกินไป", subT: 354.8,
    stats: [{ t: 358.9, label: "💡 ใช้ง่ายสำหรับทุกคน" }],
  },
  { t: 361.18, mode: "full" },
];

// Typo scene word times
const SUMMARY3 = [{ t: 309.93, text: "AI ทำงานเป็นทีม", icon: "👥" }, { t: 317.61, text: "ไม่ต้องเขียนโค้ด", icon: "🎮" }, { t: 327.38, text: "ประโยชน์กับทุกคน", icon: "🌍" }];
const FINAL4 = [
  { t: 309.93, text: "1 · AI ทำงานร่วมกันเป็นทีม", icon: "👥" },
  { t: 317.61, text: "2 · สร้างได้โดยไม่ต้องเขียนโค้ด", icon: "🎮" },
  { t: 327.38, text: "3 · มีประโยชน์กับทุกคน", icon: "🌍" },
  { t: 339.38, text: "4 · ทักษะคิดและสื่อสาร", icon: "💡" },
];
const VS = { fableT: 285.6, mythosT: 289.8, subT: 299.9 };
const CTA_T = 363.9;

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

const tone = (k?: string) => (k === "mint" ? MINT : k === "clay" ? CLAY : AMBER);

// ===========================================================================
// Web browser stage
// ===========================================================================
const BrowserChrome: React.FC = () => (
  <div
    style={{
      position: "absolute", left: 0, top: 0, width: VW, height: CHROME_H,
      background: "linear-gradient(180deg, #F1EEE7, #E6E2D9)", borderBottom: "1px solid rgba(0,0,0,0.12)",
      display: "flex", alignItems: "center", padding: "0 18px", gap: 8,
    }}
  >
    {["#FF5F57", "#FEBC2E", "#28C840"].map((c) => (
      <div key={c} style={{ width: 12, height: 12, borderRadius: 6, background: c, marginRight: 2 }} />
    ))}
    <div
      style={{
        marginLeft: 16, flex: 1, height: 30, borderRadius: 9, background: "#FFFFFF",
        border: "1px solid rgba(0,0,0,0.10)", display: "flex", alignItems: "center", gap: 8,
        padding: "0 12px", fontFamily: FONT, fontSize: 16, color: "#3A3733", fontWeight: 700,
      }}
    >
      <span style={{ fontSize: 13 }}>🔒</span>
      <span style={{ color: "#6B665E" }}>{EPISODE.page.domain}</span>
      <span style={{ color: "#8A857C", fontWeight: 700 }}>{EPISODE.page.path}</span>
    </div>
    <div style={{ width: 90, height: 24, borderRadius: 6, background: "rgba(0,0,0,0.06)" }} />
  </div>
);

function camAt(cam: CamKey[] | undefined, local: number): { fx: number; fy: number; z: number } {
  if (!cam || cam.length === 0) return { fx: 550, fy: 300, z: 1 };
  if (local <= cam[0].t) return { fx: cam[0].fx ?? 550, fy: cam[0].fy, z: cam[0].z };
  for (let i = 0; i < cam.length - 1; i++) {
    const a = cam[i], b = cam[i + 1];
    if (local >= a.t && local < b.t) {
      const p = easeInOutCos((local - a.t) / Math.max(0.001, b.t - a.t));
      return {
        fx: interpolate(p, [0, 1], [a.fx ?? 550, b.fx ?? 550]),
        fy: interpolate(p, [0, 1], [a.fy, b.fy]),
        z: interpolate(p, [0, 1], [a.z, b.z]),
      };
    }
  }
  const l = cam[cam.length - 1];
  return { fx: l.fx ?? 550, fy: l.fy, z: l.z };
}

const WebStage: React.FC<{ beat: Beat; t: number; fps: number }> = ({ beat, t, fps }) => {
  const file = beat.file || "sec_hero";
  // capture naming convention (capture_page.mjs): sec_<section> | <carousel>_NN | <tabs>_N
  // -> WEB_CLIPS[<section>] | WEB_CLIPS[<carousel>] | WEB_CLIPS[<tabs>_N]; `cssH` overrides.
  const clip = WEB_CLIPS[file] ?? WEB_CLIPS[file.replace(/^sec_/, "")] ?? WEB_CLIPS[file.replace(/_\d+$/, "")];
  const cssH = beat.cssH ?? clip?.h ?? 800;
  const local = t - beat.t;
  const cam = camAt(beat.cam, local);
  const s = S0 * cam.z;
  const pageW = 1100 * s;
  const pageH = cssH * s;
  let left = VW / 2 - cam.fx * s;
  let top = VH * 0.46 - cam.fy * s;
  left = Math.min(0, Math.max(VW - pageW, left));
  if (pageH <= VH) top = (VH - pageH) / 2; else top = Math.min(0, Math.max(VH - pageH, top));
  // page enters with a gentle settle
  const enter = easeOutCubic(local / 0.5);

  return (
    <div style={{ position: "absolute", left: 0, top: CHROME_H, width: VW, height: VH, overflow: "hidden", background: "#F5F4EE" }}>
      <div style={{ position: "absolute", left, top: top + (1 - enter) * 24, width: pageW, height: pageH }}>
        <Img src={staticFile(`${EPISODE.assetDir}/web/${file}.png`)} style={{ width: pageW, height: pageH, display: "block" }} />
        {(beat.hl || []).map((h, i) => {
          if (t < h.t) return null;
          const r = h.rect || (h.key ? R(h.key) : null);
          if (!r) return null;
          const pad = h.pad ?? 5;
          const wipe = springIn(Math.round((t - h.t) * fps), fps, 20, 120);
          return (
            <div
              key={i}
              style={{
                position: "absolute",
                left: (r.x - pad) * s, top: (r.y - pad) * s,
                width: (r.w + pad * 2) * s * wipe, height: (r.h + pad * 2) * s,
                background: "rgba(242,179,76,0.55)", borderRadius: 6 * s,
                mixBlendMode: "multiply",
                boxShadow: `0 0 0 ${1.5 * s}px rgba(217,142,31,${0.5 * wipe})`,
              }}
            />
          );
        })}
      </div>
      {/* soft edge vignettes so the crop never looks like a hard cut */}
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 40, background: "linear-gradient(180deg, rgba(0,0,0,0.10), transparent)", pointerEvents: "none" }} />
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 60, background: "linear-gradient(0deg, rgba(0,0,0,0.12), transparent)", pointerEvents: "none" }} />
    </div>
  );
};

// ===========================================================================
// Footage stage (full-bleed b-roll + kinetic headline) and clip cards
// ===========================================================================
const Footage: React.FC<{ src: string; from: number; beatStart: number; fps: number; style?: React.CSSProperties; zoom?: [number, number]; beatEnd: number; t: number }> = ({
  src, from, beatStart, fps, style, zoom = [1.04, 1.12], beatEnd, t,
}) => {
  const dur = BROLL_DUR[src] || 10;
  const p = clamp01((t - beatStart) / Math.max(0.1, beatEnd - beatStart));
  const scale = interpolate(p, [0, 1], [zoom[0], zoom[1]]);
  const loopFrames = Math.max(1, Math.floor((dur - from) * fps) - 2);
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", ...style }}>
      <div style={{ position: "absolute", inset: 0, transform: `scale(${scale})`, transformOrigin: "50% 50%" }}>
        <Loop durationInFrames={loopFrames} layout="none">
          <OffthreadVideo muted src={staticFile(`${EPISODE.assetDir}/broll/${src}.mp4`)} startFrom={Math.round(from * fps)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        </Loop>
      </div>
    </div>
  );
};

const HeadlineBlock: React.FC<{ beat: Beat; t: number; fps: number; light?: boolean }> = ({ beat, t, fps, light }) => {
  const local = Math.round((t - beat.t) * fps);
  const a = springIn(local - 4, fps, 18, 120);
  const subOn = beat.sub && t >= (beat.subT ?? beat.t + 1.2);
  const b = springIn(Math.round((t - (beat.subT ?? beat.t + 1.2)) * fps), fps, 18, 120);
  const ink = light ? INK : CREAM;
  return (
    <div style={{ position: "absolute", left: 64, top: 96, width: 820, zIndex: 5 }}>
      {beat.idx ? (
        <div
          style={{
            display: "inline-block", fontFamily: FONT, fontWeight: 800, fontSize: 22, letterSpacing: 2,
            color: NAVY, background: AMBER, padding: "4px 14px", borderRadius: 8, marginBottom: 14,
            opacity: a, transform: `translateY(${(1 - a) * 12}px)`,
          }}
        >
          {beat.idx}
        </div>
      ) : null}
      <div
        style={{
          fontFamily: FONT, fontWeight: 800, fontSize: 74, lineHeight: 1.12, color: ink,
          textShadow: light ? "none" : "0 6px 30px rgba(0,0,0,0.55)",
          opacity: a, transform: `translateY(${(1 - a) * 26}px)`,
        }}
      >
        {beat.headline}
      </div>
      <div style={{ width: 120 * a, height: 5, background: `linear-gradient(90deg, ${AMBER}, ${CLAY})`, borderRadius: 3, margin: "16px 0 14px" }} />
      {subOn ? (
        <div
          style={{
            fontFamily: FONT, fontWeight: 700, fontSize: 32, lineHeight: 1.3, color: light ? "#5A5248" : AMBER,
            textShadow: light ? "none" : "0 3px 16px rgba(0,0,0,0.55)",
            opacity: b, transform: `translateY(${(1 - b) * 14}px)`,
          }}
        >
          {beat.sub}
        </div>
      ) : null}
    </div>
  );
};

const FootageStage: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, beatEnd, t, fps }) => (
  <div style={{ position: "absolute", inset: 0 }}>
    <Footage src={beat.src || "abstract"} from={beat.from || 0} beatStart={beat.t} beatEnd={beatEnd} t={t} fps={fps} />
    <div style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg, rgba(11,14,23,0.90) 0%, rgba(11,14,23,0.62) 48%, rgba(11,14,23,0.28) 100%)" }} />
    <div style={{ position: "absolute", inset: 0, background: "linear-gradient(180deg, rgba(11,14,23,0.25), transparent 30%, transparent 70%, rgba(11,14,23,0.55))" }} />
    <HeadlineBlock beat={beat} t={t} fps={fps} />
  </div>
);

// official clip inside the stage frame (light, museum-card look)
const ClipStage: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, beatEnd, t, fps }) => {
  const src = beat.src || "nipah";
  const dur = BROLL_DUR[src] || 5;
  const loopFrames = Math.max(1, Math.floor(dur * fps) - 1);
  const local = Math.round((t - beat.t) * fps);
  const a = springIn(local - 2, fps, 18, 120);
  const subOn = beat.sub && t >= (beat.subT ?? beat.t + 1.2);
  return (
    <div style={{ position: "absolute", inset: 0, background: "#EFECE4", overflow: "hidden" }}>
      <div style={{ position: "absolute", inset: 0 }}>
        <Loop durationInFrames={loopFrames} layout="none">
          <OffthreadVideo muted src={staticFile(`${EPISODE.assetDir}/broll/${src}.mp4`)} style={{ width: "100%", height: "100%", objectFit: beat.clipFit ?? "contain" }} />
        </Loop>
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 260, background: "linear-gradient(0deg, rgba(11,14,23,0.86), rgba(11,14,23,0.0))" }} />
      <div style={{ position: "absolute", left: 40, bottom: 34, width: 1120, zIndex: 5 }}>
        <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 46, color: CREAM, textShadow: "0 4px 22px rgba(0,0,0,0.6)", opacity: a, transform: `translateY(${(1 - a) * 18}px)` }}>
          {beat.headline}
        </div>
        {subOn ? (
          <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 22, color: CREAM_DIM, marginTop: 6 }}>{beat.sub}</div>
        ) : null}
      </div>
      <div style={{ position: "absolute", right: 22, top: 18, fontFamily: FONT, fontWeight: 700, fontSize: 16, color: NAVY, background: "rgba(245,241,232,0.85)", padding: "5px 12px", borderRadius: 8, letterSpacing: 1 }}>
        {EPISODE.officialTag}
      </div>
    </div>
  );
};

// ===========================================================================
// Typography scenes
// ===========================================================================
const ChipRow: React.FC<{ items: { t: number; text: string; icon: string }[]; t: number; fps: number; big?: boolean; col?: boolean }> = ({ items, t, fps, big, col }) => (
  <div style={{ display: "flex", flexDirection: col ? "column" : "row", flexWrap: "wrap", gap: big ? 22 : 18, alignItems: col ? "stretch" : "center", justifyContent: "center" }}>
    {items.map((it, i) => {
      const a = t >= it.t ? springIn(Math.round((t - it.t) * fps), fps, 14, 140) : 0;
      return (
        <div
          key={i}
          style={{
            display: "flex", alignItems: "center", gap: 18,
            padding: big ? "22px 38px" : "16px 28px", borderRadius: 24,
            background: "rgba(245,241,232,0.10)", border: "1.5px solid rgba(242,179,76,0.55)",
            backdropFilter: "blur(14px)", WebkitBackdropFilter: "blur(14px)",
            boxShadow: "0 14px 40px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.12)",
            opacity: a, transform: `translateY(${(1 - a) * 26}px) scale(${interpolate(a, [0, 1], [0.9, 1])})`,
          }}
        >
          <span style={{ fontSize: big ? 52 : 40 }}>{it.icon}</span>
          <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: big ? 62 : 46, color: CREAM, textShadow: "0 3px 14px rgba(0,0,0,0.5)" }}>{it.text}</span>
        </div>
      );
    })}
  </div>
);

const TypoStage: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, beatEnd, t, fps }) => {
  const local = Math.round((t - beat.t) * fps);
  const a = springIn(local, fps, 18, 120);
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      <Footage src={beat.src || "abstract"} from={beat.from || 0} beatStart={beat.t} beatEnd={beatEnd} t={t} fps={fps} zoom={[1.06, 1.16]} />
      <div style={{ position: "absolute", inset: 0, background: "rgba(11,14,23,0.78)" }} />
      <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 50% 30%, rgba(242,179,76,0.16), transparent 60%)` }} />

      {beat.typo === "summary3" ? (
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 46 }}>
          <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 30, letterSpacing: 4, color: AMBER, opacity: a }}>{EPISODE.summary3Label}</div>
          <ChipRow items={SUMMARY3} t={t} fps={fps} big />
        </div>
      ) : null}

      {beat.typo === "final4" ? (
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 36 }}>
          <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 58, color: CREAM, opacity: a, transform: `translateY(${(1 - a) * 16}px)`, textAlign: "center", lineHeight: 1.15 }}>
            {EPISODE.final4.title}
            <div style={{ fontSize: 28, fontWeight: 700, color: AMBER, marginTop: 4 }}>{EPISODE.final4.sub}</div>
          </div>
          <div style={{ width: 900 }}>
            <ChipRow items={FINAL4} t={t} fps={fps} />
          </div>
        </div>
      ) : null}

      {beat.typo === "vs" ? <VsCard t={t} fps={fps} /> : null}
    </div>
  );
};

const VsCard: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  const f = t >= VS.fableT ? springIn(Math.round((t - VS.fableT) * fps), fps, 16, 120) : 0;
  const m = t >= VS.mythosT ? springIn(Math.round((t - VS.mythosT) * fps), fps, 16, 120) : 0;
  const s = t >= VS.subT ? springIn(Math.round((t - VS.subT) * fps), fps, 16, 120) : 0;
  const eq = springIn(Math.round((t - (VS.fableT - 0.6)) * fps), fps, 16, 120);
  const card = (on: number, title: string, badge: string, lines: string[], accent: string): React.ReactNode => (
    <div
      style={{
        width: 520, padding: "32px 34px", borderRadius: 28,
        background: "rgba(245,241,232,0.08)", border: `2px solid ${accent}`,
        boxShadow: `0 20px 60px rgba(0,0,0,0.5), 0 0 40px ${accent}33`,
        backdropFilter: "blur(16px)", WebkitBackdropFilter: "blur(16px)",
        opacity: on, transform: `translateY(${(1 - on) * 30}px) scale(${interpolate(on, [0, 1], [0.94, 1])})`,
      }}
    >
      <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 18, letterSpacing: 3, color: accent, marginBottom: 6 }}>{badge}</div>
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 60, color: CREAM, lineHeight: 1.05 }}>{title}</div>
      <div style={{ width: 90, height: 4, background: accent, borderRadius: 2, margin: "16px 0 18px" }} />
      {lines.map((l, i) => (
        <div key={i} style={{ fontFamily: FONT, fontWeight: 700, fontSize: 25, color: CREAM_DIM, lineHeight: 1.45 }}>
          {l}
        </div>
      ))}
    </div>
  );
  return (
    <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 30 }}>
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 30, color: AMBER, letterSpacing: 2, opacity: eq, transform: `translateY(${(1 - eq) * 10}px)` }}>
        {EPISODE.vs.eyebrow}
      </div>
      <div style={{ display: "flex", gap: 40, alignItems: "stretch" }}>
        {card(f, EPISODE.vs.left.title, EPISODE.vs.left.badge, EPISODE.vs.left.lines, AMBER)}
        <div style={{ alignSelf: "center", fontFamily: FONT, fontWeight: 800, fontSize: 46, color: CREAM_DIM, opacity: eq }}>vs</div>
        {card(m, EPISODE.vs.right.title, EPISODE.vs.right.badge, EPISODE.vs.right.lines, CLAY)}
      </div>
      <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 26, color: CREAM, background: "rgba(217,119,87,0.22)", border: "1.5px solid rgba(217,119,87,0.6)", padding: "12px 28px", borderRadius: 18, opacity: s, transform: `translateY(${(1 - s) * 14}px)` }}>
        {EPISODE.vs.conclusion}
      </div>
    </div>
  );
};

// ===========================================================================
// Overlays
// ===========================================================================
const StatChips: React.FC<{ beat: Beat; t: number; fps: number; onLight: boolean }> = ({ beat, t, fps, onLight }) => {
  const items = (beat.stats || []).filter((s) => t >= s.t);
  if (!items.length) return null;
  return (
    <div style={{ position: "absolute", left: STAGE.x + 28, bottom: H - (STAGE.y + STAGE.h) + 26, display: "flex", gap: 14, flexWrap: "wrap", width: STAGE.w - 56, zIndex: 40, alignItems: "flex-end" }}>
      {items.map((s, i) => {
        const a = springIn(Math.round((t - s.t) * fps), fps, 14, 150);
        const c = tone(s.tone);
        return (
          <div
            key={i}
            style={{
              display: "flex", alignItems: "baseline", gap: 12,
              padding: s.big ? "12px 22px 12px 20px" : "11px 20px", borderRadius: 18,
              background: "rgba(11,14,23,0.88)", border: `1.5px solid ${c}88`,
              boxShadow: `0 12px 34px rgba(0,0,0,0.45), 0 0 22px ${c}33`,
              backdropFilter: "blur(12px)", WebkitBackdropFilter: "blur(12px)",
              opacity: a, transform: `translateY(${(1 - a) * 22}px) scale(${interpolate(a, [0, 1], [0.86, 1])})`,
              transformOrigin: "left bottom",
            }}
          >
            {s.big ? <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 48, color: c, lineHeight: 1, textShadow: `0 0 18px ${c}66` }}>{s.big}</span> : null}
            <span style={{ fontFamily: FONT, fontWeight: 700, fontSize: s.big ? 24 : 27, color: CREAM, lineHeight: 1.2 }}>{s.label}</span>
          </div>
        );
      })}
    </div>
  );
};

const TopBar: React.FC<{ beat: Beat; t: number; fps: number; p: number }> = ({ beat, t, fps, p }) => {
  const local = Math.round((t - beat.t) * fps);
  const k = springIn(local - 6, fps, 18, 120);
  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: W, height: 92, zIndex: 45, display: "flex", alignItems: "center", padding: "0 80px", gap: 22 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ width: 12, height: 12, borderRadius: 6, background: CLAY, boxShadow: `0 0 12px ${CLAY}` }} />
        <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 24, letterSpacing: 4, color: CREAM }}>{EPISODE.brand}</div>
        <div style={{ width: 1, height: 26, background: "rgba(245,241,232,0.25)" }} />
        <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 20, color: CREAM_DIM, letterSpacing: 1 }}>{EPISODE.dateLabel}</div>
      </div>
      {beat.kicker && p > 0.5 ? (
        <div
          style={{
            marginLeft: 26, fontFamily: FONT, fontWeight: 700, fontSize: 24, color: NAVY,
            background: AMBER, padding: "6px 20px", borderRadius: 12,
            boxShadow: `0 6px 20px rgba(242,179,76,0.35)`,
            opacity: k * p, transform: `translateX(${(1 - k) * -18}px)`,
          }}
        >
          {beat.kicker}
        </div>
      ) : null}
    </div>
  );
};

const LowerThird: React.FC<{ beat: Beat; t: number; fps: number }> = ({ beat, t, fps }) => {
  if (!beat.lower) return null;
  const start = beat.lower.t ?? beat.t + 0.8;
  const dur = beat.lower.dur ?? 5;
  if (t < start || t > start + dur + 0.5) return null;
  const a = springIn(Math.round((t - start) * fps), fps, 18, 110);
  const out = clamp01((t - (start + dur)) / 0.45);
  const o = a * (1 - out);
  return (
    <div style={{ position: "absolute", left: 80, bottom: 150, zIndex: 46, opacity: o, transform: `translateX(${(1 - a) * -40 + out * -30}px)` }}>
      <div style={{ display: "inline-block", fontFamily: FONT, fontWeight: 800, fontSize: 20, letterSpacing: 4, color: NAVY, background: AMBER, padding: "5px 16px", borderRadius: 8 }}>BREAKING</div>
      <div style={{ marginTop: 10, fontFamily: FONT, fontWeight: 800, fontSize: 62, color: CREAM, lineHeight: 1.1, textShadow: "0 6px 30px rgba(0,0,0,0.6)" }}>{beat.lower.title}</div>
      <div style={{ marginTop: 8, display: "inline-block", fontFamily: FONT, fontWeight: 700, fontSize: 28, color: CREAM, background: "rgba(11,14,23,0.78)", padding: "8px 18px", borderRadius: 12, borderLeft: `5px solid ${CLAY}` }}>
        {beat.lower.sub}
      </div>
    </div>
  );
};

const CtaChip: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  if (t < CTA_T || t >= VO_END_SEC) return null;
  const a = springIn(Math.round((t - CTA_T) * fps), fps, 14, 130);
  return (
    <div style={{ position: "absolute", left: 80, bottom: 170, zIndex: 46, opacity: a, transform: `translateY(${(1 - a) * 24}px) scale(${interpolate(a, [0, 1], [0.9, 1])})`, transformOrigin: "left bottom" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 18, padding: "16px 30px", borderRadius: 22, background: "rgba(11,14,23,0.86)", border: `2px solid ${AMBER}`, boxShadow: `0 16px 40px rgba(0,0,0,0.5), 0 0 30px ${AMBER}44` }}>
        <span style={{ fontFamily: FONT, fontWeight: 700, fontSize: 26, color: CREAM_DIM }}>{EPISODE.cta.lead}</span>
        <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 44, color: AMBER, letterSpacing: 1 }}>{EPISODE.cta.text}</span>
      </div>
    </div>
  );
};

const ProgressBar: React.FC<{ totalFrames: number }> = ({ totalFrames }) => {
  const frame = useCurrentFrame();
  const progress = Math.min(1, frame / totalFrames);
  return (
    <div style={{ position: "absolute", top: 0, left: 0, width: "100%", height: 5, backgroundColor: "rgba(245,241,232,0.10)", zIndex: 60 }}>
      <div style={{ width: `${progress * 100}%`, height: "100%", background: `linear-gradient(90deg, ${CLAY}, ${AMBER})`, boxShadow: `0 0 10px ${AMBER}` }} />
    </div>
  );
};

// karaoke caption lane (locked gold-glow look, 16:9 placement)
const isLatin = (s: string) => /^[A-Za-z0-9]/.test(s) || /[A-Za-z0-9]$/.test(s);
const CaptionLane: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  if (t >= VO_END_SEC) return null;
  let pageIdx = -1;
  for (let i = 0; i < CAPTION_PAGES.length; i++) if (t >= CAPTION_PAGES[i].start) pageIdx = i;
  const page = pageIdx >= 0 ? CAPTION_PAGES[pageIdx] : null;
  if (!page) return null;
  const enter = spring({ frame: Math.max(0, Math.round((t - page.start) * fps)), fps, config: { damping: 18, stiffness: 160 } });
  return (
    <div style={{ position: "absolute", left: 0, right: 0, bottom: 26, display: "flex", justifyContent: "center", pointerEvents: "none", zIndex: 50 }}>
      <div
        style={{
          display: "flex", flexWrap: "wrap", justifyContent: "center", alignItems: "center", maxWidth: 1500,
          background: "rgba(11, 14, 23, 0.80)", backdropFilter: "blur(16px)", WebkitBackdropFilter: "blur(16px)",
          border: "1.5px solid rgba(242,179,76,0.30)", borderRadius: 20, padding: "10px 28px",
          boxShadow: "0 8px 32px rgba(0,0,0,0.6), 0 0 20px rgba(242,179,76,0.15)",
          transform: `scale(${interpolate(enter, [0, 1], [0.94, 1])})`, opacity: enter,
        }}
      >
        {page.words.map((w, i) => {
          const active = t >= w.s && t < w.e;
          const spoken = t >= w.e;
          const prev = i > 0 ? page.words[i - 1].w : "";
          const sep = i > 0 && (isLatin(prev) || isLatin(w.w)) ? " " : "";
          let color = "rgba(245,241,232,0.45)";
          let shadow = "none";
          let transform = "scale(1)";
          if (active) { color = GOLD_LIGHT; shadow = `0 0 16px ${GOLD}, 0 0 30px rgba(245,158,11,0.7)`; transform = "scale(1.1)"; }
          else if (spoken) { color = CREAM; shadow = "0 2px 4px rgba(0,0,0,0.4)"; }
          return (
            <span key={i} style={{ fontFamily: FONT, fontSize: 36, fontWeight: active ? 800 : 700, color, textShadow: shadow, transform, margin: "0 2px", display: "inline-block", lineHeight: 1.35 }}>
              {sep + w.w}
            </span>
          );
        })}
      </div>
    </div>
  );
};

const Endcard: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  const local = t - VO_END_SEC;
  const a = clamp01(local / 0.6);
  const s1 = springIn(Math.round((local - 0.3) * fps), fps, 18, 110);
  const s2 = springIn(Math.round((local - 0.9) * fps), fps, 18, 110);
  return (
    <div style={{ position: "absolute", inset: 0, zIndex: 100, opacity: a, background: `radial-gradient(ellipse at 50% 40%, ${NAVY_2}, ${NAVY} 70%)`, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 22 }}>
      <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 22, letterSpacing: 6, color: AMBER, opacity: s1 }}>{EPISODE.endcard.eyebrow}</div>
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 84, color: CREAM, lineHeight: 1.05, textAlign: "center", opacity: s1, transform: `translateY(${(1 - s1) * 20}px)` }}>
        {EPISODE.endcard.titleA}
        <span style={{ color: CREAM_DIM, fontWeight: 700 }}> & </span>
        {EPISODE.endcard.titleB}
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
export type TripoYTNewsV1Props = { durationSec?: number };

export const calculateTripoYTNewsV1Metadata: CalculateMetadataFunction<TripoYTNewsV1Props> = ({ props }) => {
  const fps = 25;
  const durationSec = props.durationSec || TOTAL_DURATION_SEC;
  return { durationInFrames: Math.ceil(durationSec * fps), fps, width: W, height: H };
};

export const TripoYTNewsV1: React.FC<TripoYTNewsV1Props> = ({ durationSec = TOTAL_DURATION_SEC }) => {
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
          // keep the outgoing beat under the incoming one for a crossfade
          if (t < bStart || t >= bEnd + 0.45) return null;
          const fadeIn = clamp01((t - bStart) / 0.35);
          const isWeb = b.media === "web";
          return (
            <div key={`m${i}`} style={{ position: "absolute", inset: 0, opacity: fadeIn, zIndex: i }}>
              {isWeb ? (
                <>
                  <BrowserChrome />
                  <WebStage beat={b} t={t} fps={fps} />
                </>
              ) : null}
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
