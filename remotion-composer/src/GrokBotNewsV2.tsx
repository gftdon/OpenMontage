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
import { CAPTION_PAGES } from "./grokBotNewsV2Captions";
import { WEB_CLIPS, WEB_RECTS, WebRect } from "./grokBotNewsV2Web";

// ===========================================================================
// GrokBotNewsV2 — 16:9 AI-news report (1920x1080@25)
// Format "Youtube-YT-News-Style01-V2":
// Report subject: YOUTUBE VIDEO ("The NEW Grok Bot is Here (10 MASSIVE updates)")
// Left stage: YouTube cuts in museum cards / full-bleed + fresh stock b-roll + typography scenes
// Right stage: Continuous avatar morphing between full-frame and 9:16 vertical card
// Timing spine: Whisper word-level timestamps + SRT calibrated
// B-roll Freshness: V2 ledger-verified 0 repeats, fresh stock & yt cuts
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
const VO_END_SEC = 261.3;
const TOTAL_DURATION_SEC = 265.7; // + 4.4 s endcard
const MODE_BLEND_SEC = 0.55;

// ---- Episode config (swap per episode — every on-screen string lives here) --
const EPISODE = {
  assetDir: "grokBotNewsV2", // public/<assetDir>/{avatar_source.mp4, broll/, web/}
  brand: "AI TECH NEWS",
  dateLabel: "31 ต.ค. 2026",
  page: { domain: "youtube.com", path: "/watch?v=P_hvEpI0twQ" },
  officialTag: "SOURCE · ROBONUGGETS",
  cta: { lead: "ลองพิมพ์คุยกับ Grok ได้ที่", text: "แอป X (Twitter)" },
  endcard: {
    eyebrow: "AI TECH NEWS · OCTOBER 2026",
    titleA: "Grok Bot Updates",
    titleB: "10 Massive Features",
    sub: "YouTube: Jay E | RoboNuggets · The NEW Grok Bot is Here (10 MASSIVE updates)",
    cta: "กดติดตามเพื่อไม่พลาดทุกข่าวสาร AI",
  },
  summary3Label: "3 จุดเด่นสำคัญของ Grok Bot",
  final4: {
    title: "ยกระดับการทำงานด้วย AI บนแอป X",
    sub: "ผู้ช่วยส่วนตัวอัจฉริยะที่พร้อมดูแลคุณตลอด 24 ชั่วโมง",
  },
  vs: {
    eyebrow: "PERSONALITY MODES",
    conclusion: "เลือกสไตล์คำตอบให้เหมาะกับบริบทการทำงานของคุณ",
    left: {
      title: "NORMAL MODE",
      badge: "สุภาพ · ทางการ",
      lines: [
        "✓ คำตอบสุภาพและตรงไปตรงมา",
        "✓ เหมาะสำหรับใช้ทำงานจริงจัง",
        "✓ ค้นคว้าและสรุปความรู้ชัดเจน",
      ],
    },
    right: {
      title: "FUN MODE",
      badge: "อารมณ์ขัน · เป็นกันเอง",
      lines: [
        "✓ มีลูกเล่น กวนๆ แฝงอารมณ์ขัน",
        "✓ ใช้คำพูดแบบเพื่อนสนิท",
        "✓ คุยเพลิดเพลิน สนุก ไม่น่าเบื่อ",
      ],
    },
  },
};

// ---- Stage geometry (locked) ----------------------------------------------
const W = 1920;
const H = 1080;
const STAGE = { x: 80, y: 100, w: 1210, h: 840, r: 22 };
const CHROME_H = 46;
const VW = STAGE.w;
const VH = STAGE.h - CHROME_H; // 794
const AV = { x: 1362, y: 96, w: 478, h: 850, r: 26 }; // 0.5624 ~ 9:16
const AV_CX = 960;

// ---- B-roll durations (public/<assetDir>/broll, 1080p25) -------------------
const BROLL_DUR: Record<string, number> = {
  ai_assistant_concept: 15.00,
  api_system_integration: 8.00,
  automation_workflow_gear: 30.00,
  chat_modes_abstract: 10.04,
  creative_art_ai: 9.80,
  cyber_security_protect: 30.00,
  fast_digital_speed: 8.00,
  live_news_breaking: 20.00,
  multi_device_sync: 8.00,
  office_coworking_team: 18.48,
  pdf_document_reading: 10.00,
  receipt_accounting_calc: 17.52,
  smart_reasoning_brain: 8.40,
  social_media_app_mobile: 8.80,
  yt_agent_automation: 18.08,
  yt_chat_modes: 18.08,
  yt_context_reasoning: 14.08,
  yt_elon_tweet: 12.08,
  yt_fast_model: 20.08,
  yt_grok_overview: 17.08,
  yt_image_generation: 17.08,
  yt_new_ui_sidebar: 18.08,
  yt_pages_documents: 20.08,
  yt_realtime_x_posts: 15.08,
  yt_stripe_connectors: 18.08,
  yt_vision_camera: 18.08,
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
  file?: string;
  cssH?: number;
  cam?: CamKey[];
  hl?: Highlight[];
  src?: string;
  from?: number;
  headline?: string;
  sub?: string;
  subT?: number;
  idx?: string;
  clipFit?: "cover" | "contain";
  typo?: "summary3" | "vs" | "final4";
  stats?: Stat[];
  lower?: { title: string; sub: string; t?: number; dur?: number };
}

const R = (k: string): WebRect => WEB_RECTS[k] || { x: 230, y: 0, w: 600, h: 40 };

