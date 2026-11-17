import React, { useEffect, useState } from "react";
import {
  OffthreadVideo,
  Loop,
  interpolate,
  spring,
  staticFile,
  continueRender,
  delayRender,
  useCurrentFrame,
  useVideoConfig,
  CalculateMetadataFunction,
} from "remotion";
import { CAPTION_PAGES } from "./gptImage26NewsV2Captions";
import { WEB_CLIPS, WEB_RECTS, WebRect } from "./gptImage26NewsWeb";

// ===========================================================================
// GptImage26NewsV2 — 16:9 AI-news report (1920x1080@25)
// Format "Youtube-YT-News-Style01-V2":
// Report subject: YOUTUBE VIDEO ("GPT-Image-2.6: Faster image generation with Flare and Sunburst")
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
const VO_END_SEC = 336.5;
const TOTAL_DURATION_SEC = 341.0; // + 4.5 s endcard
const MODE_BLEND_SEC = 0.55;

// ---- Episode config (swap per episode — every on-screen string lives here) --
const EPISODE = {
  assetDir: "gptImage26NewsV2", // public/<assetDir>/{avatar_source.mp4, broll/, web/}
  brand: "AI TECH NEWS",
  dateLabel: "7 พ.ย. 2026",
  page: { domain: "youtube.com", path: "/watch?v=9ZxCOHkfn_8" },
  officialTag: "SOURCE · OPENAI",
  cta: { lead: "ทดลองใช้งาน GPT-Image-2.6 ได้แล้ววันนี้ที่", text: "OpenAI API & Codex" },
  endcard: {
    eyebrow: "AI TECH NEWS · NOVEMBER 2026",
    titleA: "GPT-Image-2.6",
    titleB: "Faster with Flare & Sunburst",
    sub: "YouTube: OpenAI · GPT-Image-2.6: Faster image generation with Flare and Sunburst",
    cta: "กดติดตามเพื่อไม่พลาดทุกข่าวสาร AI",
  },
  summary3Label: "3 จุดเปลี่ยนสำคัญของ GPT-Image-2.6",
  final4: {
    title: "ยกระดับการสร้างสรรค์ด้วย AI เจนภาพรุ่นใหม่",
    sub: "เปลี่ยนไอเดียในหัวเป็นภาพจริงได้รวดเร็วทันใจและคมชัดยิ่งขึ้น",
  },
  vs: {
    eyebrow: "FLARE VS SUNBURST",
    conclusion: "สเก็ตช์โครงสร้างด้วย Flare แล้วส่งต่อ Sunburst จัดการความสวยงามระดับสูง",
    left: {
      title: "FLARE",
      badge: "ช่างสเก็ตช์ร่าง · รวดเร็ว",
      lines: [
        "✓ ขึ้นโครงร่างภาพแบบคร่าวๆ รวดเร็ว",
        "✓ ตรวจสอบทิศทางแสงและองค์ประกอบ",
        "✓ สร้างภาพเสร็จได้ในเวลาเพียง 6 วินาที",
      ],
    },
    right: {
      title: "SUNBURST",
      badge: "ช่างลงสี · ความละเอียดสูง",
      lines: [
        "✓ เก็บรายละเอียดพื้นผิว แสงเงา คมชัด",
        "✓ จัดการความสวยงามในระดับมืออาชีพ",
        "✓ ได้ภาพสมบูรณ์แบบพร้อมนำไปใช้งานจริง",
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
  architect_concept_draft: 30.00,
  artist_pencil_sketch: 15.04,
  boutique_customer_sale: 19.44,
  creative_vision_light: 8.40,
  digital_art_creative: 30.00,
  drinking_water_glass: 30.00,
  ecommerce_package_order: 14.00,
  fast_city_traffic: 8.28,
  fine_oil_painter: 9.00,
  graphic_designer_ui: 17.96,
  hourglass_sand_time: 10.04,
  photo_studio_lights: 9.76,
  printing_posters_press: 11.44,
  social_creator_workspace: 19.64,
  software_engineer_code: 10.00,
  team_brainstorming_board: 14.48,
  yt_api_docs: 10.04,
  yt_complexity_levels: 11.04,
  yt_intro_banner: 6.00,
  yt_looping_gif: 7.04,
  yt_markup_refine: 13.04,
  yt_prompt_koi: 8.00,
  yt_sprite_sheet: 9.04,
  yt_svg_icons: 9.00,
  yt_svg_origami: 9.00,
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

// ---- BEATS (Every footage file appears in AT MOST ONE BEAT) ---------------
const BEATS: Beat[] = [
  // --- PART 1: HOOK & THE WAITING PROBLEM (0.00 - 47.82) ---
  {
    t: 0.0,
    mode: "full",
    lower: {
      title: "GPT-IMAGE-2.6 IS HERE",
      sub: "FASTER IMAGE GENERATION WITH FLARE & SUNBURST",
      t: 1.0,
      dur: 5.5,
    },
  },
  {
    t: 6.84,
    mode: "pip",
    media: "broll",
    src: "ecommerce_package_order",
    kicker: "IMAGE PROBLEM",
    headline: "อยากได้รูปภาพไปใช้งาน",
    sub: "ขายของออนไลน์ ทำโปสเตอร์ หรืองานนำเสนอ",
    stats: [
      { t: 8.4, big: "COMMERCE", label: "ใช้ลงขายของ", tone: "amber" },
      { t: 9.5, big: "POSTER", label: "ทำโปสเตอร์งาน", tone: "mint" },
    ],
  },
  {
    t: 14.34,
    mode: "pip",
    media: "broll",
    src: "artist_pencil_sketch",
    kicker: "TRADITIONAL DRAWING",
    headline: "ถ้าจ้างคนวาดก็รอนาน",
    sub: "ต้องใช้เวลาหลายวันหรือสัปดาห์กว่าจะได้รูป",
    stats: [
      { t: 15.1, big: "HIRE ARTIST", label: "จ้างคนวาด", tone: "clay" },
      { t: 16.1, big: "WAIT TIME", label: "ต้องใช้เวลารอ", tone: "amber" },
    ],
  },
  {
    t: 17.98,
    mode: "pip",
    media: "broll",
    src: "digital_art_creative",
    kicker: "AI IMAGE ERA",
    headline: "AI วาดรูปเข้ามามีบทบาท",
    sub: "แค่พิมพ์ข้อความสั่ง ตัวระบบก็สร้างภาพออกมาให้",
    stats: [
      { t: 19.2, big: "AI ART", label: "ปัญญาประดิษฐ์วาดรูป", tone: "amber" },
      { t: 24.3, big: "PROMPT", label: "พิมพ์ข้อความสั่งงาน", tone: "mint" },
    ],
  },
  {
    t: 28.76,
    mode: "pip",
    media: "broll",
    src: "hourglass_sand_time",
    kicker: "THE WAITING PROBLEM",
    headline: "ปัญหาที่เจอบ่อยคือ การรอคอย",
    sub: "บางครั้งต้องนั่งจ้องหน้าจอรอนาทีสองนาทีกว่าภาพจะขึ้น",
    stats: [
      { t: 30.9, big: "WAITING", label: "ปัญหาการรอคอย", tone: "clay" },
      { t: 35.8, big: "1-2 MIN", label: "รอนาทีสองนาทีต่อภาพ", tone: "amber" },
    ],
  },
  {
    t: 44.18,
    mode: "full",
  },
  {
    t: 47.82,
    mode: "pip",
    media: "clip",
    src: "yt_intro_banner",
    clipFit: "contain",
    kicker: "NEW ANNOUNCEMENT",
    headline: "เปิดตัว GPT-Image-2.6",
    sub: "ระบบสร้างภาพรุ่นใหม่ล่าสุดจาก OpenAI",
    stats: [
      { t: 49.5, big: "GPT-IMAGE 2.6", label: "โมเดลรุ่นใหม่ล่าสุด", tone: "amber" },
    ],
  },
  {
    t: 52.14,
    mode: "pip",
    media: "clip",
    src: "yt_prompt_koi",
    clipFit: "contain",
    kicker: "API & CODEX RELEASE",
    headline: "นำมาใส่ใน API และ Codex",
    sub: "ความเร็วสร้างภาพเพิ่มขึ้นจากเดิมถึง 50%",
    stats: [
      { t: 56.2, big: "API + CODEX", label: "เชื่อมต่อในระบบ", tone: "mint" },
      { t: 63.9, big: "+50% FASTER", label: "ความเร็วเพิ่มขึ้น", tone: "amber" },
    ],
  },
  {
    t: 65.20,
    mode: "full",
  },

  // --- PART 2: FLARE & SUNBURST (74.68 - 136.86) ---
  {
    t: 74.68,
    mode: "pip",
    media: "clip",
    src: "yt_complexity_levels",
    clipFit: "contain",
    kicker: "TWO NEW ENGINES",
    headline: "2 เครื่องมือใหม่: Flare & Sunburst",
    sub: "ออกแบบมาเพื่อทำหน้าที่คนละบทบาทอย่างชัดเจน",
    stats: [
      { t: 79.2, big: "FLARE", label: "ตัวแรกชื่อ Flare", tone: "amber" },
      { t: 81.0, big: "SUNBURST", label: "อีกตัวชื่อ Sunburst", tone: "mint" },
    ],
  },
  {
    t: 88.62,
    mode: "pip",
    media: "broll",
    src: "architect_concept_draft",
    kicker: "FLARE · CONCEPT SKETCH",
    headline: "Flare: ช่างสเก็ตช์ภาพร่าง",
    sub: "ขึ้นโครงสร้างคร่าวๆ เพื่อดูแสง องค์ประกอบ และตำแหน่ง",
    stats: [
      { t: 90.2, big: "SKETCH", label: "ช่างสเก็ตช์ภาพ", tone: "amber" },
      { t: 97.7, big: "LAYOUT", label: "ขึ้นโครงร่างคร่าวๆ", tone: "mint" },
    ],
  },
  {
    t: 104.68,
    mode: "pip",
    media: "broll",
    src: "fine_oil_painter",
    kicker: "SUNBURST · FINE DETAILS",
    headline: "Sunburst: ช่างลงสีรายละเอียดสูง",
    sub: "รับหน้าที่เก็บพื้นผิว แสงเงา และความคมชัดของภาพ",
    stats: [
      { t: 107.1, big: "COLORIST", label: "ช่างลงสีละเอียด", tone: "mint" },
      { t: 111.0, big: "TEXTURE", label: "เก็บแสงเงาพื้นผิว", tone: "amber" },
    ],
  },
  {
    t: 114.66,
    mode: "pip",
    media: "typo",
    typo: "vs",
    src: "creative_vision_light",
    kicker: "WORKFLOW COMPARISON",
    headline: "Flare vs Sunburst: ผสานพลัง 2 ขั้นตอน",
    sub: "วาดโครงร่างรอบแรกด้วย Flare แล้วส่งต่อให้ Sunburst จัดการความสวยงาม",
  },

  // --- PART 3: 50% FASTER & 6-SECOND GENERATION (136.86 - 207.86) ---
  {
    t: 136.86,
    mode: "full",
  },
  {
    t: 143.62,
    mode: "pip",
    media: "broll",
    src: "fast_city_traffic",
    kicker: "SPEED MATTERS",
    headline: "ความเร็วเพิ่ม 50% ลดเวลารอครึ่งหนึ่ง",
    sub: "จากเดิม 10 วินาทีต่อภาพ ลดลงเหลือเพียง 5 วินาที",
    stats: [
      { t: 146.0, big: "10 SEC", label: "ระบบเดิม 10 วินาที", tone: "clay" },
      { t: 152.2, big: "5 SEC", label: "ระบบใหม่เหลือ 5 วิ", tone: "mint" },
    ],
  },
  {
    t: 153.02,
    mode: "pip",
    media: "clip",
    src: "yt_markup_refine",
    clipFit: "contain",
    kicker: "6-SECOND GENERATION",
    headline: "Flare คุณภาพเริ่มต้น เสร็จใน 6 วินาที",
    sub: "ทดลองสร้างและแก้ไขภาพได้ในเสี้ยวเวลา",
    stats: [
      { t: 158.0, big: "FLARE FAST", label: "ระดับคุณภาพเริ่มต้น", tone: "amber" },
      { t: 164.3, big: "6 SECONDS", label: "เสร็จในเวลา 6 วินาที", tone: "mint" },
    ],
  },
  {
    t: 166.26,
    mode: "pip",
    media: "broll",
    src: "drinking_water_glass",
    kicker: "BLINK OF AN EYE",
    headline: "เร็วเท่าเวลาก้มหยิบแก้วน้ำ",
    sub: "เวลาระดับ 6 วินาที แทบจะเท่ากับเวลาที่เรากะพริบตา",
    stats: [
      { t: 167.1, big: "6 SEC", label: "สปีดระดับกะพริบตา", tone: "amber" },
      { t: 171.1, big: "NO DELAY", label: "ก้มหยิบแก้วน้ำก็ได้ภาพ", tone: "mint" },
    ],
  },
  {
    t: 171.80,
    mode: "pip",
    media: "broll",
    src: "graphic_designer_ui",
    kicker: "CREATIVE TESTING",
    headline: "ประโยชน์สูงสุดช่วงทดลองไอเดีย",
    sub: "ลองเปลี่ยนสีพื้นหลังหรือมุมกล้องของสินค้าได้ทันที",
    stats: [
      { t: 176.5, big: "EXPERIMENT", label: "ทดลองไอเดียใหม่ๆ", tone: "amber" },
      { t: 185.7, big: "ANGLES", label: "เปลี่ยนมุมกล้องสินค้า", tone: "mint" },
    ],
  },
  {
    t: 192.46,
    mode: "pip",
    media: "clip",
    src: "yt_svg_origami",
    clipFit: "contain",
    kicker: "RAPID ITERATION",
    headline: "ได้ภาพตัวอย่างหลายแบบใน 1 นาที",
    sub: "ระยะเวลาเหลือหลักวินาที ความคิดสร้างสรรค์ไม่สะดุด",
    stats: [
      { t: 197.1, big: "NO BLOCK", label: "ไอเดียไม่สะดุด", tone: "mint" },
      { t: 202.6, big: "< 1 MIN", label: "ได้หลายแบบใน 1 นาที", tone: "amber" },
    ],
  },

  // --- PART 4: EVERYDAY APPLICATIONS (207.86 - 277.10) ---
  {
    t: 207.86,
    mode: "full",
  },
  {
    t: 222.76,
    mode: "pip",
    media: "broll",
    src: "photo_studio_lights",
    kicker: "PRODUCT PHOTOGRAPHY",
    headline: "ภาพถ่ายสินค้าและโปรดักต์ช็อต",
    sub: "พ่อค้าแม่ค้าออนไลน์จำลองฉากหลังใหม่ได้ทันใจตามเทศกาล",
    stats: [
      { t: 228.2, big: "PRODUCT SHOT", label: "ภาพถ่ายสินค้า", tone: "amber" },
      { t: 239.2, big: "SEASONS", label: "เปลี่ยนฉากตามเทศกาล", tone: "mint" },
    ],
  },
  {
    t: 243.52,
    mode: "pip",
    media: "broll",
    src: "printing_posters_press",
    kicker: "POSTERS & MEDIA",
    headline: "งานโปสเตอร์ ใบปลิว และสื่อประชาสัมพันธ์",
    sub: "ขึ้นภาพร่างแล้วเห็นตำแหน่งสำหรับจัดวางตัวหนังสือได้ทันที",
    stats: [
      { t: 247.6, big: "POSTER/FLYER", label: "แผ่นพับ ใบปลิว นำเสนอ", tone: "amber" },
    ],
  },
  {
    t: 250.96,
    mode: "pip",
    media: "clip",
    src: "yt_svg_icons",
    clipFit: "contain",
    kicker: "VECTOR & ICONS",
    headline: "ขึ้นภาพร่างสำหรับจัดวางตัวหนังสือ",
    sub: "เห็นตำแหน่งว่างสำหรับใส่ข้อความและไอคอนทันที",
    stats: [
      { t: 255.5, big: "TEXT LAYOUT", label: "เห็นตำแหน่งวางข้อความ", tone: "mint" },
      { t: 258.0, big: "SVG ICONS", label: "ไอคอนคมชัดทุกขนาด", tone: "amber" },
    ],
  },
  {
    t: 259.40,
    mode: "pip",
    media: "broll",
    src: "team_brainstorming_board",
    kicker: "TEAM COLLABORATION",
    headline: "ประชุมกลุ่ม ทุกคนเห็นภาพตรงกันทันที",
    sub: "สั่งสร้างภาพขึ้นมาดูพร้อมกันในไม่กี่วินาที ไม่ต้องอธิบายยืดยาว",
    stats: [
      { t: 263.1, big: "BRAINSTORM", label: "ประชุมงานเป็นกลุ่ม", tone: "mint" },
      { t: 271.1, big: "SAME VISION", label: "เห็นภาพตรงกันทันที", tone: "amber" },
    ],
  },

  // --- PART 5: CODEX & APP WORKFLOWS (277.10 - 336.5) ---
  {
    t: 277.10,
    mode: "pip",
    media: "broll",
    src: "software_engineer_code",
    kicker: "CODEX INTEGRATION",
    headline: "นำระบบเข้าไปใส่ใน Codex",
    sub: "เครื่องมือช่วยเขียนโค้ด ทำให้นักพัฒนาสร้างฟังก์ชันใหม่ๆ ได้ง่ายขึ้น",
    stats: [
      { t: 281.6, big: "CODEX", label: "เครื่องมือช่วยเขียนโค้ด", tone: "amber" },
      { t: 288.5, big: "DEV SPEED", label: "สร้างฟังก์ชันใหม่ได้ง่ายขึ้น", tone: "mint" },
    ],
  },
  {
    t: 285.86,
    mode: "pip",
    media: "clip",
    src: "yt_api_docs",
    clipFit: "contain",
    kicker: "API DEVELOPERS",
    headline: "นักพัฒนาสร้างฟังก์ชันภาพในแอปได้ทันที",
    sub: "รองรับการเชื่อมต่อผ่าน API พารามิเตอร์ใหม่ใช้งานได้แล้ววันนี้",
    stats: [
      { t: 288.0, big: "API INTEGRATION", label: "เชื่อมต่อง่าย", tone: "mint" },
    ],
  },
  {
    t: 294.66,
    mode: "pip",
    media: "clip",
    src: "yt_sprite_sheet",
    clipFit: "contain",
    kicker: "FASTER APPS",
    headline: "แอปแต่งรูปโหลดเร็วขึ้นอย่างเห็นได้ชัด",
    sub: "หน้าจอหมุนรอประมวลผลสั้นลง รองรับ Sprite Sheet แอนิเมชัน",
    stats: [
      { t: 298.2, big: "SPEED UP", label: "แอปโหลดเร็วขึ้น", tone: "mint" },
      { t: 303.3, big: "NO WAITING", label: "หน้าจอหมุนรอสั้นลง", tone: "amber" },
    ],
  },
  {
    t: 306.46,
    mode: "pip",
    media: "clip",
    src: "yt_looping_gif",
    clipFit: "contain",
    kicker: "CONTENT CREATORS",
    headline: "ทำคอนเทนต์ลงสื่อสังคมออนไลน์ได้ไวขึ้น",
    sub: "เตรียมภาพประกอบบทความหรือโปรโมชันเสร็จไว มีลูกเล่น GIF",
    stats: [
      { t: 311.9, big: "CONTENT", label: "คนทำคอนเทนต์ประหยัดเวลา", tone: "mint" },
      { t: 316.0, big: "LOOP GIF", label: "แอนิเมชันลูปต่อเนื่อง", tone: "amber" },
    ],
  },
  {
    t: 316.54,
    mode: "pip",
    media: "broll",
    src: "boutique_customer_sale",
    kicker: "MORE TIME FOR BUSINESS",
    headline: "มีเวลาเหลือไปดูแลการขายและลูกค้า",
    sub: "ไม่ต้องเสียเวลากับงานภาพ เอาเวลาไปสร้างรายได้และพูดคุยกับลูกค้า",
    stats: [
      { t: 318.0, big: "BUSINESS", label: "โฟกัสเรื่องการขาย", tone: "amber" },
      { t: 320.5, big: "CUSTOMERS", label: "ดูแลลูกค้าได้เต็มที่", tone: "mint" },
    ],
  },
  {
    t: 322.68,
    mode: "pip",
    media: "typo",
    typo: "summary3",
    src: "social_creator_workspace",
    kicker: "FINAL RECAP",
    headline: "3 จุดเปลี่ยนสำคัญของ GPT-Image-2.6",
    sub: "ลดระยะเวลารอ เปลี่ยนความคิดในหัวเป็นภาพได้อย่างลื่นไหล",
  },
  {
    t: 334.14,
    mode: "full",
  },
];

// Typo scene word times
const SUMMARY3 = [
  { t: 323.0, text: "1 · Flare + Sunburst: แยกสเก็ตช์และลงสีละเอียด", icon: "🎨" },
  { t: 326.0, text: "2 · สร้างภาพเร็วขึ้น 50% เริ่มต้นแค่ 6 วินาที", icon: "⚡" },
  { t: 329.5, text: "3 · รองรับทั้ง SVG, GIF และฝังใน Codex ได้ทันที", icon: "💻" },
];

const FINAL4 = [
  { t: 323.0, text: "1 · ความเร็วสร้างภาพเพิ่มขึ้น 50%", icon: "⚡" },
  { t: 325.5, text: "2 · สเก็ตช์ร่างด้วย Flare เสร็จใน 6 วินาที", icon: "✏️" },
  { t: 328.0, text: "3 · ลงสีและเก็บรายละเอียดด้วย Sunburst", icon: "🎨" },
  { t: 330.5, text: "4 · รองรับ SVG, Sprite Sheet และเชื่อมใน Codex", icon: "💻" },
];

const VS = { fableT: 116.0, mythosT: 122.0, subT: 128.0 };
const CTA_T = 334.5;

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
            fontSize: 20,
            color,
            lineHeight: 1.1,
            letterSpacing: 0.5,
          }}
        >
          {stat.big}
        </span>
      ) : null}
      <span
        style={{
          fontFamily: FONT,
          fontWeight: 500,
          fontSize: 14,
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
  const s = springIn(localFrame, fps, 14, 150);
  return (
    <div
      style={{
        position: "absolute",
        left: 80,
        bottom: 80,
        transform: `translateY(${(1 - s) * 40}px)`,
        opacity: interpolate(s, [0, 0.3, 1], [0, 1, 1]),
        zIndex: 50,
        background: "rgba(11,14,23,0.92)",
        backdropFilter: "blur(20px)",
        border: `1px solid rgba(242,179,76,0.35)`,
        borderLeft: `6px solid ${AMBER}`,
        borderRadius: 18,
        padding: "16px 28px",
        display: "flex",
        flexDirection: "column",
        gap: 4,
        boxShadow: "0 20px 50px rgba(0,0,0,0.7), 0 0 30px rgba(242,179,76,0.15)",
        maxWidth: 750,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#FF5F56", boxShadow: "0 0 8px #FF5F56" }} />
        <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 13, letterSpacing: 2, color: AMBER }}>
          BREAKING NEWS
        </span>
      </div>
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 28, color: CREAM, lineHeight: 1.15 }}>
        {title}
      </div>
      <div style={{ fontFamily: FONT, fontWeight: 500, fontSize: 16, color: CREAM_DIM, lineHeight: 1.3 }}>
        {sub}
      </div>
    </div>
  );
};

