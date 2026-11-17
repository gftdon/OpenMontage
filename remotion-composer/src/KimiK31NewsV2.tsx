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
import { CAPTION_PAGES } from "./kimiK31NewsV2Captions";
import { WEB_CLIPS, WEB_RECTS, WebRect } from "./kimiK31NewsWeb";

// ===========================================================================
// KimiK31NewsV2 — 16:9 AI-news report (1920x1080@25)
// Format "Youtube-YT-News-Style01-V2":
// Report subject: YOUTUBE VIDEO ("Does Kimi K3.1 Pro Replace Opus 5.5? (Full Comparison)")
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
const VO_END_SEC = 531.0;
const TOTAL_DURATION_SEC = 535.4; // + 4.4 s endcard
const MODE_BLEND_SEC = 0.55;

// ---- Episode config (swap per episode — every on-screen string lives here) --
const EPISODE = {
  assetDir: "kimiK31NewsV2", // public/<assetDir>/{avatar_source.mp4, broll/, web/}
  brand: "AI BENCHMARK NEWS",
  dateLabel: "26 ต.ค. 2026",
  page: { domain: "youtube.com", path: "/watch?v=_XXX5K-EMoc" },
  officialTag: "SOURCE · PROMPT ENGINEERING",
  cta: { lead: "ติดตามข่าวสาร AI ได้ที่", text: "youtube.com/@fable" },
  endcard: {
    eyebrow: "AI BENCHMARK NEWS · OCTOBER 2026",
    titleA: "Kimi K3.1 Pro",
    titleB: "vs Opus 5.5",
    sub: "YouTube: Prompt Engineering · Kimi K3.1 Pro and Opus 5.5 (13 Tasks)",
    cta: "กดติดตามเพื่อไม่พลาดทุกข่าวสาร AI",
  },
  summary3Label: "3 ประเด็นสำคัญที่เราจะมาดูกัน",
  final4: {
    title: "แนวทางการเลือกใช้ AI Coding",
    sub: "เลือกตัวที่ใช่ให้เหมาะกับงานและงบประมาณ",
  },
  vs: {
    eyebrow: "BENCHMARK SUMMARY",
    conclusion: "ช่องว่างระหว่างตัวท็อปกับตัวประหยัดแคบลงเรื่อย ๆ",
    left: {
      title: "KIMI K3.1 PRO",
      badge: "MOONSHOT AI · $45.91",
      lines: [
        "✓ ราคาถูกกว่าประมาณ 50%",
        "✓ บิลรวมเพียง 55% ของ Opus",
        "✓ เก่งคุ้มค่าในงานสเกลใหญ่",
      ],
    },
    right: {
      title: "CLAUDE OPUS 5.5",
      badge: "ANTHROPIC · $83.46",
      lines: [
        "✓ โมเดลระดับเรือธงสูงสุด",
        "✓ ความแม่นยำสูง สม่ำเสมอ",
        "✓ เหมาะกับงานสำคัญที่พลาดไม่ได้",
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
  abstract_code_stream: 29.88,
  ai_chatbot_dialogue: 20.88,
  business_tech_team: 14.60,
  chef_plating: 13.56,
  chess_tactics: 18.40,
  city_night_hyperlapse: 10.08,
  cloud_datacenter_servers: 15.32,
  craftsman_carpenter: 8.20,
  digital_particles_wave: 20.16,
  electric_meter: 19.36,
  handshake_deal: 8.08,
  kitchen_modern: 16.60,
  mobile_app_development: 15.00,
  money_calculator: 28.00,
  programming_fingers: 11.08,
  yt_intro_contestants: 15.08,
  yt_13tasks_grid: 15.08,
  yt_four_apps_preview: 15.08,
  yt_cost_preview: 17.08,
  yt_four_groups: 24.08,
  yt_claude_setup: 25.08,
  yt_same_prompts: 25.08,
  yt_nca_growth: 37.08,
  yt_rl_ant: 35.08,
  yt_galaxy_collision: 40.08,
  yt_sdf_dragon: 40.08,
  yt_webgl_planet: 40.08,
  yt_blender_room: 40.08,
  yt_keyboard: 30.08,
  yt_frontend_web: 37.08,
  yt_33rules: 36.08,
  yt_benchmark_table: 25.08,
  yt_cost_table: 35.08,
  yt_caching: 40.08,
  yt_rules_summary: 30.08,
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
  // --- PART 1: INTRO & HOOK (0.00 - 94.42) ---
  {
    t: 0.0,
    mode: "full",
    lower: {
      title: "KIMI K3.1 PRO vs OPUS 5.5",
      sub: "13 LONG-HORIZON AGENTIC CODING TASKS",
      t: 1.5,
      dur: 7.0,
    },
  },
  {
    t: 21.74,
    mode: "pip",
    media: "clip",
    src: "yt_intro_contestants",
    clipFit: "contain",
    kicker: "CONTESTANTS",
    headline: "Kimi K3.1 Pro vs Opus 5.5",
    sub: "ศึก AI สองค่ายใหญ่ระดับท็อป",
    stats: [
      { t: 23.84, big: "KIMI", label: "Moonshot AI", tone: "amber" },
      { t: 32.8, big: "OPUS 5.5", label: "Anthropic", tone: "clay" },
    ],
  },
  {
    t: 25.55,
    mode: "full",
  },
  {
    t: 27.96,
    mode: "pip",
    media: "typo",
    typo: "summary3",
    src: "digital_particles_wave",
    kicker: "AGENDA",
    headline: "3 ประเด็นสำคัญของวันนี้",
  },
  {
    t: 31.83,
    mode: "pip",
    media: "clip",
    src: "yt_cost_preview",
    clipFit: "contain",
    kicker: "PRICE COMPARISON",
    headline: "ราคาถูกกว่าประมาณครึ่งหนึ่ง",
    sub: "ตัวหนึ่งเก่งแต่แพง อีกตัวราคาประหยัด",
    stats: [
      { t: 33.0, big: "TOP TIER", label: "เก่งแต่ราคาสูง", tone: "clay" },
      { t: 39.8, big: "HALF PRICE", label: "ถูกกว่าครึ่งหนึ่ง", tone: "mint" },
    ],
  },
  {
    t: 47.47,
    mode: "full",
  },
  {
    t: 49.76,
    mode: "pip",
    media: "broll",
    src: "craftsman_carpenter",
    kicker: "ANALOGY",
    headline: "เปรียบเหมือนการจ้างช่าง",
    sub: "ช่างฝีมือดีค่าแรงแพง vs ช่างค่าแรงถูกกว่าครึ่ง",
    stats: [
      { t: 55.4, big: "ช่างคนที่ 1", label: "ฝีมือดีแต่แพง", tone: "clay" },
      { t: 57.4, big: "ช่างคนที่ 2", label: "ค่าแรงถูกกว่าครึ่ง", tone: "mint" },
    ],
  },
  {
    t: 66.38,
    mode: "full",
  },
  {
    t: 74.45,
    mode: "pip",
    media: "clip",
    src: "yt_13tasks_grid",
    clipFit: "contain",
    kicker: "THE BENCHMARK",
    headline: "ทดสอบเขียนโปรแกรม 13 งาน",
    sub: "งานที่ยาวและซับซ้อนภายใต้เงื่อนไขเดียวกัน",
    stats: [
      { t: 82.2, big: "13 TASKS", label: "งานเขียนโปรแกรมซับซ้อน", tone: "amber" },
    ],
  },
  {
    t: 88.42,
    mode: "full",
  },

  // --- PART 2: CONTESTANTS & PRICING (94.42 - 205.32) ---
  {
    t: 94.42,
    mode: "pip",
    media: "broll",
    src: "ai_chatbot_dialogue",
    kicker: "AI BASICS",
    headline: "โมเดล AI คืออะไร",
    sub: "โปรแกรมพิมพ์คุยโต้ตอบ เปรียบเหมือนสมองของ AI",
    stats: [
      { t: 101.3, big: "CHATGPT", label: "ตัวอย่างโมเดลภาษายอดนิยม", tone: "amber" },
    ],
  },
  {
    t: 124.98,
    mode: "pip",
    media: "clip",
    src: "yt_claude_setup",
    clipFit: "contain",
    kicker: "CONTESTANT 1",
    headline: "Claude Opus 5.5",
    sub: "โมเดลระดับท็อปจาก Anthropic อเมริกา",
    stats: [
      { t: 127.5, big: "OPUS 5.5", label: "Anthropic USA", tone: "clay" },
      { t: 142.6, big: "CODING", label: "โดดเด่นเรื่องโค้ด", tone: "amber" },
    ],
  },
  {
    t: 147.86,
    mode: "pip",
    media: "clip",
    src: "yt_benchmark_table",
    clipFit: "contain",
    kicker: "CONTESTANT 2",
    headline: "Kimi K3.1 Pro",
    sub: "โมเดลจาก Moonshot AI ประเทศจีน",
    stats: [
      { t: 155.1, big: "MOONSHOT AI", label: "China Flagship", tone: "amber" },
      { t: 168.4, big: "~50% OFF", label: "ราคาถูกกว่าครึ่งหนึ่ง", tone: "mint" },
    ],
  },
  {
    t: 170.91,
    mode: "full",
  },
  {
    t: 175.58,
    mode: "pip",
    media: "broll",
    src: "cloud_datacenter_servers",
    kicker: "AI COST",
    headline: "การใช้งานระดับธุรกิจ",
    sub: "คิดเงินตามปริมาณการใช้งานจริง",
  },
  {
    t: 184.14,
    mode: "pip",
    media: "broll",
    src: "electric_meter",
    kicker: "UTILITY BILL",
    headline: "คิดเงินคล้ายค่าไฟ",
    sub: "ยิ่งใช้งานเยอะ ยิ่งต้องจ่ายเยอะ",
    stats: [
      { t: 187.6, big: "USAGE-BASED", label: "คิดค่าบริการตาม Token", tone: "amber" },
    ],
  },
  {
    t: 191.36,
    mode: "pip",
    media: "broll",
    src: "money_calculator",
    kicker: "SAVINGS IMPACT",
    headline: "ส่วนต่างครึ่งหนึ่ง",
    sub: "อาจประหยัดได้หลักหมื่นถึงหลักแสนบาท",
    stats: [
      { t: 198.1, big: "หลักหมื่น", label: "ประหยัดต้นทุน", tone: "mint" },
      { t: 198.9, big: "หลักแสน+", label: "สำหรับบริษัทใหญ่", tone: "mint" },
    ],
  },

  // --- PART 3: LONG-HORIZON AGENTIC TASKS (205.32 - 308.19) ---
  {
    t: 205.32,
    mode: "full",
  },
  {
    t: 217.44,
    mode: "pip",
    media: "broll",
    src: "mobile_app_development",
    kicker: "TERM 1 · CODING",
    headline: "Coding คือการเขียนโปรแกรม",
    sub: "สั่งการคอมพิวเตอร์สร้างแอปและเว็บไซต์",
  },
  {
    t: 232.50,
    mode: "pip",
    media: "clip",
    src: "yt_same_prompts",
    clipFit: "contain",
    kicker: "TERM 2 · AGENTIC",
    headline: "Agentic คือ AI ลงมือทำเอง",
    sub: "เปิดไฟล์ อ่านโค้ด แก้ไข ทดลองรันอัตโนมัติ",
    stats: [
      { t: 242.4, big: "AUTONOMOUS", label: "ทำงานหลายขั้นตอนเอง", tone: "amber" },
      { t: 247.8, big: "LOOP", label: "อ่าน แก้ไข ทดลองรัน", tone: "mint" },
    ],
  },
  {
    t: 256.20,
    mode: "pip",
    media: "broll",
    src: "chess_tactics",
    kicker: "TERM 3 · LONG-HORIZON",
    headline: "งานยาวขอบฟ้าไกล",
    sub: "ต้องวางแผนต่อเนื่องหลายขั้นตอน ไม่หลงทาง",
  },
  {
    t: 267.84,
    mode: "full",
  },
  {
    t: 274.64,
    mode: "pip",
    media: "broll",
    src: "kitchen_modern",
    kicker: "ANALOGY",
    headline: "รีโนเวทห้องครัวคืองานยาว",
    sub: "วางแผน รื้อของ จัดซื้อ ติดตั้ง ตรวจสอบ",
    stats: [
      { t: 280.3, big: "PLAN", label: "วางแผนงานล่วงหน้า", tone: "amber" },
      { t: 284.6, big: "VERIFY", label: "ตรวจสอบทุกขั้นตอน", tone: "mint" },
    ],
  },
  {
    t: 289.42,
    mode: "pip",
    media: "clip",
    src: "yt_four_groups",
    clipFit: "contain",
    kicker: "THE 13 TASKS",
    headline: "โจทย์ใหญ่ 13 งานใน 4 กลุ่ม",
    sub: "จำสิ่งที่ทำ คิดต่อเนื่อง ไม่หลงทางกลางคัน",
    stats: [
      { t: 294.4, big: "13 TASKS", label: "งานสเกลใหญ่", tone: "amber" },
      { t: 301.2, big: "CONTEXT", label: "รักษาบริบทต่อเนื่อง", tone: "mint" },
    ],
  },

  // --- PART 4: FAIR TESTING IN CLAUDE CODE (308.19 - 416.32) ---
  {
    t: 308.19,
    mode: "full",
  },
  {
    t: 321.57,
    mode: "pip",
    media: "clip",
    src: "yt_four_apps_preview",
    clipFit: "contain",
    kicker: "CONDITION 1",
    headline: "ใช้เครื่องมือเดียวกัน: Claude Code",
    sub: "โต๊ะทำงานเปิดไฟล์ แก้ไข และรันโค้ด",
    stats: [
      { t: 324.0, big: "CLAUDE CODE", label: "สภาพแวดล้อมเดียวกัน", tone: "amber" },
    ],
  },
  {
    t: 335.14,
    mode: "pip",
    media: "clip",
    src: "yt_33rules",
    clipFit: "contain",
    kicker: "CONDITION 2 & 3",
    headline: "คำสั่งเดิม & Effort เท่ากัน",
    sub: "ไม่มีใครได้คำใบ้ ใช้แรงคิดระดับเดียวกัน",
    stats: [
      { t: 336.8, big: "SAME PROMPT", label: "ตัวอักษรต่อตัวอักษร", tone: "amber" },
      { t: 344.0, big: "EQUAL EFFORT", label: "แรงคิดเท่ากัน", tone: "mint" },
    ],
  },
  {
    t: 349.14,
    mode: "pip",
    media: "clip",
    src: "yt_cost_table",
    clipFit: "contain",
    kicker: "CONDITION 4",
    headline: "ตรวจคะแนนอัตโนมัติ",
    sub: "เปลี่ยนเฉพาะชื่อโมเดล AI เท่านั้น",
    stats: [
      { t: 354.1, big: "AUTO-GRADE", label: "ตรวจด้วยสคริปต์", tone: "mint" },
      { t: 361.8, big: "MODEL STRING", label: "สิ่งเดียวที่เปลี่ยน", tone: "amber" },
    ],
  },
  {
    t: 363.30,
    mode: "pip",
    media: "broll",
    src: "chef_plating",
    kicker: "ANALOGY",
    headline: "เหมือนการแข่งทำอาหาร",
    sub: "ครัวเดียวกัน วัตถุดิบเดียวกัน โจทย์เดียวกัน",
    stats: [
      { t: 379.4, big: "REAL SKILL", label: "วัดกันที่ฝีมือแท้จริง", tone: "amber" },
    ],
  },
  {
    t: 387.40,
    mode: "full",
  },
  {
    t: 392.69,
    mode: "pip",
    media: "clip",
    src: "yt_nca_growth",
    clipFit: "contain",
    kicker: "TASK 1 · RESEARCH",
    headline: "Neural Cellular Automata",
    sub: "ความถูกต้องและความสม่ำเสมอของงาน",
    stats: [
      { t: 398.5, big: "CONSISTENT", label: "ทำได้สม่ำเสมอ", tone: "mint" },
      { t: 402.1, big: "VALUE", label: "เทียบความคุ้มค่า", tone: "amber" },
    ],
  },
  {
    t: 403.20,
    mode: "pip",
    media: "clip",
    src: "yt_rl_ant",
    clipFit: "contain",
    kicker: "TASK 2 · REINFORCEMENT LEARNING",
    headline: "RL Ant Robot Simulation",
    sub: "หากตัวถูกทำงานได้ใกล้เคียง ถือเป็นข่าวดี",
    stats: [
      { t: 405.1, big: "~50% COST", label: "ประหยัดต้นทุนครึ่งหนึ่ง", tone: "mint" },
    ],
  },
  {
    t: 410.62,
    mode: "pip",
    media: "clip",
    src: "yt_sdf_dragon",
    clipFit: "contain",
    kicker: "TASK 3 · 3D SDF DRAGON",
    headline: "งานยากซับซ้อนสูง",
    sub: "ตัวที่แพงกว่าอาจคุ้มกว่าในระยะยาว",
    stats: [
      { t: 414.7, big: "ACCURACY", label: "ความแม่นยำในงานยาก", tone: "clay" },
    ],
  },

  // --- PART 5: IMPLICATIONS FOR USERS & SUMMARY (416.32 - 531.00) ---
  {
    t: 416.32,
    mode: "full",
  },
  {
    t: 422.60,
    mode: "pip",
    media: "clip",
    src: "yt_galaxy_collision",
    clipFit: "contain",
    kicker: "BENEFIT 1",
    headline: "การแข่งขันทำให้ AI ถูกลง",
    sub: "เจ้าใหญ่ต้องปรับตัว ทั้งเรื่องราคาและคุณภาพ",
    stats: [
      { t: 425.5, big: "CHEAPER AI", label: "ราคาเข้าถึงง่ายขึ้น", tone: "mint" },
      { t: 436.7, big: "WINNER", label: "ผู้ใช้งานได้ประโยชน์", tone: "amber" },
    ],
  },
  {
    t: 438.94,
    mode: "pip",
    media: "clip",
    src: "yt_frontend_web",
    clipFit: "contain",
    kicker: "BENEFIT 2",
    headline: "แอปและบริการดีขึ้นเร็วขึ้น",
    sub: "บริษัทลดต้นทุน นำ AI ช่วยพัฒนาเร็วขึ้น",
  },
  {
    t: 451.02,
    mode: "pip",
    media: "broll",
    src: "business_tech_team",
    kicker: "BENEFIT 3",
    headline: "ทางเลือกสำหรับธุรกิจ",
    sub: "ไม่จำเป็นต้องเลือกตัวที่แพงที่สุดเสมอไป",
    stats: [
      { t: 455.9, big: "MORE CHOICES", label: "ทางเลือกหลากหลาย", tone: "mint" },
    ],
  },
  {
    t: 461.08,
    mode: "full",
  },
  {
    t: 463.94,
    mode: "pip",
    media: "broll",
    src: "programming_fingers",
    kicker: "SMART STRATEGY",
    headline: "งานทั่วไปใช้งานตัวประหยัด",
    sub: "งานซ้ำ ๆ หรืองานที่พลาดได้เพื่อประหยัดต้นทุน",
    stats: [
      { t: 470.8, big: "ROUTINE", label: "ใช้โมเดลราคาถูก", tone: "mint" },
    ],
  },
  {
    t: 472.30,
    mode: "pip",
    media: "clip",
    src: "yt_caching",
    clipFit: "contain",
    kicker: "MISSION CRITICAL",
    headline: "งานสำคัญยอมจ่ายแพงขึ้น",
    sub: "งานยาวที่พลาดไม่ได้ เพื่อความมั่นใจสูงสุด",
    stats: [
      { t: 478.2, big: "CRITICAL", label: "ใช้ตัวท็อปเพื่อความมั่นใจ", tone: "amber" },
    ],
  },
  {
    t: 479.40,
    mode: "pip",
    media: "clip",
    src: "yt_rules_summary",
    clipFit: "contain",
    kicker: "VERIFY YOURSELF",
    headline: "อย่าเชื่อแค่ชื่อเสียงหรือราคา",
    sub: "ทดสอบกับงานจริงของตัวเองเสมอ",
  },
  {
    t: 489.76,
    mode: "full",
  },
  {
    t: 491.90,
    mode: "pip",
    media: "typo",
    typo: "vs",
    kicker: "VS COMPARISON",
    src: "abstract_code_stream",
  },
  {
    t: 509.32,
    mode: "pip",
    media: "typo",
    typo: "final4",
    kicker: "KEY TAKEAWAY",
    src: "city_night_hyperlapse",
  },
  {
    t: 518.12,
    mode: "full",
  },
];

// Typo scene word times
const SUMMARY3 = [
  { t: 28.5, text: "1 · รู้จักโมเดล AI ทั้งสองตัว", icon: "🤖" },
  { t: 29.5, text: "2 · โจทย์เขียนโค้ด 13 งาน", icon: "🧪" },
  { t: 30.5, text: "3 · ใครคุ้มค่าที่สุด", icon: "💡" },
];

const FINAL4 = [
  { t: 510.5, text: "1 · ประเมินความเสี่ยงของงาน", icon: "🎯" },
  { t: 512.2, text: "2 · งานทั่วไปเลือกตัวประหยัด", icon: "💸" },
  { t: 514.5, text: "3 · งานสำคัญเลือกตัวท็อป", icon: "🛡️" },
  { t: 516.5, text: "4 · ทดสอบกับงานจริงของตัวเอง", icon: "⚡" },
];

const VS = { fableT: 494.0, mythosT: 497.0, subT: 504.6 };
const CTA_T = 524.0;

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
        background: "rgba(11, 14, 23, 0.6)",
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

// official clip inside the stage frame (light/dark museum-card look)
const ClipStage: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, beatEnd, t, fps }) => {
  const src = beat.src || "yt_cost_table";
  const dur = BROLL_DUR[src] || 5;
  const loopFrames = Math.max(1, Math.floor(dur * fps) - 1);
  const local = Math.round((t - beat.t) * fps);
  const a = springIn(local - 2, fps, 18, 120);
  const subOn = beat.sub && t >= (beat.subT ?? beat.t + 1.2);
  const hasStats = Boolean(beat.stats && beat.stats.length > 0);
  return (
    <div style={{ position: "absolute", inset: 0, background: "#0D111A", overflow: "hidden" }}>
      <div style={{ position: "absolute", inset: 0 }}>
        <Loop durationInFrames={loopFrames} layout="none">
          <OffthreadVideo muted src={staticFile(`${EPISODE.assetDir}/broll/${src}.mp4`)} style={{ width: "100%", height: "100%", objectFit: beat.clipFit ?? "contain" }} />
        </Loop>
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: hasStats ? 200 : 260, background: "linear-gradient(0deg, rgba(11,14,23,0.86), rgba(11,14,23,0.0))" }} />
      {!hasStats && beat.headline ? (
        <div style={{ position: "absolute", left: 40, bottom: 34, width: 1120, zIndex: 5 }}>
          <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 46, color: CREAM, textShadow: "0 4px 22px rgba(0,0,0,0.6)", opacity: a, transform: `translateY(${(1 - a) * 18}px)` }}>
            {beat.headline}
          </div>
          {subOn ? (
            <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 22, color: CREAM_DIM, marginTop: 6 }}>{beat.sub}</div>
          ) : null}
        </div>
      ) : null}
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
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 52, color: CREAM, lineHeight: 1.05 }}>{title}</div>
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
  const enterKicker = springIn(Math.round((t - beat.t) * fps), fps, 16, 130);
  return (
    <div
      style={{
        position: "absolute",
        left: STAGE.x,
        top: 34,
        right: W - (STAGE.x + STAGE.w),
        height: 48,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        zIndex: 40,
        pointerEvents: "none",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            background: "rgba(11, 14, 23, 0.8)",
            border: "1px solid rgba(245,241,232,0.16)",
            borderRadius: 10,
            padding: "6px 14px",
            boxShadow: "0 6px 20px rgba(0,0,0,0.4)",
          }}
        >
          <div style={{ width: 8, height: 8, borderRadius: "50%", background: CLAY }} />
          <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 15, letterSpacing: 2, color: CREAM }}>
            {EPISODE.brand}
          </span>
        </div>

        {beat.mode === "pip" && beat.kicker ? (
          <div
            style={{
              fontFamily: MONO,
              fontWeight: 700,
              fontSize: 12.5,
              letterSpacing: 2.5,
              color: NAVY,
              background: AMBER,
              borderRadius: 8,
              padding: "5px 12px",
              opacity: enterKicker * p,
              transform: `translateX(${(1 - enterKicker) * -10}px)`,
              boxShadow: "0 4px 14px rgba(242,179,76,0.4)",
            }}
          >
            {beat.kicker}
          </div>
        ) : null}
      </div>

      <div
        style={{
          fontFamily: MONO,
          fontSize: 13,
          letterSpacing: 2,
          color: CREAM_DIM,
          background: "rgba(11, 14, 23, 0.6)",
          padding: "5px 12px",
          borderRadius: 8,
          border: "1px solid rgba(245,241,232,0.1)",
        }}
      >
        {EPISODE.dateLabel}
      </div>
    </div>
  );
};

