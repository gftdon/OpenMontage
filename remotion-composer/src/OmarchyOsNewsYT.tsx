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
import { CAPTION_PAGES } from "./omarchyNewsCaptions";
import { WEB_CLIPS, WEB_RECTS, WebRect } from "./omarchyNewsWeb";

// ===========================================================================
// OmarchyOsNewsYT — 16:9 AI-news report (1920x1080@25)
// Format "Youtube-YT-News-Style01-V1": the report subject is a YOUTUBE VIDEO
// (Alex Finn — "Omarchy is the BEST Operating System on Earth").
// The left stage carries clips cut from the source video (museum cards +
// full-bleed footage) picked to match what the presenter says, stock b-roll
// with kinetic Thai headlines, and typography scenes — while one continuous
// avatar morphs between FULL-FRAME and a 9:16 anchor card on the right.
// Timing spine = whisper word timing (omarchyNewsCaptions.ts), never the SRT.
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
const VO_END_SEC = 423.6; // last whisper word end (423.36) + 0.3
const TOTAL_DURATION_SEC = 428.0; // + 4.4 s endcard
const MODE_BLEND_SEC = 0.55;

// ---- Episode config (swap per episode — every on-screen string lives here) --
const EPISODE = {
  assetDir: "omarchyOsNews", // public/<assetDir>/{avatar_source.mp4, broll/, web/}
  brand: "AI OS REPORT",
  dateLabel: "16 ก.ย. 2026",
  page: { domain: "youtube.com", path: "/watch?v=UJKkS4KLVOo" }, // browser chrome URL pill
  officialTag: "SOURCE · ALEX FINN", // tag on `clip` beats
  cta: { lead: "ค้นหาข้อมูลเพิ่มเติมและดาวน์โหลดได้ที่", text: "omarchy.com" },
  endcard: {
    eyebrow: "AI OS REPORT · SEPTEMBER 2026",
    titleA: "OMARCHY OS",
    titleB: "ระบบปฏิบัติการ AI ยุคใหม่",
    sub: "ต้นฉบับ: Alex Finn — Omarchy is the BEST Operating System on Earth",
    cta: "ข้อมูลเพิ่มเติม · omarchy.com",
  },
  summary3Label: "สรุปฟีเจอร์เด่น",
  final4: { title: "สรุป Omarchy OS 4 ข้อ", sub: "ระบบปฏิบัติการ AI ที่ทุกคนใช้ได้ · ไม่ต้องรู้โค้ด" },
  vs: {
    eyebrow: "ความแตกต่างของระบบปฏิบัติการ",
    left: { title: "Windows / Mac", badge: "TRADITIONAL", lines: ["AI เป็นแค่ฟีเจอร์เสริมทีหลัง", "หน้าต่างโปรแกรมซ้อนทับ", "ต้องคลิกจัดการเองหมด"] },
    right: { title: "Omarchy OS", badge: "AI FIRST", lines: ["AI ฝังในแกนกลางระบบ", "จัดวางหน้าจออัตโนมัติ", "สั่งงานด้วยเสียงและข้อความ"] },
    conclusion: "💡 Omarchy = AI ไม่ใช่แค่ส่วนเสริม แต่คือหัวใจของระบบ",
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
// presenter centre in the 1920x1080 source (face midline)
const AV_CX = 940;
const AV_CY = 540;
const S0 = VW / 1100; // capture CSS px -> stage px at zoom 1

// ---- B-roll durations (public/<assetDir>/broll, 1080p25; yt_* = clips cut from the YouTube source) ----
const BROLL_DUR: Record<string, number> = {
  abstract: 30.0,
  ai_network: 30.0,
  brain: 10.0,
  coding: 14.96,
  cyber: 30.0,
  gaming: 24.16,
  office: 14.8,
  shopping: 10.0,
  studio: 8.0,
  typing: 12.16,
  yt_apps: 25.08,
  yt_desktop: 20.08,
  yt_focus: 25.08,
  yt_herder: 30.08,
  yt_hermes: 30.08,
  yt_install: 27.08,
  yt_logo: 17.08,
  yt_tiling: 28.08,
  yt_webapp: 30.08,
  yt_why: 20.08,
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

const BEATS: Beat[] = [
  // ---- Part 1: Intro & What is OS & What is Omarchy -----------------------
  {
    t: 0.0,
    mode: "full",
    lower: {
      title: "Omarchy — ระบบปฏิบัติการที่ใช้ AI เป็นหัวใจหลัก",
      sub: "เปลี่ยนคอมพิวเตอร์ให้มีผู้ช่วยอัจฉริยะในตัว — ยุคใหม่เริ่มแล้ว",
      t: 1.2,
      dur: 8.0,
    },
  },
  {
    t: 11.38,
    mode: "pip",
    media: "broll",
    src: "brain",
    kicker: "สมองของคอมพิวเตอร์",
    headline: "ระบบปฏิบัติการคืออะไร?",
    sub: "โปรแกรมหลักที่ทำให้คอมพิวเตอร์ของเราทำงานได้",
    subT: 14.9,
    stats: [
      { t: 16.12, label: "🧠 สมองคอมพิวเตอร์" },
      { t: 29.95, label: "🪟 Windows" },
      { t: 30.4, label: "🍎 macOS" },
    ],
  },
  { t: 32.88, mode: "full" }, // Pivot: "ทีนี้ Omarchy มันคืออะไร แล้วมันพิเศษยังไง"
  {
    t: 37.06,
    mode: "pip",
    media: "clip",
    src: "yt_why",
    clipFit: "cover",
    kicker: "AI ฝังอยู่ในทุกส่วน",
    headline: "Omarchy — ระบบปฏิบัติการ AI",
    sub: "มี AI หรือปัญญาประดิษฐ์ ฝังอยู่ในทุกส่วนของระบบ",
    subT: 40.2,
    stats: [
      { t: 41.0, big: "AI-First", label: "AI ฝังในทุกส่วนของระบบ", tone: "mint" },
      { t: 48.4, label: "🖱️ ไม่ต้องคลิกเปิดทำเองหมด" },
    ],
  },
  {
    t: 53.72,
    mode: "pip",
    media: "clip",
    src: "yt_herder",
    clipFit: "contain",
    kicker: "ผู้ช่วยส่วนตัวในเครื่อง",
    headline: "เหมือนมีผู้ช่วยอัจฉริยะ",
    sub: "คอยช่วยเราทำงานตลอดเวลา แค่บอกว่าอยากทำอะไร",
    subT: 55.2,
    stats: [
      { t: 58.6, big: "ผู้ช่วย AI", label: "ดูแลงานตลอดเวลา", tone: "mint" },
      { t: 63.8, label: "⚡ จัดการงานให้อัตโนมัติ" },
    ],
  },
  // ---- Part 2: What Omarchy Can Do ----------------------------------------
  { t: 64.4, mode: "full" }, // Pivot: "ทีนี้เรามาดูกันว่า Omarchy ทำอะไรได้บ้างนะคะ"
  {
    t: 68.18,
    mode: "pip",
    media: "broll",
    src: "typing",
    idx: "01",
    kicker: "ฟีเจอร์เด่น 01 · สั่งงานง่าย",
    headline: "สั่งงานด้วยเสียงหรือพิมพ์",
    sub: "ไม่ต้องเปิดโปรแกรมอีเมล แค่บอก AI ช่วยร่างอีเมลขอลา",
    subT: 77.24,
    stats: [
      { t: 70.5, label: "🎙️ สั่งงานด้วยเสียงและข้อความ" },
      { t: 82.7, label: "✉️ ร่างอีเมลขอลาทันที" },
    ],
  },
  {
    t: 87.08,
    mode: "pip",
    media: "clip",
    src: "yt_focus",
    clipFit: "contain",
    idx: "02",
    kicker: "ฟีเจอร์เด่น 02 · จัดการไฟล์",
    headline: "ค้นหาไฟล์ได้ทันที",
    sub: "ไม่ต้องเปิดหาทีละโฟลเดอร์ แค่บอกให้หาไฟล์รายงานเมื่อวาน",
    subT: 98.3,
    stats: [
      { t: 101.3, big: "ค้นหาทันที", label: "ไม่ต้องค้นทีละโฟลเดอร์", tone: "mint" },
    ],
  },
  {
    t: 106.36,
    mode: "pip",
    media: "clip",
    src: "yt_tiling",
    clipFit: "contain",
    idx: "03",
    kicker: "ฟีเจอร์เด่น 03 · Auto Tiling",
    headline: "จัดวางหน้าจออัตโนมัติ",
    sub: "เปิดอีเมล ปฏิทิน เอกสาร พร้อมกันโดยหน้าจอไม่ซ้อนทับ",
    subT: 114.6,
    stats: [
      { t: 109.4, label: "🖥️ เปิดหลายโปรแกรมพร้อมกัน" },
      { t: 112.7, big: "Auto Tiling", label: "หน้าจอแบ่งงานอัตโนมัติ", tone: "mint" },
    ],
  },
  // ---- Part 3: Difference & Linux Base ------------------------------------
  { t: 125.1, mode: "full" }, // Pivot: "แล้ว Omarchy มันแตกต่างจาก Windows หรือ macOS ที่เราใช้กันอยู่ยังไงนะคะ"
  {
    t: 130.94,
    mode: "pip",
    media: "typo",
    typo: "vs",
    src: "abstract",
    kicker: "ความแตกต่างจากระบบเดิม",
  },
  {
    t: 152.4,
    mode: "pip",
    media: "broll",
    src: "cyber",
    kicker: "สร้างบน Linux",
    headline: "สร้างบนรากฐาน Linux",
    sub: "ระบบปฏิบัติการฟรีที่เสถียร ปลอดภัย และเซิร์ฟเวอร์โลกใช้กัน",
    subT: 157.02,
    stats: [
      { t: 163.7, big: "เสถียร ปลอดภัย", label: "ระบบมาตรฐานระดับโลก", tone: "mint" },
      { t: 167.2, label: "🌐 เซิร์ฟเวอร์เว็บไซต์ระดับโลกใช้" },
    ],
  },
  {
    t: 169.92,
    mode: "pip",
    media: "clip",
    src: "yt_install",
    clipFit: "contain",
    kicker: "แก้ปัญหา Linux เดิม",
    headline: "Linux ที่ใครก็ใช้ได้",
    sub: "Omarchy เอา AI มาเป็นตัวกลาง ไม่ต้องมีความรู้เทคนิคเลย",
    subT: 173.84,
    stats: [
      { t: 177.44, big: "AI ตัวกลาง", label: "เชื่อมคนใช้กับระบบ", tone: "mint" },
      { t: 181.0, label: "✨ ใช้งานง่ายไม่ต้องรู้โค้ด" },
    ],
  },
  // ---- Part 4: Benefits for Everyday Users ---------------------------------
  { t: 181.86, mode: "full" }, // Pivot: "ทีนี้มาพูดถึงเรื่องที่หลายคนสงสัยกันนะคะ"
  {
    t: 185.36,
    mode: "pip",
    media: "clip",
    src: "yt_desktop",
    clipFit: "cover",
    idx: "ประโยชน์ 1",
    kicker: "ประโยชน์จริง 01 · ประหยัดเวลา",
    headline: "ประหยัดเวลาการทำงาน",
    sub: "ลดเวลาเปิดโปรแกรม หาไฟล์ จัดหน้าจอ ได้วันละเป็นชั่วโมง",
    subT: 198.52,
    stats: [
      { t: 189.1, label: "⏱️ ประหยัดเวลา" },
      { t: 208.32, big: "เป็นชั่วโมง", label: "ประหยัดเวลาต่อวัน", tone: "mint" },
    ],
  },
  {
    t: 212.8,
    mode: "pip",
    media: "broll",
    src: "shopping",
    idx: "ประโยชน์ 2",
    kicker: "ประโยชน์จริง 02 · ทำงานไวขึ้น",
    headline: "งานขายของออนไลน์",
    sub: "ร้านค้า แชทลูกค้า สต็อกสินค้า บัญชี จัดให้พร้อมทำงานทันที",
    subT: 220.42,
    stats: [
      { t: 220.42, label: "🛍️ หน้าเว็บร้านค้า" },
      { t: 224.0, label: "💬 แชทลูกค้า" },
      { t: 228.64, label: "📊 ตารางสต็อกสินค้า" },
    ],
  },
  {
    t: 230.26,
    mode: "pip",
    media: "clip",
    src: "yt_webapp",
    clipFit: "contain",
    kicker: "สั่งคำเดียวเปิดครบ",
    headline: "เปิดหน้าจอทำงานในคำสั่งเดียว",
    sub: "AI จัดเตรียมทุกอย่างให้พร้อมทำงานในคำสั่งเดียว",
    subT: 235.48,
    stats: [
      { t: 235.48, big: "คำสั่งเดียว", label: "พร้อมเริ่มงานทันที", tone: "mint" },
    ],
  },
  {
    t: 239.24,
    mode: "pip",
    media: "clip",
    src: "yt_apps",
    clipFit: "contain",
    idx: "ประโยชน์ 3",
    kicker: "ประโยชน์จริง 03 · ประหยัดเงิน",
    headline: "ประหยัดค่าใช้จ่าย",
    sub: "สร้างบน Linux ฟรี ไม่กินทรัพยากร ชุบชีวิตคอมพิวเตอร์เก่า",
    subT: 242.0,
    stats: [
      { t: 244.0, big: "ใช้ฟรี 100%", label: "ไม่ต้องซื้อระบบราคาแพง", tone: "mint" },
      { t: 250.0, label: "💻 ชุบชีวิตคอมพิวเตอร์เครื่องเก่า" },
    ],
  },
  // ---- Part 5: Vibe Coding ------------------------------------------------
  { t: 256.54, mode: "full" }, // Pivot: "ทีนี้มาพูดถึงเรื่องที่น่าสนใจอีกเรื่องนะคะ"
  {
    t: 259.16,
    mode: "pip",
    media: "broll",
    src: "coding",
    kicker: "เทรนด์ใหม่ · Vibe Coding",
    headline: "Vibe Coding คืออะไร?",
    sub: "เขียนโปรแกรมโดยไม่ต้องรู้ภาษาโค้ด แค่บอก AI สิ่งที่อยากได้",
    subT: 263.58,
    stats: [
      { t: 263.58, big: "Vibe Coding", label: "เขียนโค้ดด้วยภาษาคน", tone: "mint" },
      { t: 267.54, label: "✨ แค่บอกความต้องการ" },
    ],
  },
  {
    t: 272.92,
    mode: "pip",
    media: "clip",
    src: "yt_hermes",
    clipFit: "contain",
    kicker: "Omarchy รองรับ Vibe Coding",
    headline: "สร้างเว็บไซต์ได้ในพริบตา",
    sub: "อยากได้เว็บขายเสื้อผ้า สีชมพู มีตะกร้าและระบบชำระเงิน",
    subT: 278.58,
    stats: [
      { t: 284.18, label: "🛒 มีตะกร้าและระบบชำระเงิน" },
    ],
  },
  {
    t: 284.18,
    mode: "pip",
    media: "broll",
    src: "ai_network",
    kicker: "AI สร้างให้ทั้งหมด",
    headline: "สร้างเว็บได้ไม่ต้องจ้างโปรแกรมเมอร์",
    sub: "ประหยัดค่าใช้จ่ายหลักหมื่นหลักแสน AI สร้างให้ได้เลย",
    subT: 285.0,
    stats: [
      { t: 285.0, big: "ไม่ต้องจ้าง", label: "ประหยัดงบก้อนใหญ่", tone: "mint" },
    ],
  },
  {
    t: 294.36,
    mode: "pip",
    media: "broll",
    src: "cyber",
    kicker: "เปลี่ยนโลกธุรกิจ",
    headline: "เกิดขึ้นแล้ววันนี้",
    sub: "ทุกคนสร้างแอปหรือเว็บไซต์ของตัวเองได้ โดยไม่ต้องเขียนโค้ด",
    subT: 297.44,
    stats: [
      { t: 300.86, label: "🚀 อนาคตมาถึงแล้วบน Omarchy" },
      { t: 308.42, big: "เปลี่ยนโลก", label: "สร้างโอกาสทางธุรกิจใหม่", tone: "mint" },
    ],
  },
  // ---- Part 6: Who is it for ----------------------------------------------
  { t: 310.6, mode: "full" }, // Pivot: "ทีนี้หลายคนอาจจะสงสัยว่า แล้วมันเหมาะกับใครบ้างล่ะ"
  {
    t: 314.58,
    mode: "pip",
    media: "clip",
    src: "yt_why",
    clipFit: "cover",
    kicker: "กลุ่มผู้ใช้งาน",
    headline: "Omarchy เหมาะกับใคร?",
    sub: "คนที่ชอบเทคโนโลยี และคนทำธุรกิจที่อยากใช้ AI ช่วยงานเต็มที่",
    subT: 322.0,
    stats: [
      { t: 325.14, label: "💡 คนชอบเทคโนโลยีใหม่" },
      { t: 329.27, label: "🏢 เจ้าของธุรกิจยุค AI" },
    ],
  },
  {
    t: 336.32,
    mode: "pip",
    media: "broll",
    src: "office",
    kicker: "ผู้ช่วยตลอด 24 ชม.",
    headline: "ผู้ช่วยส่วนตัว 24 ชั่วโมง",
    sub: "ทำงานคนเดียวแต่เหมือนมีทีมงาน ไม่มีวันลา ไม่มีวันหยุด",
    subT: 341.6,
    stats: [
      { t: 345.29, big: "24 ชั่วโมง", label: "ไม่มีวันลา ไม่มีวันหยุด", tone: "mint" },
      { t: 350.0, label: "👥 เหมาะกับทีมเล็ก / ทำงานคนเดียว" },
    ],
  },
  {
    t: 352.98,
    mode: "pip",
    media: "broll",
    src: "abstract",
    kicker: "เตรียมพร้อมรับอนาคต",
    headline: "ก้าวให้ทันการเปลี่ยนแปลง",
    sub: "เริ่มรู้จักระบบที่มี AI เป็นหัวใจวันนี้ เพื่อพร้อมสำหรับอนาคต",
    subT: 356.24,
    stats: [
      { t: 359.94, label: "📈 AI เข้ามาในทุกส่วนชีวิต" },
      { t: 364.25, big: "ไม่ตกเทรนด์", label: "พร้อมรับอนาคต", tone: "mint" },
    ],
  },
  // ---- Part 7: Summary & Wrap Up ------------------------------------------
  { t: 367.9, mode: "full" }, // Pivot: "สรุปง่ายๆ เลยนะคะ"
  {
    t: 369.1,
    mode: "pip",
    media: "typo",
    typo: "final4",
    src: "abstract",
    kicker: "สรุป Omarchy OS 4 ข้อ",
  },
  {
    t: 389.14,
    mode: "pip",
    media: "clip",
    src: "yt_logo",
    clipFit: "cover",
    kicker: "ยุคใหม่ของคอมพิวเตอร์",
    headline: "ผู้ช่วยที่เข้าใจเราแท้จริง",
    sub: "ก้าวแรกของยุคที่คอมพิวเตอร์ทำงานร่วมกับเรา",
    subT: 392.0,
    stats: [
      { t: 396.82, big: "ยุคใหม่", label: "คอมพิวเตอร์ทำงานร่วมกับเรา", tone: "mint" },
    ],
  },
  { t: 401.82, mode: "full" }, // Full frame outro until VO_END_SEC (CTA chip at 405.4)
];

// Typo scene word times
const SUMMARY3 = [
  { t: 369.2, text: "AI ฝังในทุกส่วนของระบบ", icon: "🤖" },
  { t: 374.6, text: "เร็วขึ้น ทำงานได้มากขึ้น", icon: "⚡" },
  { t: 385.6, text: "ไม่ต้องรู้โค้ดก็ทำได้ทุกคน", icon: "✨" },
];
const FINAL4 = [
  { t: 369.2, text: "1 · ระบบปฏิบัติการที่มี AI ฝังในทุกส่วน", icon: "🤖" },
  { t: 374.6, text: "2 · ใช้งานง่ายขึ้น เร็วขึ้น ทำงานได้มากขึ้น", icon: "⚡" },
  { t: 380.0, text: "3 · จัดการไฟล์ อีเมล และสร้างเว็บไซต์", icon: "📂" },
  { t: 385.6, text: "4 · ไม่ต้องเก่งไอที ก็ทำได้ทุกคน", icon: "✨" },
];
const VS = { fableT: 130.94, mythosT: 137.04, subT: 147.88 };
const CTA_T = 405.4;

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
  const src = beat.src || "yt_logo";
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
          <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 24, color: AMBER, marginTop: 4, textShadow: "0 2px 14px rgba(0,0,0,0.6)" }}>
            {beat.sub}
          </div>
        ) : null}
      </div>
      {/* museum-card official tag pill */}
      <div
        style={{
          position: "absolute", right: 24, top: 24, padding: "6px 16px", borderRadius: 10,
          background: "rgba(11,14,23,0.78)", border: "1px solid rgba(245,241,232,0.18)",
          fontFamily: FONT, fontWeight: 800, fontSize: 14, letterSpacing: 2, color: AMBER,
          boxShadow: "0 6px 18px rgba(0,0,0,0.4)", backdropFilter: "blur(8px)",
        }}
      >
        {EPISODE.officialTag}
      </div>
    </div>
  );
};

