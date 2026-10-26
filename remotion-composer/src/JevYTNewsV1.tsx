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
import { CAPTION_PAGES } from "./jevNewsCaptions";
import { WEB_CLIPS, WEB_RECTS, WebRect } from "./jevNewsWeb";

// ===========================================================================
// JevYTNewsV1 — 16:9 AI-news report (1920x1080@25)
// Format "Youtube-YT-News-Style01-V1": the report subject is a YOUTUBE VIDEO
// (Theo - t3.gg — "Jev is incredible"), not a web page.
// The left stage carries clips cut from the source video (museum cards +
// full-bleed footage) picked to match what the presenter says, stock b-roll
// with kinetic Thai headlines, and typography scenes — while one continuous
// avatar morphs between FULL-FRAME and a 9:16 anchor card on the right.
// Timing spine = whisper word timing (jevNewsCaptions.ts), never the SRT.
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
const VO_END_SEC = 387.1; // last whisper word end (386.76) + 0.3
const TOTAL_DURATION_SEC = 391.5; // + 4.4 s endcard
const MODE_BLEND_SEC = 0.55;

// ---- Episode config (swap per episode — every on-screen string lives here) --
const EPISODE = {
  assetDir: "jev-news", // public/<assetDir>/{avatar_source.mp4, broll/, web/}
  brand: "AI TECH NEWS",
  dateLabel: "21 ก.ย. 2026",
  page: { domain: "youtube.com", path: "/watch?v=F3YXg7AaKWE" }, // browser chrome URL pill
  officialTag: "SOURCE · THEO - T3.GG", // tag on `clip` beats
  cta: { lead: "อ่านข้อมูลและผลทดสอบ Jev ได้ที่", text: "typesafe.ai" },
  endcard: {
    eyebrow: "AI TECH NEWS · SEPTEMBER 2026",
    titleA: "JEV AI CLASSIFIER",
    titleB: "เร็ว 20-200X · TYPESAFE",
    sub: "ต้นฉบับ: Theo - t3․gg — Jev is incredible",
    cta: "ข้อมูลเพิ่มเติม · typesafe.ai",
  },
  summary3Label: "สรุป 3 ข้อเด่น",
  final4: { title: "สรุปประเด็นสำคัญ 4 ข้อ", sub: "Jev AI · ตัวจำแนกข้อมูลยุคใหม่ที่เร็วและแม่นยำ" },
  vs: {
    eyebrow: "เทียบหน้าที่ AI ในระบบงานจริง",
    left: {
      title: "Reasoning AI (นักคิด)",
      badge: "SYSTEM 2",
      lines: ["ChatGPT / Claude / Astra", "คิดวิเคราะห์ปัญหาซับซ้อน", "ใช้เวลาประมวลผลนานกว่า"],
    },
    right: {
      title: "Jev AI (ตัวจำแนก)",
      badge: "SYSTEM 1",
      lines: ["แยกประเภทข้อมูลเร็วจัด (70ms)", "รูปแบบ Typesafe ไม่หลอน (0%)", "Output Tokens ฟรี รันคุ้มค่า"],
    },
    conclusion: "💡 Jev ไม่ได้มาแทนที่ แต่เป็นเพื่อนร่วมทีมที่เสริมพลังกัน",
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
const AV_CX = 940;
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
  dna: 8.32,
  handshake: 11.48,
  office: 14.8,
  server_lights: 23.52,
  shopping: 10.0,
  trading: 8.0,
  typing: 12.16,
  warehouse: 20.44,
  // YouTube source clips (Theo - t3.gg — F3YXg7AaKWE)
  yt_announcement: 24.12,
  yt_baml_code: 30.08,
  yt_checkers: 25.12,
  yt_classify32k: 30.12,
  yt_email: 30.08,
  yt_matrix: 40.08,
  yt_pareto: 35.08,
  yt_system1: 25.08,
  yt_table: 25.12,
  yt_zero_error: 35.08,
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

const BEATS: Beat[] = [
  // ---- Part 1: Intro & What is Jev ----------------------------------------
  // L1-4 (0.00 - 13.86) Cold open (full frame)
  {
    t: 0.0,
    mode: "full",
    lower: {
      title: "JEV: AI CLASSIFIER เร็วจัด 200X",
      sub: "โมเดล System 1 ตัวใหม่จาก Typesafe AI — แยกประเภทข้อมูลระดับเสี้ยววิ",
      t: 1.2,
      dur: 7.5,
    },
  },
  // L5-6 (13.86 - 21.54)
  {
    t: 13.86,
    mode: "pip",
    media: "clip",
    src: "yt_announcement",
    clipFit: "contain",
    kicker: "เปิดตัว AI ตัวใหม่: Jev",
    headline: "Jev: System 1 AI Model",
    sub: "พัฒนาโดยผู้ร่วมสร้าง ChatGPT เดิม",
    subT: 17.18,
    stats: [{ t: 15.05, big: "Jev", label: "Frontier Classifier", tone: "amber" }],
  },
  // L7 (21.54 - 28.36)
  {
    t: 21.54,
    mode: "pip",
    media: "broll",
    src: "ai_network",
    kicker: "ออกแบบมาทำงานคนละแบบ",
    headline: "ออกแบบคนละแบบกับ LLM ทั่วไป",
    sub: "ไม่ใช่เพื่อสร้างข้อความ แต่เพื่อแยกประเภท",
    subT: 25.0,
  },
  // L8 (28.36 - 30.10) Full frame pivot
  { t: 28.36, mode: "full" },
  // L9-10 (30.10 - 39.68)
  {
    t: 30.10,
    mode: "pip",
    media: "broll",
    src: "brain",
    kicker: "AI แบบ ChatGPT = นักคิด",
    headline: "ChatGPT / Claude = นักวิเคราะห์",
    sub: "ถามคำถามซับซ้อน ค่อย ๆ คิด ค่อย ๆ วิเคราะห์",
    subT: 33.66,
    stats: [{ t: 30.67, label: "🧠 คิดลึกและวิเคราะห์ซับซ้อน" }],
  },
  // L11-12 (39.68 - 48.74)
  {
    t: 39.68,
    mode: "pip",
    media: "clip",
    src: "yt_system1",
    clipFit: "contain",
    kicker: "Jev = ตัวจำแนกความเร็วสูง",
    headline: "System 1 vs System 2 AI",
    sub: "Jev เน้นการจำแนกที่รวดเร็วระดับเสี้ยววินาที",
    subT: 43.54,
    stats: [{ t: 44.96, big: "ตัวจำแนก", label: "Fast Classifier", tone: "mint" }],
  },
  // L13 (48.74 - 50.56) Full frame pivot
  { t: 48.74, mode: "full" },
  // L14-15 (50.56 - 58.10)
  {
    t: 50.56,
    mode: "pip",
    media: "clip",
    src: "yt_email",
    clipFit: "cover",
    kicker: "ตัวอย่าง: คัดกรองอีเมล 1,000 ฉบับ",
    headline: "คัดแยกอีเมล 1,000 ฉบับ",
    sub: "แยกอีเมลสำคัญ · สแปม · โฆษณา",
    subT: 54.8,
    stats: [{ t: 51.52, big: "1,000+", label: "อีเมลต่อวัน", tone: "amber" }],
  },
  // L16-17 (58.10 - 68.00)
  {
    t: 58.10,
    mode: "pip",
    media: "broll",
    src: "typing",
    kicker: "ถ้าใช้ AI ทั่วไป = ช้าและแพง",
    headline: "ใช้ LLM ตัวใหญ่: ช้าและแพงเกินไป",
    sub: "เพราะถูกออกแบบมาเพื่องานที่ซับซ้อนกว่านี้",
    subT: 64.26,
    stats: [{ t: 64.26, label: "⚠️ เสียเวลาและงบประมาณ", tone: "clay" }],
  },
  // L18-19 (68.00 - 75.36)
  {
    t: 68.00,
    mode: "pip",
    media: "broll",
    src: "server_lights",
    kicker: "Jev ทำงานนี้ได้เร็วมาก",
    headline: "Jev ทำงานได้เร็วมาก ๆ",
    sub: "สร้างมาเพื่องานแยกประเภทโดยเฉพาะ",
    subT: 71.88,
    stats: [{ t: 70.8, big: "เร็วทันที", label: "ตอบสนองในเสี้ยววิ", tone: "mint" }],
  },
  // L20-21 (75.36 - 82.56)
  {
    t: 75.36,
    mode: "pip",
    media: "broll",
    src: "warehouse",
    kicker: "พนักงานคัดแยกมืออาชีพ",
    headline: "เหมือนพนักงานคัดแยกมืออาชีพ",
    sub: "หยิบปุ๊บ รู้ปั๊บ ว่าควรส่งไปแผนกไหน",
    subT: 78.46,
    stats: [{ t: 76.62, label: "📬 คัดแยกและส่งต่อแม่นยำ" }],
  },

  // ---- Part 2: 3 ข้อดีของ Jev ---------------------------------------------
  // L22 (82.56 - 86.60) Full frame pivot
  { t: 82.56, mode: "full" },
  // L23-25 (86.60 - 93.66) ข้อดีที่ 1
  {
    t: 86.60,
    mode: "pip",
    media: "clip",
    src: "yt_checkers",
    clipFit: "cover",
    kicker: "ข้อดีที่ 1: ความเร็ว (Speed)",
    headline: "ความเร็วเหนือระดับ 20-200x",
    sub: "เร็วกว่า AI ตัวใหญ่หลายเท่า ตอบสนองทันที",
    subT: 91.22,
    stats: [
      { t: 88.95, big: "20-200x", label: "เร็วกว่า LLM ทั่วไป", tone: "mint" },
      { t: 91.22, big: "70ms", label: "Latency ต่ำสุด", tone: "mint" },
    ],
  },
  // L26-27 (93.66 - 100.46)
  {
    t: 93.66,
    mode: "pip",
    media: "broll",
    src: "abstract",
    kicker: "ไม่ต้องคิดวิเคราะห์ยาว ๆ",
    headline: "รับข้อมูลปุ๊บ จำแนกปั๊บ",
    sub: "ไม่ต้องเสียเวลา Generate ข้อความยาว ๆ",
    subT: 96.84,
  },
  // L28-30 (100.46 - 113.58) ข้อดีที่ 2
  {
    t: 100.46,
    mode: "pip",
    media: "clip",
    src: "yt_baml_code",
    clipFit: "contain",
    kicker: "ข้อดีที่ 2: ความปลอดภัย Typesafe",
    headline: "ระบบ Typesafe ปลอดภัย",
    sub: "คำตอบต้องอยู่ในกรอบ Schema ที่กำหนดล่วงหน้า",
    subT: 107.1,
    stats: [{ t: 103.74, big: "Typesafe", label: "Schema-aligned", tone: "mint" }],
  },
  // L31 (113.58 - 115.04) Full frame pivot
  { t: 113.58, mode: "full" },
  // L32-34 (115.04 - 128.66)
  {
    t: 115.04,
    mode: "pip",
    media: "broll",
    src: "chat_ai",
    kicker: "ปัญหาของ AI ทั่วไป",
    headline: "AI ทั่วไปมักตอบกำกวม",
    sub: "'น่าจะใช่ แต่ก็ไม่แน่ใจ' นำไปต่อยอดในระบบยาก",
    subT: 121.48,
    stats: [{ t: 125.42, label: "⚠️ เสี่ยงเกิด Hallucination", tone: "clay" }],
  },
  // L35-37 (128.66 - 140.38)
  {
    t: 128.66,
    mode: "pip",
    media: "clip",
    src: "yt_zero_error",
    clipFit: "contain",
    kicker: "Jev ตอบชัดเจน ไร้ความคลุมเครือ",
    headline: "สแปม หรือ ไม่ใช่สแปม ชัดเจน",
    sub: "อัตราความผิดพลาดด้าน Schema เป็น 0%",
    subT: 133.76,
    stats: [
      { t: 130.32, big: "0%", label: "Type Error Rate", tone: "mint" },
      { t: 136.58, big: "100%", label: "นำไปต่อระบบได้ทันที", tone: "mint" },
    ],
  },
  // L38-41 (140.38 - 152.02) ข้อดีที่ 3
  {
    t: 140.38,
    mode: "pip",
    media: "clip",
    src: "yt_pareto",
    clipFit: "contain",
    kicker: "ข้อดีที่ 3: ค่าใช้จ่ายถูกกว่ามาก",
    headline: "ประหยัดต้นทุน 40-400x",
    sub: "กินทรัพยากรน้อย Output Tokens ฟรี",
    subT: 144.9,
    stats: [
      { t: 142.84, big: "400x", label: "ถูกกว่าโมเดลใหญ่", tone: "mint" },
      { t: 149.0, big: "FREE", label: "Output Tokens", tone: "mint" },
    ],
  },
  // L42-44 (152.02 - 165.70)
  {
    t: 152.02,
    mode: "pip",
    media: "broll",
    src: "trading",
    kicker: "สำคัญมากสำหรับคนทำธุรกิจ",
    headline: "ประมวลผลข้อมูลระดับล้านชิ้น",
    sub: "ส่วนต่างต้นทุนต่อครั้ง คูณจำนวนมหาศาล",
    subT: 156.1,
    stats: [{ t: 157.66, big: "ล้านชิ้น/วัน", label: "Scale ได้จริง", tone: "mint" }],
  },

  // ---- Part 3: แทนที่ AI อื่นไหม? ------------------------------------------
  // L45-46 (165.70 - 172.06)
  {
    t: 165.70,
    mode: "pip",
    media: "clip",
    src: "yt_table",
    clipFit: "contain",
    kicker: "คำถามสำคัญ: จะมาแทนที่ AI อื่นไหม?",
    headline: "Jev จะมาแทนที่ AI อื่นไหม?",
    sub: "Frontiers, Old and New — การเปรียบเทียบ",
    subT: 169.04,
  },
  // L47 (172.06 - 173.50) Full frame pivot
  { t: 172.06, mode: "full" },
  // L48-50 (173.50 - 183.42)
  {
    t: 173.50,
    mode: "pip",
    media: "broll",
    src: "coding",
    kicker: "ไม่ได้มาแทนที่ Reasoning Model",
    headline: "ไม่แทนที่ Astra หรือ Fable",
    sub: "เพราะเป็น AI คนละประเภทอย่างสิ้นเชิง",
    subT: 176.86,
    stats: [{ t: 177.14, label: "🧠 Reasoning Models ยังจำเป็น" }],
  },
  // L51-58 (183.42 - 218.10) Typo VS scene
  {
    t: 183.42,
    mode: "pip",
    media: "typo",
    typo: "vs",
    src: "abstract",
    kicker: "เปรียบเทียบหน้าที่พนักงานในออฟฟิศ",
  },
  // L59 (218.10 - 220.56) Full frame pivot
  { t: 218.10, mode: "full" },

  // ---- Part 4: เกี่ยวข้องกับชีวิตประจำวัน & ธุรกิจ ----------------------------
  // L60-63 (220.56 - 234.74)
  {
    t: 220.56,
    mode: "pip",
    media: "broll",
    src: "city_night",
    kicker: "ประโยชน์กับชีวิตประจำวัน",
    headline: "ทำงานเบื้องหลังแอปทุกวัน",
    sub: "เทคโนโลยีที่ซ่อนอยู่ในบริการที่เราใช้",
    subT: 225.48,
    stats: [{ t: 232.84, label: "📱 ซ่อนอยู่ในแอปประจำวัน" }],
  },
  // L64 (234.74 - 235.71) Full frame pivot
  { t: 234.74, mode: "full" },
  // L65-68 (235.71 - 251.58) ตัวอย่าง 1: กรองข้อความโซเชียล
  {
    t: 235.71,
    mode: "pip",
    media: "broll",
    src: "cyber",
    kicker: "ตัวอย่างที่ 1: กรองข้อความโซเชียล",
    headline: "กรองข้อความโซเชียลมีเดีย",
    sub: "แยกข้อความปกติ ออกจากข้อความที่ไม่เหมาะสม",
    subT: 240.52,
    stats: [{ t: 247.48, label: "🛡️ Content Moderation เรียลไทม์" }],
  },
  // L69-71 (251.58 - 262.78) ตัวอย่าง 2: จัดหมวดหมู่สินค้า
  {
    t: 251.58,
    mode: "pip",
    media: "broll",
    src: "shopping",
    kicker: "ตัวอย่างที่ 2: จัดหมวดหมู่สินค้าออนไลน์",
    headline: "จัดหมวดหมู่สินค้าออนไลน์",
    sub: "จำแนกสินค้าหลายล้านรายการให้ค้นหาง่าย",
    subT: 256.52,
    stats: [{ t: 255.1, label: "🛍️ E-Commerce Categorization" }],
  },
  // L72-75 (262.78 - 276.74) ตัวอย่าง 3: กรองอีเมลสแปม
  {
    t: 262.78,
    mode: "pip",
    media: "clip",
    src: "yt_email",
    from: 5,
    clipFit: "cover",
    kicker: "ตัวอย่างที่ 3: คัดกรองอีเมลสแปม",
    headline: "คัดกรองอีเมลสแปมแม่นยำ",
    sub: "เปิดกล่องข้อความ เจอเฉพาะเรื่องสำคัญ",
    subT: 268.92,
    stats: [{ t: 275.14, label: "📧 Smart Inbox Filtering" }],
  },
  // L76-78 (276.74 - 286.73) ธุรกิจ
  {
    t: 276.74,
    mode: "pip",
    media: "clip",
    src: "yt_classify32k",
    clipFit: "contain",
    kicker: "ประโยชน์สำหรับคนทำธุรกิจ",
    headline: "ธุรกิจร้านค้าออนไลน์",
    sub: "ลูกค้าทักเข้ามาหลายร้อยคำถามต่อวัน",
    subT: 284.88,
    stats: [{ t: 277.8, big: "ธุรกิจ", label: "ประหยัดเวลาและคน", tone: "mint" }],
  },
  // L79-81 (286.73 - 300.36) แยกประเภทคำถาม
  {
    t: 286.73,
    mode: "pip",
    media: "broll",
    src: "office",
    kicker: "ส่งต่อไปยังทีมที่รับผิดชอบ",
    headline: "ส่งต่อแผนกที่รับผิดชอบทันที",
    sub: "จัดส่ง · คืนสินค้า · สอบถามราคา",
    subT: 291.14,
    stats: [
      { t: 291.14, label: "📦 เรื่องจัดส่ง" },
      { t: 293.48, label: "🔄 คืนสินค้า" },
      { t: 295.48, label: "🏷️ สอบถามราคา" },
    ],
  },

  // ---- Part 5: สรุป & บทสรุปอนาคต AI --------------------------------------
  // L82 (300.36 - 305.30) Full frame pivot
  { t: 300.36, mode: "full" },
  // L83-89 (305.30 - 336.82) Typo final4 scene
  {
    t: 305.30,
    mode: "pip",
    media: "typo",
    typo: "final4",
    src: "abstract",
    from: 5,
    kicker: "สรุป 4 ประเด็นสำคัญของ Jev",
  },
  // L90-93 (336.82 - 354.62)
  {
    t: 336.82,
    mode: "pip",
    media: "clip",
    src: "yt_matrix",
    clipFit: "contain",
    kicker: "อนาคต AI: ไม่ได้มีแค่แบบเดียว",
    headline: "AI หลากหลายแบบทำงานร่วมกัน",
    sub: "โมเดลนักคิด + โมเดลแยกประเภท = ทรงพลังที่สุด",
    subT: 345.26,
    stats: [{ t: 341.0, big: "Multi-Model", label: "การทำงานผสานกัน", tone: "mint" }],
  },
  // L94-98 (354.62 - 375.16)
  {
    t: 354.62,
    mode: "pip",
    media: "broll",
    src: "datacenter",
    kicker: "ประโยชน์สำหรับผู้ใช้ทั่วไป",
    headline: "แอปฉลาดขึ้น · เร็วขึ้น · แม่นยำขึ้น",
    sub: "บริการในชีวิตประจำวันสะดวกสบายยิ่งขึ้น",
    subT: 361.5,
    stats: [
      { t: 362.2, label: "⚡ เร็วขึ้น" },
      { t: 364.2, label: "🎯 แม่นยำขึ้น" },
    ],
  },
  // L99-101 (375.16 - 387.10) Outro (full frame)
  {
    t: 375.16,
    mode: "full",
    lower: {
      title: "กด Like & Subscribe",
      sub: "เพื่อไม่พลาดการอัปเดตเทคโนโลยี AI ล่าสุด",
      t: 378.0,
      dur: 8.0,
    },
  },
];

// Typo scene word times
const SUMMARY3 = [
  { t: 308.2, text: "จำแนกข้อมูลเร็วจัด", icon: "⚡" },
  { t: 324.8, text: "Typesafe ปลอดภัย ไม่มั่ว", icon: "🛡️" },
  { t: 325.6, text: "ประหยัดต้นทุน 400x", icon: "💸" },
];
const FINAL4 = [
  { t: 308.2, text: "1 · ตัวจำแนกข้อมูลเร็วจัด (20-200x)", icon: "⚡" },
  { t: 324.8, text: "2 · ระบบ Typesafe ปลอดภัย ไม่มั่ว (0% Error)", icon: "🛡️" },
  { t: 325.6, text: "3 · ประหยัดต้นทุนมหาศาล (Output ฟรี)", icon: "💸" },
  { t: 331.7, text: "4 · ทำงานเสริม ไม่แทนที่ AI นักคิด", icon: "🤝" },
];
const VS = { fableT: 191.2, mythosT: 196.0, subT: 213.1 };
const CTA_T = 381.1;

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
      zIndex: 20,
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
      <div style={{ width: "100%", height: "100%", transform: `scale(${scale})`, transformOrigin: "center" }}>
        <Loop durationInFrames={loopFrames}>
          <OffthreadVideo muted src={staticFile(`${EPISODE.assetDir}/broll/${src}.mp4`)} startFrom={Math.round(from * fps)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        </Loop>
      </div>
    </div>
  );
};

const FootageStage: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, beatEnd, t, fps }) => {
  const local = t - beat.t;
  const hSpring = springIn(Math.round(local * fps), fps, 14, 120);
  const subSpring = beat.subT ? springIn(Math.round((t - beat.subT) * fps), fps, 16, 110) : 0;
  return (
    <div style={{ position: "absolute", inset: 0, background: NAVY_2 }}>
      {beat.src ? <Footage src={beat.src} from={beat.from || 0} beatStart={beat.t} beatEnd={beatEnd} t={t} fps={fps} /> : null}
      <div style={{ position: "absolute", inset: 0, background: "linear-gradient(180deg, rgba(11,14,23,0.3) 0%, rgba(11,14,23,0.85) 100%)" }} />
      <div style={{ position: "absolute", left: 60, right: 60, bottom: 80, zIndex: 5 }}>
        {beat.idx ? (
          <div style={{ display: "inline-block", background: AMBER, color: NAVY, padding: "4px 14px", borderRadius: 8, fontSize: 18, fontWeight: 800, marginBottom: 14 }}>
            {beat.idx}
          </div>
        ) : null}
        {beat.headline ? (
          <div
            style={{
              fontSize: 54, fontWeight: 800, color: CREAM, lineHeight: 1.15,
              opacity: hSpring, transform: `translateY(${(1 - hSpring) * 20}px)`,
              textShadow: "0 4px 24px rgba(0,0,0,0.7)",
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
            flex: 1, background: "rgba(242,179,76,0.12)", border: "1.5px solid rgba(242,179,76,0.45)", borderRadius: 20,
            padding: "26px 28px", display: "flex", flexDirection: "column", gap: 16,
            opacity: sRight, transform: `translateY(${(1 - sRight) * 24}px)`,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: 26, fontWeight: 800, color: AMBER }}>{cfg.right.title}</span>
            <span style={{ background: AMBER, color: NAVY, fontSize: 14, fontWeight: 800, padding: "3px 10px", borderRadius: 6 }}>{cfg.right.badge}</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {cfg.right.lines.map((l, i) => (
              <div key={i} style={{ fontSize: 22, fontWeight: 700, color: CREAM, lineHeight: 1.3 }}>✓ {l}</div>
            ))}
          </div>
        </div>
      </div>
      {t >= VS.subT ? (
        <div style={{ background: "rgba(245,241,232,0.08)", border: "1px solid rgba(245,241,232,0.16)", borderRadius: 14, padding: "14px 22px", fontSize: 24, fontWeight: 700, color: MINT, opacity: sSub, transform: `translateY(${(1 - sSub) * 10}px)` }}>
          {cfg.conclusion}
        </div>
      ) : <div style={{ height: 50 }} />}
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
      <span style={{ fontSize: 30 }}>👉</span>
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
export type JevYTNewsV1Props = { durationSec?: number };

export const calculateJevYTNewsV1Metadata: CalculateMetadataFunction<JevYTNewsV1Props> = ({ props }) => {
  const fps = 25;
  const durationSec = props.durationSec || TOTAL_DURATION_SEC;
  return { durationInFrames: Math.ceil(durationSec * fps), fps, width: W, height: H };
};

export const JevYTNewsV1: React.FC<JevYTNewsV1Props> = ({ durationSec = TOTAL_DURATION_SEC }) => {
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