// ---- BEATS (Every footage file appears in AT MOST ONE BEAT) ---------------
const BEATS: Beat[] = [
  // --- INTRO & HOOK (0.00 - 32.68) ---
  {
    t: 0.0,
    mode: "full",
    lower: {
      title: "THE NEW GROK BOT IS HERE",
      sub: "10 MASSIVE UPDATES · AI ASSISTANT ON X",
      t: 1.0,
      dur: 7.0,
    },
  },
  {
    t: 10.88,
    mode: "pip",
    media: "clip",
    src: "yt_elon_tweet",
    clipFit: "contain",
    kicker: "VIRAL ON X",
    headline: "ผู้ช่วย AI ตัวใหม่บนแอป X",
    sub: "Elon Musk เผยเป็นผลิตภัณฑ์ที่เติบโตเร็วที่สุด",
    stats: [
      { t: 11.8, big: "GROK BOT", label: "ผู้ช่วยส่วนตัวบน X", tone: "amber" },
      { t: 15.0, big: "X APP", label: "ในทวิตเตอร์เดิม", tone: "mint" },
    ],
  },
  {
    t: 20.50,
    mode: "pip",
    media: "broll",
    src: "ai_assistant_concept",
    kicker: "PERSONAL ASSISTANT",
    headline: "ช่วยค้นหาข้อมูลและออกไอเดีย",
    sub: "เปรียบเสมือนมีผู้ช่วยส่วนตัวคอยตอบคำถามเวลาคิดงานไม่ออก",
    stats: [
      { t: 21.0, big: "RESEARCH", label: "ค้นหาข้อมูล", tone: "mint" },
      { t: 23.0, big: "IDEATION", label: "ช่วยออกไอเดีย", tone: "amber" },
    ],
  },
  {
    t: 25.38,
    mode: "pip",
    media: "clip",
    src: "yt_grok_overview",
    clipFit: "contain",
    kicker: "10 MASSIVE UPDATES",
    headline: "อัปเดตใหม่ 10 ฟีเจอร์ใหญ่",
    sub: "ออกแบบให้คนทั่วไปใช้งานได้สะดวก โดยไม่ต้องรู้เรื่องคอมพิวเตอร์",
    stats: [
      { t: 26.8, big: "10 UPDATES", label: "อัปเดตใหม่ล่าสุด", tone: "amber" },
      { t: 30.0, big: "EASY TO USE", label: "คนทั่วไปใช้ง่าย", tone: "mint" },
    ],
  },

  // --- UPDATE 1: REASONING (32.68 - 48.04) ---
  {
    t: 32.68,
    mode: "pip",
    media: "broll",
    src: "smart_reasoning_brain",
    kicker: "UPDATE 1 · REASONING",
    headline: "ความฉลาดในการตอบคำถาม",
    sub: "ระบบเวอร์ชันใหม่เข้าใจบริบทและเงื่อนไขได้ละเอียดลึกซึ้งยิ่งขึ้น",
    stats: [
      { t: 33.6, big: "CONTEXT", label: "เข้าใจบริบทละเอียดขึ้น", tone: "mint" },
    ],
  },
  {
    t: 39.40,
    mode: "pip",
    media: "clip",
    src: "yt_context_reasoning",
    clipFit: "contain",
    kicker: "ACCURATE ANSWERS",
    headline: "คำถามยาว เงื่อนไขเยอะ ก็ตรงจุด",
    sub: "จับใจความสำคัญและให้คำตอบได้ตรงเป้าหมายมากกว่าเดิม",
    stats: [
      { t: 40.1, big: "LONG PROMPT", label: "คำถามซับซ้อน", tone: "amber" },
      { t: 44.3, big: "PRECISE", label: "ตอบตรงประเด็น", tone: "mint" },
    ],
  },

  // --- UPDATE 2: REAL-TIME DATA (48.04 - 71.06) ---
  {
    t: 48.04,
    mode: "full",
  },
  {
    t: 56.16,
    mode: "pip",
    media: "clip",
    src: "yt_realtime_x_posts",
    clipFit: "contain",
    kicker: "UPDATE 2 · REAL-TIME DATA",
    headline: "ดึงข้อมูลสดๆ จากโพสต์บน X",
    sub: "เอไอทั่วไปรู้แค่ข้อมูลในอดีต แต่ Grok อ่านโพสต์ใหม่ล่าสุดได้ตลอดเวลา",
    stats: [
      { t: 58.0, big: "REAL-TIME", label: "อ่านโพสต์สดๆ บน X", tone: "mint" },
      { t: 62.5, big: "BREAKING", label: "อัปเดตข่าวสารวันนี้", tone: "amber" },
    ],
  },
  {
    t: 64.16,
    mode: "pip",
    media: "broll",
    src: "live_news_breaking",
    kicker: "INSTANT KNOWLEDGE",
    headline: "พิมพ์ถามปุ๊บ รวบรวมข้อเท็จจริงปั๊บ",
    sub: "ระบบจะสรุปเหตุการณ์ด่วนและข่าวสารวันนี้ให้ฟังทันที",
    stats: [
      { t: 66.8, big: "FACTS", label: "รวบรวมข้อเท็จจริงล่าสุด", tone: "mint" },
    ],
  },

  // --- UPDATE 3: IMAGE GENERATION (71.06 - 93.42) ---
  {
    t: 71.06,
    mode: "pip",
    media: "clip",
    src: "yt_image_generation",
    clipFit: "contain",
    kicker: "UPDATE 3 · IMAGE GEN",
    headline: "สร้างรูปภาพจากข้อความ",
    sub: "เพียงอธิบายสิ่งที่อยากได้ เช่น แมวนั่งกินกาแฟริมหน้าต่างตอนฝนตก",
    stats: [
      { t: 72.9, big: "IMAGE AI", label: "สร้างรูปจากข้อความ", tone: "amber" },
      { t: 79.2, big: "PROMPT", label: "แมวนั่งกินกาแฟริมหน้าต่าง", tone: "mint" },
    ],
  },
  {
    t: 81.52,
    mode: "pip",
    media: "broll",
    src: "creative_art_ai",
    kicker: "STUNNING VISUALS",
    headline: "วาดภาพเสร็จในไม่กี่วินาที",
    sub: "ภาพมีความสมจริง รายละเอียดชัดเจน พร้อมโพสต์ลงโซเชียลทันที",
    stats: [
      { t: 84.6, big: "SECONDS", label: "วาดรูปในไม่กี่วินาที", tone: "mint" },
      { t: 86.8, big: "REALISTIC", label: "ภาพสมจริง คมชัด", tone: "amber" },
    ],
  },

  // --- UPDATE 4: COMPUTER VISION (93.42 - 121.24) ---
  {
    t: 93.42,
    mode: "full",
  },
  {
    t: 99.34,
    mode: "pip",
    media: "clip",
    src: "yt_vision_camera",
    clipFit: "contain",
    kicker: "UPDATE 4 · COMPUTER VISION",
    headline: "ถ่ายรูปส่งเข้าแชทให้ช่วยอ่าน",
    sub: "ส่งรูปเอกสาร ฉลากสินค้า หรือภาษาต่างประเทศ ให้ Grok แปลไทยได้",
    stats: [
      { t: 100.1, big: "VISION", label: "อ่านรูปภาพและเอกสาร", tone: "mint" },
      { t: 107.5, big: "TRANSLATE", label: "แปลภาษาไทยให้ทันที", tone: "amber" },
    ],
  },
  {
    t: 109.66,
    mode: "pip",
    media: "broll",
    src: "receipt_accounting_calc",
    kicker: "SMART RECEIPT SCAN",
    headline: "สรุปยอดเงินจากใบเสร็จยาวๆ",
    sub: "สั่งรวมยอดเงินเฉพาะหมวดหมู่ได้ ไม่ต้องเพ่งอ่านหรือกดเครื่องคิดเลขเอง",
    stats: [
      { t: 110.8, big: "RECEIPTS", label: "อ่านใบเสร็จยาวๆ", tone: "clay" },
      { t: 114.1, big: "AUTO CALC", label: "รวมยอดเงินอัตโนมัติ", tone: "mint" },
    ],
  },

  // --- UPDATE 5: CHAT MODES (121.24 - 147.41) ---
  {
    t: 121.24,
    mode: "pip",
    media: "clip",
    src: "yt_chat_modes",
    clipFit: "contain",
    kicker: "UPDATE 5 · CHAT MODES",
    headline: "เลือกโหมดคุยได้ 2 สไตล์",
    sub: "สลับโหมดตามความต้องการใช้งาน ตอบสุภาพทางการ หรืออารมณ์ขัน",
    stats: [
      { t: 125.7, big: "2 MODES", label: "เลือกสไตล์การตอบ", tone: "amber" },
    ],
  },
  {
    t: 127.58,
    mode: "pip",
    media: "typo",
    typo: "vs",
    src: "chat_modes_abstract",
    kicker: "PERSONALITY",
    headline: "โหมดปกติ vs โหมดอารมณ์ขัน",
    sub: "ตอบแบบจริงจังใช้ทำงาน หรือตอบแบบใส่มุกตลกเป็นกันเอง",
  },

  // --- UPDATE 6: DOCUMENT READING (147.41 - 172.80) ---
  {
    t: 147.41,
    mode: "full",
  },
  {
    t: 151.36,
    mode: "pip",
    media: "clip",
    src: "yt_pages_documents",
    clipFit: "contain",
    kicker: "UPDATE 6 · DOCUMENT READING",
    headline: "อัปโหลด PDF หลายสิบหน้า",
    sub: "ระบบอ่านและสรุปใจความสำคัญของแต่ละบทได้ทันที",
    stats: [
      { t: 153.0, big: "PDF UPLOAD", label: "อัปโหลดไฟล์เอกสาร", tone: "amber" },
      { t: 160.0, big: "SUMMARY", label: "สรุปใจความสำคัญแต่ละบท", tone: "mint" },
    ],
  },
  {
    t: 162.28,
    mode: "pip",
    media: "broll",
    src: "pdf_document_reading",
    kicker: "DEEP DOC SEARCH",
    headline: "ถามเจาะจงเฉพาะจุดที่สนใจ",
    sub: "ค้นหาข้อมูลที่ต้องการจากในเอกสารเล่มหนาได้ในเสี้ยววินาที",
    stats: [
      { t: 168.0, big: "INSTANT SEARCH", label: "ค้นหาคำตอบในเอกสารทันที", tone: "mint" },
    ],
  },

  // --- UPDATE 7: LIGHTNING SPEED (172.80 - 191.68) ---
  {
    t: 172.80,
    mode: "full",
  },
  {
    t: 178.76,
    mode: "pip",
    media: "clip",
    src: "yt_fast_model",
    clipFit: "contain",
    kicker: "UPDATE 7 · LIGHTNING SPEED",
    headline: "รุ่นย่อยขนาดเล็ก ตอบกลับไวมาก",
    sub: "สำหรับคำถามทั่วไปในชีวิตประจำวัน พิมพ์ปุ๊บคำตอบขึ้นปั๊บไม่ต้องรอ",
    stats: [
      { t: 180.0, big: "MINI MODEL", label: "รุ่นย่อยขนาดเล็ก", tone: "amber" },
      { t: 188.0, big: "ULTRA FAST", label: "ตอบกลับเร็วมากไม่ต้องรอ", tone: "mint" },
    ],
  },

  // --- UPDATE 8: NEW UI/UX (191.68 - 215.58) ---
  {
    t: 191.68,
    mode: "pip",
    media: "clip",
    src: "yt_new_ui_sidebar",
    clipFit: "contain",
    kicker: "UPDATE 8 · NEW UI/UX",
    headline: "จัดระเบียบหน้าต่างใหม่ เข้าใจง่าย",
    sub: "แถบด้านข้างแยกประวัติการคุยชัดเจน กลับมาคุยต่อเรื่องเดิมได้สบาย",
    stats: [
      { t: 195.0, big: "CLEAN UI", label: "จัดระเบียบหน้าต่างใหม่", tone: "mint" },
      { t: 200.0, big: "SIDEBAR", label: "ประวัติการคุยแยกชัดเจน", tone: "amber" },
    ],
  },
  {
    t: 202.42,
    mode: "pip",
    media: "broll",
    src: "multi_device_sync",
    kicker: "CROSS-DEVICE SYNC",
    headline: "เชื่อมต่อคอมพิวเตอร์และมือถือ",
    sub: "บทสนทนาที่คุยค้างไว้จะซิงค์ตามไปแสดงในทุกอุปกรณ์แบบไร้รอยต่อ",
    stats: [
      { t: 206.0, big: "SYNC", label: "เชื่อมคอมฯ กับมือถือ", tone: "mint" },
      { t: 210.0, big: "ALL DEVICES", label: "แสดงผลทุกอุปกรณ์", tone: "amber" },
    ],
  },

  // --- UPDATE 9: CONNECTORS & API (215.58 - 235.20) ---
  {
    t: 215.58,
    mode: "full",
  },
  {
    t: 221.90,
    mode: "pip",
    media: "clip",
    src: "yt_stripe_connectors",
    clipFit: "contain",
    kicker: "UPDATE 9 · CONNECTORS & API",
    headline: "เปิดเชื่อมต่อไปยังแอปอื่น",
    sub: "นักพัฒนาสามารถนำความฉลาดของ Grok ไปช่วยดูแลบริการลูกค้าในแอปต่างๆ",
    stats: [
      { t: 223.0, big: "INTEGRATION", label: "เชื่อมต่อโปรแกรมอื่น", tone: "amber" },
      { t: 230.0, big: "CUSTOMER CARE", label: "ระบบบริการลูกค้าฉลาดขึ้น", tone: "mint" },
    ],
  },

  // --- UPDATE 10: AUTOMATION (235.20 - 253.82) ---
  {
    t: 235.20,
    mode: "pip",
    media: "clip",
    src: "yt_agent_automation",
    clipFit: "contain",
    kicker: "UPDATE 10 · AUTOMATION",
    headline: "ตั้งค่าให้ทำงานแทนเราอัตโนมัติ",
    sub: "วางขั้นตอนให้ช่วยติดตามข่าวที่สนใจ สรุปเนื้อหาสำคัญส่งให้อ่านทุกเช้า",
    stats: [
      { t: 236.0, big: "AUTOMATION", label: "ทำงานแทนเราอัตโนมัติ", tone: "mint" },
      { t: 242.0, big: "DAILY BRIEF", label: "สรุปข่าวส่งทุกเช้า", tone: "amber" },
    ],
  },
  {
    t: 244.56,
    mode: "pip",
    media: "typo",
    typo: "summary3",
    src: "automation_workflow_gear",
    kicker: "KEY ADVANTAGES",
    headline: "3 จุดเด่นสำคัญของ Grok Bot",
    sub: "สรุปภาพรวมผู้ช่วย AI ยุคใหม่ที่ช่วยลดขั้นตอนการทำงานซ้ำๆ",
  },

  // --- CLOSING & CTA (253.82 - 261.30) ---
  {
    t: 253.82,
    mode: "full",
  },
];

