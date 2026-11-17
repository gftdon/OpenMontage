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
import { CAPTION_PAGES } from "./gpt61TerraNewsV2Captions";
import { WEB_CLIPS, WEB_RECTS, WebRect } from "./gpt61TerraNewsWeb";

// ===========================================================================
// Gpt61TerraNewsV2 — 16:9 AI-news report (1920x1080@25)
// Format "Youtube-YT-News-Style01-V2":
// Report subject: YOUTUBE VIDEO ("GPT-6.1 Terra is now in orbit" - OpenAI)
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
const VO_END_SEC = 505.7;
const TOTAL_DURATION_SEC = 510.1; // + 4.4 s endcard
const MODE_BLEND_SEC = 0.55;

// ---- Episode config (swap per episode — every on-screen string lives here) --
const EPISODE = {
  assetDir: "gpt61TerraNewsV2", // public/<assetDir>/{avatar_source.mp4, broll/, web/}
  brand: "AI TECH NEWS",
  dateLabel: "27 ต.ค. 2026",
  page: { domain: "youtube.com", path: "/watch?v=tTuk4pGnT0A" },
  officialTag: "SOURCE · OPENAI",
  cta: { lead: "ติดตามข่าวสาร AI ได้ที่", text: "youtube.com/@fable" },
  endcard: {
    eyebrow: "AI TECH NEWS · OCTOBER 2026",
    titleA: "GPT-6.1 Terra",
    titleB: "Now in Orbit",
    sub: "YouTube: OpenAI · GPT-6.1 Terra is now in orbit",
    cta: "กดติดตามเพื่อไม่พลาดทุกข่าวสาร AI",
  },
  summary3Label: "3 ความสามารถสำคัญของ GPT-6.1 Terra",
  final4: {
    title: "เตรียมตัวสู่ยุค AI Computer Use",
    sub: "เปิดใจ เรียนรู้ และปรับตัวให้พร้อมสำหรับอนาคต",
  },
  vs: {
    eyebrow: "THE NEW PARADIGM",
    conclusion: "เปลี่ยนจากการพิมพ์คุย สู่การลงมือทำงานแทนมนุษย์จริง",
    left: {
      title: "TRADITIONAL CHAT AI",
      badge: "TEXT ONLY · PASSIVE",
      lines: [
        "✗ ต้องคอยก๊อปปี้ข้อมูลไปแปะ",
        "✗ ทำงานข้ามแอปไม่ได้",
        "✗ มนุษย์ต้องคลิกและกรอกเอง",
      ],
    },
    right: {
      title: "GPT-6.1 TERRA",
      badge: "COMPUTER USE · ACTIVE",
      lines: [
        "✓ เข้าใจสิ่งที่อยู่บนหน้าจอคอมพิวเตอร์",
        "✓ สลับแอปและคลิกเมาส์แทนเรา",
        "✓ ปลอดภัย ขอการยืนยันก่อนเสมอ",
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
const AV_CY = 540;
const S0 = VW / 1100;

// ---- B-roll durations (public/<assetDir>/broll, 1080p25) -------------------
const BROLL_DUR: Record<string, number> = {
  ai_computer_vision: 15.0,
  app_ecosystem_network: 11.2,
  business_meeting_colleagues: 15.6,
  coffee_break_relax: 7.96,
  cost_savings_growth: 15.96,
  digital_folder_database: 29.92,
  futuristic_smart_office: 12.0,
  human_ai_collaboration: 13.04,
  invoice_receipt_accounting: 9.88,
  keyboard_copy_paste: 14.16,
  modern_city_day: 25.12,
  multitasking_screens: 16.6,
  natural_text_typing: 11.68,
  office_clock_timelapse: 25.52,
  person_smiling_laptop: 12.04,
  rocket_space_orbit: 20.04,
  security_approval_shield: 10.0,
  spreadsheet_data_finance: 20.08,
  tablet_finger_touch: 20.04,
  tired_computer_worker: 18.64,
  voice_audio_wave: 10.0,
  yt_blender_build: 5.52,
  yt_chatgpt_viewer: 5.52,
  yt_diecast_hand: 3.52,
  yt_earth_zoom: 4.0,
  yt_lisbon_tram: 3.52,
  yt_orbit: 3.0,
  yt_paid_plans: 3.52,
  yt_photo_prompt: 2.52,
  yt_sees_does: 3.52,
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
  // --- PART 1: INTRO & HOOK (0.00 - 101.07) ---
  {
    t: 0.0,
    mode: "full",
    lower: {
      title: "GPT-6.1 TERRA IS IN ORBIT",
      sub: "NEW COMPUTER USE MODEL · FASTER & CHEAPER",
      t: 1.5,
      dur: 7.0,
    },
  },
  {
    t: 4.74,
    mode: "pip",
    media: "broll",
    src: "tired_computer_worker",
    kicker: "WORKDAY REALITY",
    headline: "เหนื่อยล้ากับงานซ้ำซาก",
    sub: "นั่งทำงานหน้าคอมพ์ทั้งวัน คลิกไปคลิกมา",
    stats: [
      { t: 6.0, big: "FULL DAY", label: "ทำงานหน้าคอมพิวเตอร์", tone: "clay" },
    ],
  },
  {
    t: 12.94,
    mode: "pip",
    media: "broll",
    src: "keyboard_copy_paste",
    kicker: "REPETITIVE TASKS",
    headline: "ก๊อปปี้ วาง วนลูปเดิม",
    sub: "เปิดโปรแกรมนั้น สลับโปรแกรมนี้จนปวดหัว ปวดตา",
    stats: [
      { t: 14.4, big: "COPY PASTE", label: "งานสลับหน้าจอเดิมๆ", tone: "clay" },
    ],
  },
  {
    t: 20.32,
    mode: "full",
  },
  {
    t: 21.59,
    mode: "pip",
    media: "broll",
    src: "human_ai_collaboration",
    kicker: "THE DREAM ASSISTANT",
    headline: "ถ้าคุณมีผู้ช่วยส่วนตัว",
    sub: "นั่งมองหน้าจอเดียวกับคุณ สั่งคำเดียวจัดการให้ครบ",
    stats: [
      { t: 22.0, big: "AI ASSISTANT", label: "ผู้ช่วยเคียงข้างคุณ", tone: "mint" },
      { t: 33.0, big: "1 COMMAND", label: "สั่งคำเดียวจัดการเสร็จ", tone: "amber" },
    ],
  },
  {
    t: 40.14,
    mode: "full",
  },
  {
    t: 52.44,
    mode: "pip",
    media: "clip",
    src: "yt_orbit",
    clipFit: "contain",
    kicker: "OFFICIAL LAUNCH",
    headline: "GPT-6.1 Terra is in orbit",
    sub: "OpenAI เปิดตัวโมเดลใหม่สู่สายตาคนทั้งโลก",
    stats: [
      { t: 53.4, big: "GPT-6.1", label: "Terra Model", tone: "amber" },
      { t: 54.9, big: "IN ORBIT", label: "พร้อมใช้งานจริง", tone: "mint" },
    ],
  },
  {
    t: 58.88,
    mode: "pip",
    media: "broll",
    src: "rocket_space_orbit",
    kicker: "WHAT IS IN ORBIT?",
    headline: "ขึ้นสู่วงโคจรการทำงาน",
    sub: "AI รุ่นใหม่ล่าสุดที่พร้อมให้ทุกคนเริ่มใช้งานจริง",
    stats: [
      { t: 65.2, big: "NEW MODEL", label: "ปัญญาประดิษฐ์รุ่นล่าสุด", tone: "amber" },
    ],
  },
  {
    t: 77.20,
    mode: "full",
  },
  {
    t: 83.82,
    mode: "pip",
    media: "clip",
    src: "yt_lisbon_tram",
    clipFit: "contain",
    kicker: "COMPUTER USE",
    headline: "ใช้คอมพิวเตอร์แทนมนุษย์",
    sub: "ไม่ได้แค่พิมพ์คุย แต่ลงมือสั่งการหน้าจอได้จริง",
    stats: [
      { t: 84.5, big: "COMPUTER USE", label: "สั่งการแทนมนุษย์", tone: "mint" },
    ],
  },
  {
    t: 87.52,
    mode: "pip",
    media: "typo",
    typo: "summary3",
    src: "futuristic_smart_office",
    kicker: "HIGHLIGHTS",
    headline: "3 ความสามารถสำคัญของ Terra",
    sub: "สิ่งที่จะเข้ามาเปลี่ยนวิถีชีวิตการทำงานของเรา",
  },
  {
    t: 99.50,
    mode: "full",
  },

  // --- PART 2: VISION & HANDS (101.07 - 202.72) ---
  {
    t: 104.52,
    mode: "pip",
    media: "broll",
    src: "ai_computer_vision",
    kicker: "COMPUTER VISION",
    headline: "AI ที่มี 'ตา' เป็นของตัวเอง",
    sub: "เข้าใจสิ่งที่อยู่บนหน้าจอคอมพิวเตอร์ของเราได้",
    stats: [
      { t: 109.3, big: "VISION", label: "มองเห็นหน้าจอ", tone: "amber" },
    ],
  },
  {
    t: 114.34,
    mode: "pip",
    media: "clip",
    src: "yt_photo_prompt",
    clipFit: "contain",
    kicker: "VISION & INPUT",
    headline: "เข้าใจภาพและคำสั่งบนหน้าจอ",
    sub: "อ่านภาพถ่ายและแปลงเป็นโจทย์ทำงาน 3D อัตโนมัติ",
    stats: [
      { t: 116.0, big: "INPUT", label: "ประมวลผลคำสั่งและรูป", tone: "amber" },
    ],
  },
  {
    t: 120.60,
    mode: "pip",
    media: "broll",
    src: "multitasking_screens",
    kicker: "SEAMLESS WORKFLOW",
    headline: "ไม่ต้องก๊อปปี้แปะอีกต่อไป",
    sub: "Terra มองเห็นหน้าจอเดียวกับเรา เหมือนมีคนมานั่งดูอยู่ข้างๆ",
    stats: [
      { t: 132.0, big: "SAME SCREEN", label: "มองเห็นจอเดียวกัน", tone: "mint" },
    ],
  },
  {
    t: 139.53,
    mode: "pip",
    media: "broll",
    src: "spreadsheet_data_finance",
    kicker: "ELEMENT DETECTION",
    headline: "รู้ปุ่ม ช่องกรอก และตาราง Excel",
    sub: "เข้าใจว่าตัวเลขไหนคืออะไร และรูปภาพที่เปิดอยู่คืออะไร",
    stats: [
      { t: 143.1, big: "UI AWARE", label: "จำแนกองค์ประกอบจอ", tone: "amber" },
    ],
  },
  {
    t: 151.86,
    mode: "full",
  },
  {
    t: 153.66,
    mode: "pip",
    media: "clip",
    src: "yt_blender_build",
    clipFit: "contain",
    kicker: "CROSS-APP EXECUTION",
    headline: "มี 'มือ' ทำงานข้ามแอปพลิเคชัน",
    sub: "ควบคุม Blender สร้างโมเดล 3D ทีละขั้นตอนอัตโนมัติ",
    stats: [
      { t: 157.1, big: "APP ACTIONS", label: "ทำงานข้ามแอปอิสระ", tone: "mint" },
    ],
  },
  {
    t: 161.94,
    mode: "pip",
    media: "clip",
    src: "yt_chatgpt_viewer",
    clipFit: "contain",
    kicker: "CHATGPT WORK",
    headline: "เชื่อมต่อผลงานกลับสู่ระบบ",
    sub: "เปิดดูและหมุนวัตถุ 3D ใน ChatGPT Work ได้ทันที",
    stats: [
      { t: 163.0, big: "CHATGPT WORK", label: "พื้นที่ทำงานใหม่", tone: "amber" },
    ],
  },
  {
    t: 164.88,
    mode: "pip",
    media: "broll",
    src: "invoice_receipt_accounting",
    kicker: "REAL-LIFE EXAMPLE",
    headline: "ตัวอย่าง: บันทึกใบเสร็จเข้าบัญชี",
    sub: "ปกติเราต้องเปิดอีเมล จดเลข สลับหน้าจอ พิมพ์ลงบัญชี",
    stats: [
      { t: 167.8, big: "INVOICE", label: "อ่านตัวเลขจากใบเสร็จ", tone: "clay" },
    ],
  },
  {
    t: 181.04,
    mode: "pip",
    media: "broll",
    src: "tablet_finger_touch",
    kicker: "HANDS-FREE ACTION",
    headline: "คุณแค่นั่งดูอยู่เฉย ๆ",
    sub: "Terra เปิดอีเมล ค้นหายอดเงิน เปิดโปรแกรมบัญชี และกรอกข้อมูลให้เสร็จ",
    stats: [
      { t: 184.0, big: "HANDS FREE", label: "ไม่ต้องแตะเมาส์/คีย์บอร์ด", tone: "mint" },
    ],
  },
  {
    t: 198.34,
    mode: "full",
  },

  // --- PART 3: NATURAL LANGUAGE & WHOLE WORKDAY (202.72 - 299.55) ---
  {
    t: 202.72,
    mode: "pip",
    media: "clip",
    src: "yt_sees_does",
    clipFit: "contain",
    kicker: "SEES IT · DOES IT",
    headline: "Sees it. Does it.",
    sub: "มองเห็นสิ่งที่อยู่บนจอ แล้วลงมือปฏิบัติการแทนเราทันที",
    stats: [
      { t: 203.5, big: "SEES IT", label: "ตาเข้าใจหน้าจอ", tone: "amber" },
      { t: 205.0, big: "DOES IT", label: "มือทำงานแทนเรา", tone: "mint" },
    ],
  },
  {
    t: 209.79,
    mode: "pip",
    media: "broll",
    src: "natural_text_typing",
    kicker: "NATURAL LANGUAGE",
    headline: "เขียนและสื่อสารเป็นธรรมชาติ",
    sub: "ไม่ใช่ภาษาหุ่นยนต์แข็งกระด้าง แต่เข้าใจอารมณ์และบริบท",
    stats: [
      { t: 215.1, big: "NATURAL", label: "ภาษาเป็นธรรมชาติมาก", tone: "mint" },
    ],
  },
  {
    t: 228.46,
    mode: "full",
  },
  {
    t: 233.06,
    mode: "pip",
    media: "broll",
    src: "business_meeting_colleagues",
    kicker: "PRO SECRETARY",
    headline: "เหมือนมีเลขามืออาชีพ",
    sub: "เขียนอีเมลทางการ ร่างข้อความทักทาย สรุปประชุมเป็นชั่วโมงใน 2 บรรทัด",
    stats: [
      { t: 237.4, big: "EMAILS", label: "ร่างอีเมลทางการ", tone: "amber" },
      { t: 244.3, big: "SUMMARY", label: "สรุปประชุมกระชับ", tone: "mint" },
    ],
  },
  {
    t: 246.44,
    mode: "full",
  },
  {
    t: 256.86,
    mode: "pip",
    media: "broll",
    src: "office_clock_timelapse",
    kicker: "WHOLE WORKDAY",
    headline: "ผู้ช่วยตลอด 8 ชม. ทำงาน",
    sub: "สร้างขึ้นมาเพื่อดูแลงานตลอดทั้งวันทำงานอย่างต่อเนื่อง",
    stats: [
      { t: 259.2, big: "8 HOURS", label: "วันทำงานเต็มวัน", tone: "amber" },
    ],
  },
  {
    t: 272.52,
    mode: "pip",
    media: "broll",
    src: "digital_folder_database",
    kicker: "TASK OFFLOADING",
    headline: "สะสางงานหยุมหยิมที่กินพลัง",
    sub: "หาเอกสารเก่า จัดระเบียบไฟล์ ตอบอีเมลซ้ำๆ ที่ทำให้หมดแรง",
    stats: [
      { t: 276.7, big: "FILES & EMAILS", label: "งานที่กินแรงกินเวลา", tone: "clay" },
    ],
  },
  {
    t: 286.86,
    mode: "pip",
    media: "broll",
    src: "coffee_break_relax",
    kicker: "MORE FREE TIME",
    headline: "มีเวลาโฟกัสงานสำคัญและพักผ่อน",
    sub: "AI มารับช่วงต่อ เพื่อให้คุณได้ดื่มกาแฟและพักผ่อนสายตา",
    stats: [
      { t: 290.7, big: "FOCUS", label: "ทำงานสำคัญจริง", tone: "mint" },
      { t: 295.7, big: "COFFEE", label: "พักผ่อนสบายขึ้น", tone: "amber" },
    ],
  },
  {
    t: 299.55,
    mode: "full",
  },

  // --- PART 4: SPEED, PRICING & SAFETY (299.55 - 398.34) ---
  {
    t: 315.08,
    mode: "pip",
    media: "clip",
    src: "yt_paid_plans",
    clipFit: "contain",
    kicker: "PRICING & SPEED",
    headline: "เร็วขึ้น และราคาถูกลงกว่าเดิม",
    sub: "Available on all paid plans · ChatGPT Work & Codex",
    stats: [
      { t: 322.5, big: "FASTER", label: "ประมวลผลไวขึ้น", tone: "mint" },
      { t: 324.7, big: "50% OFF", label: "ราคาถูกลงกว่าเดิม", tone: "mint" },
    ],
  },
  {
    t: 327.08,
    mode: "pip",
    media: "broll",
    src: "cost_savings_growth",
    kicker: "COST EFFICIENCY",
    headline: "ต้นทุนเทคโนโลยีถูกลงอย่างมีนัยสำคัญ",
    sub: "บริษัทผู้พัฒนาสามารถนำไปใส่ในโปรแกรมที่เราใช้ทุกวันได้ง่ายขึ้น",
    stats: [
      { t: 331.1, big: "LOW COST", label: "เข้าถึงได้ทุกคน", tone: "mint" },
    ],
  },
  {
    t: 338.46,
    mode: "pip",
    media: "broll",
    src: "app_ecosystem_network",
    kicker: "APP INTEGRATION",
    headline: "ปุ่มผู้ช่วยในโปรแกรมทั่วไป",
    sub: "ในอนาคตอันใกล้ โปรแกรมธรรมดาที่เราใช้อาจมีปุ่มผู้ช่วยโผล่ขึ้นมาทันที",
    stats: [
      { t: 348.7, big: "1-CLICK", label: "ปุ่มผู้ช่วยในทุกแอป", tone: "amber" },
    ],
  },
  {
    t: 354.52,
    mode: "full",
  },
  {
    t: 368.00,
    mode: "pip",
    media: "broll",
    src: "security_approval_shield",
    kicker: "SAFETY BY DESIGN",
    headline: "ทำงานเป็น 'ผู้ช่วย' ไม่ใช่ 'เจ้านาย'",
    sub: "การส่งเมล โอนเงิน หรือลบข้อมูล จะหยุดขอการยืนยันจากเราก่อนเสมอ",
    stats: [
      { t: 372.9, big: "ASSISTANT", label: "ไม่ใช่เจ้านาย", tone: "mint" },
      { t: 382.0, big: "CONFIRM", label: "ขออนุญาตก่อนเสมอ", tone: "amber" },
    ],
  },
  {
    t: 388.64,
    mode: "full",
  },

  // --- PART 5: SUMMARY & CTA (398.34 - 505.70) ---
  {
    t: 398.34,
    mode: "full",
  },
  {
    t: 411.96,
    mode: "pip",
    media: "typo",
    typo: "vs",
    src: "modern_city_day",
    kicker: "NEW ERA OF WORK",
    headline: "ก้าวสู่ยุคใหม่ของการทำงาน",
    sub: "เปลี่ยนจากพิมพ์แชท สู่การให้ AI ช่วยสะสางงานแทนเราจริงๆ",
  },
  {
    t: 422.66,
    mode: "pip",
    media: "clip",
    src: "yt_diecast_hand",
    clipFit: "contain",
    kicker: "TANGIBLE RESULTS",
    headline: "ผลงานสำเร็จที่จับต้องได้",
    sub: "ช่วยหยิบ ช่วยจับ ช่วยพิมพ์ จนได้ผลงานสำเร็จสมบูรณ์",
    stats: [
      { t: 426.0, big: "ACTIONS", label: "สะสางงานแทนเรา", tone: "mint" },
    ],
  },
  {
    t: 429.56,
    mode: "full",
  },
  {
    t: 437.70,
    mode: "pip",
    media: "broll",
    src: "voice_audio_wave",
    kicker: "EASY TO USE",
    headline: "ยิ่งฉลาด ยิ่งใช้งานง่าย",
    sub: "ไม่ต้องจำปุ่มหรือตั้งค่า แค่พูดภาษาไทยบอกสิ่งที่ต้องการ",
    stats: [
      { t: 444.1, big: "EASY", label: "ไม่ต้องเรียนโค้ด", tone: "mint" },
      { t: 451.2, big: "THAI VO", label: "พูดสั่งเป็นภาษาไทย", tone: "amber" },
    ],
  },
  {
    t: 456.13,
    mode: "full",
  },
  {
    t: 459.62,
    mode: "pip",
    media: "typo",
    typo: "final4",
    src: "person_smiling_laptop",
    kicker: "FUTURE MINDSET",
    headline: "เปิดใจยอมรับเทคโนโลยีใหม่",
    sub: "จินตนาการถึงสิ่งที่คุณอยากให้ผู้ช่วยทำแทนคุณมากที่สุด",
  },
  {
    t: 469.50,
    mode: "full",
  },
  {
    t: 475.40,
    mode: "full",
    lower: {
      title: "งานแรกที่คุณอยากสั่งคืออะไร?",
      sub: "ลองพิมพ์คอมเมนต์แชร์ความคิดเห็นกันด้านล่างได้เลยนะคะ",
      t: 476.0,
      dur: 5.0,
    },
  },
  {
    t: 494.32,
    mode: "full",
  },
];

// Typo scene word times
const SUMMARY3 = [
  { t: 94.2, text: "1 · มีตาเข้าใจหน้าจอคอมพิวเตอร์", icon: "👁️" },
  { t: 96.8, text: "2 · มีมือทำงานข้ามแอปพลิเคชัน", icon: "🖱️" },
  { t: 98.2, text: "3 · เร็วขึ้น ถูกลง และปลอดภัย", icon: "⚡" },
];

const FINAL4 = [
  { t: 461.0, text: "1 · ไม่ต้องกังวลเรื่องการเขียนโค้ด", icon: "💻" },
  { t: 463.5, text: "2 · ยิ่งเทคโนโลยีฉลาด ยิ่งใช้ง่าย", icon: "✨" },
  { t: 465.5, text: "3 · เปิดใจยอมรับและเรียนรู้สิ่งใหม่", icon: "💡" },
  { t: 467.5, text: "4 · จินตนาการถึงผู้ช่วยทำงานส่วนตัว", icon: "🚀" },
];

const VS = { fableT: 413.0, mythosT: 416.5, subT: 419.5 };
const CTA_T = 481.0;

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
    <Footage src={beat.src || "tired_computer_worker"} from={beat.from || 0} beatStart={beat.t} beatEnd={beatEnd} t={t} fps={fps} />
    <div style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg, rgba(11,14,23,0.90) 0%, rgba(11,14,23,0.62) 48%, rgba(11,14,23,0.28) 100%)" }} />
    <div style={{ position: "absolute", inset: 0, background: "linear-gradient(180deg, rgba(11,14,23,0.25), transparent 30%, transparent 70%, rgba(11,14,23,0.55))" }} />
    <HeadlineBlock beat={beat} t={t} fps={fps} />
  </div>
);

// official clip inside the stage frame (light/dark museum-card look)
const ClipStage: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, beatEnd, t, fps }) => {
  const src = beat.src || "yt_orbit";
  const dur = BROLL_DUR[src] || 5;
  const loopFrames = Math.max(1, Math.floor(dur * fps) - 1);
  const local = Math.round((t - beat.t) * fps);
  const a = springIn(local - 2, fps, 18, 120);
  const subOn = beat.sub && t >= (beat.subT ?? beat.t + 1.2);
  const hasStats = Boolean(beat.stats && beat.stats.length > 0);

  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        top: CHROME_H,
        width: VW,
        height: VH,
        background: "linear-gradient(180deg, #131726, #0D101C)",
        overflow: "hidden",
      }}
    >
      <div style={{ position: "absolute", inset: 0, opacity: a }}>
        <Loop durationInFrames={loopFrames} layout="none">
          <OffthreadVideo
            muted
            src={staticFile(`${EPISODE.assetDir}/broll/${src}.mp4`)}
            style={{ width: "100%", height: "100%", objectFit: beat.clipFit ?? "contain" }}
          />
        </Loop>
      </div>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: 0,
          height: 140,
          background: "linear-gradient(180deg, rgba(11,14,23,0.85), transparent)",
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 28,
          top: 24,
          display: "flex",
          alignItems: "center",
          gap: 12,
          opacity: a,
          transform: `translateY(${(1 - a) * 10}px)`,
        }}
      >
        <span
          style={{
            fontFamily: FONT,
            fontWeight: 800,
            fontSize: 14,
            letterSpacing: 2,
            color: NAVY,
            background: AMBER,
            padding: "4px 10px",
            borderRadius: 6,
          }}
        >
          {EPISODE.officialTag}
        </span>
        <span
          style={{
            fontFamily: FONT,
            fontWeight: 700,
            fontSize: 22,
            color: CREAM,
            textShadow: "0 2px 10px rgba(0,0,0,0.6)",
          }}
        >
          {beat.headline}
        </span>
      </div>
      {subOn ? (
        <div
          style={{
            position: "absolute",
            left: 28,
            top: 64,
            fontFamily: FONT,
            fontWeight: 700,
            fontSize: 20,
            color: AMBER,
            textShadow: "0 2px 10px rgba(0,0,0,0.7)",
            opacity: springIn(Math.round((t - (beat.subT ?? beat.t + 1.2)) * fps), fps, 18, 120),
          }}
        >
          {beat.sub}
        </div>
      ) : null}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          height: hasStats ? 120 : 60,
          background: "linear-gradient(0deg, rgba(11,14,23,0.85), transparent)",
          pointerEvents: "none",
        }}
      />
    </div>
  );
};