const CtaChip: React.FC<{ fps: number; localFrame: number }> = ({ fps, localFrame }) => {
  const s = springIn(localFrame, fps, 14, 150);
  return (
    <div
      style={{
        position: "absolute",
        left: "50%",
        bottom: 120,
        transform: `translateX(-50%) scale(${s}) translateY(${(1 - s) * 30}px)`,
        opacity: interpolate(s, [0, 0.4, 1], [0, 1, 1]),
        zIndex: 60,
        background: "rgba(11,14,23,0.92)",
        backdropFilter: "blur(20px)",
        border: `1px solid rgba(242,179,76,0.4)`,
        borderRadius: 28,
        padding: "16px 36px",
        display: "flex",
        alignItems: "center",
        gap: 16,
        boxShadow: "0 20px 60px rgba(0,0,0,0.7), 0 0 40px rgba(242,179,76,0.25)",
      }}
    >
      <span style={{ fontSize: 24 }}>👉</span>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span style={{ fontFamily: FONT, fontWeight: 500, fontSize: 14, color: CREAM_DIM }}>
          {EPISODE.cta.lead}
        </span>
        <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 20, color: AMBER, letterSpacing: 0.5 }}>
          {EPISODE.cta.text}
        </span>
      </div>
    </div>
  );
};