// Typo scene word times
const SUMMARY3 = [
  { t: 245.0, text: "1 · ดึงข้อมูลสดใหม่จาก X แบบ Real-time", icon: "🌐" },
  { t: 247.5, text: "2 · วิเคราะห์เอกสาร สรุปข่าว และรูปภาพ", icon: "📄" },
  { t: 250.5, text: "3 · วางขั้นตอนทำงานแทนเราอัตโนมัติ", icon: "⚡" },
];

const FINAL4 = [
  { t: 245.0, text: "1 · ความฉลาดและบริบทที่แม่นยำขึ้น", icon: "🧠" },
  { t: 247.0, text: "2 · สร้างภาพและอ่านเอกสารครบวงจร", icon: "🎨" },
  { t: 249.0, text: "3 · โหมดคุยหลากหลายและทำงานไว", icon: "⚡" },
  { t: 251.0, text: "4 · เชื่อมต่อแอปและทำงานอัตโนมัติ", icon: "🚀" },
];

const VS = { fableT: 127.8, mythosT: 137.5, subT: 145.0 };
const CTA_T = 255.0;

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

// ---- Sub-components -------------------------------------------------------

const BrowserChrome: React.FC = () => (
  <div
    style={{
      height: CHROME_H,
      background: "linear-gradient(180deg, #1B2134, #141928)",
      borderBottom: "1px solid rgba(245,241,232,0.08)",
      display: "flex",
      alignItems: "center",
      padding: "0 18px",
      gap: 14,
      boxSizing: "border-box",
      zIndex: 2,
      position: "relative",
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
        maxWidth: 520,
        height: 28,
        borderRadius: 7,
        background: "rgba(11,14,23,0.55)",
        border: "1px solid rgba(245,241,232,0.08)",
        display: "flex",
        alignItems: "center",
        padding: "0 12px",
        gap: 8,
        fontFamily: MONO,
        fontSize: 12.5,
        color: CREAM_DIM,
      }}
    >
      <span style={{ color: AMBER, fontSize: 11 }}>🔒</span>
      <span style={{ color: CREAM, fontWeight: 600 }}>{EPISODE.page.domain}</span>
      <span style={{ color: "rgba(245,241,232,0.4)" }}>{EPISODE.page.path}</span>
    </div>
  </div>
);

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