// ===========================================================================
// Typography scenes (summary3, vs, final4)
// ===========================================================================

const Summary3Scene: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, beatEnd, t, fps }) => (
  <div style={{ position: "absolute", inset: 0 }}>
    <Footage src={beat.src || "futuristic_smart_office"} from={beat.from || 0} beatStart={beat.t} beatEnd={beatEnd} t={t} fps={fps} zoom={[1.02, 1.08]} />
    <div style={{ position: "absolute", inset: 0, background: "rgba(11,14,23,0.86)" }} />
    <div style={{ position: "absolute", left: 64, top: 90, width: 880 }}>
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 58, color: CREAM, lineHeight: 1.15, marginBottom: 12 }}>
        {EPISODE.summary3Label}
      </div>
      <div style={{ width: 90, height: 4, background: AMBER, borderRadius: 2, marginBottom: 38 }} />
      <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        {SUMMARY3.map((it, i) => {
          if (t < it.t) return null;
          const springV = springIn(Math.round((t - it.t) * fps), fps, 16, 130);
          return (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 20,
                background: "rgba(20,26,43,0.82)",
                border: "1px solid rgba(242,179,76,0.30)",
                borderRadius: 16,
                padding: "18px 26px",
                opacity: springV,
                transform: `translateX(${(1 - springV) * 36}px)`,
                boxShadow: "0 8px 30px rgba(0,0,0,0.35)",
              }}
            >
              <div style={{ fontSize: 34 }}>{it.icon}</div>
              <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 30, color: CREAM }}>{it.text}</div>
            </div>
          );
        })}
      </div>
    </div>
  </div>
);