// ---- Caption lane (locked karaoke look) -----------------------------------
const CaptionLane: React.FC<{ t: number }> = ({ t }) => {
  const page = CAPTION_PAGES.find((p) => t >= p.start && t < p.end);
  if (!page || !page.words || page.words.length === 0) return null;

  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 30,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        zIndex: 40,
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          background: "rgba(11,14,23,0.85)",
          backdropFilter: "blur(16px)",
          border: "1px solid rgba(245,241,232,0.12)",
          borderRadius: 22,
          padding: "10px 28px",
          boxShadow: "0 12px 36px rgba(0,0,0,0.5)",
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          gap: 6,
          maxWidth: 1200,
        }}
      >
        {page.words.map((w, i) => {
          const isActive = t >= w.s && t < w.e;
          const isPast = t >= w.e;
          return (
            <span
              key={i}
              style={{
                fontFamily: FONT,
                fontWeight: 800,
                fontSize: 27,
                lineHeight: 1.3,
                color: isActive ? GOLD_LIGHT : isPast ? CREAM : "rgba(245,241,232,0.45)",
                textShadow: isActive
                  ? `0 0 16px ${GOLD}, 0 0 28px ${GOLD}`
                  : isPast
                  ? "0 2px 4px rgba(0,0,0,0.6)"
                  : "none",
                transform: isActive ? "scale(1.06)" : "scale(1)",
                transition: "color 0.1s, transform 0.1s",
                display: "inline-block",
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

// ---- Left stage renderer --------------------------------------------------
const LeftStage: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({
  beat, beatEnd, t, fps,
}) => {
  if (beat.media === "clip" && beat.src) {
    return (
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: NAVY_2,
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Museum Card Frame */}
        <div
          style={{
            position: "absolute",
            left: 36,
            right: 36,
            top: 24,
            bottom: 120,
            borderRadius: 16,
            overflow: "hidden",
            boxShadow: "0 14px 40px rgba(0,0,0,0.65), 0 0 0 1px rgba(245,241,232,0.1)",
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
            <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 32, color: CREAM, lineHeight: 1.2 }}>
              {beat.headline}
            </div>
          ) : null}
          {beat.sub ? (
            <div style={{ fontFamily: FONT, fontWeight: 500, fontSize: 18, color: CREAM_DIM, lineHeight: 1.3 }}>
              {beat.sub}
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  if (beat.media === "typo" && beat.typo === "vs") {
    const p1 = clamp01((t - VS.fableT) / 0.5);
    const p2 = clamp01((t - VS.mythosT) / 0.5);
    const s1 = easeOutCubic(p1);
    const s2 = easeOutCubic(p2);
    const vs = EPISODE.vs;

    return (
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: NAVY_2,
          overflow: "hidden",
          padding: "36px 44px",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          boxSizing: "border-box",
        }}
      >
        {/* Background video layer */}
        {beat.src ? (
          <div style={{ position: "absolute", inset: 0, opacity: 0.16 }}>
            <Footage src={beat.src} from={0} beatStart={beat.t} beatEnd={beatEnd} fps={fps} t={t} />
          </div>
        ) : null}

        {/* Header */}
        <div style={{ zIndex: 10, display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 14, letterSpacing: 2, color: AMBER }}>
            {vs.eyebrow}
          </div>
          <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 30, color: CREAM }}>
            {beat.headline || "Flare vs Sunburst"}
          </div>
        </div>

        {/* VS Two Columns */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, zIndex: 10 }}>
          {/* Left: Flare */}
          <div
            style={{
              background: "rgba(11,14,23,0.85)",
              border: `1px solid ${AMBER}55`,
              borderTop: `4px solid ${AMBER}`,
              borderRadius: 16,
              padding: "20px 24px",
              display: "flex",
              flexDirection: "column",
              gap: 12,
              transform: `translateY(${(1 - s1) * 20}px)`,
              opacity: s1,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 24, color: AMBER }}>
                {vs.left.title}
              </span>
              <span style={{ fontFamily: FONT, fontSize: 13, color: CREAM_DIM, background: "rgba(242,179,76,0.15)", padding: "3px 10px", borderRadius: 10 }}>
                {vs.left.badge}
              </span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {vs.left.lines.map((l, i) => (
                <span key={i} style={{ fontFamily: FONT, fontWeight: 500, fontSize: 15, color: CREAM }}>
                  {l}
                </span>
              ))}
            </div>
          </div>

          {/* Right: Sunburst */}
          <div
            style={{
              background: "rgba(11,14,23,0.85)",
              border: `1px solid ${MINT}55`,
              borderTop: `4px solid ${MINT}`,
              borderRadius: 16,
              padding: "20px 24px",
              display: "flex",
              flexDirection: "column",
              gap: 12,
              transform: `translateY(${(1 - s2) * 20}px)`,
              opacity: s2,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 24, color: MINT }}>
                {vs.right.title}
              </span>
              <span style={{ fontFamily: FONT, fontSize: 13, color: CREAM_DIM, background: "rgba(143,214,180,0.15)", padding: "3px 10px", borderRadius: 10 }}>
                {vs.right.badge}
              </span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {vs.right.lines.map((l, i) => (
                <span key={i} style={{ fontFamily: FONT, fontWeight: 500, fontSize: 15, color: CREAM }}>
                  {l}
                </span>
              ))}
            </div>
          </div>
        </div>

        {/* Conclusion footer */}
        <div
          style={{
            zIndex: 10,
            background: "rgba(245,241,232,0.06)",
            border: "1px solid rgba(245,241,232,0.12)",
            borderRadius: 12,
            padding: "10px 18px",
            fontFamily: FONT,
            fontWeight: 500,
            fontSize: 15,
            color: CREAM_DIM,
            textAlign: "center",
          }}
        >
          💡 {vs.conclusion}
        </div>
      </div>
    );
  }

  if (beat.media === "typo" && beat.typo === "summary3") {
    return (
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: NAVY_2,
          overflow: "hidden",
          padding: "44px 50px",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          boxSizing: "border-box",
        }}
      >
        {beat.src ? (
          <div style={{ position: "absolute", inset: 0, opacity: 0.16 }}>
            <Footage src={beat.src} from={0} beatStart={beat.t} beatEnd={beatEnd} fps={fps} t={t} />
          </div>
        ) : null}

        <div style={{ zIndex: 10, display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 14, letterSpacing: 2, color: AMBER }}>
            KEY TAKEAWAYS
          </div>
          <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 32, color: CREAM }}>
            {EPISODE.summary3Label}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 18, zIndex: 10 }}>
          {SUMMARY3.map((item, i) => {
            const active = t >= item.t;
            const p = clamp01((t - item.t) / 0.4);
            const s = easeOutCubic(p);
            return (
              <div
                key={i}
                style={{
                  background: active ? "rgba(11,14,23,0.85)" : "rgba(11,14,23,0.45)",
                  border: `1px solid ${active ? AMBER : "rgba(245,241,232,0.1)"}`,
                  borderLeft: `5px solid ${active ? AMBER : "rgba(245,241,232,0.2)"}`,
                  borderRadius: 14,
                  padding: "16px 22px",
                  display: "flex",
                  alignItems: "center",
                  gap: 16,
                  transform: `translateX(${(1 - s) * -20}px)`,
                  opacity: active ? 1 : 0.4,
                  boxShadow: active ? "0 10px 30px rgba(0,0,0,0.5)" : "none",
                }}
              >
                <span style={{ fontSize: 26 }}>{item.icon}</span>
                <span style={{ fontFamily: FONT, fontWeight: 700, fontSize: 20, color: CREAM }}>
                  {item.text}
                </span>
              </div>
            );
          })}
        </div>

        <div style={{ zIndex: 10, fontFamily: FONT, fontSize: 15, color: CREAM_DIM }}>
          {beat.sub}
        </div>
      </div>
    );
  }

  return null;
};