const TopBar: React.FC<{ kicker?: string }> = ({ kicker }) => (
  <div
    style={{
      position: "absolute",
      left: STAGE.x,
      top: 36,
      width: STAGE.w,
      display: "flex",
      justifyContent: "space-between",
      alignItems: "center",
      zIndex: 30,
    }}
  >
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <div
        style={{
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: AMBER,
          boxShadow: `0 0 12px ${AMBER}`,
        }}
      />
      <span
        style={{
          fontFamily: FONT,
          fontWeight: 800,
          fontSize: 16,
          letterSpacing: 2,
          color: CREAM,
        }}
      >
        {EPISODE.brand}
      </span>
      <span style={{ color: "rgba(245,241,232,0.25)", fontSize: 14 }}>•</span>
      <span
        style={{
          fontFamily: MONO,
          fontSize: 13,
          color: CREAM_DIM,
          letterSpacing: 0.5,
        }}
      >
        {EPISODE.dateLabel}
      </span>
    </div>
    {kicker ? (
      <div
        style={{
          background: "rgba(242,179,76,0.12)",
          border: `1px solid rgba(242,179,76,0.35)`,
          padding: "4px 14px",
          borderRadius: 20,
          fontFamily: FONT,
          fontWeight: 700,
          fontSize: 13,
          letterSpacing: 1.5,
          color: AMBER,
        }}
      >
        {kicker}
      </div>
    ) : null}
  </div>
);