const VsScene: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, beatEnd, t, fps }) => {
  const cfg = EPISODE.vs;
  const leftOn = t >= VS.fableT;
  const rightOn = t >= VS.mythosT;
  const subOn = t >= VS.subT;
  const sLeft = springIn(Math.round((t - VS.fableT) * fps), fps, 16, 120);
  const sRight = springIn(Math.round((t - VS.mythosT) * fps), fps, 16, 120);
  const sSub = springIn(Math.round((t - VS.subT) * fps), fps, 16, 120);

  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <Footage src={beat.src || "modern_city_day"} from={beat.from || 0} beatStart={beat.t} beatEnd={beatEnd} t={t} fps={fps} zoom={[1.02, 1.08]} />
      <div style={{ position: "absolute", inset: 0, background: "rgba(11,14,23,0.88)" }} />
      <div style={{ position: "absolute", left: 54, top: 70, right: 54 }}>
        <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 18, letterSpacing: 3, color: AMBER, marginBottom: 8 }}>
          {cfg.eyebrow}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 26, marginBottom: 20 }}>
          {leftOn ? (
            <div
              style={{
                background: "rgba(20,26,43,0.85)",
                border: "2px solid rgba(217,119,87,0.55)",
                borderRadius: 18,
                padding: "24px 28px",
                opacity: sLeft,
                transform: `translateY(${(1 - sLeft) * 24}px)`,
              }}
            >
              <div style={{ display: "inline-block", background: "rgba(217,119,87,0.20)", color: CLAY, fontFamily: MONO, fontSize: 13, fontWeight: 700, padding: "3px 10px", borderRadius: 6, marginBottom: 8 }}>
                {cfg.left.badge}
              </div>
              <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 34, color: CREAM, marginBottom: 16 }}>
                {cfg.left.title}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {cfg.left.lines.map((ln, i) => (
                  <div key={i} style={{ fontFamily: FONT, fontWeight: 600, fontSize: 22, color: CREAM_DIM }}>
                    {ln}
                  </div>
                ))}
              </div>
            </div>
          ) : <div />}
          {rightOn ? (
            <div
              style={{
                background: "rgba(20,26,43,0.92)",
                border: `2px solid ${AMBER}`,
                borderRadius: 18,
                padding: "24px 28px",
                boxShadow: "0 0 40px rgba(242,179,76,0.20)",
                opacity: sRight,
                transform: `translateY(${(1 - sRight) * 24}px)`,
              }}
            >
              <div style={{ display: "inline-block", background: "rgba(242,179,76,0.20)", color: AMBER, fontFamily: MONO, fontSize: 13, fontWeight: 700, padding: "3px 10px", borderRadius: 6, marginBottom: 8 }}>
                {cfg.right.badge}
              </div>
              <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 34, color: CREAM, marginBottom: 16 }}>
                {cfg.right.title}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {cfg.right.lines.map((ln, i) => (
                  <div key={i} style={{ fontFamily: FONT, fontWeight: 700, fontSize: 22, color: CREAM }}>
                    {ln}
                  </div>
                ))}
              </div>
            </div>
          ) : <div />}
        </div>
        {subOn ? (
          <div
            style={{
              background: "rgba(242,179,76,0.12)",
              border: "1px solid rgba(242,179,76,0.40)",
              borderRadius: 14,
              padding: "14px 24px",
              textAlign: "center",
              fontFamily: FONT,
              fontWeight: 800,
              fontSize: 24,
              color: CREAM,
              opacity: sSub,
              transform: `scale(${0.96 + sSub * 0.04})`,
            }}
          >
            ⚡ {cfg.conclusion}
          </div>
        ) : null}
      </div>
    </div>
  );
};

