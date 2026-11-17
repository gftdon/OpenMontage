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
import { CAPTION_PAGES } from "./claudeArtifactsNewsV2Captions";
import { WEB_CLIPS, WEB_RECTS, WebRect } from "./claudeArtifactsNewsWeb";

// ===========================================================================
// ClaudeArtifactsNewsV2 — 16:9 AI-news report (1920x1080@25)
// Format "Youtube-YT-News-Style01-V2":
// Report subject: YOUTUBE VIDEO ("Master 95% of Claude's New Artifacts in 15 minutes" by Ben AI)
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
const VO_END_SEC = 495.6;
const TOTAL_DURATION_SEC = 500.0; // + 4.4 s endcard
const MODE_BLEND_SEC = 0.55;

// ---- Episode config (swap per episode — every on-screen string lives here) --
const EPISODE = {
  assetDir: "v261110-claude-artifacts", // public/<assetDir>/{avatar_source.mp4, broll/, web/}
  brand: "AI TECH NEWS",
  dateLabel: "10 พ.ย. 2026",
  page: { domain: "youtube.com", path: "/watch?v=Lodg0K3_zqk" },
  officialTag: "SOURCE · BEN AI",
  cta: { lead: "ทดลองใช้งาน Claude Artifacts ได้แล้ววันนี้ที่", text: "claude.ai" },
  endcard: {
    eyebrow: "AI TECH NEWS · NOVEMBER 2026",
    titleA: "Claude Artifacts",
    titleB: "Docs · Dashboards · Slides · Motion · Design",
    sub: "YouTube: Ben AI · Master 95% of Claude's New Artifacts in 15 minutes",
    cta: "กดติดตามเพื่อไม่พลาดทุกข่าวสาร AI",
  },
  summary3Label: "กรอบ 5 ขั้นตอนสร้างแดชบอร์ด (3 ขั้นแรก)",
  final4: {
    title: "ยกระดับการทำงานด้วย Claude Artifacts",
    sub: "เปลี่ยนจากแช็ตข้อความยาวสู่เอกสาร แดชบอร์ด และแอปพลิเคชันใช้งานจริง",
  },
  vs: {
    eyebrow: "TRADITIONAL CHAT VS LIVE ARTIFACTS",
    conclusion: "เปลี่ยนข้อความยาวในแช็ตเป็นหน้าเอกสารและแดชบอร์ดที่เปิดแก้ไขร่วมกันได้ทันที",
    left: {
      title: "TRADITIONAL CHAT",
      badge: "ข้อความยาวในแช็ต · ตรวจทานยาก",
      lines: [
        "✓ AI ตอบกลับเป็นข้อความยาวในช่องแช็ต",
        "✓ สั่งแก้ทีไร ระบบมักจะเขียนใหม่ทั้งฉบับ",
        "✓ เสียเวลาตรวจทานและนำไปต่อยอดได้ช้า",
      ],
    },
    right: {
      title: "LIVE ARTIFACTS",
      badge: "หน้าทำงานแยกข้างแช็ต · สดและยืดหยุ่น",
      lines: [
        "✓ แสดงผลเป็นเอกสาร แดชบอร์ด หรือสไลด์",
        "✓ ไฮไลต์สั่งแก้เฉพาะบรรทัดที่ต้องการได้เลย",
        "✓ ดึงข้อมูลสดและแชร์ลิงก์ให้ทีมใช้งานได้ทันที",
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
  analytics_growth_chart: 17.12,
  calendar_automation_schedule: 12.36,
  corporate_handshake_deal: 10.00,
  dashboard_futuristic_data: 30.00,
  digital_workflow_keyboard: 10.16,
  global_cloud_network: 10.00,
  modern_city_night: 8.00,
  team_collaboration_success: 10.68,
  team_office_workflow: 24.00,
  text_frustration: 15.80,
  time_saving_clock: 14.88,
  yt_alternatives_software: 26.04,
  yt_apps_auto_sync: 29.04,
  yt_apps_daily_report: 34.04,
  yt_apps_kanban: 27.08,
  yt_artifacts_intro: 23.04,
  yt_artifacts_layout: 19.04,
  yt_dashboard_drilldown: 24.04,
  yt_dashboard_framework_intro: 24.04,
  yt_dashboard_permissions: 29.04,
  yt_dashboard_pulse: 25.04,
  yt_dashboard_slash: 15.00,
  yt_dashboard_ui_inspiration: 30.04,
  yt_dashboard_warehouse: 29.04,
  yt_design_canvas: 30.08,
  yt_design_multiboard: 34.08,
  yt_docs_export: 19.04,
  yt_docs_inline_edit: 24.04,
  yt_docs_rich_content: 24.04,
  yt_docs_slash: 20.04,
  yt_docs_tabs: 24.04,
  yt_motion_export: 34.08,
  yt_motion_opus: 29.04,
  yt_motion_timeline: 34.04,
  yt_slides_design_system: 39.04,
  yt_slides_presenter: 33.04,
  yt_slides_templates_behance: 34.04,
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
  // --- PART 1: HOOK & LIVE ARTIFACTS (0.00 - 38.42) ---
  {
    t: 0.0,
    mode: "full",
    lower: {
      title: "CLAUDE'S NEW ARTIFACTS",
      sub: "DOCS · DASHBOARDS · SLIDES · MOTION · DESIGN",
      t: 1.0,
      dur: 7.0,
    },
  },
  {
    t: 11.68,
    mode: "pip",
    media: "clip",
    src: "yt_artifacts_intro",
    clipFit: "contain",
    kicker: "LIVE ARTIFACTS",
    headline: "ระบบใหม่เปิดให้แก้ไขและแชร์สด",
    sub: "สร้างหน้าทำงานเคียงข้างแช็ต แก้ไขร่วมกันและแชร์ผ่านลิงก์ได้ทันที",
    stats: [
      { t: 13.0, big: "LIVE URL", label: "แชร์ผ่านลิงก์สด", tone: "mint" },
    ],
  },
  {
    t: 16.66,
    mode: "pip",
    media: "clip",
    src: "yt_alternatives_software",
    clipFit: "contain",
    kicker: "SOFTWARE ALTERNATIVE",
    headline: "ทางเลือกใหม่แทน Docs & Notion",
    sub: "ต้นทางระบุว่านำมาใช้แทน Google Docs, Notion และ Figma ได้",
    stats: [
      { t: 18.5, big: "DOCS & NOTION", label: "ทางเลือกซอฟต์แวร์", tone: "amber" },
      { t: 22.0, big: "FIGMA", label: "งานออกแบบและแอป", tone: "mint" },
    ],
  },
  {
    t: 24.38,
    mode: "pip",
    media: "broll",
    src: "text_frustration",
    kicker: "WORKFLOW BOTTLENECK",
    headline: "คอขวดของการตรวจงาน AI",
    sub: "เสียเวลากับการตรวจทานและแก้ไขข้อความยาวในช่องแช็ต",
    stats: [
      { t: 26.5, big: "BOTTLENECK", label: "คอขวดในแช็ต", tone: "clay" },
      { t: 30.0, big: "WALL OF TEXT", label: "อ่านข้อความยาว", tone: "amber" },
    ],
  },
  {
    t: 32.44,
    mode: "pip",
    media: "clip",
    src: "yt_artifacts_layout",
    clipFit: "contain",
    kicker: "VISUAL FORMAT",
    headline: "จัดหน้าให้อ่านและตรวจงานไวขึ้น",
    sub: "จัดรูปแบบผลลัพธ์เป็นหน้าเอกสารที่เปิดอ่านและแก้ไขได้เร็วกว่าเดิม",
    stats: [
      { t: 34.5, big: "FASTER READ", label: "เปิดอ่านรวดเร็ว", tone: "mint" },
    ],
  },

  // --- PART 2: CLAUDE DOCS (38.42 - 100.34) ---
  {
    t: 38.42,
    mode: "pip",
    media: "clip",
    src: "yt_docs_slash",
    clipFit: "contain",
    kicker: "CLAUDE DOCS",
    headline: "เครื่องมือชิ้นแรก: Claude Docs",
    sub: "พิมพ์คำสั่ง slash docs ในแช็ต หรือเลือกจากแท็บ Artifacts",
    stats: [
      { t: 40.5, big: "CLAUDE DOCS", label: "ทำหน้าที่คล้าย Docs", tone: "amber" },
      { t: 46.5, big: "/docs", label: "พิมพ์คำสั่งใช้งาน", tone: "mint" },
    ],
  },
  {
    t: 51.14,
    mode: "pip",
    media: "clip",
    src: "yt_docs_inline_edit",
    clipFit: "contain",
    kicker: "INLINE EDITING",
    headline: "ไฮไลต์แก้เฉพาะจุด ไม่ต้องเริ่มใหม่",
    sub: "พิมพ์แก้เองได้โดยตรง หรือกด Edit with Claude เพื่อแก้เฉพาะบรรทัดนั้น",
    stats: [
      { t: 53.0, big: "DIRECT EDIT", label: "พิมพ์แก้ได้เอง", tone: "amber" },
      { t: 58.0, big: "HIGHLIGHT", label: "ไฮไลต์เลือกแก้", tone: "mint" },
      { t: 66.0, big: "@CLAUDE", label: "แท็กแก้เฉพาะจุด", tone: "amber" },
    ],
  },
  {
    t: 70.38,
    mode: "pip",
    media: "clip",
    src: "yt_docs_tabs",
    clipFit: "contain",
    kicker: "TAB SYSTEM",
    headline: "เพิ่มแถบแท็บแยกหัวข้องาน",
    sub: "แบ่งแท็บเป็นค้นคว้าข้อมูล โครงเรื่อง รูปหน้าปก และสคริปต์",
    stats: [
      { t: 72.0, big: "TABS", label: "แยกหัวข้องาน", tone: "mint" },
      { t: 76.5, big: "4 TABS", label: "ค้นคว้า โครง สคริปต์", tone: "amber" },
    ],
  },
  {
    t: 82.74,
    mode: "pip",
    media: "clip",
    src: "yt_docs_rich_content",
    clipFit: "contain",
    kicker: "RICH DOCUMENTS",
    headline: "ใส่ตาราง รูปภาพ และแท็กเพื่อนร่วมทีม",
    sub: "รองรับหัวข้อ ตาราง เช็กลิสต์ ลากรูป แท็กทีม ใส่วันที่ และฝังแผนภูมิ",
    stats: [
      { t: 85.0, big: "RICH MEDIA", label: "ตารางและรูปภาพ", tone: "mint" },
      { t: 90.0, big: "CHARTS", label: "ฝังแผนภูมิข้อมูล", tone: "amber" },
    ],
  },
  {
    t: 94.36,
    mode: "pip",
    media: "clip",
    src: "yt_docs_export",
    clipFit: "contain",
    kicker: "ONE-CLICK EXPORT",
    headline: "ส่งออกไฟล์ Docs, Word, PDF, Notion",
    sub: "ทำงานเสร็จแล้วสามารถส่งออกไปใช้งานต่อในโปรแกรมอื่นได้ทันที",
    stats: [
      { t: 96.5, big: "EXPORT", label: "Docs Word PDF Notion", tone: "mint" },
    ],
  },

  // --- PART 3: THAI PERSPECTIVE & SOP (100.34 - 145.38) ---
  {
    t: 100.34,
    mode: "full",
  },
  {
    t: 107.34,
    mode: "pip",
    media: "broll",
    src: "time_saving_clock",
    kicker: "SAVE REVIEW TIME",
    headline: "ลดเวลาตรวจงานได้จริง",
    sub: "ไม่ต้องเสียเวลากับ AI ที่ชอบเขียนข้อความใหม่ทั้งหน้าจนตรวจทานยาก",
    stats: [
      { t: 109.5, big: "TIME SAVED", label: "ลดเวลาตรวจงาน", tone: "mint" },
      { t: 113.0, big: "NO REWRITE", label: "ไม่ต้องเขียนใหม่ทั้งหน้า", tone: "amber" },
    ],
  },
  {
    t: 116.36,
    mode: "pip",
    media: "broll",
    src: "team_office_workflow",
    kicker: "THAI BUSINESS SOP",
    headline: "รวมคู่มือขั้นตอนการทำงานบริษัท",
    sub: "สมมติว่าต้องทำเอกสารขั้นตอนการทำงาน หรือคู่มือมาตรฐาน SOP ในไทย",
    stats: [
      { t: 118.5, big: "SOP GUIDE", label: "คู่มือขั้นตอนทำงาน", tone: "amber" },
      { t: 125.0, big: "TEAM HUB", label: "รวมข้อมูลในหน้านี้", tone: "mint" },
    ],
  },
  {
    t: 131.80,
    mode: "pip",
    media: "broll",
    src: "calendar_automation_schedule",
    kicker: "SCHEDULED TASKS",
    headline: "ตั้งเวลารายงานส่งผลลัพธ์ล่วงหน้า",
    sub: "สั่งระบบทำรายงานการตลาดหรือร่างโพสต์โซเชียลทุกวันหรือทุกสัปดาห์",
    stats: [
      { t: 134.0, big: "REPORTS", label: "รายงานการตลาด", tone: "amber" },
      { t: 139.0, big: "AUTOMATION", label: "ตั้งเวลารายวัน/สัปดาห์", tone: "mint" },
    ],
  },

  // --- PART 4: CLAUDE DASHBOARDS & 5-STEP FRAMEWORK (145.38 - 270.48) ---
  {
    t: 145.38,
    mode: "full",
  },
  {
    t: 152.88,
    mode: "pip",
    media: "clip",
    src: "yt_dashboard_pulse",
    clipFit: "contain",
    kicker: "CLAUDE DASHBOARDS",
    headline: "แดชบอร์ดรายงานข้อมูลแบบสด",
    sub: "ดึงข้อมูลล่าสุดจากตัวเชื่อมต่อมาอัปเดตให้อัตโนมัติทุกครั้งที่เปิดดู",
    stats: [
      { t: 154.5, big: "LIVE DATA", label: "อัปเดตสดอัตโนมัติ", tone: "mint" },
      { t: 161.0, big: "CONNECTORS", label: "เชื่อมต่อข้อมูลตรง", tone: "amber" },
    ],
  },
  {
    t: 167.84,
    mode: "pip",
    media: "clip",
    src: "yt_dashboard_drilldown",
    clipFit: "contain",
    kicker: "AUDITABLE FORMULAS",
    headline: "กดดูที่มาตัวเลขได้ทุกตัว",
    sub: "แสดงสูตรคำนวณ คำสั่งดึงข้อมูล และชุดข้อมูลดิบที่มาของตัวเลขนั้น",
    stats: [
      { t: 170.0, big: "DRILL DOWN", label: "กดดูสูตรคำนวณ", tone: "amber" },
      { t: 173.0, big: "RAW DATA", label: "แสดงชุดข้อมูลดิบ", tone: "mint" },
    ],
  },
  {
    t: 175.92,
    mode: "pip",
    media: "clip",
    src: "yt_dashboard_warehouse",
    clipFit: "contain",
    kicker: "WAREHOUSE & LIMITS",
    headline: "ฐานข้อมูล 100MB และ CSV 1GB",
    sub: "มีฐานข้อมูลในตัว จุได้ 100MB อัปโหลด CSV 1GB เชื่อม Snowflake/BigQuery",
    stats: [
      { t: 178.0, big: "100 MB", label: "ฐานข้อมูลในตัว", tone: "mint" },
      { t: 182.0, big: "1 GB CSV", label: "อัปโหลดไฟล์ข้อมูล", tone: "amber" },
      { t: 187.5, big: "SNOWFLAKE", label: "Snowflake / BigQuery", tone: "mint" },
    ],
  },
  {
    t: 190.12,
    mode: "pip",
    media: "clip",
    src: "yt_dashboard_framework_intro",
    clipFit: "contain",
    kicker: "5-STEP FRAMEWORK",
    headline: "กรอบ 5 ขั้นตอนสร้างแดชบอร์ด",
    sub: "ผู้สร้างคลิปแนะนำกรอบการทำงาน 5 ขั้นตอนเพื่อสร้างบอร์ดที่ใช้งานได้จริง",
    stats: [
      { t: 192.0, big: "PROVEN STEPS", label: "กรอบการทำงาน 5 ข้อ", tone: "amber" },
    ],
  },
  {
    t: 200.02,
    mode: "pip",
    media: "typo",
    typo: "summary3",
    src: "analytics_growth_chart",
    kicker: "STEPS 1 - 3",
    headline: "3 ขั้นตอนแรก: โฟกัสและตรวจข้อมูล",
    sub: "จำกัดเรื่องตัดสินใจ เลือกตัวชี้วัด และให้ Claude ตรวจสอบข้อมูลก่อนสร้าง",
  },
  {
    t: 223.74,
    mode: "pip",
    media: "clip",
    src: "yt_dashboard_ui_inspiration",
    clipFit: "contain",
    kicker: "STEP 4 · UI FIRST",
    headline: "ขั้นตอนที่ 4: ออกแบบหน้าตาก่อน",
    sub: "วางภาพแดชบอร์ดที่ชอบจาก Pinterest, Dribbble หรือ Mobbin ให้ระบบร่างแบบ",
    stats: [
      { t: 226.0, big: "DRIBBBLE", label: "หาไอเดียหน้าตาบอร์ด", tone: "amber" },
      { t: 233.0, big: "2-3 DRAFTS", label: "ให้ AI ทำร่าง 2-3 แบบ", tone: "mint" },
    ],
  },
  {
    t: 237.88,
    mode: "pip",
    media: "clip",
    src: "yt_dashboard_slash",
    clipFit: "contain",
    kicker: "STEP 5 · BUILD",
    headline: "ขั้นตอนที่ 5: สั่ง /dashboard",
    sub: "พิมพ์คำสั่ง slash dashboard เพื่อสร้าง และใช้ความคิดเห็นปรับรายละเอียด",
    stats: [
      { t: 240.0, big: "/dashboard", label: "พิมพ์คำสั่งสร้าง", tone: "mint" },
    ],
  },
  {
    t: 244.90,
    mode: "pip",
    media: "clip",
    src: "yt_dashboard_permissions",
    clipFit: "contain",
    kicker: "DATA PERMISSIONS",
    headline: "ระบบความปลอดภัยอิงสิทธิ์รายบุคคล",
    sub: "ถ้าเพื่อนร่วมทีมไม่ต่อระบบ Stripe ไว้ ก็จะไม่สามารถมองเห็นตัวเลขรายได้",
    stats: [
      { t: 247.5, big: "SECURITY", label: "อิงสิทธิ์ผู้เปิดดู", tone: "clay" },
      { t: 254.0, big: "STRIPE PERM", label: "ไม่ต่อ Stripe ไม่เห็นยอด", tone: "amber" },
    ],
  },
  {
    t: 259.34,
    mode: "pip",
    media: "broll",
    src: "global_cloud_network",
    kicker: "AVAILABILITY",
    headline: "ใช้งานผ่านหน้าต่าง Claude ทันที",
    sub: "ต้นทางไม่ระบุราคาค่าบริการหรือการเปิดใช้ในไทยแยกเป็นพิเศษ แต่ใช้งานได้เลย",
    stats: [
      { t: 261.0, big: "PRICING", label: "ไม่ระบุราคาแยก", tone: "amber" },
      { t: 268.0, big: "AVAILABLE", label: "ใช้งานผ่าน Claude", tone: "mint" },
    ],
  },

  // --- PART 5: CLAUDE SLIDES (270.48 - 333.22) ---
  {
    t: 270.48,
    mode: "full",
  },
  {
    t: 280.32,
    mode: "pip",
    media: "clip",
    src: "yt_slides_presenter",
    clipFit: "contain",
    kicker: "CLAUDE SLIDES",
    headline: "สไลด์นำเสนอแทน Google Slides / PPT",
    sub: "สั่งผ่าน /slide มีโหมดผู้นำเสนอฉายได้ทันที แก้ไขข้อความ และส่งออก PDF/PPT",
    stats: [
      { t: 282.0, big: "/slide", label: "เรียกใช้ใน Artifacts", tone: "amber" },
      { t: 285.5, big: "PRESENTER", label: "โหมดผู้นำเสนอพร้อมฉาย", tone: "mint" },
      { t: 298.5, big: "PDF / PPT", label: "ส่งออกไฟล์ได้ทันที", tone: "amber" },
    ],
  },
  {
    t: 300.78,
    mode: "pip",
    media: "clip",
    src: "yt_slides_design_system",
    clipFit: "contain",
    kicker: "DESIGN SYSTEM",
    headline: "ตั้งค่าสี ฟอนต์ และโลโก้จากเว็บไซต์",
    sub: "วางลิงก์เว็บไซต์บริษัทเพื่อให้ระบบดึงข้อมูลมาเก็บ หรือนำรูปแบบจาก Dribbble",
    stats: [
      { t: 304.5, big: "BRAND KIT", label: "สี ฟอนต์ โลโก้", tone: "mint" },
      { t: 309.0, big: "URL IMPORT", label: "วางลิงก์ดึงข้อมูล", tone: "amber" },
    ],
  },
  {
    t: 317.84,
    mode: "pip",
    media: "clip",
    src: "yt_slides_templates_behance",
    clipFit: "contain",
    kicker: "28 SLIDE TEMPLATES",
    headline: "แม่แบบเลย์เอาต์ 28 รูปแบบ & คุมน้ำเสียง",
    sub: "มีเทมเพลต 28 แบบ หาไอเดียจาก Behance และจัดทำแนวทางภาษาให้น้ำเสียงตรงใจ",
    stats: [
      { t: 324.0, big: "28 LAYOUTS", label: "แม่แบบคัดล่วงหน้า", tone: "mint" },
      { t: 326.5, big: "BEHANCE", label: "ไอเดียจาก Behance", tone: "amber" },
      { t: 331.0, big: "VOICE TONE", label: "คุมน้ำเสียงข้อความ", tone: "mint" },
    ],
  },

  // --- PART 6: CLAUDE MOTION (333.22 - 373.48) ---
  {
    t: 333.22,
    mode: "pip",
    media: "clip",
    src: "yt_motion_opus",
    clipFit: "contain",
    kicker: "CLAUDE MOTION",
    headline: "สร้างวิดีโออนิเมชันด้วย Opus 5.5",
    sub: "สร้างภาพเคลื่อนไหวจากโค้ด ไม่กินทรัพยากรสูง ประหยัดโทเคนและแก้ง่าย",
    stats: [
      { t: 335.5, big: "OPUS 5.5", label: "พลังการสร้างวิดีโอ", tone: "mint" },
      { t: 346.5, big: "CODE-BASED", label: "สร้างภาพจากโค้ด", tone: "amber" },
    ],
  },
  {
    t: 350.02,
    mode: "pip",
    media: "clip",
    src: "yt_motion_timeline",
    clipFit: "contain",
    kicker: "TIMELINE EDITOR",
    headline: "แถบตัดต่อเหมือน After Effects",
    sub: "มีไทม์ไลน์แสดงฉาก แก้ข้อความบนแต่ละเฟรม ปรับสีและฟอนต์ได้ทันที",
    stats: [
      { t: 353.0, big: "TIMELINE", label: "เหมือน After Effects", tone: "mint" },
      { t: 359.0, big: "PER FRAME", label: "แก้ข้อความรายเฟรม", tone: "amber" },
    ],
  },
  {
    t: 362.38,
    mode: "pip",
    media: "clip",
    src: "yt_motion_export",
    clipFit: "contain",
    kicker: "MP4 EXPORT & LIMIT",
    headline: "ส่งออกไฟล์ MP4 ได้ทันที",
    sub: "ข้อจำกัดปัจจุบันยังไม่สามารถใส่ไฟล์เสียงพากย์หรือไฟล์ MP3 ของตัวเองเข้าไปได้",
    stats: [
      { t: 364.5, big: "MP4 EXPORT", label: "ส่งออกวิดีโอตรง", tone: "mint" },
      { t: 370.0, big: "NO MP3 YET", label: "ยังไม่รองรับไฟล์เสียง", tone: "clay" },
    ],
  },

  // --- PART 7: CLAUDE DESIGN CANVAS (373.48 - 401.56) ---
  {
    t: 373.48,
    mode: "pip",
    media: "clip",
    src: "yt_design_canvas",
    clipFit: "contain",
    kicker: "CLAUDE DESIGN",
    headline: "ผืนผ้าใบออกแบบสไตล์ Figma",
    sub: "เรียกใช้ด้วย slash design ออกแบบหน้าเว็บ ภาพโซเชียล หรือคู่มือ",
    stats: [
      { t: 376.0, big: "FIGMA STYLE", label: "คล้ายโปรแกรม Figma", tone: "amber" },
      { t: 380.0, big: "/design", label: "คำสั่งเปิดผืนผ้าใบ", tone: "mint" },
    ],
  },
  {
    t: 387.40,
    mode: "pip",
    media: "clip",
    src: "yt_design_multiboard",
    clipFit: "contain",
    kicker: "MULTI-BOARD EXPORT",
    headline: "แสดงผลหลายบอร์ด & ส่งออก HTML",
    sub: "ปรับสี ขนาด ฟอนต์ ส่งออกภาพ PDF, PowerPoint, Google Slides, HTML",
    stats: [
      { t: 389.5, big: "MULTI-BOARD", label: "วางหลายบอร์ดพร้อมกัน", tone: "mint" },
      { t: 396.0, big: "HTML / SLIDES", label: "ส่งออกได้หลายฟอร์แมต", tone: "amber" },
    ],
  },

  // --- PART 8: BUILD INTERNAL APPS (401.56 - 454.02) ---
  {
    t: 401.56,
    mode: "pip",
    media: "clip",
    src: "yt_apps_kanban",
    clipFit: "contain",
    kicker: "INTERNAL APPS",
    headline: "สร้างแอปคัมบังใช้ในทีมแทน Notion",
    sub: "แปลงโค้ด HTML มาสร้างกระดานจัดการงานควบคุมขั้นตอนการผลิตวิดีโอ",
    stats: [
      { t: 407.5, big: "HTML TO APP", label: "แปลงโค้ดเป็นแอป", tone: "amber" },
      { t: 414.5, big: "KANBAN BOARD", label: "กระดานคัมบังแทน Notion", tone: "mint" },
    ],
  },
  {
    t: 421.40,
    mode: "pip",
    media: "clip",
    src: "yt_apps_auto_sync",
    clipFit: "contain",
    kicker: "AUTOMATED SYNC",
    headline: "ผูกข้อมูลจาก Docs สู่คัมบังอัตโนมัติ",
    sub: "เมื่อมีสคริปต์ใน Docs ข้อมูลจะซิงก์เข้าบอร์ด และตั้งเวลารายวันย้ายสถานะเอง",
    stats: [
      { t: 426.0, big: "DOCS SYNC", label: "ดึงข้อมูลจาก Docs สด", tone: "mint" },
      { t: 431.0, big: "DAILY CHECK", label: "ตรวจสถานะงานทุกวัน", tone: "amber" },
    ],
  },
  {
    t: 437.20,
    mode: "pip",
    media: "clip",
    src: "yt_apps_daily_report",
    clipFit: "contain",
    kicker: "DAILY BRIEFING & CLEANUP",
    headline: "สรุปข่าว 24 ชม. & ตรวจไฟล์ซ้ำซ้อน",
    sub: "สร้างหน้ารายงานสรุปประจำวัน และตั้งเวลารายสัปดาห์เคลียร์ไฟล์เก่าประหยัดพื้นที่",
    stats: [
      { t: 440.0, big: "24H REPORT", label: "รายงานสรุปประจำวัน", tone: "amber" },
      { t: 447.0, big: "WEEKLY CLEAN", label: "แจ้งเตือนไฟล์ซ้ำซ้อน", tone: "mint" },
    ],
  },

  // --- PART 9: ECOSYSTEM SUMMARY & CTA (454.02 - 500.0) ---
  {
    t: 454.02,
    mode: "pip",
    media: "typo",
    typo: "final4",
    src: "modern_city_night",
    kicker: "ECOSYSTEM SUMMARY",
    headline: "สรุปภาพรวม 5 เครื่องมือใหม่",
    sub: "รวมข้อมูลและการวิเคราะห์ไว้ในหน้าเดียว ลดการสลับโปรแกรมทำงาน",
  },
  {
    t: 471.80,
    mode: "pip",
    media: "broll",
    src: "team_collaboration_success",
    kicker: "THAI TEAM PRODUCTIVITY",
    headline: "ลดเวลาทวงงานในแช็ตกลุ่ม",
    sub: "บอร์ดอัปเดตอัตโนมัติช่วยลดเวลาคอยถามความคืบหน้าของแต่ละแผนก",
    stats: [
      { t: 474.0, big: "NO MORE CHAT", label: "ลดทวงงานในแช็ต", tone: "mint" },
      { t: 480.0, big: "TEAM SYNC", label: "ทุกคนเห็นสถานะตรงกัน", tone: "amber" },
    ],
  },
  {
    t: 485.72,
    mode: "full",
  },
];

// Typo scene word times
const SUMMARY3 = [
  { t: 201.0, text: "1 · ตั้งเป้าหมาย: จำกัดเรื่องตัดสินใจเพียง 1-3 เรื่อง", icon: "🎯" },
  { t: 210.5, text: "2 · คัดเลือกตัวชี้วัด: ใช้เพียง 5-10 ตัวที่ตอบโจทย์", icon: "📊" },
  { t: 216.0, text: "3 · ตรวจสอบข้อมูล: ยืนยันวิธีนับตัวเลขกับ Claude ก่อน", icon: "🔍" },
];

const FINAL4 = [
  { t: 455.0, text: "1 · Docs: ไฮไลต์แก้ทีละประโยค ไม่ต้องสั่งเขียนใหม่ทั้งหน้า", icon: "📄" },
  { t: 459.5, text: "2 · Dashboards: เชื่อมต่อข้อมูลสด เจาะดูสูตรคำนวณได้ทุกตัว", icon: "📊" },
  { t: 464.0, text: "3 · Slides & Motion: ทำสไลด์และวิดีโออนิเมชันพร้อมส่งออก", icon: "🎬" },
  { t: 468.0, text: "4 · Internal Apps: ผูกงานคัมบังควบคุมการผลิตแบบอัตโนมัติ", icon: "💻" },
];

const VS = { fableT: 102.0, mythosT: 104.0, subT: 106.0 };
const CTA_T = 492.9;

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
          fontWeight: 700,
          fontSize: 13.5,
          color: CREAM,
          letterSpacing: 0.2,
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
  const opacity = interpolate(s, [0, 0.3, 1], [0, 1, 1]);
  const y = interpolate(s, [0, 1], [40, 0]);
  return (
    <div
      style={{
        position: "absolute",
        left: STAGE.x,
        bottom: 120,
        transform: `translateY(${y}px)`,
        opacity,
        zIndex: 40,
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div
        style={{
          alignSelf: "flex-start",
          background: CLAY,
          color: CREAM,
          padding: "5px 14px",
          borderRadius: 6,
          fontFamily: FONT,
          fontWeight: 800,
          fontSize: 14,
          letterSpacing: 2,
        }}
      >
        BREAKING NEWS
      </div>
      <div
        style={{
          background: "rgba(11,14,23,0.92)",
          backdropFilter: "blur(20px)",
          border: "1px solid rgba(245,241,232,0.15)",
          borderLeft: `6px solid ${AMBER}`,
          padding: "16px 28px",
          borderRadius: 16,
          maxWidth: 900,
          boxShadow: "0 20px 50px rgba(0,0,0,0.6)",
        }}
      >
        <div
          style={{
            fontFamily: FONT,
            fontWeight: 800,
            fontSize: 34,
            color: CREAM,
            lineHeight: 1.2,
            letterSpacing: 0.5,
          }}
        >
          {title}
        </div>
        <div
          style={{
            fontFamily: FONT,
            fontWeight: 700,
            fontSize: 18,
            color: AMBER,
            marginTop: 6,
            letterSpacing: 1,
          }}
        >
          {sub}
        </div>
      </div>
    </div>
  );
};

const CaptionLane: React.FC<{ t: number }> = ({ t }) => {
  const curPage = CAPTION_PAGES.find((p) => t >= p.start && t <= p.end);
  if (!curPage) return null;
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 26,
        display: "flex",
        justifyContent: "center",
        zIndex: 50,
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          background: "rgba(11,14,23,0.85)",
          backdropFilter: "blur(16px)",
          border: "1px solid rgba(245,241,232,0.12)",
          borderRadius: 30,
          padding: "10px 28px",
          display: "flex",
          gap: 10,
          alignItems: "center",
          boxShadow: "0 10px 30px rgba(0,0,0,0.5)",
          maxWidth: 1500,
        }}
      >
        {curPage.words.map((w, i) => {
          const isSpoken = t >= w.s;
          return (
            <span
              key={i}
              style={{
                fontFamily: FONT,
                fontWeight: 800,
                fontSize: 32,
                color: isSpoken ? GOLD : CREAM,
                textShadow: isSpoken ? `0 0 16px ${GOLD}, 0 0 30px ${GOLD_LIGHT}` : "none",
                transition: "color 0.08s ease",
                letterSpacing: 0.5,
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

const TypoSummary3: React.FC<{ t: number; fps: number; beatStart: number }> = ({ t, fps, beatStart }) => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      padding: "50px 60px",
      display: "flex",
      flexDirection: "column",
      justifyContent: "center",
      gap: 22,
      zIndex: 5,
    }}
  >
    <div
      style={{
        fontFamily: FONT,
        fontWeight: 800,
        fontSize: 36,
        color: AMBER,
        letterSpacing: 1,
        marginBottom: 10,
      }}
    >
      {EPISODE.summary3Label}
    </div>
    {SUMMARY3.map((item, i) => {
      const active = t >= item.t;
      const s = active ? springIn(Math.round((t - item.t) * fps), fps, 14, 150) : 0;
      return (
        <div
          key={i}
          style={{
            transform: `scale(${interpolate(s, [0, 1], [0.85, 1])}) translateY(${interpolate(s, [0, 1], [30, 0])}px)`,
            opacity: interpolate(s, [0, 0.4, 1], [0, 1, 1]),
            background: "rgba(11,14,23,0.85)",
            backdropFilter: "blur(20px)",
            border: `1px solid rgba(245,241,232,0.15)`,
            borderLeft: `6px solid ${i === 0 ? AMBER : i === 1 ? MINT : CLAY}`,
            borderRadius: 16,
            padding: "18px 26px",
            display: "flex",
            alignItems: "center",
            gap: 18,
            boxShadow: "0 12px 36px rgba(0,0,0,0.45)",
          }}
        >
          <span style={{ fontSize: 32 }}>{item.icon}</span>
          <span
            style={{
              fontFamily: FONT,
              fontWeight: 700,
              fontSize: 24,
              color: CREAM,
              lineHeight: 1.3,
            }}
          >
            {item.text}
          </span>
        </div>
      );
    })}
  </div>
);

const TypoVs: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  const leftActive = t >= VS.fableT;
  const rightActive = t >= VS.mythosT;
  const subActive = t >= VS.subT;

  const leftS = leftActive ? springIn(Math.round((t - VS.fableT) * fps), fps, 15, 140) : 0;
  const rightS = rightActive ? springIn(Math.round((t - VS.mythosT) * fps), fps, 15, 140) : 0;
  const subS = subActive ? springIn(Math.round((t - VS.subT) * fps), fps, 15, 140) : 0;

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        padding: "36px 48px",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        zIndex: 5,
      }}
    >
      <div
        style={{
          fontFamily: FONT,
          fontWeight: 800,
          fontSize: 22,
          letterSpacing: 2,
          color: AMBER,
        }}
      >
        {EPISODE.vs.eyebrow}
      </div>

      <div style={{ display: "flex", gap: 24, flex: 1, margin: "20px 0" }}>
        {/* LEFT CARD */}
        <div
          style={{
            flex: 1,
            transform: `scale(${interpolate(leftS, [0, 1], [0.9, 1])}) translateY(${interpolate(leftS, [0, 1], [25, 0])}px)`,
            opacity: interpolate(leftS, [0, 0.4, 1], [0, 1, 1]),
            background: "rgba(11,14,23,0.88)",
            backdropFilter: "blur(20px)",
            border: `1px solid rgba(242,179,76,0.35)`,
            borderTop: `5px solid ${AMBER}`,
            borderRadius: 18,
            padding: "24px 28px",
            display: "flex",
            flexDirection: "column",
            gap: 14,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 32, color: AMBER }}>
              {EPISODE.vs.left.title}
            </span>
            <span
              style={{
                background: "rgba(242,179,76,0.15)",
                color: AMBER,
                fontSize: 12,
                fontFamily: FONT,
                fontWeight: 700,
                padding: "3px 10px",
                borderRadius: 8,
              }}
            >
              {EPISODE.vs.left.badge}
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 4 }}>
            {EPISODE.vs.left.lines.map((l, i) => (
              <span key={i} style={{ fontFamily: FONT, fontWeight: 600, fontSize: 17, color: CREAM, lineHeight: 1.35 }}>
                {l}
              </span>
            ))}
          </div>
        </div>

        {/* RIGHT CARD */}
        <div
          style={{
            flex: 1,
            transform: `scale(${interpolate(rightS, [0, 1], [0.9, 1])}) translateY(${interpolate(rightS, [0, 1], [25, 0])}px)`,
            opacity: interpolate(rightS, [0, 0.4, 1], [0, 1, 1]),
            background: "rgba(11,14,23,0.88)",
            backdropFilter: "blur(20px)",
            border: `1px solid rgba(217,119,87,0.35)`,
            borderTop: `5px solid ${CLAY}`,
            borderRadius: 18,
            padding: "24px 28px",
            display: "flex",
            flexDirection: "column",
            gap: 14,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 32, color: CLAY }}>
              {EPISODE.vs.right.title}
            </span>
            <span
              style={{
                background: "rgba(217,119,87,0.15)",
                color: CLAY,
                fontSize: 12,
                fontFamily: FONT,
                fontWeight: 700,
                padding: "3px 10px",
                borderRadius: 8,
              }}
            >
              {EPISODE.vs.right.badge}
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 4 }}>
            {EPISODE.vs.right.lines.map((l, i) => (
              <span key={i} style={{ fontFamily: FONT, fontWeight: 600, fontSize: 17, color: CREAM, lineHeight: 1.35 }}>
                {l}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* CONCLUSION CHIP */}
      <div
        style={{
          transform: `translateY(${interpolate(subS, [0, 1], [20, 0])}px)`,
          opacity: interpolate(subS, [0, 0.4, 1], [0, 1, 1]),
          background: "rgba(143,214,180,0.12)",
          border: `1px solid rgba(143,214,180,0.35)`,
          padding: "12px 20px",
          borderRadius: 12,
          fontFamily: FONT,
          fontWeight: 700,
          fontSize: 17,
          color: MINT,
          textAlign: "center",
        }}
      >
        💡 {EPISODE.vs.conclusion}
      </div>
    </div>
  );
};