const StatChip: React.FC<{ stat: Stat; idx: number; fps: number; t: number }> = ({ stat, idx, fps, t }) => {
  const localFrame = Math.max(0, Math.round((t - stat.t) * fps));
  const s = springIn(localFrame, fps, 14, 160);
  const color = tone(stat.tone);
  return (
    <div
      style={{
        transform: `scale(${s}) translateY(${(1 - s) * 20}px)`,
        opacity: interpolate(s, [0, 0.4, 1], [0, 1, 1]),
        background: "rgba(11,14,23,0.88)",
        backdropFilter: "blur(16px)",
        border: `1px solid rgba(245,241,232,0.14)`,
        borderLeft: `4px solid ${color}`,
        borderRadius: 14,
        padding: "10px 18px",
        display: "flex",
        flexDirection: "column",
        gap: 2,
        boxShadow: "0 12px 32px rgba(0,0,0,0.5)",
      }}
    >
      {stat.big ? (
        <span
          style={{
            fontFamily: FONT,
            fontWeight: 800,
            fontSize: 22,
            color,
            lineHeight: 1.1,
          }}
        >
          {stat.big}
        </span>
      ) : null}
      <span
        style={{
          fontFamily: FONT,
          fontWeight: 600,
          fontSize: 13,
          color: CREAM,
          lineHeight: 1.2,
        }}
      >
        {stat.label}
      </span>
    </div>
  );
};

const LowerThird: React.FC<{ title: string; sub: string; fps: number; localFrame: number }> = ({
  title, sub, fps, localFrame,
}) => {
  const s = springIn(localFrame, fps, 16, 120);
  return (
    <div
      style={{
        position: "absolute",
        left: 80,
        bottom: 80,
        zIndex: 40,
        transform: `translateY(${(1 - s) * 40}px)`,
        opacity: interpolate(s, [0, 0.3, 1], [0, 1, 1]),
      }}
    >
      <div
        style={{
          background: "linear-gradient(135deg, rgba(20,26,43,0.96) 0%, rgba(11,14,23,0.96) 100%)",
          backdropFilter: "blur(20px)",
          border: "1px solid rgba(242,179,76,0.3)",
          borderLeft: `6px solid ${AMBER}`,
          borderRadius: 18,
          padding: "20px 32px",
          maxWidth: 900,
          boxShadow: "0 20px 60px rgba(0,0,0,0.7), 0 0 30px rgba(242,179,76,0.15)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#FF5F56", boxShadow: "0 0 10px #FF5F56" }} />
          <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 13, letterSpacing: 2, color: AMBER }}>
            BREAKING REPORT
          </span>
        </div>
        <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 36, color: CREAM, lineHeight: 1.2, letterSpacing: -0.5 }}>
          {title}
        </div>
        <div style={{ fontFamily: FONT, fontWeight: 500, fontSize: 18, color: CREAM_DIM, marginTop: 4 }}>
          {sub}
        </div>
      </div>
    </div>
  );
};

const CtaChip: React.FC<{ fps: number; localFrame: number }> = ({ fps, localFrame }) => {
  const s = springIn(localFrame, fps, 14, 140);
  return (
    <div
      style={{
        position: "absolute",
        left: "50%",
        bottom: 120,
        transform: `translateX(-50%) scale(${s}) translateY(${(1 - s) * 20}px)`,
        opacity: interpolate(s, [0, 0.3, 1], [0, 1, 1]),
        zIndex: 40,
        background: "rgba(11,14,23,0.92)",
        backdropFilter: "blur(20px)",
        border: `2px solid ${AMBER}`,
        borderRadius: 40,
        padding: "14px 32px",
        display: "flex",
        alignItems: "center",
        gap: 14,
        boxShadow: "0 20px 50px rgba(0,0,0,0.7), 0 0 40px rgba(242,179,76,0.25)",
      }}
    >
      <span style={{ fontFamily: FONT, fontWeight: 600, fontSize: 18, color: CREAM_DIM }}>
        {EPISODE.cta.lead}
      </span>
      <div
        style={{
          background: AMBER,
          color: NAVY,
          fontFamily: FONT,
          fontWeight: 800,
          fontSize: 18,
          padding: "6px 18px",
          borderRadius: 20,
        }}
      >
        {EPISODE.cta.text}
      </div>
    </div>
  );
};

// ---- Caption lane (karaoke locked look) -----------------------------------
const CaptionLane: React.FC<{ t: number }> = ({ t }) => {
  let activePage: (typeof CAPTION_PAGES)[0] | null = null;
  for (const page of CAPTION_PAGES) {
    if (t >= page.start && t < page.end) {
      activePage = page;
      break;
    }
  }
  if (!activePage) return null;

  return (
    <div
      style={{
        position: "absolute",
        left: "50%",
        bottom: 38,
        transform: "translateX(-50%)",
        background: "rgba(11,14,23,0.85)",
        backdropFilter: "blur(14px)",
        border: "1px solid rgba(245,241,232,0.12)",
        borderRadius: 26,
        padding: "8px 24px",
        display: "flex",
        alignItems: "center",
        gap: 6,
        zIndex: 40,
        boxShadow: "0 10px 30px rgba(0,0,0,0.6)",
      }}
    >
      {activePage.words.map((w, i) => {
        const isSpoken = t >= w.s;
        const isCurrent = t >= w.s && t < w.e;
        return (
          <span
            key={i}
            style={{
              fontFamily: FONT,
              fontWeight: 800,
              fontSize: 24,
              color: isCurrent ? GOLD_LIGHT : isSpoken ? GOLD : CREAM,
              textShadow: isCurrent
                ? `0 0 16px ${GOLD}, 0 0 32px ${GOLD}`
                : isSpoken
                ? `0 0 10px rgba(245,158,11,0.5)`
                : "none",
              transition: "color 0.1s, text-shadow 0.1s",
            }}
          >
            {w.w}
          </span>
        );
      })}
    </div>
  );
};