const Final4Scene: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, beatEnd, t, fps }) => (
  <div style={{ position: "absolute", inset: 0 }}>
    <Footage src={beat.src || "person_smiling_laptop"} from={beat.from || 0} beatStart={beat.t} beatEnd={beatEnd} t={t} fps={fps} zoom={[1.02, 1.08]} />
    <div style={{ position: "absolute", inset: 0, background: "rgba(11,14,23,0.88)" }} />
    <div style={{ position: "absolute", left: 64, top: 80, width: 880 }}>
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 56, color: CREAM, lineHeight: 1.15, marginBottom: 8 }}>
        {EPISODE.final4.title}
      </div>
      <div style={{ fontFamily: FONT, fontWeight: 600, fontSize: 26, color: AMBER, marginBottom: 14 }}>
        {EPISODE.final4.sub}
      </div>
      <div style={{ width: 90, height: 4, background: AMBER, borderRadius: 2, marginBottom: 32 }} />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {FINAL4.map((it, i) => {
          if (t < it.t) return null;
          const springV = springIn(Math.round((t - it.t) * fps), fps, 16, 130);
          return (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 16,
                background: "rgba(20,26,43,0.85)",
                border: "1px solid rgba(242,179,76,0.30)",
                borderRadius: 14,
                padding: "16px 20px",
                opacity: springV,
                transform: `translateX(${(1 - springV) * 24}px)`,
                boxShadow: "0 6px 24px rgba(0,0,0,0.3)",
              }}
            >
              <div style={{ fontSize: 32 }}>{it.icon}</div>
              <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 22, color: CREAM, lineHeight: 1.3 }}>{it.text}</div>
            </div>
          );
        })}
      </div>
    </div>
  </div>
);