const TypoFinal4: React.FC<{ t: number; fps: number }> = ({ t, fps }) => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      padding: "44px 56px",
      display: "flex",
      flexDirection: "column",
      justifyContent: "center",
      gap: 16,
      zIndex: 5,
    }}
  >
    <div style={{ marginBottom: 4 }}>
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 32, color: AMBER, letterSpacing: 0.5 }}>
        {EPISODE.final4.title}
      </div>
      <div style={{ fontFamily: FONT, fontWeight: 600, fontSize: 17, color: CREAM_DIM, marginTop: 4 }}>
        {EPISODE.final4.sub}
      </div>
    </div>
    {FINAL4.map((item, i) => {
      const active = t >= item.t;
      const s = active ? springIn(Math.round((t - item.t) * fps), fps, 14, 150) : 0;
      return (
        <div
          key={i}
          style={{
            transform: `scale(${interpolate(s, [0, 1], [0.9, 1])}) translateY(${interpolate(s, [0, 1], [25, 0])}px)`,
            opacity: interpolate(s, [0, 0.4, 1], [0, 1, 1]),
            background: "rgba(11,14,23,0.88)",
            backdropFilter: "blur(20px)",
            border: `1px solid rgba(245,241,232,0.14)`,
            borderLeft: `5px solid ${i === 0 ? AMBER : i === 1 ? MINT : i === 2 ? CLAY : AMBER_DEEP}`,
            borderRadius: 14,
            padding: "14px 22px",
            display: "flex",
            alignItems: "center",
            gap: 16,
            boxShadow: "0 10px 28px rgba(0,0,0,0.45)",
          }}
        >
          <span style={{ fontSize: 26 }}>{item.icon}</span>
          <span style={{ fontFamily: FONT, fontWeight: 700, fontSize: 21, color: CREAM, lineHeight: 1.3 }}>
            {item.text}
          </span>
        </div>
      );
    })}
  </div>
);

