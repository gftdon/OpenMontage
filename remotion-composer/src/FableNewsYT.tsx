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
import { CAPTION_PAGES } from "./fableNewsCaptions";
import { WEB_CLIPS, WEB_RECTS, WebRect } from "./fableNewsWeb";

// ===========================================================================
// FableNewsYT — 16:9 AI-news report (1920x1080@25)
// Format: one continuous avatar that morphs between FULL-FRAME and a 9:16
// "anchor card" pinned to the right; the left stage carries a live browser
// view of the real anthropic.com launch page (camera pans/zooms + marker
// highlights synced to what the presenter says), full-bleed b-roll with
// kinetic Thai headlines, official Anthropic clips, and typography scenes.
// Timing spine = whisper word timing (fableNewsCaptions.ts), never the SRT.
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
const VO_END_SEC = 455.6;
const TOTAL_DURATION_SEC = 460.0;
const MODE_BLEND_SEC = 0.55;

// ---- Episode config (swap per episode — every on-screen string lives here) --
const EPISODE = {
  assetDir: "fable-news", // public/<assetDir>/{avatar_source.mp4, broll/, web/}
  brand: "AI NEWS",
  dateLabel: "3 ก.ย. 2026",
  page: { domain: "anthropic.com", path: "/claude-fable-and-mythos-5-1" }, // browser chrome URL pill
  officialTag: "OFFICIAL · ANTHROPIC", // tag on `clip` beats
  cta: { lead: "ลองใช้ได้เลยที่", text: "claude.ai" },
  endcard: {
    eyebrow: "AI NEWS · SEPTEMBER 2026",
    titleA: "Claude Fable 5.1",
    titleB: "Mythos 5.1",
    sub: "อ่านฉบับเต็ม · anthropic.com/claude-fable-and-mythos-5-1",
    cta: "ลองใช้ได้เลยที่ claude.ai",
  },
  summary3Label: "สรุปง่าย ๆ",
  final4: { title: "Claude Fable 5.1", sub: "AI ที่ฉลาดที่สุดในโลกตอนนี้" },
  vs: {
    eyebrow: "AI ตัวเดียวกัน · ฉลาดเท่ากัน · ต่างกันที่ “ใครใช้ได้”",
    left: { title: "Fable 5.1", badge: "GENERALLY AVAILABLE", lines: ["ทุกคนใช้ได้เลย", "claude.ai · API", "Claude Code · Cowork"] },
    right: { title: "Mythos 5.1", badge: "TRUSTED ACCESS", lines: ["เฉพาะนักวิจัย · ผู้เชี่ยวชาญ", "สายวิทยาศาสตร์ + ไซเบอร์", "ที่ผ่านการตรวจสอบแล้วเท่านั้น"] },
    conclusion: "🔓 Mythos ปลดล็อคความสามารถที่ต้องใช้ความรับผิดชอบสูง",
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

// ---- B-roll durations (public/<assetDir>/broll, 1080p25; transcode_broll.sh prints them) ----
const BROLL_DUR: Record<string, number> = {
  abstract: 30, ai_network: 30, brain: 10, chat_ai: 19.48, city_night: 22.36,
  coding: 14.96, cyber: 30, datacenter: 9.12, dna: 8.32, handshake: 11.48,
  lab: 15.2, microscope: 8, molecule: 18.64, nipah: 4.96, office: 14.8,
  protein: 14.2, server_lights: 23.52, shopping: 10, trading: 8, typing: 12.16,
  venus: 30, venus_volcano: 15, warehouse: 20.44,
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
  { t: 0.0, mode: "full", lower: { title: "ข่าวใหญ่วงการ AI", sub: "Anthropic เปิดตัว Claude Fable 5.1 & Mythos 5.1", t: 1.3, dur: 5.2 } },
  // ---- launch -----------------------------------------------------------
  {
    t: 13.34, mode: "pip", media: "web", file: "sec_hero", kicker: "เปิดตัว 2 รุ่นใหม่พร้อมกัน",
    cam: [{ t: 0, fy: 400, z: 1.0 }, { t: 6.5, fy: 380, z: 1.1 }],
  },
  {
    t: 20.06, mode: "pip", media: "web", file: "sec_hero", kicker: "Claude Fable 5.1 · Claude Mythos 5.1",
    cam: [{ t: 0, fy: 370, z: 1.28 }, { t: 4, fy: 360, z: 1.36 }],
    stats: [{ t: 20.3, big: "Fable 5.1", label: "เวอร์ชันสำหรับทุกคน" }, { t: 22.6, big: "Mythos 5.1", label: "เวอร์ชันนักวิจัย", tone: "clay" }],
  },
  { t: 24.1, mode: "pip", media: "broll", src: "chat_ai", headline: "Claude คืออะไร?", sub: "AI ผู้ช่วยอัจฉริยะ พิมพ์คุยได้ · สั่งงานได้", subT: 27.2, kicker: "รู้จัก Claude" },
  {
    t: 34.0, mode: "pip", media: "broll", src: "office", from: 1, headline: "ช่วยได้ทุกงาน", kicker: "รู้จัก Claude",
    stats: [{ t: 34.3, label: "✍️ เขียนงาน" }, { t: 35.5, label: "📊 วิเคราะห์ข้อมูล" }, { t: 37.2, label: "💻 เขียนโปรแกรม" }, { t: 39.0, label: "💡 คิดไอเดียธุรกิจ" }],
  },
  { t: 41.3, mode: "full" },
  // ---- 3 upgrades -------------------------------------------------------
  { t: 43.52, mode: "pip", media: "broll", src: "coding", idx: "01", headline: "เขียนโค้ดเก่งที่สุดในโลก", sub: "ณ ตอนนี้ — ชนะ AI ของทุกบริษัท", subT: 47.5, kicker: "เก่งขึ้นยังไง · ข้อ 1" },
  {
    t: 49.96, mode: "pip", media: "web", file: "sec_table", kicker: "ผลทดสอบ Agentic coding",
    cam: [{ t: 0, fy: 330, z: 1.05 }, { t: 3, fy: 300, z: 1.22 }],
    hl: [
      { t: 50.6, rect: colRect("Fable 5.1", rowRect("Fable 5.1 Fable 5")) },
      { t: 52.0, rect: rowRect("Agentic coding Terminal") },
      { t: 54.2, rect: colRect("GPT", rowRect("Fable 5.1 Fable 5")) },
    ],
    stats: [{ t: 52.4, big: "55.8%", label: "Fable 5.1 · Terminal-Bench 4.0" }, { t: 54.4, big: "37.3%", label: "GPT-5.6 Sol", tone: "clay" }],
  },
  {
    t: 57.8, mode: "pip", media: "broll", src: "office", from: 5, idx: "02", headline: "งานความรู้ทั่วไป", kicker: "เก่งขึ้นยังไง · ข้อ 2",
    stats: [{ t: 60.4, label: "📄 วิเคราะห์เอกสาร" }, { t: 62.0, label: "📝 ทำรายงาน" }, { t: 63.9, label: "🧾 สรุปข้อมูล" }],
  },
  {
    t: 65.17, mode: "pip", media: "web", file: "quote_10", kicker: "ละเอียดขึ้น · แม่นยำขึ้น · อ่านง่ายขึ้น",
    cam: [{ t: 0, fy: 168, z: 1.46, fx: 535 }, { t: 7, fy: 168, z: 1.54, fx: 535 }],
    hl: [{ t: 69.5, key: "q_canva_writing" }],
    stats: [{ t: 65.6, label: "🗣️ Canva · Head of AI" }],
  },
  {
    t: 73.06, mode: "pip", media: "web", file: "quote_00", kicker: "งานยาวแค่ไหน ผลลัพธ์ก็ยังอ่านรู้เรื่อง",
    cam: [{ t: 0, fy: 168, z: 1.46, fx: 535 }, { t: 8, fy: 168, z: 1.54, fx: 535 }],
    hl: [{ t: 77.4, key: "q_js_readable" }],
    stats: [{ t: 73.5, label: "🗣️ Jane Street Capital" }],
  },
  { t: 82.2, mode: "pip", media: "broll", src: "brain", idx: "03", headline: "แก้ปัญหาที่ยากมาก ๆ", sub: "คิดลึก · หาต้นตอของปัญหา", subT: 86.5, kicker: "เก่งขึ้นยังไง · ข้อ 3" },
  {
    t: 85.78, mode: "pip", media: "web", file: "sec_millennium", kicker: "ไม่ใช่แค่แก้ที่ปลายเหตุ",
    cam: [{ t: 0, fy: 120, z: 1.56 }, { t: 12, fy: 120, z: 1.64 }],
    hl: [{ t: 87.8, key: "mill_avoid" }, { t: 90.5, key: "mill_root" }, { t: 96.0, key: "mill_none" }],
    stats: [{ t: 98.4, label: "🔎 Claude Fable 5.1 หาสาเหตุจริง ๆ" }],
  },
  { t: 101.7, mode: "full" },
  // ---- customer stories -------------------------------------------------
  { t: 108.2, mode: "pip", media: "broll", src: "trading", idx: "CASE 1", headline: "Millennium", sub: "บริษัทการเงินระดับโลก", subT: 109.5, kicker: "ตัวอย่างจากบริษัทจริง" },
  {
    t: 111.56, mode: "pip", media: "web", file: "quote_02", kicker: "Millennium · บั๊กที่ไม่มีใครหาเจอ",
    cam: [{ t: 0, fy: 168, z: 1.46, fx: 535 }, { t: 12, fy: 168, z: 1.54, fx: 535 }],
    hl: [{ t: 116.4, key: "q_mill_million" }, { t: 121.0, key: "q_mill_years" }],
    stats: [{ t: 117.1, big: "1 ใน 1,000,000", label: "โอกาสเกิดบั๊ก" }, { t: 121.3, big: "4–5 ปี", label: "ไม่มีใครหาสาเหตุเจอ", tone: "clay" }],
  },
  { t: 125.62, mode: "pip", media: "broll", src: "coding", from: 6, headline: "แกะโค้ด · วิเคราะห์ crash", sub: "หาต้นตอที่ซ่อนอยู่ในระบบภายนอก", subT: 128.7, kicker: "Millennium" },
  {
    t: 132.02, mode: "pip", media: "web", file: "quote_02", kicker: "Millennium · ครั้งแรกในรอบ 5 ปี",
    cam: [{ t: 0, fy: 168, z: 1.52, fx: 535 }, { t: 6, fy: 168, z: 1.6, fx: 535 }],
    hl: [{ t: 133.0, key: "q_mill_first" }],
    stats: [{ t: 135.9, big: "ครั้งแรกใน 5 ปี", label: "ที่มีใครหาบั๊กนี้เจอ" }],
  },
  { t: 138.7, mode: "pip", media: "broll", src: "datacenter", idx: "CASE 2", headline: "MongoDB", sub: "สร้าง prototype ระบบใหม่", subT: 140.5, kicker: "ตัวอย่างจากบริษัทจริง" },
  {
    t: 141.9, mode: "pip", media: "web", file: "quote_03", kicker: "MongoDB · ทำงานเองจนเสร็จ",
    cam: [{ t: 0, fy: 168, z: 1.46, fx: 535 }, { t: 13, fy: 168, z: 1.54, fx: 535 }],
    hl: [{ t: 145.4, key: "q_mongo_3days" }],
    stats: [{ t: 146.1, big: "3 วัน", label: "สร้าง prototype เสร็จ" }, { t: 148.0, label: "🤖 ทำงานเอง ไม่ต้องมีคนคอยดู" }, { t: 150.1, label: "🌅 ตื่นเช้ามางานเสร็จพร้อมสรุป" }],
  },
  { t: 155.7, mode: "pip", media: "broll", src: "microscope", idx: "CASE 3", headline: "Rakuten", sub: "ตรวจสอบงานวิจัยทางคลินิก", subT: 157.5, kicker: "ตัวอย่างจากบริษัทจริง" },
  {
    t: 160.1, mode: "pip", media: "web", file: "quote_07", kicker: "Rakuten · เจอสิ่งที่ AI อื่นมองข้าม",
    cam: [{ t: 0, fy: 168, z: 1.46, fx: 535 }, { t: 16, fy: 168, z: 1.56, fx: 535 }],
    hl: [{ t: 162.9, key: "q_rak_three" }],
    stats: [{ t: 163.2, big: "AI 3 ตัว", label: "ตรวจแล้วบอกว่า “ผ่าน”", tone: "clay" }, { t: 167.0, label: "⚠️ Fable 5.1 เจอจุดบกพร่อง" }, { t: 172.4, label: "🧪 เสนอสมมติฐานใหม่ ในบ่ายเดียว" }],
  },
  { t: 176.3, mode: "pip", media: "broll", src: "warehouse", idx: "CASE 4", headline: "Shopify", sub: "ทำงานยาว ๆ ได้ดีมาก", subT: 178.8, kicker: "ตัวอย่างจากบริษัทจริง" },
  {
    t: 179.9, mode: "pip", media: "web", file: "quote_17", kicker: "Shopify · ทำงานหลายชั่วโมงไม่หลุดประเด็น",
    cam: [{ t: 0, fy: 168, z: 1.46, fx: 535 }, { t: 12, fy: 168, z: 1.54, fx: 535 }],
    hl: [{ t: 181.4, key: "q_shop_long" }],
    stats: [{ t: 183.1, label: "⏱️ ปล่อยทำงานหลายชั่วโมง" }, { t: 185.0, label: "🗒️ จดบันทึกเอง · จัดลำดับเอง" }, { t: 188.5, label: "▶️ ทำต่อจากจุดที่ค้างไว้" }],
  },
  // ---- pricing ----------------------------------------------------------
  {
    t: 191.72, mode: "pip", media: "web", file: "sec_cost", kicker: "ราคา · ถูกลงกว่าเดิม",
    cam: [{ t: 0, fy: 330, z: 1.2 }, { t: 3.5, fy: 380, z: 1.2 }, { t: 7.5, fy: 880, z: 1.05 }, { t: 16, fy: 880, z: 1.1 }],
    hl: [{ t: 194.5, key: "cost_25" }, { t: 202.0, key: "cost_45" }],
    stats: [{ t: 198.3, big: "−25%", label: "งานทั่วไป", tone: "mint" }, { t: 206.1, big: "−45%", label: "งานหนัก / agentic", tone: "mint" }],
  },
  { t: 208.1, mode: "pip", media: "typo", typo: "summary3", src: "abstract", kicker: "สรุปง่าย ๆ" },
  { t: 213.86, mode: "full" },
  // ---- science ----------------------------------------------------------
  { t: 219.4, mode: "pip", media: "broll", src: "lab", headline: "งานวิจัยวิทยาศาสตร์", sub: "อาจเปลี่ยนโลกไปเลย", subT: 223.2, kicker: "เรื่องที่น่าทึ่งที่สุด" },
  {
    t: 225.9, mode: "pip", media: "web", file: "sec_science", idx: "01", kicker: "① การออกแบบยา",
    cam: [{ t: 0, fy: 130, z: 1.1 }, { t: 4, fy: 300, z: 1.22 }, { t: 8, fy: 330, z: 1.22 }],
    hl: [{ t: 227.6, key: "sci_title" }],
  },
  { t: 233.96, mode: "pip", media: "broll", src: "molecule", headline: "โปรตีนจับเป้าหมายในร่างกาย", sub: "เหมือนกุญแจที่ต้องเข้ากับแม่กุญแจพอดี", subT: 238.0, kicker: "① การออกแบบยา" },
  { t: 240.74, mode: "pip", media: "clip", src: "nipah", headline: "Claude Mythos 5.1 ออกแบบโปรตีน", sub: "ที่มา: anthropic.com — โปรตีนที่ Claude ออกแบบ (สีส้ม) จับเป้าหมาย (สีเทา)", subT: 245.6, kicker: "① การออกแบบยา" },
  { t: 247.5, mode: "pip", media: "broll", src: "lab", from: 7, headline: "ทดสอบในห้องแล็บจริง", sub: "ผลปรากฏว่า…", subT: 251.0, kicker: "① การออกแบบยา" },
  {
    t: 253.6, mode: "pip", media: "web", file: "sec_science", kicker: "ก้าวกระโดดในวงการยา",
    cam: [{ t: 0, fy: 470, z: 1.32 }, { t: 14, fy: 490, z: 1.38 }],
    hl: [{ t: 254.9, key: "sci_10x" }, { t: 257.6, key: "sci_50" }, { t: 261.3, key: "sci_1015" }],
    stats: [{ t: 255.3, big: "10×", label: "จับได้ดีกว่าของมนุษย์", tone: "mint" }, { t: 257.8, big: "~50%", label: "อัตราสำเร็จ", tone: "mint" }, { t: 261.4, big: "10–15%", label: "ปกติทั่วไป", tone: "clay" }],
  },
  { t: 268.0, mode: "pip", media: "broll", src: "venus", idx: "02", headline: "แผนที่ดาวศุกร์ใหม่", sub: "จากข้อมูลยาน NASA Magellan เมื่อ 30 ปีก่อน", subT: 272.0, kicker: "② แผนที่ดาวศุกร์" },
  {
    t: 276.37, mode: "pip", media: "clip", src: "venus_volcano", clipFit: "cover", headline: "ภูเขาไฟบนดาวศุกร์", sub: "ที่มา: anthropic.com — แผนที่ความสูงใหม่ที่ Claude สร้าง", subT: 283.0, kicker: "② แผนที่ดาวศุกร์",
    stats: [{ t: 279.7, big: "10–20 km", label: "ความละเอียดแผนที่เดิม", tone: "clay" }, { t: 288.0, big: "2–3 km", label: "แผนที่ใหม่", tone: "mint" }],
  },
  {
    t: 289.73, mode: "pip", media: "web", file: "sec_venus", kicker: "② แผนที่ดาวศุกร์ · แจกฟรีทั่วโลก",
    cam: [{ t: 0, fy: 190, z: 1.26 }, { t: 12, fy: 230, z: 1.3 }],
    hl: [{ t: 290.6, key: "venus_25" }, { t: 294.2, key: "venus_release" }, { t: 296.2, key: "venus_cc" }],
    stats: [{ t: 291.0, big: "+25%", label: "แม่นยำขึ้นกว่าเดิม", tone: "mint" }, { t: 296.7, label: "🌍 แจกฟรี · Creative Commons" }],
  },
  { t: 302.1, mode: "pip", media: "broll", src: "dna", idx: "03", headline: "งานวิจัยชีววิทยา", sub: "วิเคราะห์ยีน · โปรตีน", subT: 304.5, kicker: "③ ชีววิทยา" },
  { t: 305.78, mode: "pip", media: "broll", src: "server_lights", headline: "ช้า และ แพง", sub: "ต้องใช้คอมพิวเตอร์ระดับสูง (GPU)", subT: 308.5, kicker: "③ ชีววิทยา" },
  {
    t: 311.48, mode: "pip", media: "web", file: "sec_compbio", kicker: "Claude ปรับแต่งโค้ดของโมเดล",
    cam: [{ t: 0, fy: 150, z: 1.36 }, { t: 6, fy: 170, z: 1.42 }],
    hl: [{ t: 312.5, key: "bio_slow" }, { t: 315.8, key: "bio_kernels" }],
  },
  {
    t: 317.86, mode: "pip", media: "web", file: "bio_chart_0", cssH: 724, kicker: "เร็วขึ้น · ถูกลง",
    cam: [{ t: 0, fy: 330, z: 1.08 }, { t: 7, fy: 350, z: 1.14 }],
    stats: [{ t: 319.9, big: "2.5×", label: "เร็วขึ้นสูงสุด", tone: "mint" }, { t: 322.8, big: "−30–60%", label: "ลดค่าใช้จ่าย", tone: "mint" }],
  },
  {
    t: 325.06, mode: "pip", media: "web", file: "sec_compbio", kicker: "จากเป็นสัปดาห์ → ไม่กี่วัน",
    cam: [{ t: 0, fy: 330, z: 1.4 }, { t: 10, fy: 350, z: 1.46 }],
    hl: [{ t: 326.4, key: "bio_weeks" }, { t: 331.5, key: "bio_open" }],
    stats: [{ t: 327.6, big: "สัปดาห์ → วัน", label: "งานทีมวิศวกร" }, { t: 333.3, label: "🔓 เปิดโค้ดให้ทุกคนใช้ฟรี" }],
  },
  { t: 335.98, mode: "full" },
  // ---- safety -----------------------------------------------------------
  {
    t: 341.12, mode: "pip", media: "web", file: "sec_safety", kicker: "ความปลอดภัย",
    cam: [{ t: 0, fy: 120, z: 1.1 }, { t: 3, fy: 300, z: 1.24 }, { t: 6, fy: 320, z: 1.24 }],
    hl: [{ t: 343.8, key: "safety_testing" }],
  },
  {
    t: 347.16, mode: "pip", media: "broll", src: "cyber", headline: "ทดสอบเข้มข้นก่อนปล่อย", kicker: "ความปลอดภัย",
    stats: [{ t: 349.0, label: "🛡️ ความปลอดภัยไซเบอร์" }, { t: 352.3, label: "🧬 ป้องกันการสร้างอาวุธชีวภาพ" }, { t: 355.6, label: "🎭 ป้องกันคนร้ายหลอก AI" }],
  },
  {
    t: 357.08, mode: "pip", media: "web", file: "sec_cyber", kicker: "ตรวจสอบโดยทีมภายใน + ผู้เชี่ยวชาญภายนอก",
    cam: [{ t: 0, fy: 200, z: 1.4 }, { t: 7, fy: 220, z: 1.46 }],
    hl: [{ t: 358.9, key: "cyber_external" }, { t: 360.6, key: "cyber_gray" }, { t: 362.2, key: "cyber_jailbreak" }],
  },
  {
    t: 364.19, mode: "pip", media: "web", file: "sec_efs", kicker: "Enterprise Frontier Safeguards",
    cam: [{ t: 0, fy: 120, z: 1.4 }, { t: 5, fy: 150, z: 1.46 }, { t: 12, fy: 160, z: 1.46 }],
    hl: [{ t: 364.4, key: "efs_title" }, { t: 369.6, key: "efs_store" }],
    stats: [{ t: 373.9, big: "ไม่เก็บ", label: "Anthropic", tone: "mint" }, { t: 374.7, big: "ไม่เห็น", label: "ข้อมูลของคุณ", tone: "mint" }, { t: 375.4, big: "ไม่แตะ", label: "เลย", tone: "mint" }],
  },
  { t: 376.5, mode: "pip", media: "broll", src: "server_lights", from: 8, headline: "ข้อมูลอยู่ในระบบของบริษัทคุณเอง", sub: "ปลอดภัยมากสำหรับข้อมูลธุรกิจ", subT: 377.4, kicker: "Enterprise Frontier Safeguards" },
  {
    t: 381.2, mode: "pip", media: "web", file: "sec_precise", kicker: "ลดการบล็อกผิดพลาด",
    cam: [{ t: 0, fy: 130, z: 1.26 }, { t: 5, fy: 150, z: 1.3 }],
    hl: [{ t: 383.0, key: "precise_benign" }],
    stats: [{ t: 383.6, label: "🚫 ระบบเดิมเข้มเกินไป · บล็อกคำถามปกติ" }],
  },
  {
    t: 386.84, mode: "pip", media: "web", file: "sec_precise", kicker: "รุ่นนี้แก้แล้ว",
    cam: [{ t: 0, fy: 400, z: 1.3 }, { t: 11, fy: 420, z: 1.34 }],
    hl: [{ t: 390.6, key: "precise_60" }, { t: 393.4, key: "precise_85" }],
    stats: [{ t: 390.8, big: "−60%", label: "บล็อกผิดพลาด · งานไซเบอร์", tone: "mint" }, { t: 393.6, big: "−85%", label: "บล็อกผิดพลาด · งานชีววิทยา", tone: "mint" }],
  },
  { t: 398.8, mode: "full" },
  // ---- Fable vs Mythos --------------------------------------------------
  {
    t: 402.9, mode: "pip", media: "web", file: "sec_trusted", kicker: "Fable 5.1 vs Mythos 5.1",
    cam: [{ t: 0, fy: 140, z: 1.26 }, { t: 5, fy: 150, z: 1.3 }],
    hl: [{ t: 403.9, key: "trusted_identical" }],
    stats: [{ t: 404.2, big: "AI ตัวเดียวกัน", label: "ฉลาดเท่ากัน" }],
  },
  { t: 407.97, mode: "pip", media: "typo", typo: "vs", src: "abstract", from: 10, kicker: "Fable 5.1 vs Mythos 5.1" },
  { t: 424.2, mode: "full" },
  { t: 426.31, mode: "pip", media: "typo", typo: "final4", src: "city_night", kicker: "สรุปสุดท้าย" },
  { t: 434.32, mode: "full" },
];

// Typo scene word times
const SUMMARY3 = [{ t: 209.5, text: "ฉลาดขึ้น", icon: "🧠" }, { t: 210.5, text: "เก่งขึ้น", icon: "🚀" }, { t: 211.7, text: "ถูกลง", icon: "💸" }];
const FINAL4 = [{ t: 428.3, text: "ฉลาดที่สุดในโลก", icon: "🧠" }, { t: 430.2, text: "ใช้งานง่าย", icon: "✨" }, { t: 431.4, text: "ราคาถูกลง", icon: "💸" }, { t: 432.6, text: "ปลอดภัยมากขึ้น", icon: "🛡️" }];
const VS = { fableT: 408.8, mythosT: 410.6, subT: 420.0 };
const CTA_T = 448.7;

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
export type FableNewsYTProps = { durationSec?: number };

export const calculateFableNewsYTMetadata: CalculateMetadataFunction<FableNewsYTProps> = ({ props }) => {
  const fps = 25;
  const durationSec = props.durationSec || TOTAL_DURATION_SEC;
  return { durationInFrames: Math.ceil(durationSec * fps), fps, width: W, height: H };
};

export const FableNewsYT: React.FC<FableNewsYTProps> = ({ durationSec = TOTAL_DURATION_SEC }) => {
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