// Stage switcher
const LeftStage: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, beatEnd, t, fps }) => {
  if (beat.mode === "full" || !beat.media || beat.media === "none") return null;
  if (beat.media === "typo") {
    if (beat.typo === "summary3") return <Summary3Scene beat={beat} beatEnd={beatEnd} t={t} fps={fps} />;
    if (beat.typo === "vs") return <VsScene beat={beat} beatEnd={beatEnd} t={t} fps={fps} />;
    if (beat.typo === "final4") return <Final4Scene beat={beat} beatEnd={beatEnd} t={t} fps={fps} />;
  }
  if (beat.media === "clip") return <ClipStage beat={beat} beatEnd={beatEnd} t={t} fps={fps} />;
  if (beat.media === "broll") return <FootageStage beat={beat} beatEnd={beatEnd} t={t} fps={fps} />;
  return null;
};

// ---- Overlays -------------------------------------------------------------

const TopBar: React.FC<{ kicker?: string }> = ({ kicker }) => (
  <div
    style={{
      position: "absolute",
      left: 80,
      right: 80,
      top: 28,
      height: 48,
      display: "flex",
      alignItems: "center",
      gap: 14,
      zIndex: 20,
    }}
  >
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        background: "rgba(20,26,43,0.85)",
        border: "1px solid rgba(245,241,232,0.12)",
        borderRadius: 24,
        padding: "6px 16px",
        boxShadow: "0 6px 20px rgba(0,0,0,0.35)",
      }}
    >
      <div style={{ width: 8, height: 8, borderRadius: "50%", background: CLAY }} />
      <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 14, letterSpacing: 2, color: CREAM }}>
        {EPISODE.brand}
      </span>
      <span style={{ color: "rgba(245,241,232,0.3)", fontSize: 13 }}>·</span>
      <span style={{ fontFamily: FONT, fontWeight: 600, fontSize: 13, color: CREAM_DIM }}>
        {EPISODE.dateLabel}
      </span>
    </div>
    {kicker ? (
      <div
        style={{
          background: "rgba(242,179,76,0.16)",
          border: "1px solid rgba(242,179,76,0.40)",
          borderRadius: 20,
          padding: "5px 14px",
          fontFamily: FONT,
          fontWeight: 800,
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
  const local = Math.round((t - stat.t) * fps);
  const a = springIn(local, fps, 14, 150);
  const tColor = tone(stat.tone);
  return (
    <div
      style={{
        background: "rgba(11,14,23,0.88)",
        border: `1.5px solid ${tColor}`,
        borderRadius: 14,
        padding: stat.big ? "10px 18px" : "10px 18px",
        display: "inline-flex",
        alignItems: "baseline",
        gap: 10,
        boxShadow: `0 8px 30px rgba(0,0,0,0.55), 0 0 20px ${tColor}33`,
        opacity: a,
        transform: `translateY(${(1 - a) * 16}px) scale(${0.9 + a * 0.1})`,
      }}
    >
      {stat.big ? (
        <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 36, color: tColor, lineHeight: 1 }}>
          {stat.big}
        </span>
      ) : null}
      <span style={{ fontFamily: FONT, fontWeight: 700, fontSize: stat.big ? 20 : 24, color: CREAM, lineHeight: 1 }}>
        {stat.label}
      </span>
    </div>
  );
};

const LowerThird: React.FC<{ title: string; sub: string; fps: number; localFrame: number }> = ({
  title, sub, fps, localFrame,
}) => {
  const a = springIn(localFrame, fps, 18, 120);
  return (
    <div
      style={{
        position: "absolute",
        left: 80,
        bottom: 150,
        zIndex: 30,
        maxWidth: 1100,
        opacity: a,
        transform: `translateY(${(1 - a) * 24}px)`,
      }}
    >
      <div
        style={{
          display: "inline-block",
          background: CLAY,
          color: CREAM,
          fontFamily: FONT,
          fontWeight: 800,
          fontSize: 16,
          letterSpacing: 2.5,
          padding: "4px 12px",
          borderRadius: 6,
          marginBottom: 10,
          boxShadow: "0 4px 14px rgba(0,0,0,0.4)",
        }}
      >
        BREAKING
      </div>
      <div
        style={{
          fontFamily: FONT,
          fontWeight: 800,
          fontSize: 60,
          lineHeight: 1.1,
          color: CREAM,
          textShadow: "0 4px 30px rgba(0,0,0,0.8)",
          marginBottom: 8,
        }}
      >
        {title}
      </div>
      <div
        style={{
          fontFamily: FONT,
          fontWeight: 700,
          fontSize: 26,
          color: AMBER,
          textShadow: "0 2px 20px rgba(0,0,0,0.8)",
        }}
      >
        {sub}
      </div>
    </div>
  );
};

const CtaChip: React.FC<{ fps: number; localFrame: number }> = ({ fps, localFrame }) => {
  const a = springIn(localFrame, fps, 18, 120);
  return (
    <div
      style={{
        position: "absolute",
        left: 80,
        bottom: 170,
        zIndex: 30,
        background: "rgba(20,26,43,0.92)",
        border: `2px solid ${AMBER}`,
        borderRadius: 18,
        padding: "14px 26px",
        display: "flex",
        alignItems: "center",
        gap: 14,
        boxShadow: "0 10px 40px rgba(0,0,0,0.6), 0 0 30px rgba(242,179,76,0.3)",
        opacity: a,
        transform: `translateY(${(1 - a) * 20}px)`,
      }}
    >
      <div style={{ fontSize: 26 }}>▶️</div>
      <div>
        <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 16, color: CREAM_DIM, letterSpacing: 1 }}>
          {EPISODE.cta.lead}
        </div>
        <div style={{ fontFamily: MONO, fontWeight: 700, fontSize: 24, color: AMBER }}>
          {EPISODE.cta.text}
        </div>
      </div>
    </div>
  );
};