const LowerThird: React.FC<{ beat: Beat; t: number; fps: number }> = ({ beat, t, fps }) => {
  if (!beat.lower) return null;
  const l = beat.lower;
  const startT = beat.t + (l.t ?? 0);
  const dur = l.dur ?? 5;
  const dt = t - startT;
  if (dt < 0 || dt > dur) return null;
  const enter = springIn(Math.round(dt * fps), fps, 16, 120);
  const exit = dt > dur - 0.4 ? clamp01((dur - dt) / 0.4) : 1;
  const alpha = enter * exit;

  return (
    <div
      style={{
        position: "absolute",
        left: STAGE.x,
        bottom: 120,
        zIndex: 45,
        opacity: alpha,
        transform: `translateY(${(1 - enter) * 20}px)`,
        pointerEvents: "none",
        maxWidth: 1000,
      }}
    >
      <div
        style={{
          display: "inline-block",
          fontFamily: MONO,
          fontWeight: 800,
          fontSize: 13,
          letterSpacing: 3,
          color: NAVY,
          background: CLAY,
          padding: "5px 14px",
          borderRadius: 6,
          marginBottom: 10,
        }}
      >
        BREAKING REPORT
      </div>
      <div
        style={{
          fontFamily: FONT,
          fontWeight: 800,
          fontSize: 56,
          color: CREAM,
          lineHeight: 1.1,
          textShadow: "0 6px 28px rgba(0,0,0,0.85)",
        }}
      >
        {l.title}
      </div>
      <div
        style={{
          fontFamily: FONT,
          fontWeight: 600,
          fontSize: 24,
          color: AMBER,
          marginTop: 6,
          textShadow: "0 2px 14px rgba(0,0,0,0.8)",
        }}
      >
        {l.sub}
      </div>
    </div>
  );
};