// ===========================================================================
// Typography scenes (Summary3, Final4, VsCard)
// ===========================================================================
const ChipRow: React.FC<{ items: { t: number; text: string; icon: string }[]; t: number; fps: number; big?: boolean }> = ({ items, t, fps, big }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: big ? 20 : 14, width: "100%", maxWidth: 860 }}>
    {items.map((item, i) => {
      const on = t >= item.t;
      const a = springIn(Math.round((t - item.t) * fps), fps, 16, 120);
      return (
        <div
          key={i}
          style={{
            display: "flex", alignItems: "center", gap: 20, padding: big ? "18px 28px" : "14px 22px",
            borderRadius: 18, background: "rgba(245,241,232,0.07)", border: "1px solid rgba(242,179,76,0.30)",
            boxShadow: "0 10px 30px rgba(0,0,0,0.45)", backdropFilter: "blur(12px)",
            opacity: on ? a : 0, transform: `translateX(${(1 - a) * -24}px)`,
          }}
        >
          <span style={{ fontSize: big ? 42 : 32 }}>{item.icon}</span>
          <span style={{ fontFamily: FONT, fontWeight: 700, fontSize: big ? 32 : 25, color: CREAM, lineHeight: 1.25 }}>{item.text}</span>
        </div>
      );
    })}
  </div>
);

const TypoStage: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, beatEnd, t, fps }) => {
  const local = Math.round((t - beat.t) * fps);
  const a = springIn(local - 2, fps, 16, 120);
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      <Footage src={beat.src || "abstract"} from={beat.from || 0} beatStart={beat.t} beatEnd={beatEnd} t={t} fps={fps} zoom={[1.02, 1.08]} />
      <div style={{ position: "absolute", inset: 0, background: "rgba(11,14,23,0.85)" }} />
      <div style={{ position: "absolute", inset: 0, background: `radial-gradient(circle at 50% 50%, rgba(242,179,76,0.08), transparent 70%)` }} />

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
export type OmarchyOsNewsYTProps = { durationSec?: number };

export const calculateOmarchyOsNewsYTMetadata: CalculateMetadataFunction<OmarchyOsNewsYTProps> = ({ props }) => {
  const fps = 25;
  const durationSec = props.durationSec || TOTAL_DURATION_SEC;
  return { durationInFrames: Math.ceil(durationSec * fps), fps, width: W, height: H };
};

export const OmarchyOsNewsYT: React.FC<OmarchyOsNewsYTProps> = ({ durationSec = TOTAL_DURATION_SEC }) => {
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