const EndCard: React.FC = () => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      background: "radial-gradient(ellipse at 50% 40%, #1A2238 0%, #0B0E17 80%)",
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      zIndex: 60,
      gap: 18,
    }}
  >
    <div
      style={{
        fontFamily: FONT,
        fontWeight: 800,
        fontSize: 16,
        letterSpacing: 3,
        color: AMBER,
        textTransform: "uppercase",
      }}
    >
      {EPISODE.endcard.eyebrow}
    </div>
    <div style={{ textAlign: "center", lineHeight: 1.15 }}>
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 72, color: CREAM }}>
        {EPISODE.endcard.titleA}
      </div>
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 44, color: AMBER, marginTop: 4 }}>
        {EPISODE.endcard.titleB}
      </div>
    </div>
    <div
      style={{
        fontFamily: FONT,
        fontWeight: 600,
        fontSize: 18,
        color: CREAM_DIM,
        maxWidth: 820,
        textAlign: "center",
        lineHeight: 1.4,
        marginTop: 6,
      }}
    >
      {EPISODE.endcard.sub}
    </div>
    <div
      style={{
        marginTop: 20,
        background: `linear-gradient(135deg, ${AMBER}, ${AMBER_DEEP})`,
        color: INK,
        fontFamily: FONT,
        fontWeight: 800,
        fontSize: 22,
        padding: "14px 38px",
        borderRadius: 40,
        letterSpacing: 1,
        boxShadow: `0 12px 36px rgba(242,179,76,0.35)`,
      }}
    >
      {EPISODE.endcard.cta}
    </div>
  </div>
);