// ---- EndCard --------------------------------------------------------------
const EndCard: React.FC = () => {
  const cfg = EPISODE.endcard;
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        background: "linear-gradient(135deg, #0B0E17 0%, #182036 100%)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 20,
        zIndex: 100,
      }}
    >
      <div
        style={{
          fontFamily: FONT,
          fontWeight: 700,
          fontSize: 14,
          letterSpacing: 3,
          color: AMBER,
        }}
      >
        {cfg.eyebrow}
      </div>
      <div style={{ textAlign: "center", display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 52, color: CREAM, lineHeight: 1.1 }}>
          {cfg.titleA}
        </div>
        <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 36, color: AMBER, lineHeight: 1.2 }}>
          {cfg.titleB}
        </div>
      </div>
      <div
        style={{
          fontFamily: FONT,
          fontWeight: 500,
          fontSize: 18,
          color: CREAM_DIM,
          maxWidth: 800,
          textAlign: "center",
          lineHeight: 1.4,
        }}
      >
        {cfg.sub}
      </div>
      <div
        style={{
          marginTop: 20,
          background: "rgba(242,179,76,0.15)",
          border: `1px solid ${AMBER}`,
          borderRadius: 24,
          padding: "12px 32px",
          fontFamily: FONT,
          fontWeight: 700,
          fontSize: 18,
          color: AMBER,
          letterSpacing: 1,
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

export type GptImage26NewsV2Props = {
  durationSec?: number;
};

export const calculateGptImage26NewsV2Metadata: CalculateMetadataFunction<GptImage26NewsV2Props> = async () => ({
  durationInFrames: Math.ceil(TOTAL_DURATION_SEC * 25),
  fps: 25,
  width: W,
  height: H,
});

export const GptImage26NewsV2: React.FC<GptImage26NewsV2Props> = () => {
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
