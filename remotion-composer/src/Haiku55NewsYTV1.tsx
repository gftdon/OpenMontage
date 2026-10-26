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
import { CAPTION_PAGES } from "./haiku55NewsCaptions";
import { WEB_CLIPS, WEB_RECTS, WebRect } from "./haiku55NewsWeb";

// ===========================================================================
// Haiku55NewsYTV1 — 16:9 AI-news report (1920x1080@25)
// Format "Youtube-YT-News-Style01-V1": the report subject is a YOUTUBE VIDEO
// (Theo - t3.gg — "finally a good small model"), not a web page.
// The left stage carries clips cut from the source video (museum cards +
// full-bleed footage) picked to match what the presenter says, stock b-roll
// with kinetic Thai headlines, and typography scenes — while one continuous
// avatar morphs between FULL-FRAME and a 9:16 anchor card on the right.
// Timing spine = whisper word timing (haiku55NewsCaptions.ts), never the SRT.
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
const VO_END_SEC = 610.12; // last whisper word end (609.82) + 0.3
const TOTAL_DURATION_SEC = 614.52; // + 4.4 s endcard
const MODE_BLEND_SEC = 0.55;

// ---- Episode config (swap per episode — every on-screen string lives here) --
const EPISODE = {
  assetDir: "haiku55-news", // public/<assetDir>/{avatar_source.mp4, broll/, web/}
  brand: "AI TECH NEWS",
  dateLabel: "9 ต.ค. 2026",
  page: { domain: "youtube.com", path: "/watch?v=38_6C0dkKmU" }, // browser chrome URL pill
  officialTag: "SOURCE · THEO - T3.GG", // tag on `clip` beats
  cta: { lead: "อ่านข้อมูลและทดลอง Claude 3.5 Haiku ได้ที่", text: "anthropic.com" },
  endcard: {
    eyebrow: "AI TECH NEWS · OCTOBER 2026",
    titleA: "CLAUDE 3.5 HAIKU",
    titleB: "เล็ก · ไวปานสายฟ้า · ประหยัด 75%",
    sub: "ต้นฉบับ: Theo - t3․gg — finally a good small model",
    cta: "ข้อมูลเพิ่มเติม · anthropic.com",
  },
  summary3Label: "3 ข้อที่ทุกคนใฝ่ฝันจาก AI",
  final4: { title: "สรุปประเด็นสำคัญ 4 ข้อ", sub: "Claude 3.5 Haiku · โมเดลจิ๋วที่ฉลาดเทียบเท่าเรือธง" },
  vs: {
    eyebrow: "แนวทางการเลือกใช้งาน AI ให้เหมาะกับงาน",
    left: {
      title: "Claude Sonnet (ตัวท็อป)",
      badge: "COMPLEX 10%",
      lines: [
        "งานซับซ้อนระดับสูง",
        "วางแผนกลยุทธ์ธุรกิจองค์กร",
        "ร่างสัญญากฎหมายห้ามพลาด",
        "งานวิจัยลึกซึ้งขั้นสูง",
      ],
    },
    right: {
      title: "Claude Haiku (ตัวเล็ก)",
      badge: "EVERYDAY 90%",
      lines: [
        "งาน 90% ในแต่ละวัน",
        "ตอบแชทลูกค้าทันที (< 1s)",
        "สรุปเอกสาร คัดแยกข้อมูล",
        "แปลภาษา & ช่วยเขียนโค้ด",
      ],
    },
    conclusion: "💡 เลือกโมเดลให้ตรงงาน: ประหยัดเงิน 70-80% และงานเสร็จไวกว่าเดิม",
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
  abstract: 30.00,
  ai_network: 30.00,
  brain: 10.00,
  chat_ai: 19.48,
  city_night: 22.36,
  coding: 14.96,
  cyber: 30.00,
  datacenter: 9.12,
  dna: 8.32,
  handshake: 11.48,
  office: 14.80,
  server_lights: 23.52,
  shopping: 10.00,
  trading: 8.00,
  typing: 12.16,
  warehouse: 20.44,
  // YouTube source clips (Theo - t3.gg — 38_6C0dkKmU)
  yt_announcement: 26.08,
  yt_tweet_rage: 26.08,
  yt_pricing_table: 40.08,
  yt_tweet_100k: 22.08,
  yt_benchmarks: 37.08,
  yt_pareto: 36.08,
  yt_sonnet_vs_haiku: 20.08,
  yt_egg_subagents: 24.08,
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
  // ---- Part 1: Intro & What is Claude Haiku --------------------------------
  // L1-6 (0.00 - 11.80) Cold open (FULL FRAME)
  {
    t: 0.0,
    mode: "full",
    lower: {
      title: "CLAUDE 3.5 HAIKU: เล็ก เร็ว ฉลาด",
      sub: "Anthropic เปิดตัวโมเดลจิ๋วตัวใหม่ — ฉลาดเทียบชั้นโมเดลท็อป แต่ราคาถูกลง 75%",
      t: 1.2,
      dur: 8.5,
    },
  },
  // L7-9 (11.80 - 21.80)
  {
    t: 11.80,
    mode: "pip",
    media: "broll",
    src: "datacenter",
    kicker: "ปัญหาของ AI ในปัจจุบัน",
    headline: "AI ฉลาด แต่มักช้าและแพง",
    sub: "ประมวลผลนาน และค่าบริการสูงจนกระเป๋าสั่น",
    subT: 15.34,
    stats: [{ t: 17.14, big: "แพง & ช้า", label: "ข้อจำกัดเดิมของ AI", tone: "clay" }],
  },
  // L10-13 (21.80 - 32.26)
  {
    t: 21.80,
    mode: "pip",
    media: "broll",
    src: "ai_network",
    kicker: "การปฏิวัติ AI ยุคใหม่",
    headline: "ยุคของ AI ตัวเล็กแต่ฉลาดสุด ๆ",
    sub: "Small Language Models กำลังเข้ามาเปลี่ยนโลก",
    subT: 27.28,
    stats: [{ t: 29.88, big: "Small AI", label: "เล็กแต่ฉลาดรอบด้าน", tone: "mint" }],
  },
  // L14-17 (32.26 - 43.11) Full frame pivot
  { t: 32.26, mode: "full" },
  // L18-24 (43.11 - 59.64)
  {
    t: 43.11,
    mode: "pip",
    media: "broll",
    src: "brain",
    kicker: "เปรียบเทียบ AI ตัวใหญ่",
    headline: "AI ตัวใหญ่ = อาจารย์ศาสตราจารย์",
    sub: "รู้ทุกเรื่อง แต่คิดค่าตัวแพงลิบลิ่ว และต้องรอนาน",
    subT: 50.90,
    stats: [
      { t: 44.42, big: "Professor", label: "โมเดลยักษ์ใหญ่", tone: "amber" },
      { t: 53.54, big: "Costly", label: "ค่าบริการสูง", tone: "clay" },
    ],
  },
  // L25-29 (59.64 - 72.28)
  {
    t: 59.64,
    mode: "pip",
    media: "broll",
    src: "office",
    kicker: "เปรียบเทียบ AI ตัวเล็กในอดีต",
    headline: "AI ตัวเล็กเดิม = น้องฝึกงานวันแรก",
    sub: "ทำงานไว ค่าตัวถูก แต่ตอบผิด ๆ ถูก ๆ จนไม่กล้าใช้",
    subT: 64.50,
    stats: [{ t: 64.50, big: "Fast", label: "ไวแต่หลอนง่าย", tone: "amber" }],
  },
  // L30-36 (72.28 - 94.46)
  {
    t: 72.28,
    mode: "pip",
    media: "clip",
    src: "yt_announcement",
    clipFit: "contain",
    kicker: "Anthropic เปิดตัวโมเดลใหม่",
    headline: "Claude 3.5 Haiku เปิดตัวแล้ว!",
    sub: "โมเดลเล็กที่เร็วที่สุด และฉลาดที่สุดเท่าที่เคยปล่อยมา",
    subT: 81.00,
    stats: [
      { t: 75.82, big: "Anthropic", label: "ผู้พัฒนา Claude", tone: "amber" },
      { t: 81.00, big: "Haiku 3.5", label: "Small & Fast", tone: "mint" },
    ],
  },
  // L37-43 (94.46 - 108.66)
  {
    t: 94.46,
    mode: "pip",
    media: "clip",
    src: "yt_tweet_rage",
    clipFit: "contain",
    kicker: "กระแสตอบรับทั่วโลก",
    headline: "Theo t3.gg & วงการตื่นเต้น",
    sub: "สรุปจุดเด่น ความสามารถ และความคุ้มค่า",
    subT: 98.88,
    stats: [{ t: 98.88, big: "Summary", label: "เจาะลึกความคุ้มค่า", tone: "amber" }],
  },

  // ---- Part 2: Why Small Models Matter -------------------------------------
  // L44-47 (108.66 - 119.30) Full frame pivot
  { t: 108.66, mode: "full" },
  // L48-53 (119.30 - 133.35) Typo summary3 scene
  {
    t: 119.30,
    mode: "pip",
    media: "typo",
    typo: "summary3",
    src: "abstract",
    kicker: "3 สิ่งที่ทุกคนใฝ่ฝันอยากได้จาก AI",
  },
  // L54-65 (133.35 - 164.44)
  {
    t: 133.35,
    mode: "pip",
    media: "broll",
    src: "server_lights",
    kicker: "The AI Trilemma",
    headline: "ในอดีตได้แค่ 2 ใน 3 ข้อเสมอ",
    sub: "ถ้าฉลาดก็ช้าและแพง ส่วนตัวถูกก็มักจะตอบผิด",
    subT: 142.89,
    stats: [{ t: 137.26, big: "2 in 3", label: "ข้อจำกัดคลาสสิก", tone: "clay" }],
  },
  // L66-70 (164.44 - 179.36)
  {
    t: 164.44,
    mode: "pip",
    media: "clip",
    src: "yt_egg_subagents",
    clipFit: "contain",
    kicker: "ตัวอย่างเปรียบเทียบในชีวิตจริง",
    headline: "จ้างเชฟ 5 ดาวมาทอดไข่ดาว?",
    sub: "งานทั่วไปไม่จำเป็นต้องใช้โมเดลแพงที่สุด",
    subT: 172.76,
    stats: [{ t: 169.10, big: "5-Star Chef", label: "สิ้นเปลืองต้นทุน", tone: "clay" }],
  },
  // L71-77 (179.36 - 198.18)
  {
    t: 179.36,
    mode: "pip",
    media: "clip",
    src: "yt_benchmarks",
    clipFit: "contain",
    kicker: "ทลายขีดจำกัดเดิม",
    headline: "ทำลายขีดจำกัดเดิมจนหมดสิ้น",
    sub: "ประมวลผลเร็วกว่าเดิม ใช้พลังงานคอมพิวเตอร์น้อยลง",
    subT: 187.72,
    stats: [
      { t: 184.92, big: "Lightweight", label: "กินพลังงานต่ำ", tone: "mint" },
      { t: 192.74, big: "Instant", label: "ตอบสนองในเสี้ยววิ", tone: "mint" },
    ],
  },
  // L78-85 (198.18 - 219.21)
  {
    t: 198.18,
    mode: "pip",
    media: "broll",
    src: "coding",
    kicker: "ฉลาดเทียบชั้นรุ่นท็อปปีที่แล้ว",
    headline: "ฉลาดเท่าโมเดลท็อปปีที่แล้ว",
    sub: "พนักงานหัวกะทิ ที่วิ่งส่งงานไวเหมือนติดจรวด",
    subT: 207.34,
    stats: [
      { t: 202.02, big: "Top Tier", label: "ความฉลาดระดับเรือธง", tone: "amber" },
      { t: 210.19, big: "Rocket", label: "ส่งงานไวติดจรวด", tone: "mint" },
    ],
  },

  // ---- Part 3: 4 Use Cases in Real Life ------------------------------------
  // L86-91 (219.21 - 233.50) Full frame pivot
  { t: 219.21, mode: "full" },
  // L92-98 (233.50 - 252.14)
  {
    t: 233.50,
    mode: "pip",
    media: "broll",
    src: "chat_ai",
    kicker: "การใช้งานจริง 1: ตอบแชทลูกค้า",
    headline: "1 · ระบบตอบแชทลูกค้าอัตโนมัติ",
    sub: "แก้ปัญหาลูกค้าต้องรอแอดมินตอบเป็นชั่วโมง",
    subT: 241.30,
    stats: [{ t: 238.54, big: "Customer Chat", label: "บริการ 24 ชั่วโมง", tone: "amber" }],
  },
  // L99-106 (252.14 - 274.05)
  {
    t: 252.14,
    mode: "pip",
    media: "broll",
    src: "typing",
    kicker: "ตอบกลับในไม่ถึง 1 วินาที",
    headline: "ตอบกลับในเวลาไม่ถึง 1 วินาที",
    sub: "เข้าใจภาษาพูด เช็คสต็อกสินค้า บริการ 24 ชม.",
    subT: 261.18,
    stats: [
      { t: 255.00, big: "< 1 Sec", label: "ตอบกลับทันใจ", tone: "mint" },
      { t: 269.00, big: "24/7", label: "ดูแลตลอดเวลา", tone: "mint" },
    ],
  },
  // L107-112 (274.05 - 289.68)
  {
    t: 274.05,
    mode: "pip",
    media: "broll",
    src: "office",
    kicker: "การใช้งานจริง 2: สรุปเอกสารยาว",
    headline: "2 · สรุปเอกสารรายงาน & อีเมล",
    sub: "ย่อยรายงาน 30-40 หน้า โดยไม่ต้องอ่านทีละบรรทัด",
    subT: 283.17,
    stats: [{ t: 279.50, big: "30-40 หน้า", label: "อ่านและย่อยทันที", tone: "amber" }],
  },
  // L113-118 (289.68 - 306.12)
  {
    t: 289.68,
    mode: "pip",
    media: "broll",
    src: "handshake",
    kicker: "สรุปประเด็นหลักทันที",
    headline: "ดึงสาระสำคัญ & Action Item",
    sub: "สรุปข้อดี ข้อสังเกต สิ่งที่ต้องทำต่อ เป็นข้อ ๆ",
    subT: 297.56,
    stats: [{ t: 297.56, big: "Actionable", label: "สรุปเข้าใจง่าย", tone: "mint" }],
  },
  // L119-126 (306.12 - 327.24)
  {
    t: 306.12,
    mode: "pip",
    media: "broll",
    src: "city_night",
    kicker: "การใช้งานจริง 3: สร้างคอนเทนต์ & แปลภาษา",
    headline: "3 · เขียนคอนเทนต์ & แปลภาษา",
    sub: "แคปชั่นโพสต์ขายของ จดหมายธุรกิจ แปลภาษาเนียนเป็นธรรมชาติ",
    subT: 316.22,
    stats: [
      { t: 309.46, big: "Content", label: "เขียน & แปลภาษา", tone: "amber" },
      { t: 320.48, big: "Natural", label: "ภาษาไทยสละสลวย", tone: "mint" },
    ],
  },
  // L127-133 (327.24 - 346.22)
  {
    t: 327.24,
    mode: "pip",
    media: "clip",
    src: "yt_benchmarks",
    clipFit: "contain",
    kicker: "การใช้งานจริง 4: ผู้ช่วยเขียนโค้ด",
    headline: "4 · ผู้ช่วยเขียนโปรแกรม & เว็บไซต์",
    sub: "ตรวจสอบจุดพิมพ์ผิด แนะนำวิธีแก้ สร้างระบบเสร็จไวกว่าเดิม",
    subT: 337.50,
    stats: [{ t: 331.96, big: "Coding", label: "FrontierCode 46.4%", tone: "mint" }],
  },

  // ---- Part 4: Token Economics & 100k Threshold ----------------------------
  // L134-140 (346.22 - 357.84) Full frame pivot
  {
    t: 346.22,
    mode: "full",
    lower: {
      title: "เงื่อนไขราคา 100,000 โทเค็น",
      sub: "จุดสังเกตสำคัญที่ผู้เชี่ยวชาญและคนใช้งานจริงต้องรู้",
      t: 349.0,
      dur: 7.0,
    },
  },
  // L141-147 (357.84 - 391.88)
  {
    t: 357.84,
    mode: "pip",
    media: "broll",
    src: "abstract",
    kicker: "Token คืออะไร?",
    headline: "Token = หน่วยวัดปริมาณคำพูด",
    sub: "คล้ายมิเตอร์ค่าน้ำ ค่าไฟ หรือเน็ตมือถือตามการใช้จริง",
    subT: 376.19,
    stats: [{ t: 367.93, big: "Token", label: "หน่วยวัดข้อมูล AI", tone: "amber" }],
  },
  // L148-151 (391.88 - 405.15)
  {
    t: 391.88,
    mode: "pip",
    media: "broll",
    src: "warehouse",
    kicker: "ปริมาณ 100,000 โทเค็น",
    headline: "100,000 โทเค็น = หนังสือ 200-300 หน้า",
    sub: "ส่งประมวลผลพร้อมกันทั้งเล่มในครั้งเดียว",
    subT: 397.20,
    stats: [{ t: 394.18, big: "200-300 หน้า", label: "≈ 100K Tokens", tone: "amber" }],
  },
  // L152-158 (405.15 - 431.04)
  {
    t: 405.15,
    mode: "pip",
    media: "clip",
    src: "yt_pricing_table",
    clipFit: "contain",
    kicker: "ตารางราคา Anthropic",
    headline: "ไม่เกิน 100K = ราคาถูกมาก",
    sub: "Input $0.10 / Output $0.50 ต่อ 1 ล้านโทเค็น",
    subT: 414.15,
    stats: [
      { t: 414.15, big: "$0.10", label: "Input / 1M Tokens", tone: "mint" },
      { t: 426.45, big: "Tier", label: "บันไดราคาเมื่อเกิน 100K", tone: "clay" },
    ],
  },
  // L159-164 (431.04 - 449.60)
  {
    t: 431.04,
    mode: "pip",
    media: "clip",
    src: "yt_tweet_100k",
    clipFit: "contain",
    kicker: "ความคุ้มค่าในการใช้งานจริง",
    headline: "ทำไมยัง 'คุ้มค่าสุด ๆ'?",
    sub: "เพราะงาน 90% ใช้ข้อมูลไม่ถึงเพดาน 100K",
    subT: 440.26,
    stats: [{ t: 437.28, big: "คุ้มค่าสุด ๆ", label: "90% อยู่ในเรทถูกสุด", tone: "mint" }],
  },
  // L165-173 (449.60 - 476.86)
  {
    t: 449.60,
    mode: "pip",
    media: "clip",
    src: "yt_pareto",
    clipFit: "contain",
    kicker: "ประหยัดต้นทุน 70-80%",
    headline: "ประหยัดค่าใช้จ่ายได้ถึง 70-80%",
    sub: "Pareto Frontier — ประสิทธิภาพสูงสุดในราคาต่ำสุด",
    subT: 467.44,
    stats: [
      { t: 467.44, big: "70-80%", label: "ประหยัดค่าใช้จ่าย", tone: "mint" },
      { t: 471.42, big: "Pareto", label: "คุ้มค่าที่สุดในกลุ่ม", tone: "mint" },
    ],
  },

  // ---- Part 5: Future & Decision Guide -------------------------------------
  // L174-179 (476.86 - 494.38) Full frame pivot
  { t: 476.86, mode: "full" },
  // L180-187 (494.38 - 518.30)
  {
    t: 494.38,
    mode: "pip",
    media: "broll",
    src: "shopping",
    kicker: "AI ฝังในแอปทุกวัน",
    headline: "AI ฝังอยู่ในทุกแอปพลิเคชัน",
    sub: "แอปแต่งรูป · สมุดจด · แอปสั่งอาหาร ฉลาดขึ้นหมด",
    subT: 508.50,
    stats: [
      { t: 502.86, big: "Ubiquitous", label: "เข้าถึงทุกคน", tone: "mint" },
      { t: 515.74, big: "Everyday Apps", label: "ฉลาดขึ้นโดยไม่แพง", tone: "amber" },
    ],
  },
  // L188-192 (518.30 - 537.64)
  {
    t: 518.30,
    mode: "pip",
    media: "broll",
    src: "cyber",
    kicker: "ไร้อาการโหลดค้าง",
    headline: "ต้นทุนต่ำ · ตอบสนองทันใจ",
    sub: "ไม่มีอาการโหลดค้าง ตอบกลับทันทีในเสี้ยววินาที",
    subT: 530.53,
    stats: [
      { t: 525.73, big: "Low Cost", label: "ต้นทุนเซิร์ฟเวอร์ต่ำ", tone: "mint" },
      { t: 533.73, big: "Zero Lag", label: "ไม่โหลดค้าง", tone: "mint" },
    ],
  },
  // L193-200 (537.64 - 565.70)
  {
    t: 537.64,
    mode: "pip",
    media: "clip",
    src: "yt_sonnet_vs_haiku",
    clipFit: "contain",
    kicker: "แนวทางเลือกใช้งาน AI",
    headline: "งานซับซ้อนพิเศษ -> Claude Sonnet",
    sub: "วางแผนกลยุทธ์ สัญญากฎหมาย งานวิจัยขั้นลึกซึ้ง",
    subT: 549.30,
    stats: [{ t: 561.24, big: "Sonnet 3.5", label: "สำหรับงานซับซ้อนสูง", tone: "amber" }],
  },
  // L201-208 (565.70 - 591.60) Typo VS scene
  {
    t: 565.70,
    mode: "pip",
    media: "typo",
    typo: "vs",
    src: "abstract",
    kicker: "เปรียบเทียบการเลือกใช้โมเดล",
  },
  // L209-213 (591.60 - 610.12) Outro (FULL FRAME)
  {
    t: 591.60,
    mode: "full",
    lower: {
      title: "กด Like & Subscribe",
      sub: "เพื่อไม่พลาดการอัปเดตเทคโนโลยี AI และโมเดลล่าสุด",
      t: 593.0,
      dur: 6.5,
    },
  },
];

// Typo scene word times
const SUMMARY3 = [
  { t: 125.7, text: "1 · ฉลาดรอบรู้ทุกด้าน", icon: "🧠" },
  { t: 128.2, text: "2 · ตอบกลับไวปานสายฟ้า", icon: "⚡" },
  { t: 131.1, text: "3 · ค่าบริการราคาประหยัด", icon: "💸" },
];
const FINAL4 = [
  { t: 308.2, text: "1 · ตัวจำแนกข้อมูลเร็วจัด", icon: "⚡" },
  { t: 324.8, text: "2 · ปลอดภัย ไม่มั่ว", icon: "🛡️" },
  { t: 325.6, text: "3 · ประหยัดต้นทุน 75%", icon: "💸" },
  { t: 331.7, text: "4 · ทำงานร่วมกับโมเดลท็อป", icon: "🤝" },
];
const VS = { sonnetT: 546.2, haikuT: 565.7, subT: 580.5 };
const CTA_T = 600.5;

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
    </div>
  );
};