// ---- Left stage: YouTube clip / B-roll / Typography ------------------------
const LeftStage: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({
  beat, beatEnd, t, fps,
}) => {
  if (beat.media === "clip" && beat.src) {
    return (
      <div style={{ position: "absolute", inset: 0, background: NAVY_2, overflow: "hidden" }}>
        {/* Source Video Clip in Museum Card */}
        <div
          style={{
            position: "absolute",
            inset: 32,
            bottom: 120,
            borderRadius: 16,
            overflow: "hidden",
            boxShadow: "0 16px 40px rgba(0,0,0,0.6), 0 0 0 1px rgba(245,241,232,0.1)",
            background: "#000",
          }}
        >
          <Footage
            src={beat.src}
            from={beat.from ?? 0}
            beatStart={beat.t}
            beatEnd={beatEnd}
            fps={fps}
            t={t}
            zoom={beat.clipFit === "cover" ? [1.02, 1.08] : [1.0, 1.0]}
            style={{ width: "100%", height: "100%" }}
          />
          {/* Official Tag pill */}
          <div
            style={{
              position: "absolute",
              top: 14,
              left: 14,
              background: "rgba(11,14,23,0.85)",
              backdropFilter: "blur(10px)",
              border: "1px solid rgba(242,179,76,0.35)",
              padding: "4px 12px",
              borderRadius: 12,
              fontFamily: FONT,
              fontWeight: 700,
              fontSize: 12,
              letterSpacing: 1.5,
              color: AMBER,
              zIndex: 10,
            }}
          >
            {EPISODE.officialTag}
          </div>
        </div>

        {/* Lower headline + sub description */}
        <div
          style={{
            position: "absolute",
            left: 36,
            right: 36,
            bottom: 24,
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          {beat.headline ? (
            <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 26, color: CREAM, lineHeight: 1.2 }}>
              {beat.headline}
            </div>
          ) : null}
          {beat.sub ? (
            <div style={{ fontFamily: FONT, fontWeight: 500, fontSize: 16, color: CREAM_DIM, lineHeight: 1.3 }}>
              {beat.sub}
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  if (beat.media === "broll" && beat.src) {
    return (
      <div style={{ position: "absolute", inset: 0, overflow: "hidden", background: NAVY_2 }}>
        {/* Full-bleed B-roll background */}
        <Footage
          src={beat.src}
          from={beat.from ?? 0}
          beatStart={beat.t}
          beatEnd={beatEnd}
          fps={fps}
          t={t}
          zoom={[1.05, 1.15]}
        />
        {/* Gradient dark overlay */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: "linear-gradient(180deg, rgba(11,14,23,0.4) 0%, rgba(11,14,23,0.85) 75%, rgba(11,14,23,0.96) 100%)",
          }}
        />
        {/* Kinetic Thai Headline + Sub */}
        <div
          style={{
            position: "absolute",
            left: 40,
            right: 40,
            bottom: 40,
            display: "flex",
            flexDirection: "column",
            gap: 8,
            zIndex: 10,
          }}
        >
          {beat.kicker ? (
            <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 14, letterSpacing: 2, color: AMBER }}>
              {beat.kicker}
            </div>
          ) : null}
          {beat.headline ? (
            <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 34, color: CREAM, lineHeight: 1.2, textShadow: "0 4px 16px rgba(0,0,0,0.8)" }}>
              {beat.headline}
            </div>
          ) : null}
          {beat.sub ? (
            <div style={{ fontFamily: FONT, fontWeight: 500, fontSize: 19, color: CREAM_DIM, lineHeight: 1.4, maxWidth: 880 }}>
              {beat.sub}
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  if (beat.media === "typo" && beat.typo) {
    // Typography scenes: summary3 or vs
    if (beat.typo === "vs") {
      const cfg = EPISODE.vs;
      return (
        <div style={{ position: "absolute", inset: 0, overflow: "hidden", background: NAVY_2 }}>
          {beat.src ? (
            <>
              <Footage src={beat.src} from={0} beatStart={beat.t} beatEnd={beatEnd} fps={fps} t={t} zoom={[1.02, 1.08]} />
              <div style={{ position: "absolute", inset: 0, background: "rgba(11,14,23,0.88)" }} />
            </>
          ) : null}
          <div style={{ position: "absolute", inset: 36, display: "flex", flexDirection: "column", gap: 20, zIndex: 10 }}>
            <div>
              <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 14, letterSpacing: 2, color: AMBER }}>
                {cfg.eyebrow}
              </div>
              <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 32, color: CREAM, marginTop: 4 }}>
                {beat.headline}
              </div>
            </div>

            {/* Split cards: Left vs Right */}
            <div style={{ display: "flex", gap: 20, flex: 1 }}>
              {/* Left card */}
              <div
                style={{
                  flex: 1,
                  background: "rgba(20,26,43,0.75)",
                  border: "1px solid rgba(245,241,232,0.12)",
                  borderRadius: 18,
                  padding: "24px 28px",
                  display: "flex",
                  flexDirection: "column",
                  gap: 16,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 22, color: CREAM }}>
                    {cfg.left.title}
                  </span>
                  <span style={{ fontFamily: FONT, fontWeight: 700, fontSize: 12, padding: "4px 10px", borderRadius: 8, background: "rgba(217,119,87,0.2)", color: CLAY }}>
                    {cfg.left.badge}
                  </span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {cfg.left.lines.map((l, i) => (
                    <div key={i} style={{ fontFamily: FONT, fontWeight: 500, fontSize: 17, color: CREAM_DIM, lineHeight: 1.3 }}>
                      {l}
                    </div>
                  ))}
                </div>
              </div>

              {/* Right card */}
              <div
                style={{
                  flex: 1,
                  background: "rgba(20,26,43,0.75)",
                  border: `1px solid rgba(242,179,76,0.35)`,
                  borderRadius: 18,
                  padding: "24px 28px",
                  display: "flex",
                  flexDirection: "column",
                  gap: 16,
                  boxShadow: "0 10px 30px rgba(242,179,76,0.08)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 22, color: AMBER }}>
                    {cfg.right.title}
                  </span>
                  <span style={{ fontFamily: FONT, fontWeight: 700, fontSize: 12, padding: "4px 10px", borderRadius: 8, background: "rgba(143,214,180,0.2)", color: MINT }}>
                    {cfg.right.badge}
                  </span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {cfg.right.lines.map((l, i) => (
                    <div key={i} style={{ fontFamily: FONT, fontWeight: 500, fontSize: 17, color: CREAM, lineHeight: 1.3 }}>
                      {l}
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div style={{ fontFamily: FONT, fontWeight: 600, fontSize: 16, color: MINT }}>
              {cfg.conclusion}
            </div>
          </div>
        </div>
      );
    }

    if (beat.typo === "summary3") {
      return (
        <div style={{ position: "absolute", inset: 0, overflow: "hidden", background: NAVY_2 }}>
          {beat.src ? (
            <>
              <Footage src={beat.src} from={0} beatStart={beat.t} beatEnd={beatEnd} fps={fps} t={t} zoom={[1.02, 1.08]} />
              <div style={{ position: "absolute", inset: 0, background: "rgba(11,14,23,0.88)" }} />
            </>
          ) : null}
          <div style={{ position: "absolute", inset: 40, display: "flex", flexDirection: "column", gap: 24, zIndex: 10 }}>
            <div>
              <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 14, letterSpacing: 2, color: AMBER }}>
                {beat.kicker || "SUMMARY"}
              </div>
              <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 34, color: CREAM, marginTop: 4 }}>
                {EPISODE.summary3Label}
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 18, marginTop: 8 }}>
              {SUMMARY3.map((item, idx) => {
                const isRevealed = t >= item.t;
                const localF = Math.max(0, Math.round((t - item.t) * fps));
                const s = isRevealed ? springIn(localF, fps, 14, 150) : 0;
                return (
                  <div
                    key={idx}
                    style={{
                      transform: isRevealed ? `scale(${s}) translateX(${(1 - s) * -20}px)` : "scale(0.9)",
                      opacity: isRevealed ? interpolate(s, [0, 0.4, 1], [0, 1, 1]) : 0.25,
                      background: isRevealed ? "rgba(20,26,43,0.85)" : "rgba(20,26,43,0.3)",
                      backdropFilter: "blur(16px)",
                      border: `1px solid ${isRevealed ? "rgba(242,179,76,0.4)" : "rgba(245,241,232,0.06)"}`,
                      borderLeft: `5px solid ${isRevealed ? AMBER : "rgba(245,241,232,0.2)"}`,
                      borderRadius: 16,
                      padding: "18px 24px",
                      display: "flex",
                      alignItems: "center",
                      gap: 16,
                      boxShadow: isRevealed ? "0 10px 30px rgba(0,0,0,0.5)" : "none",
                    }}
                  >
                    <span style={{ fontSize: 26 }}>{item.icon}</span>
                    <span style={{ fontFamily: FONT, fontWeight: 700, fontSize: 22, color: isRevealed ? CREAM : CREAM_DIM }}>
                      {item.text}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      );
    }
  }

  return <div style={{ position: "absolute", inset: 0, background: NAVY_2 }} />;
};

// ---- Endcard --------------------------------------------------------------
const EndCard: React.FC = () => {
  const cfg = EPISODE.endcard;
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        background: NAVY,
        zIndex: 50,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 20,
      }}
    >
      <div
        style={{
          fontFamily: FONT,
          fontWeight: 800,
          fontSize: 16,
          letterSpacing: 3,
          color: AMBER,
        }}
      >
        {cfg.eyebrow}
      </div>
      <div style={{ textAlign: "center" }}>
        <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 64, color: CREAM, lineHeight: 1.1 }}>
          {cfg.titleA}
        </div>
        <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 48, color: AMBER, lineHeight: 1.2 }}>
          {cfg.titleB}
        </div>
      </div>
      <div style={{ fontFamily: FONT, fontWeight: 500, fontSize: 20, color: CREAM_DIM, marginTop: 8 }}>
        {cfg.sub}
      </div>
      <div
        style={{
          background: AMBER,
          color: NAVY,
          fontFamily: FONT,
          fontWeight: 800,
          fontSize: 24,
          padding: "14px 36px",
          borderRadius: 30,
          boxShadow: "0 10px 40px rgba(242,179,76,0.45)",
          marginTop: 14,
        }}
      >
        {cfg.cta}
      </div>
    </div>
  );
};