const CtaChip: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  if (t < CTA_T || t >= VO_END_SEC) return null;
  const dt = t - CTA_T;
  const enter = springIn(Math.round(dt * fps), fps, 16, 120);
  return (
    <div
      style={{
        position: "absolute",
        left: STAGE.x,
        bottom: 120,
        zIndex: 48,
        opacity: enter,
        transform: `translateY(${(1 - enter) * 16}px)`,
        pointerEvents: "none",
        display: "flex",
        alignItems: "center",
        gap: 14,
        background: "rgba(11, 14, 23, 0.9)",
        border: `2px solid ${AMBER}`,
        borderRadius: 16,
        padding: "12px 24px",
        boxShadow: `0 14px 40px rgba(0,0,0,0.6), 0 0 24px rgba(242,179,76,0.35)`,
      }}
    >
      <span style={{ fontSize: 28 }}>👉</span>
      <span style={{ fontFamily: FONT, fontWeight: 700, fontSize: 24, color: CREAM }}>{EPISODE.cta.lead}</span>
      <span style={{ fontFamily: MONO, fontWeight: 800, fontSize: 24, color: AMBER }}>{EPISODE.cta.text}</span>
    </div>
  );
};

const ProgressBar: React.FC<{ totalFrames: number }> = ({ totalFrames }) => {
  const frame = useCurrentFrame();
  const progress = clamp01(frame / Math.max(1, totalFrames));
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
export type KimiK31NewsV2Props = { durationSec?: number };

export const calculateKimiK31NewsV2Metadata: CalculateMetadataFunction<KimiK31NewsV2Props> = ({ props }) => {
  const fps = 25;
  const durationSec = props.durationSec || TOTAL_DURATION_SEC;
  return { durationInFrames: Math.ceil(durationSec * fps), fps, width: W, height: H };
};

export const KimiK31NewsV2: React.FC<KimiK31NewsV2Props> = ({ durationSec = TOTAL_DURATION_SEC }) => {
  useThaiFonts();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const totalFrames = Math.ceil(durationSec * fps);

  let beatIdx = 0;
  for (let i = 0; i < BEATS.length; i++) if (t >= BEATS[i].t) beatIdx = i;
  const beat = BEATS[beatIdx];
  const beatEndOf = (i: number) => (i + 1 < BEATS.length ? BEATS[i + 1].t : VO_END_SEC);

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
          <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 300, background: "linear-gradient(180deg, transparent, rgba(11,14,23,0.55))", opacity: 1 - p, pointerEvents: "none" }} />
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