const CaptionLane: React.FC<{ t: number }> = ({ t }) => {
  const page = CAPTION_PAGES.find((p) => t >= p.start && t < p.end);
  if (!page) return null;
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 26,
        display: "flex",
        justifyContent: "center",
        pointerEvents: "none",
        zIndex: 40,
      }}
    >
      <div
        style={{
          background: "rgba(11,14,23,0.78)",
          padding: "10px 28px",
          borderRadius: 22,
          display: "inline-flex",
          gap: 12,
          fontFamily: FONT,
          fontWeight: 800,
          fontSize: 36,
          boxShadow: "0 6px 30px rgba(0,0,0,0.6)",
        }}
      >
        {page.words.map((w, i) => {
          const on = t >= w.s;
          return (
            <span
              key={i}
              style={{
                color: on ? GOLD : CREAM,
                textShadow: on
                  ? `0 0 20px ${GOLD}, 0 0 35px ${GOLD_LIGHT}`
                  : "0 2px 10px rgba(0,0,0,0.7)",
                transition: "color 0.08s ease",
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

const EndCard: React.FC = () => {
  const cfg = EPISODE.endcard;
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        background: "radial-gradient(ellipse at center, #1B233D 0%, #0B0E17 75%)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 50,
      }}
    >
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 18, letterSpacing: 4, color: AMBER, marginBottom: 16 }}>
        {cfg.eyebrow}
      </div>
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 92, lineHeight: 1.05, color: CREAM, textAlign: "center", marginBottom: 20 }}>
        <span>{cfg.titleA}</span>
        <span style={{ color: AMBER }}> · </span>
        <span style={{ color: AMBER }}>{cfg.titleB}</span>
      </div>
      <div style={{ fontFamily: FONT, fontWeight: 600, fontSize: 24, color: CREAM_DIM, marginBottom: 44 }}>
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

export type Gpt61TerraNewsV2Props = {
  durationSec?: number;
};

export const calculateGpt61TerraNewsV2Metadata: CalculateMetadataFunction<Gpt61TerraNewsV2Props> = async () => ({
  durationInFrames: Math.ceil(TOTAL_DURATION_SEC * 25),
  fps: 25,
  width: W,
  height: H,
});

export const Gpt61TerraNewsV2: React.FC<Gpt61TerraNewsV2Props> = () => {
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
  const card = {
    x: interpolate(p, [0, 1], [0, AV.x]),
    y: interpolate(p, [0, 1], [0, AV.y]),
    w: interpolate(p, [0, 1], [W, AV.w]),
    h: interpolate(p, [0, 1], [H, AV.h]),
    r: interpolate(p, [0, 1], [0, AV.r]),
  };
  const scale = interpolate(p, [0, 1], [1, AV.h / H]);
  const cx = interpolate(p, [0, 1], [960, AV_CX]);
  const cy = interpolate(p, [0, 1], [540, AV_CY]);
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