const CtaChip: React.FC<{ fps: number; localFrame: number }> = ({ fps, localFrame }) => {
  const s = springIn(localFrame, fps, 15, 140);
  return (
    <div
      style={{
        position: "absolute",
        left: STAGE.x,
        bottom: 140,
        transform: `translateY(${interpolate(s, [0, 1], [30, 0])}px)`,
        opacity: interpolate(s, [0, 0.4, 1], [0, 1, 1]),
        background: "rgba(11,14,23,0.92)",
        backdropFilter: "blur(20px)",
        border: `1px solid rgba(242,179,76,0.4)`,
        borderLeft: `6px solid ${AMBER}`,
        borderRadius: 16,
        padding: "14px 24px",
        display: "flex",
        alignItems: "center",
        gap: 14,
        zIndex: 45,
        boxShadow: "0 16px 40px rgba(0,0,0,0.6)",
      }}
    >
      <span style={{ fontSize: 24 }}>👉</span>
      <div style={{ display: "flex", flexDirection: "column" }}>
        <span style={{ fontFamily: FONT, fontWeight: 600, fontSize: 15, color: CREAM_DIM }}>
          {EPISODE.cta.lead}
        </span>
        <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 22, color: AMBER, letterSpacing: 0.5 }}>
          {EPISODE.cta.text}
        </span>
      </div>
    </div>
  );
};