// ===========================================================================
// MAIN COMPOSITION
// ===========================================================================

export type GrokBotNewsV2Props = {
  durationSec?: number;
};

export const calculateGrokBotNewsV2Metadata: CalculateMetadataFunction<GrokBotNewsV2Props> = async () => ({
  durationInFrames: Math.ceil(TOTAL_DURATION_SEC * 25),
  fps: 25,
  width: W,
  height: H,
});

export const GrokBotNewsV2: React.FC<GrokBotNewsV2Props> = () => {
  useThaiFonts();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  // Active beat
  let curIdx = 0;
  for (let i = 0; i < BEATS.length; i++) {
    if (t >= BEATS[i].t) curIdx = i; else break;
  }
  const curBeat = BEATS[curIdx];
  const nextBeat = BEATS[curIdx + 1];
  const prevBeat = curIdx > 0 ? BEATS[curIdx - 1] : undefined;
  const beatEnd = nextBeat ? nextBeat.t : VO_END_SEC;

  // PIP morph
  const p = pipProgress(t);

  // Avatar card geometry
  const card = {
    x: interpolate(p, [0, 1], [0, AV.x]),
    y: interpolate(p, [0, 1], [0, AV.y]),
    w: interpolate(p, [0, 1], [W, AV.w]),
    h: interpolate(p, [0, 1], [H, AV.h]),
    r: interpolate(p, [0, 1], [0, AV.r]),
  };

  const scale = card.h / H;
  const innerLeft = -(AV_CX - card.w / scale / 2) * scale;

  // Stage fade/slide
  const stageOpacity = interpolate(p, [0, 0.4], [0, 1], { extrapolateRight: "clamp" });
  const stageSlide = interpolate(p, [0, 1], [-40, 0]);

  // Crossfade between beats
  const localT = t - curBeat.t;
  const crossfade = clamp01(localT / 0.35);

  // Lower third & CTA
  const showLower = curBeat.lower && t >= (curBeat.lower.t ?? curBeat.t) && t < (curBeat.lower.t ?? curBeat.t) + (curBeat.lower.dur ?? 6);
  const showCta = t >= CTA_T && t < VO_END_SEC && curBeat.mode === "full";

  // Endcard
  const showEnd = t >= VO_END_SEC;

  return (
    <div style={{ width: W, height: H, background: NAVY, position: "relative", overflow: "hidden" }}>
      {/* Background dot grid + subtle ambient glow */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage: "radial-gradient(rgba(245,241,232,0.06) 1px, transparent 1px)",
          backgroundSize: "28px 28px",
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 900,
          height: 900,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(242,179,76,0.08) 0%, transparent 70%)",
          left: -200,
          top: -200,
          pointerEvents: "none",
        }}
      />

      {/* Top bar (visible in pip mode) */}
      <div style={{ opacity: stageOpacity, transition: "opacity 0.2s" }}>
        <TopBar kicker={curBeat.kicker} />
      </div>

      {/* LEFT STAGE */}
      <div
        style={{
          position: "absolute",
          left: STAGE.x,
          top: STAGE.y,
          width: STAGE.w,
          height: STAGE.h,
          borderRadius: STAGE.r,
          overflow: "hidden",
          boxShadow: "0 20px 60px rgba(0,0,0,0.65), 0 0 0 1px rgba(245,241,232,0.08)",
          opacity: stageOpacity,
          transform: `translateX(${stageSlide}px)`,
          zIndex: 10,
        }}
      >
        <BrowserChrome />
        <div style={{ position: "absolute", left: 0, top: CHROME_H, width: VW, height: VH }}>
          {prevBeat && crossfade < 1 && prevBeat.mode === "pip" && prevBeat.media && prevBeat.media !== "none" ? (
            <div style={{ position: "absolute", inset: 0, opacity: 1 - crossfade }}>
              <LeftStage beat={prevBeat} beatEnd={curBeat.t} t={t} fps={fps} />
            </div>
          ) : null}
          {curBeat.mode === "pip" && curBeat.media && curBeat.media !== "none" ? (
            <div style={{ position: "absolute", inset: 0, opacity: crossfade }}>
              <LeftStage beat={curBeat} beatEnd={beatEnd} t={t} fps={fps} />
            </div>
          ) : null}
        </div>
      </div>

      {/* Active Stat Chips (stage bottom-left) */}
      {curBeat.stats && curBeat.stats.length > 0 && curBeat.mode === "pip" ? (
        <div
          style={{
            position: "absolute",
            left: STAGE.x + 36,
            bottom: H - (STAGE.y + STAGE.h) + 26,
            display: "flex",
            gap: 14,
            zIndex: 25,
            opacity: stageOpacity,
          }}
        >
          {curBeat.stats.map((st, i) => (t >= st.t ? <StatChip key={i} stat={st} idx={i} fps={fps} t={t} /> : null))}
        </div>
      ) : null}

      {/* RIGHT STAGE: CONTINUOUS AVATAR (morphs full <-> 9:16 card) */}
      <div
        style={{
          position: "absolute",
          left: card.x,
          top: card.y,
          width: card.w,
          height: card.h,
          borderRadius: card.r,
          overflow: "hidden",
          zIndex: 20,
          boxShadow: p > 0.05 ? `0 20px 60px rgba(0,0,0,0.65), 0 0 0 2px rgba(245,241,232,0.14), 0 0 30px rgba(242,179,76,${0.25 * p})` : "none",
        }}
      >
        <div
          style={{
            position: "absolute",
            left: p > 0.01 ? innerLeft : 0,
            top: 0,
            width: W,
            height: H,
            transform: `scale(${scale})`,
            transformOrigin: "0 0",
          }}
        >
          <OffthreadVideo
            src={staticFile(`${EPISODE.assetDir}/avatar_source.mp4`)}
            style={{ width: W, height: H, objectFit: "cover" }}
          />
        </div>
      </div>

      {/* Overlays */}
      {showLower && curBeat.lower ? (
        <LowerThird
          title={curBeat.lower.title}
          sub={curBeat.lower.sub}
          fps={fps}
          localFrame={Math.round((t - (curBeat.lower.t ?? curBeat.t)) * fps)}
        />
      ) : null}

      {showCta ? <CtaChip fps={fps} localFrame={Math.round((t - CTA_T) * fps)} /> : null}

      {/* Karaoke caption lane */}
      {!showEnd ? <CaptionLane t={t} /> : null}

      {/* Endcard */}
      {showEnd ? <EndCard /> : null}
    </div>
  );
};