// ===========================================================================
// Clip stage (official video in museum card)
// ===========================================================================
const ClipStage: React.FC<{ beat: Beat; t: number; fps: number }> = ({ beat, t, fps }) => {
  const src = beat.src || "yt_announcement";
  const durSec = BROLL_DUR[src] ?? 10;
  const loopDurFrames = Math.max(1, Math.round(durSec * fps));
  const fit = beat.clipFit || "contain";

  return (
    <div style={{ position: "absolute", inset: 0, background: NAVY_2, display: "flex", flexDirection: "column" }}>
      {/* Top bar with official source badge */}
      <div
        style={{
          height: 48, background: "rgba(0,0,0,0.4)", borderBottom: "1px solid rgba(245,241,232,0.10)",
          display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 22px",
          zIndex: 10,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 8, height: 8, borderRadius: 4, background: AMBER, boxShadow: `0 0 10px ${AMBER}` }} />
          <span style={{ fontFamily: FONT, fontSize: 14, fontWeight: 800, color: CREAM, letterSpacing: 1.5 }}>
            {EPISODE.officialTag}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 13, color: AMBER }}>▶</span>
          <span style={{ fontFamily: MONO, fontSize: 12, fontWeight: 700, color: CREAM_DIM }}>RECORDING</span>
        </div>
      </div>

      {/* Video frame */}
      <div style={{ flex: 1, position: "relative", overflow: "hidden", background: fit === "contain" ? "#F5F1E8" : "#000" }}>
        <Loop durationInFrames={loopDurFrames}>
          <OffthreadVideo
            src={staticFile(`${EPISODE.assetDir}/broll/${src}.mp4`)}
            style={{
              position: "absolute", inset: 0, width: "100%", height: "100%",
              objectFit: fit,
            }}
          />
        </Loop>
        {/* Subtle vignette on cover */}
        {fit === "cover" ? (
          <div
            style={{
              position: "absolute", inset: 0,
              boxShadow: "inset 0 0 120px rgba(11,14,23,0.6)",
              pointerEvents: "none",
            }}
          />
        ) : null}
      </div>

      {/* Headline banner across bottom */}
      {beat.headline ? (
        <div
          style={{
            background: "linear-gradient(180deg, rgba(11,14,23,0.85), rgba(11,14,23,0.98))",
            borderTop: "1px solid rgba(245,241,232,0.12)",
            padding: "16px 24px", display: "flex", flexDirection: "column", gap: 4,
          }}
        >
          <div style={{ fontSize: 26, fontWeight: 800, color: CREAM, letterSpacing: 0.2 }}>
            {beat.headline}
          </div>
          {beat.sub ? (
            <div style={{ fontSize: 17, fontWeight: 600, color: CREAM_DIM }}>
              {beat.sub}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};

// ===========================================================================
// Footage stage (full-bleed b-roll with kinetic Thai headline)
// ===========================================================================
const FootageStage: React.FC<{ beat: Beat; t: number; fps: number }> = ({ beat, t, fps }) => {
  const src = beat.src || "abstract";
  const durSec = BROLL_DUR[src] ?? 10;
  const loopDurFrames = Math.max(1, Math.round(durSec * fps));
  const local = t - beat.t;
  const sHead = springIn(Math.round(local * fps), fps, 16, 120);
  const sSub = beat.subT ? springIn(Math.round((t - beat.subT) * fps), fps, 18, 120) : sHead;

  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", background: "#000" }}>
      <Loop durationInFrames={loopDurFrames}>
        <OffthreadVideo
          src={staticFile(`${EPISODE.assetDir}/broll/${src}.mp4`)}
          style={{
            position: "absolute", inset: 0, width: "100%", height: "100%",
            objectFit: "cover",
          }}
        />
      </Loop>
      {/* Gradients to keep typography readable */}
      <div
        style={{
          position: "absolute", inset: 0,
          background: "linear-gradient(180deg, rgba(11,14,23,0.3) 0%, rgba(11,14,23,0.85) 75%, rgba(11,14,23,0.96) 100%)",
        }}
      />

      {/* Kinetic text container */}
      {beat.headline ? (
        <div
          style={{
            position: "absolute", left: 44, right: 44, bottom: 44,
            display: "flex", flexDirection: "column", gap: 10,
          }}
        >
          {beat.idx ? (
            <div
              style={{
                alignSelf: "flex-start",
                background: AMBER, color: NAVY,
                fontSize: 14, fontWeight: 800, padding: "4px 12px", borderRadius: 6,
                letterSpacing: 1.5,
              }}
            >
              {beat.idx}
            </div>
          ) : null}
          <div
            style={{
              fontSize: 40, fontWeight: 800, color: CREAM, lineHeight: 1.18,
              textShadow: "0 4px 20px rgba(0,0,0,0.8)",
              opacity: sHead, transform: `translateY(${(1 - sHead) * 16}px)`,
            }}
          >
            {beat.headline}
          </div>
          {beat.sub ? (
            <div
              style={{
                fontSize: 22, fontWeight: 600, color: CREAM_DIM, lineHeight: 1.3,
                textShadow: "0 2px 12px rgba(0,0,0,0.8)",
                opacity: sSub, transform: `translateY(${(1 - sSub) * 12}px)`,
              }}
            >
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
  const sLeft = t >= VS.sonnetT ? springIn(Math.round((t - VS.sonnetT) * fps), fps, 15, 110) : 0;
  const sRight = t >= VS.haikuT ? springIn(Math.round((t - VS.haikuT) * fps), fps, 15, 110) : 0;
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

// ===========================================================================
// Stage multiplexer
// ===========================================================================
const StageMedia: React.FC<{ beat: Beat; t: number; fps: number }> = ({ beat, t, fps }) => {
  if (beat.media === "web") return <WebStage beat={beat} t={t} fps={fps} />;
  if (beat.media === "clip") return <ClipStage beat={beat} t={t} fps={fps} />;
  if (beat.media === "broll") return <FootageStage beat={beat} t={t} fps={fps} />;
  if (beat.media === "typo") {
    if (beat.typo === "summary3") return <Summary3Stage beat={beat} t={t} fps={fps} />;
    if (beat.typo === "vs") return <VsStage beat={beat} t={t} fps={fps} />;
    if (beat.typo === "final4") return <Final4Stage beat={beat} t={t} fps={fps} />;
  }
  return null;
};

// ===========================================================================
// Overlays (Top bar, Lower third, Chips, Endcard, Progress bar)
// ===========================================================================
const TopBar: React.FC<{ beat: Beat; t: number; p: number }> = ({ beat, t, p }) => {
  const kicker = beat.kicker;
  return (
    <div
      style={{
        position: "absolute", left: 80, top: 24, height: 48,
        display: "flex", alignItems: "center", gap: 14, zIndex: 30,
      }}
    >
      <div
        style={{
          background: NAVY_2, border: "1.5px solid rgba(245,241,232,0.15)",
          borderRadius: 12, padding: "7px 18px", display: "flex", alignItems: "center", gap: 10,
        }}
      >
        <div style={{ width: 9, height: 9, borderRadius: 5, background: CLAY }} />
        <span style={{ fontFamily: FONT, fontSize: 16, fontWeight: 800, color: CREAM, letterSpacing: 1.5 }}>
          {EPISODE.brand}
        </span>
        <span style={{ color: "rgba(245,241,232,0.3)" }}>|</span>
        <span style={{ fontFamily: FONT, fontSize: 14, fontWeight: 600, color: CREAM_DIM }}>
          {EPISODE.dateLabel}
        </span>
      </div>

      {/* Amber kicker appears in pip mode */}
      {kicker && p > 0.1 ? (
        <div
          style={{
            background: "rgba(242,179,76,0.16)", border: `1.5px solid ${AMBER}`,
            borderRadius: 12, padding: "7px 16px",
            fontFamily: FONT, fontSize: 15, fontWeight: 800, color: AMBER,
            opacity: p, transform: `translateX(${(1 - p) * 12}px)`,
          }}
        >
          {kicker}
        </div>
      ) : null}
    </div>
  );
};

const LowerThird: React.FC<{ lower: { title: string; sub: string; t?: number; dur?: number }; t: number; fps: number }> = ({ lower, t, fps }) => {
  const startT = lower.t ?? 0;
  const dur = lower.dur ?? 7;
  if (t < startT || t > startT + dur) return null;
  const local = t - startT;
  const s = springIn(Math.round(local * fps), fps, 15, 120);
  const fadeOut = t > startT + dur - 0.5 ? (startT + dur - t) / 0.5 : 1;

  return (
    <div
      style={{
        position: "absolute", left: 80, bottom: 150, zIndex: 40,
        display: "flex", flexDirection: "column", gap: 8,
        opacity: s * fadeOut, transform: `translateY(${(1 - s) * 20}px)`,
      }}
    >
      <div
        style={{
          alignSelf: "flex-start", background: AMBER, color: NAVY,
          fontSize: 14, fontWeight: 800, padding: "4px 14px", borderRadius: 6, letterSpacing: 2,
        }}
      >
        BREAKING NEWS
      </div>
      <div
        style={{
          background: "rgba(11,14,23,0.85)", borderLeft: `6px solid ${AMBER}`,
          backdropFilter: "blur(12px)", padding: "16px 26px", borderRadius: "0 14px 14px 0",
          boxShadow: "0 10px 40px rgba(0,0,0,0.5)", maxWidth: 900,
        }}
      >
        <div style={{ fontSize: 34, fontWeight: 800, color: CREAM, lineHeight: 1.15 }}>
          {lower.title}
        </div>
        <div style={{ fontSize: 20, fontWeight: 600, color: CREAM_DIM, marginTop: 4 }}>
          {lower.sub}
        </div>
      </div>
    </div>
  );
};

const StatChips: React.FC<{ stats: Stat[]; t: number; fps: number }> = ({ stats, t, fps }) => {
  return (
    <div
      style={{
        position: "absolute", left: STAGE.x + 36, bottom: H - (STAGE.y + STAGE.h) + 26,
        display: "flex", gap: 14, zIndex: 25, flexWrap: "wrap",
      }}
    >
      {stats.map((s, idx) => {
        if (t < s.t) return null;
        const local = t - s.t;
        const sp = springIn(Math.round(local * fps), fps, 14, 130);
        const col = tone(s.tone);
        return (
          <div
            key={idx}
            style={{
              background: "rgba(11,14,23,0.82)", border: `1.5px solid ${col}`,
              backdropFilter: "blur(10px)", borderRadius: 12, padding: "8px 18px",
              display: "flex", alignItems: "center", gap: 10,
              boxShadow: `0 6px 20px rgba(0,0,0,0.4), 0 0 16px ${col}33`,
              opacity: sp, transform: `scale(${interpolate(sp, [0, 1], [0.85, 1])})`,
            }}
          >
            {s.big ? (
              <span style={{ fontSize: 22, fontWeight: 800, color: col }}>{s.big}</span>
            ) : null}
            <span style={{ fontSize: 18, fontWeight: 700, color: CREAM }}>{s.label}</span>
          </div>
        );
      })}
    </div>
  );
};

const CtaChip: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  if (t < CTA_T || t >= VO_END_SEC) return null;
  const sp = springIn(Math.round((t - CTA_T) * fps), fps, 14, 120);
  return (
    <div
      style={{
        position: "absolute", left: 80, bottom: 170, zIndex: 40,
        background: "rgba(11,14,23,0.90)", border: `2px solid ${AMBER}`,
        borderRadius: 16, padding: "14px 26px", display: "flex", alignItems: "center", gap: 16,
        boxShadow: "0 10px 40px rgba(0,0,0,0.6), 0 0 24px rgba(242,179,76,0.3)",
        opacity: sp, transform: `translateY(${(1 - sp) * 20}px)`,
      }}
    >
      <div style={{ width: 12, height: 12, borderRadius: 6, background: AMBER }} />
      <span style={{ fontSize: 22, fontWeight: 700, color: CREAM }}>{EPISODE.cta.lead}</span>
      <span
        style={{
          background: AMBER, color: NAVY, fontSize: 20, fontWeight: 800,
          padding: "4px 14px", borderRadius: 8,
        }}
      >
        {EPISODE.cta.text}
      </span>
    </div>
  );
};

const ProgressBar: React.FC<{ t: number }> = ({ t }) => {
  const p = clamp01(t / VO_END_SEC);
  if (t >= VO_END_SEC) return null;
  return (
    <div style={{ position: "absolute", left: 0, bottom: 0, width: W, height: 4, background: "rgba(245,241,232,0.08)", zIndex: 50 }}>
      <div style={{ width: `${p * 100}%`, height: "100%", background: `linear-gradient(90deg, ${AMBER}, ${MINT})` }} />
    </div>
  );
};

const Endcard: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  if (t < VO_END_SEC) return null;
  const local = t - VO_END_SEC;
  const s = easeOutCubic(local / 0.6);
  const cfg = EPISODE.endcard;

  return (
    <div
      style={{
        position: "absolute", inset: 0, background: NAVY,
        zIndex: 60, display: "flex", flexDirection: "column",
        justifyContent: "center", alignItems: "center", gap: 20,
        opacity: s,
      }}
    >
      {/* Background glow */}
      <div
        style={{
          position: "absolute", width: 600, height: 600, borderRadius: 300,
          background: "radial-gradient(circle, rgba(242,179,76,0.18) 0%, transparent 70%)",
          filter: "blur(60px)", pointerEvents: "none",
        }}
      />
      <div style={{ fontSize: 18, fontWeight: 800, color: AMBER, letterSpacing: 4 }}>
        {cfg.eyebrow}
      </div>
      <div style={{ fontSize: 72, fontWeight: 800, color: CREAM, letterSpacing: 1, textAlign: "center" }}>
        {cfg.titleA}
      </div>
      <div style={{ fontSize: 44, fontWeight: 800, color: AMBER, letterSpacing: 1, textAlign: "center" }}>
        {cfg.titleB}
      </div>
      <div style={{ fontSize: 24, fontWeight: 600, color: CREAM_DIM, marginTop: 10 }}>
        {cfg.sub}
      </div>
      <div
        style={{
          marginTop: 20, background: AMBER, color: NAVY,
          fontSize: 24, fontWeight: 800, padding: "12px 36px", borderRadius: 14,
          boxShadow: "0 8px 30px rgba(242,179,76,0.4)",
        }}
      >
        {cfg.cta}
      </div>
    </div>
  );
};

// ===========================================================================
// Karaoke caption lane (locked Style 1)
// ===========================================================================
const CaptionLane: React.FC<{ t: number }> = ({ t }) => {
  if (t >= VO_END_SEC) return null;
  const page = CAPTION_PAGES.find((p) => t >= p.start && t < p.end);
  if (!page) return null;

  return (
    <div
      style={{
        position: "absolute", left: 0, right: 0, bottom: 26,
        display: "flex", justifyContent: "center", zIndex: 45,
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          background: "rgba(11,14,23,0.85)", border: "1px solid rgba(245,241,232,0.15)",
          borderRadius: 20, padding: "10px 28px", maxWidth: 1500,
          backdropFilter: "blur(12px)", boxShadow: "0 6px 30px rgba(0,0,0,0.6)",
          display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "center",
        }}
      >
        {page.words.map((w, idx) => {
          const active = t >= w.s && t < w.e;
          const past = t >= w.e;
          const col = active ? GOLD : past ? CREAM : "rgba(245,241,232,0.45)";
          return (
            <span
              key={idx}
              style={{
                fontFamily: FONT, fontSize: 34, fontWeight: active ? 800 : 700,
                color: col,
                textShadow: active ? `0 0 14px ${GOLD}` : "none",
                transform: active ? "scale(1.05)" : "none",
                transition: "color 0.1s, transform 0.1s",
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

// ===========================================================================
// Avatar component (morphs between full-frame and right card)
// ===========================================================================
const Avatar: React.FC<{ t: number; p: number }> = ({ t, p }) => {
  const card = {
    x: interpolate(p, [0, 1], [0, AV.x]),
    y: interpolate(p, [0, 1], [0, AV.y]),
    w: interpolate(p, [0, 1], [W, AV.w]),
    h: interpolate(p, [0, 1], [H, AV.h]),
    r: interpolate(p, [0, 1], [0, AV.r]),
  };

  const scale = interpolate(p, [0, 1], [1, AV.h / 1080]);
  const cx = interpolate(p, [0, 1], [960, AV_CX]);
  const cy = interpolate(p, [0, 1], [540, AV_CY]);
  const cropW = card.w / scale;
  const cropH = card.h / scale;
  const innerLeft = -(cx - cropW / 2) * scale;
  const innerTop = -(cy - cropH / 2) * scale;

  return (
    <div
      style={{
        position: "absolute",
        left: card.x, top: card.y, width: card.w, height: card.h,
        borderRadius: card.r,
        overflow: "hidden",
        border: p > 0.05 ? `2px solid rgba(245,241,232,${0.85 * p})` : "none",
        boxShadow: p > 0.05 ? `0 14px 44px rgba(0,0,0,0.65), 0 0 ${26 * p}px rgba(242,179,76,${0.25 * p})` : "none",
        zIndex: 15,
      }}
    >
      <div
        style={{
          position: "absolute",
          left: innerLeft, top: innerTop,
          width: 1920 * scale, height: 1080 * scale,
        }}
      >
        <OffthreadVideo
          src={staticFile(`${EPISODE.assetDir}/avatar_source.mp4`)}
          style={{ width: "100%", height: "100%" }}
        />
      </div>
    </div>
  );
};

// ===========================================================================
// Root Composition
// ===========================================================================
export type Haiku55NewsYTV1Props = Record<string, unknown>;

export const calculateHaiku55NewsYTV1Metadata: CalculateMetadataFunction<Haiku55NewsYTV1Props> = async () => {
  return {
    fps: 25,
    width: 1920,
    height: 1080,
    durationInFrames: Math.round(TOTAL_DURATION_SEC * 25),
  };
};

export const Haiku55NewsYTV1: React.FC<Haiku55NewsYTV1Props> = () => {
  useThaiFonts();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  // Active beat
  let curBeatIdx = 0;
  for (let i = 0; i < BEATS.length; i++) {
    if (t >= BEATS[i].t) curBeatIdx = i; else break;
  }
  const curBeat = BEATS[curBeatIdx];
  const prevBeat = curBeatIdx > 0 ? BEATS[curBeatIdx - 1] : curBeat;
  const p = pipProgress(t);

  // Left stage slide/fade
  const stageOpacity = p;
  const stageSlide = interpolate(p, [0, 1], [-40, 0]);

  // Beat transition crossfade
  const beatLocal = t - curBeat.t;
  const curOpacity = easeOutCubic(beatLocal / 0.35);

  return (
    <div
      style={{
        position: "relative", width: W, height: H, background: NAVY,
        overflow: "hidden", fontFamily: FONT,
      }}
    >
      {/* Background dot grid + subtle ambient glow */}
      <div
        style={{
          position: "absolute", inset: 0,
          backgroundImage: "radial-gradient(rgba(245,241,232,0.06) 1px, transparent 1px)",
          backgroundSize: "28px 28px",
        }}
      />
      <div
        style={{
          position: "absolute", left: "15%", top: "20%", width: 700, height: 700,
          borderRadius: 350, background: "radial-gradient(circle, rgba(242,179,76,0.08) 0%, transparent 70%)",
          filter: "blur(80px)", pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute", right: "10%", bottom: "15%", width: 600, height: 600,
          borderRadius: 300, background: "radial-gradient(circle, rgba(217,119,87,0.06) 0%, transparent 70%)",
          filter: "blur(90px)", pointerEvents: "none",
        }}
      />

      {/* Left Stage (in pip mode) */}
      <div
        style={{
          position: "absolute",
          left: STAGE.x + stageSlide, top: STAGE.y, width: STAGE.w, height: STAGE.h,
          borderRadius: STAGE.r, overflow: "hidden",
          border: "2px solid rgba(245,241,232,0.12)",
          boxShadow: "0 18px 50px rgba(0,0,0,0.6)",
          opacity: stageOpacity,
          zIndex: 10,
        }}
      >
        {/* Previous beat (fading out) */}
        {prevBeat && prevBeat !== curBeat ? (
          <div style={{ position: "absolute", inset: 0 }}>
            <StageMedia beat={prevBeat} t={t} fps={fps} />
          </div>
        ) : null}
        {/* Current beat (fading in) */}
        <div style={{ position: "absolute", inset: 0, opacity: curOpacity }}>
          <StageMedia beat={curBeat} t={t} fps={fps} />
        </div>
      </div>

      {/* Stat chips on stage */}
      {curBeat.stats ? <StatChips stats={curBeat.stats} t={t} fps={fps} /> : null}

      {/* Avatar (Continuous morphing layer) */}
      <Avatar t={t} p={p} />

      {/* Overlays */}
      <TopBar beat={curBeat} t={t} p={p} />
      {curBeat.lower ? <LowerThird lower={curBeat.lower} t={t} fps={fps} /> : null}
      <CtaChip t={t} fps={fps} />
      <CaptionLane t={t} />
      <ProgressBar t={t} />
      <Endcard t={t} fps={fps} />
    </div>
  );
};