// ===========================================================================
// MAIN COMPOSITION
// ===========================================================================

export type ClaudeArtifactsNewsV2Props = {
  durationSec?: number;
};

export const calculateClaudeArtifactsNewsV2Metadata: CalculateMetadataFunction<ClaudeArtifactsNewsV2Props> = async () => ({
  durationInFrames: Math.ceil(TOTAL_DURATION_SEC * 25),
  fps: 25,
  width: W,
  height: H,
});

export const ClaudeArtifactsNewsV2: React.FC<ClaudeArtifactsNewsV2Props> = () => {
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
  const showCta = t >= CTA_T && t < VO_END_SEC;
  const showEnd = t >= VO_END_SEC;

  return (
    <div
      style={{
        position: "relative",
        width: W,
        height: H,
        backgroundColor: NAVY,
        overflow: "hidden",
        fontFamily: FONT,
      }}
    >
      {/* BACKGROUND GRID & GLOWS */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage: `radial-gradient(rgba(245,241,232,0.06) 1.5px, transparent 1.5px)`,
          backgroundSize: "28px 28px",
          opacity: 0.7,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 200,
          top: 100,
          width: 600,
          height: 600,
          borderRadius: "50%",
          background: `radial-gradient(circle, rgba(242,179,76,0.07) 0%, transparent 70%)`,
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          right: 300,
          bottom: 100,
          width: 700,
          height: 700,
          borderRadius: "50%",
          background: `radial-gradient(circle, rgba(217,119,87,0.06) 0%, transparent 70%)`,
          pointerEvents: "none",
        }}
      />

      {/* TOP BRAND BAR */}
      <TopBar kicker={curBeat.kicker} />

      {/* LEFT STAGE (1210x840) */}
      <div
        style={{
          position: "absolute",
          left: STAGE.x + stageSlide,
          top: STAGE.y,
          width: STAGE.w,
          height: STAGE.h,
          borderRadius: STAGE.r,
          overflow: "hidden",
          opacity: stageOpacity,
          boxShadow: "0 30px 80px rgba(0,0,0,0.7), 0 0 0 1px rgba(245,241,232,0.1)",
          background: NAVY_2,
          display: "flex",
          flexDirection: "column",
          zIndex: 10,
        }}
      >
        <BrowserChrome />

        {/* VIEWPORT CONTENT AREA (1210x794) */}
        <div style={{ position: "relative", width: VW, height: VH, overflow: "hidden" }}>
          {/* PREVIOUS BEAT (crossfade out) */}
          {prevBeat && crossfade < 1 ? (
            <div style={{ position: "absolute", inset: 0, opacity: 1 - crossfade }}>
              {prevBeat.media === "broll" && prevBeat.src ? (
                <Footage
                  src={prevBeat.src}
                  from={prevBeat.from ?? 0}
                  beatStart={prevBeat.t}
                  beatEnd={curBeat.t}
                  fps={fps}
                  t={t}
                />
              ) : null}
              {prevBeat.media === "clip" && prevBeat.src ? (
                <div style={{ position: "absolute", inset: 0, background: prevBeat.clipFit === "cover" ? "#000" : CREAM }}>
                  <Loop durationInFrames={Math.max(1, Math.floor((BROLL_DUR[prevBeat.src] || 10) * fps) - 2)} layout="none">
                    <OffthreadVideo
                      muted
                      src={staticFile(`${EPISODE.assetDir}/broll/${prevBeat.src}.mp4`)}
                      style={{ width: "100%", height: "100%", objectFit: prevBeat.clipFit || "contain" }}
                    />
                  </Loop>
                </div>
              ) : null}
            </div>
          ) : null}

          {/* CURRENT BEAT */}
          <div style={{ position: "absolute", inset: 0, opacity: crossfade }}>
            {/* 1. B-ROLL (Full bleed + text) */}
            {curBeat.media === "broll" && curBeat.src ? (
              <>
                <Footage
                  src={curBeat.src}
                  from={curBeat.from ?? 0}
                  beatStart={curBeat.t}
                  beatEnd={beatEnd}
                  fps={fps}
                  t={t}
                />
                <div
                  style={{
                    position: "absolute",
                    inset: 0,
                    background: "linear-gradient(180deg, rgba(11,14,23,0.3) 0%, rgba(11,14,23,0.85) 100%)",
                  }}
                />
                {curBeat.headline ? (
                  <div
                    style={{
                      position: "absolute",
                      left: 48,
                      bottom: 48,
                      right: 48,
                      display: "flex",
                      flexDirection: "column",
                      gap: 8,
                      zIndex: 15,
                    }}
                  >
                    <div
                      style={{
                        fontFamily: FONT,
                        fontWeight: 800,
                        fontSize: 40,
                        color: CREAM,
                        lineHeight: 1.2,
                        textShadow: "0 4px 20px rgba(0,0,0,0.8)",
                      }}
                    >
                      {curBeat.headline}
                    </div>
                    {curBeat.sub ? (
                      <div
                        style={{
                          fontFamily: FONT,
                          fontWeight: 600,
                          fontSize: 22,
                          color: AMBER,
                          lineHeight: 1.3,
                          textShadow: "0 2px 10px rgba(0,0,0,0.8)",
                        }}
                      >
                        {curBeat.sub}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </>
            ) : null}

            {/* 2. CLIP (Museum card style) */}
            {curBeat.media === "clip" && curBeat.src ? (
              <div
                style={{
                  position: "absolute",
                  inset: 0,
                  background: curBeat.clipFit === "cover" ? "#000" : CREAM,
                  display: "flex",
                  flexDirection: "column",
                }}
              >
                <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
                  <Loop durationInFrames={Math.max(1, Math.floor((BROLL_DUR[curBeat.src] || 10) * fps) - 2)} layout="none">
                    <OffthreadVideo
                      muted
                      src={staticFile(`${EPISODE.assetDir}/broll/${curBeat.src}.mp4`)}
                      style={{ width: "100%", height: "100%", objectFit: curBeat.clipFit || "contain" }}
                    />
                  </Loop>
                </div>
                {/* Museum Card Bottom Bar */}
                <div
                  style={{
                    height: 80,
                    background: "rgba(11,14,23,0.92)",
                    backdropFilter: "blur(14px)",
                    borderTop: "1px solid rgba(245,241,232,0.12)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "0 28px",
                    zIndex: 10,
                  }}
                >
                  <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                    <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 20, color: CREAM }}>
                      {curBeat.headline || "SOURCE FOOTAGE"}
                    </span>
                    <span style={{ fontFamily: FONT, fontWeight: 600, fontSize: 14, color: CREAM_DIM }}>
                      {curBeat.sub || ""}
                    </span>
                  </div>
                  <div
                    style={{
                      background: "rgba(242,179,76,0.15)",
                      border: "1px solid rgba(242,179,76,0.4)",
                      padding: "4px 12px",
                      borderRadius: 6,
                      fontFamily: MONO,
                      fontWeight: 700,
                      fontSize: 12,
                      color: AMBER,
                      letterSpacing: 1,
                    }}
                  >
                    {EPISODE.officialTag}
                  </div>
                </div>
              </div>
            ) : null}

            {/* 3. TYPOGRAPHY SCENES */}
            {curBeat.media === "typo" ? (
              <div style={{ position: "absolute", inset: 0 }}>
                {curBeat.src ? (
                  <Footage
                    src={curBeat.src}
                    from={curBeat.from ?? 0}
                    beatStart={curBeat.t}
                    beatEnd={beatEnd}
                    fps={fps}
                    t={t}
                  />
                ) : null}
                <div
                  style={{
                    position: "absolute",
                    inset: 0,
                    background: "rgba(11,14,23,0.85)",
                    backdropFilter: "blur(12px)",
                  }}
                />
                {curBeat.typo === "summary3" ? <TypoSummary3 t={t} fps={fps} beatStart={curBeat.t} /> : null}
                {curBeat.typo === "vs" ? <TypoVs t={t} fps={fps} /> : null}
                {curBeat.typo === "final4" ? <TypoFinal4 t={t} fps={fps} /> : null}
              </div>
            ) : null}
          </div>
        </div>
      </div>

      {/* STAT CHIPS (Pinned to stage bottom-left, wrap) */}
      {curBeat.stats && curBeat.stats.length > 0 ? (
        <div
          style={{
            position: "absolute",
            left: STAGE.x + 28,
            top: STAGE.y + STAGE.h - 110,
            display: "flex",
            gap: 12,
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
