import React, { useEffect, useLayoutEffect, useState } from "react";
import {
  OffthreadVideo,
  Loop,
  Sequence,
  interpolate,
  spring,
  staticFile,
  continueRender,
  cancelRender,
  delayRender,
  useCurrentFrame,
  useVideoConfig,
  CalculateMetadataFunction,
} from "remotion";
import { CAPTION_PAGES } from "./gemini4CarbonNewsV3Captions";
type WebRect = {x:number;y:number;w:number;h:number};

// ===========================================================================
// Gemini4CarbonNewsV3 — 16:9 AI-news report (1920x1080@25)
// Format "Youtube-YT-News-Style01-V3":
// Report subject: YOUTUBE VIDEO ("Gemini Notebook Is Becoming an AI Agent! 10 New Features")
// Left stage: YouTube cuts in museum cards / full-bleed + fresh stock b-roll + typography scenes
// Right stage: Continuous avatar morphing between full-frame and 9:16 vertical card
// Timing spine: Whisper word-level timestamps + SRT calibrated
// B-roll Freshness: V3 ledger-verified 0 repeats, fresh stock & yt cuts
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
const VO_END_SEC = 647.32;
const TOTAL_DURATION_SEC = 651.82; // + 4.54 s endcard
const MODE_BLEND_SEC = 0.55;

// ---- Episode config (swap per episode — every on-screen string lives here) --
const EPISODE = {
  assetDir: "v261111-001-gemini-4-carbon", // public/<assetDir>/{avatar_source.mp4, broll/, web/}
  brand: "AI TECH NEWS",
  dateLabel: "11 พ.ย. 2026",
  page: { domain: "youtube.com", path: "/watch?v=lQ6wwLHqDAg" },
  officialTag: "SOURCE · PROMPT ENGINEERING",
  breakingLabel: "BREAKING NEWS",
  cta: "คุณคิดว่าการปล่อยให้ AI ทำงานข้ามวันมีประโยชน์หรือความเสี่ยงมากกว่ากัน?",
  endcard: {
    eyebrow: "AI TECH NEWS · NOVEMBER 2026",
    titleA: "Gemini 4 Carbon",
    titleB: "Google's Long-Horizon Model",
    cta: "คุณคิดว่าการปล่อยให้ AI ทำงานข้ามวันมีประโยชน์หรือความเสี่ยงมากกว่ากัน?",
  },
};

// ---- Stage geometry (locked) ----------------------------------------------
const W = 1920;
const H = 1080;

// ---- B-roll durations (public/<assetDir>/broll, 1080p25) -------------------
const BROLL_DUR: Record<string, number> = {
  "architect_drawing_blueprint": 15.0,
  "designer_3d_modeling": 18.16,
  "developer_coding_workspace": 30.0,
  "digital_network_data": 8.56,
  "gpu_datacenter_hardware": 15.0,
  "research_analysis_paper": 18.92,
  "robotics_automation_lab": 17.0,
  "space_galaxy_stars": 12.0,
  "supercomputer_server_cluster": 8.0,
  "video_creator_studio": 30.0,
  "yt_agentic_workflow": 38.08,
  "yt_antigravity_ui": 20.08,
  "yt_breakout_play": 35.08,
  "yt_breakout_weights": 31.08,
  "yt_final_fort_result": 26.08,
  "yt_fort_early_pass": 30.08,
  "yt_fort_engine_patch": 30.08,
  "yt_fort_history": 26.08,
  "yt_fort_mid_pass": 30.08,
  "yt_fort_satellite": 25.08,
  "yt_galaxies_sim": 40.08,
  "yt_house_blueprint": 20.08,
  "yt_house_walkthrough": 23.08,
  "yt_intro_title": 15.08,
  "yt_jet_engine": 20.08,
  "yt_prompt_rules_slide": 37.08,
  "yt_quadruped_expand": 18.08,
  "yt_quadruped_rl": 24.08,
  "yt_sdf_dragon_3d": 35.08,
  "yt_sdf_dragon_code": 24.08,
  "yt_seaquest_limit": 35.08,
  "yt_studio_equipment": 22.08,
  "yt_studio_lighting": 25.08,
  "yt_studio_ui": 27.08,
  "yt_subagent_scoring": 33.08,
  "yt_teacup_agents": 29.08,
  "yt_teacup_render": 30.08,
  "yt_threejs_auditing": 25.08,
  "yt_threejs_openworld": 28.08,
  "yt_threejs_smooth": 15.08
};

// ---- Beat model -----------------------------------------------------------
interface CamKey { t: number; fy: number; z: number; fx?: number }
interface Highlight { t: number; key?: string; rect?: WebRect; pad?: number }
interface Stat { t: number; big?: string; label: string; tone?: "amber" | "mint" | "clay" }

interface Beat {
  captionLane?: "top" | "bottom";
  cards?: {t:number;lines:string[]}[];
  origin?: "source" | "stock" | "ai";
  layout?: "stage" | "full";
  chrome?: boolean;
  punch?: {t:number;z:number;fx?:number;fy?:number}[];
  t: number;
  mode: "full" | "pip";
  media?: "broll" | "clip" | "typo";
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
  {
    "t": 0.0,
    "mode": "full",
    "kicker": "BREAKING NEWS",
    "lower": {
      "title": "GEMINI 4 CARBON",
      "sub": "โมเดลวิศวกรรมระยะยาวจาก Google",
      "t": 1.0,
      "dur": 4.5
    }
  },
  {
    "t": 9.0,
    "mode": "pip",
    "media": "clip",
    "src": "yt_intro_title",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "OFFICIAL ANNOUNCEMENT",
    "headline": "เปิดตัว Gemini 4 Carbon",
    "sub": "โมเดลทรงพลังที่สุดสำหรับงานวิศวกรรมระยะยาว",
    "punch": [
      {
        "t": 14.5,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 19.34,
    "mode": "pip",
    "media": "clip",
    "src": "yt_antigravity_ui",
    "origin": "source",
    "layout": "stage",
    "chrome": true,
    "kicker": "AGENTIC CODING",
    "headline": "ระบบเขียนโค้ด Anti-gravity",
    "sub": "สิทธิ์เข้าใช้งานล่วงหน้าจาก Google DeepMind"
  },
  {
    "t": 26.62,
    "mode": "pip",
    "media": "broll",
    "src": "developer_coding_workspace",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "FULL AUTONOMY",
    "headline": "ค้นข้อมูล เขียนโค้ด รันโปรแกรมเอง",
    "sub": "เอเจนต์ทำงานได้เบ็ดเสร็จบนคอมพิวเตอร์"
  },
  {
    "t": 35.18,
    "mode": "full",
    "kicker": "BEYOND BENCHMARKS"
  },
  {
    "t": 44.64,
    "mode": "pip",
    "media": "broll",
    "src": "research_analysis_paper",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "INDEPENDENT RESEARCH",
    "headline": "หยิบงานวิจัยสู่โปรแกรมจริง",
    "sub": "ค้นคว้าข้อมูลเชิงลึกและลงมือพัฒนาด้วยตนเอง"
  },
  {
    "t": 53.02,
    "mode": "pip",
    "media": "clip",
    "src": "yt_threejs_openworld",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "DEMO 01 · THREE.JS",
    "headline": "ภาพเคลื่อนไหว 3D บนเว็บ",
    "sub": "ทดสอบสร้างฉากสามมิติบนเบราว์เซอร์จากโจทย์สั้น"
  },
  {
    "t": 59.24,
    "mode": "pip",
    "media": "broll",
    "src": "designer_3d_modeling",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "GRAPHICS LIBRARY",
    "headline": "Three.js ไลบรารี 3D ยอดนิยม",
    "sub": "ส่งลิงก์วิดีโอจากแพลตฟอร์ม X เป็นภาพอ้างอิง"
  },
  {
    "t": 66.82,
    "mode": "full",
    "kicker": "FORT RUNNER PROMPT"
  },
  {
    "t": 74.3,
    "mode": "pip",
    "media": "clip",
    "src": "yt_threejs_smooth",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "GENERATION RESULT",
    "headline": "ฉาก 3D วิ่งผ่านป้อมปราการ",
    "sub": "เรนเดอร์คุณภาพสูงเทียบเท่าหรือดีกว่าต้นฉบับ"
  },
  {
    "t": 81.76,
    "mode": "pip",
    "media": "typo",
    "src": "typo_threejs",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "BROWSER 3D BENCHMARK",
    "headline": "ฉากสามมิติแบบเปิด Open World",
    "sub": "สร้างโมเดล สภาพแวดล้อม และแอนิเมชันครบชุด",
    "cards": [
      {
        "t": 81.76,
        "lines": [
          "เรนเดอร์กราฟิกสามมิติบนเว็บ",
          "โมเดลและแอนิเมชันสร้างจากโค้ด"
        ]
      }
    ],
    "stats": [
      {
        "t": 82.5,
        "big": "THREE.JS",
        "label": "WEB 3D",
        "tone": "amber"
      },
      {
        "t": 84.0,
        "big": "100%",
        "label": "CODE NATIVE",
        "tone": "mint"
      }
    ]
  },
  {
    "t": 87.1,
    "mode": "full",
    "kicker": "FIRST AUDIT INSPECTION"
  },
  {
    "t": 94.44,
    "mode": "pip",
    "media": "clip",
    "src": "yt_threejs_auditing",
    "origin": "source",
    "layout": "stage",
    "chrome": true,
    "kicker": "AUTONOMOUS SELF-AUDIT",
    "headline": "ไม่แก้โค้ดแบบสุ่ม",
    "sub": "ตรวจจับจังหวะขากระตุกและวิเคราะห์ปัญหาเอง"
  },
  {
    "t": 99.0,
    "mode": "pip",
    "media": "broll",
    "src": "digital_network_data",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "FRAME-BY-FRAME SCRIPT",
    "headline": "เขียนโปรแกรมตรวจสอบทีละเฟรม",
    "sub": "ตรวจจับการสะดุดของกล้องและตัวละครอัตโนมัติ"
  },
  {
    "t": 104.98,
    "mode": "full",
    "kicker": "SMOOTH MOTION CORRECTION",
    "punch": [
      {
        "t": 110.0,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 115.06,
    "mode": "pip",
    "media": "clip",
    "src": "yt_sdf_dragon_code",
    "origin": "source",
    "layout": "stage",
    "chrome": true,
    "kicker": "DEMO 02 · SDF DRAGON",
    "headline": "3D จากสูตรคณิตศาสตร์ล้วนๆ",
    "sub": "สร้างรูปทรงมังกรซับซ้อนโดยไม่มีไฟล์โมเดล"
  },
  {
    "t": 124.2,
    "mode": "full",
    "kicker": "KENAN CRANE EXPERIMENT"
  },
  {
    "t": 129.42,
    "mode": "pip",
    "media": "broll",
    "src": "architect_drawing_blueprint",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "INIGO QUILEZ CONCEPT",
    "headline": "ภาพแนวคิด Inigo Quilez",
    "sub": "ป้อนภาพสเก็ตช์ภาพเดียวเพื่อสร้างโมเดล SDF"
  },
  {
    "t": 134.7,
    "mode": "pip",
    "media": "typo",
    "src": "typo_sdf",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "SIGNED DISTANCE FUNCTION",
    "headline": "สมการคณิตศาสตร์กำหนดพื้นผิว",
    "sub": "คำนวณระยะห่างทุกจุดในพื้นที่สู่พื้นผิววัตถุ",
    "cards": [
      {
        "t": 134.7,
        "lines": [
          "Signed Distance Function (SDF)",
          "มังกรทั้งตัวสร้างจากโค้ดสมการคณิตศาสตร์"
        ]
      }
    ],
    "stats": [
      {
        "t": 135.5,
        "big": "SDF",
        "label": "MATH FUNCTION",
        "tone": "amber"
      },
      {
        "t": 137.5,
        "big": "0 POLYGON",
        "label": "PURE CODE",
        "tone": "mint"
      }
    ]
  },
  {
    "t": 140.46,
    "mode": "full",
    "kicker": "PURE MATHEMATICS 3D",
    "punch": [
      {
        "t": 146.0,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 152.0,
    "mode": "pip",
    "media": "clip",
    "src": "yt_sdf_dragon_3d",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "72 MINUTES RUN",
    "headline": "ประมวลผลรอบเดียว 72 นาที",
    "sub": "สร้างมังกรสมบูรณ์แบบที่มองเห็นมิติได้ทุกมุม"
  },
  {
    "t": 157.66,
    "mode": "pip",
    "media": "broll",
    "src": "supercomputer_server_cluster",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "SPATIAL REASONING",
    "headline": "มิติจากมุมที่ไม่มีในภาพต้นฉบับ",
    "sub": "ความเข้าใจโครงสร้างเชิงลึกผ่านการจำลองคณิตศาสตร์"
  },
  {
    "t": 164.68,
    "mode": "pip",
    "media": "clip",
    "src": "yt_teacup_agents",
    "origin": "source",
    "layout": "stage",
    "chrome": true,
    "kicker": "DEMO 03 · SUB-AGENTS",
    "headline": "พายุในถ้วยชา (Storm in a Teacup)",
    "sub": "สั่งงานด้วยทีมเอเจนต์ย่อยช่วยกันทำงาน"
  },
  {
    "t": 170.76,
    "mode": "full",
    "kicker": "MULTI-AGENT DECOMPOSITION"
  },
  {
    "t": 178.0,
    "mode": "pip",
    "media": "clip",
    "src": "yt_teacup_render",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "CENTRAL TIMELINE",
    "headline": "วางแผนไทม์ไลน์ส่วนกลาง",
    "sub": "กำหนดจังหวะฟ้าผ่า คลื่นชา และแสงสว่างแม่นยำ"
  },
  {
    "t": 183.84,
    "mode": "pip",
    "media": "broll",
    "src": "gpu_datacenter_hardware",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "PARALLEL AGENTS",
    "headline": "เอเจนต์เฉพาะทางแยกชิ้นส่วน",
    "sub": "ดูแลถ้วยกระเบื้อง ผิวน้ำชา แสงสว่าง และก้อนเมฆ"
  },
  {
    "t": 191.1,
    "mode": "pip",
    "media": "typo",
    "src": "typo_teacup",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "CODE SCALE",
    "headline": "โค้ดรวมเกือบ 13,000 บรรทัด",
    "sub": "ประสานงานหลายเอเจนต์โดยมนุษย์ไม่ต้องแบ่งงานย่อยเอง",
    "cards": [
      {
        "t": 191.1,
        "lines": [
          "เอเจนต์ถ้วย · เอเจนต์น้ำชา · เอเจนต์เมฆ",
          "ประสานงานผ่านเส้นเวลาจำลองอัตโนมัติ"
        ]
      }
    ],
    "stats": [
      {
        "t": 192.0,
        "big": "3 ROLES",
        "label": "SUB-AGENTS",
        "tone": "amber"
      },
      {
        "t": 194.5,
        "big": "13,000",
        "label": "LINES OF CODE",
        "tone": "mint"
      }
    ]
  },
  {
    "t": 199.32,
    "mode": "full",
    "kicker": "EVERYDAY APPLICATIONS"
  },
  {
    "t": 206.8,
    "mode": "pip",
    "media": "clip",
    "src": "yt_studio_ui",
    "origin": "source",
    "layout": "stage",
    "chrome": true,
    "kicker": "DEMO 04 · 3D STUDIO",
    "headline": "ออกแบบสตูดิโอ YouTube ในห้องเช่า",
    "sub": "แก้โจทย์พื้นที่จำกัดที่ไม่สามารถเจาะผนังได้",
    "punch": [
      {
        "t": 213.0,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 219.3,
    "mode": "pip",
    "media": "broll",
    "src": "video_creator_studio",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "ITERATIVE REFINEMENT",
    "headline": "สั่งปรับปรุงไม่ต่ำกว่า 10 รอบ",
    "sub": "โมเดลเรนเดอร์ภาพ ตรวจสอบ และแก้ไขรวม 15 รอบ"
  },
  {
    "t": 225.3,
    "mode": "pip",
    "media": "clip",
    "src": "yt_studio_lighting",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "LIGHTING & CAMERAS",
    "headline": "ปรับมุมกล้องและสลับเปิดปิดไฟ",
    "sub": "คลิกเปลี่ยนมุมมอง ปรับเลนส์ และตรวจระยะห่างโต๊ะกับผนัง"
  },
  {
    "t": 231.82,
    "mode": "pip",
    "media": "clip",
    "src": "yt_studio_equipment",
    "origin": "source",
    "layout": "stage",
    "chrome": true,
    "kicker": "EQUIPMENT LIST",
    "headline": "รายการอุปกรณ์แนะนำพร้อมใช้",
    "sub": "จำลองระยะจัดวางอย่างแม่นยำก่อนซื้อจริง",
    "punch": [
      {
        "t": 238.0,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 244.56,
    "mode": "full",
    "kicker": "CREATOR PERSPECTIVE"
  },
  {
    "t": 250.06,
    "mode": "pip",
    "media": "typo",
    "src": "typo_studio",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "PRACTICAL BENEFIT",
    "headline": "จำลองห้องสามมิติก่อนซื้อของจริง",
    "sub": "ช่วยคนขายของออนไลน์และยูทูบเบอร์วางแผนสตูดิโอ",
    "cards": [
      {
        "t": 250.06,
        "lines": [
          "ป้อนขนาดห้องเช่าเพื่อวางไฟและกล้อง",
          "ตรวจสอบมุมมองก่อนตัดสินใจซื้อจริง"
        ]
      }
    ],
    "stats": [
      {
        "t": 251.0,
        "big": "15 PASSES",
        "label": "SELF-AUDIT",
        "tone": "amber"
      },
      {
        "t": 253.5,
        "big": "3D SIM",
        "label": "ROOM PLANNER",
        "tone": "mint"
      }
    ]
  },
  {
    "t": 257.48,
    "mode": "pip",
    "media": "clip",
    "src": "yt_house_blueprint",
    "origin": "source",
    "layout": "stage",
    "chrome": true,
    "kicker": "DEMO 05 · 1949 BLUEPRINT",
    "headline": "พิมพ์เขียวบ้าน Marcel Breuer ปี 1949",
    "sub": "เอกสารสถาปัตยกรรมจากหอสมุดรัฐสภาอเมริกัน",
    "punch": [
      {
        "t": 263.0,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 268.78,
    "mode": "pip",
    "media": "clip",
    "src": "yt_house_walkthrough",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "4 HOURS COMPUTE",
    "headline": "บ้าน 3D สำรวจทะลุห้องได้ทั้งหลัง",
    "sub": "แปลงแปลนกระดาษสู่พื้นที่จำลองในเวลา 4 ชั่วโมง"
  },
  {
    "t": 277.6,
    "mode": "full",
    "kicker": "OUR TAKE · REASONING"
  },
  {
    "t": 285.42,
    "mode": "pip",
    "media": "typo",
    "src": "typo_blueprint",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "REDUCING 3D BARRIER",
    "headline": "ลดภาระการขึ้นโครงสร้างสามมิติ",
    "sub": "คนทั่วไปสร้างพื้นที่จำลองได้โดยไม่ต้องพึ่งทีมงานหลายฝ่าย",
    "cards": [
      {
        "t": 285.42,
        "lines": [
          "เปลี่ยนภาพแปลนกระดาษแผ่นเดียว",
          "เป็นพื้นที่จำลองเดินสำรวจได้จริง"
        ]
      }
    ],
    "stats": [
      {
        "t": 286.5,
        "big": "4 HOURS",
        "label": "COMPUTE TIME",
        "tone": "amber"
      },
      {
        "t": 289.0,
        "big": "1 IMAGE",
        "label": "INPUT BLUEPRINT",
        "tone": "mint"
      }
    ]
  },
  {
    "t": 293.4,
    "mode": "full",
    "kicker": "AUTONOMOUS RECONSTRUCTION",
    "punch": [
      {
        "t": 298.0,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 301.38,
    "mode": "full",
    "kicker": "LARGE-SCALE EXPERIMENT",
    "punch": [
      {
        "t": 306.5,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 311.64,
    "mode": "pip",
    "media": "clip",
    "src": "yt_fort_history",
    "origin": "source",
    "layout": "stage",
    "chrome": true,
    "kicker": "DEMO 06 · QILA BALA HISSAR",
    "headline": "ป้อมปราการประวัติศาสตร์ Peshawar",
    "sub": "สถานที่แทบไม่มีข้อมูลออนไลน์และเอกสารขาดหาย"
  },
  {
    "t": 319.76,
    "mode": "pip",
    "media": "clip",
    "src": "yt_fort_satellite",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "SATELLITE RECONNAISSANCE",
    "headline": "ภาพถ่ายดาวเทียม Esri World Imagery",
    "sub": "โมเดลค้นหาภาพถ่ายดาวเทียมเพื่อวัดขนาดกำแพงจริง"
  },
  {
    "t": 327.56,
    "mode": "full",
    "kicker": "NO BLENDER · NO THREE.JS"
  },
  {
    "t": 334.36,
    "mode": "pip",
    "media": "clip",
    "src": "yt_fort_early_pass",
    "origin": "source",
    "layout": "stage",
    "chrome": true,
    "kicker": "NEW TOOL · 67.JS",
    "headline": "สร้างด้วย 67.js เอนจินใหม่เอี่ยม",
    "sub": "เครื่องมือ 3D โอเพนซอร์สที่เปิดตัวได้เพียงหนึ่งเดือน"
  },
  {
    "t": 342.5,
    "mode": "full",
    "kicker": "100+ UNATTENDED PASSES"
  },
  {
    "t": 349.78,
    "mode": "pip",
    "media": "typo",
    "src": "typo_research_phase",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "PHASE 1: RESEARCH FIRST",
    "headline": "เริ่มจากการสืบค้นข้อมูลเชิงลึก",
    "sub": "โมเดลไม่รีบขึ้นรูป 3D แต่ใช้วิธีอ่านบันทึกประวัติศาสตร์",
    "cards": [
      {
        "t": 349.78,
        "lines": [
          "ช่วงแรกโมเดลไม่ขึ้นรูปสามมิติ",
          "แต่ใช้เวลาไปกับการสืบค้นข้อมูล 30 แหล่ง"
        ]
      }
    ],
    "stats": [
      {
        "t": 351.0,
        "big": "30 SOURCES",
        "label": "HISTORICAL DOCS",
        "tone": "amber"
      },
      {
        "t": 353.0,
        "big": "1890s",
        "label": "COLONIAL RECORDS",
        "tone": "mint"
      }
    ]
  },
  {
    "t": 355.78,
    "mode": "pip",
    "media": "clip",
    "src": "yt_fort_mid_pass",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "ARCHITECTURAL TIMELINE",
    "headline": "สร้างตามประวัติศาสตร์จริง",
    "sub": "อิฐโคลนยุคซิกข์ 1830 และกำแพงนอกยุคอังกฤษ 1849",
    "punch": [
      {
        "t": 360.5,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 364.5,
    "mode": "full",
    "kicker": "HISTORICAL FIDELITY"
  },
  {
    "t": 373.0,
    "mode": "pip",
    "media": "clip",
    "src": "yt_final_fort_result",
    "origin": "source",
    "layout": "stage",
    "chrome": true,
    "kicker": "CONFIDENCE LABELS",
    "headline": "ติดป้ายจุดที่คาดเดาขึ้นเอง",
    "sub": "ส่วนที่ไม่มีบันทึกชัดเจนจะระบุว่าเป็นการคาดเดา"
  },
  {
    "t": 381.68,
    "mode": "full",
    "kicker": "ENGINE LIMITATIONS"
  },
  {
    "t": 390.74,
    "mode": "pip",
    "media": "clip",
    "src": "yt_fort_engine_patch",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "CODE REPAIR",
    "headline": "แก้ซอร์สโค้ดของเอนจิน 67.js",
    "sub": "แก้โค้ดเครื่องมือเอง 6 ครั้ง รวมแก้บักของเอนจิน 2 ครั้ง"
  },
  {
    "t": 399.0,
    "mode": "pip",
    "media": "clip",
    "src": "yt_jet_engine",
    "origin": "source",
    "layout": "stage",
    "chrome": true,
    "kicker": "COMPLEX MECHANISM",
    "headline": "สร้างภาพตัดขวางเครื่องยนต์เจ็ต",
    "sub": "แยกชิ้นส่วนกลไกซับซ้อนและส่งออกไฟล์ 3D ได้ทันที"
  },
  {
    "t": 408.1,
    "mode": "full",
    "kicker": "AUTONOMOUS GRADING"
  },
  {
    "t": 413.58,
    "mode": "pip",
    "media": "clip",
    "src": "yt_subagent_scoring",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "FRESH SUB-AGENT SCORING",
    "headline": "เอเจนต์ตัวใหม่ตรวจงานทุก 10 รอบ",
    "sub": "ให้คะแนนภาพเทียบกับรูปถ่ายจริงโดยไม่ดูข้อมูลเก่า"
  },
  {
    "t": 422.34,
    "mode": "pip",
    "media": "typo",
    "src": "typo_scoring",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "SCORE PROGRESSION",
    "headline": "คะแนนพัฒนาจาก 3 สู่ 5 เต็ม 10",
    "sub": "เริ่มจากรูปทรงหยาบๆ จนสมบูรณ์ขึ้นในเวลา 20 ชั่วโมง",
    "cards": [
      {
        "t": 422.34,
        "lines": [
          "รอบที่ 1: คะแนน 3/10 (รูปทรงหยาบ)",
          "รอบที่ 65: คะแนน 5/10 (เวลา 20 ชั่วโมง)"
        ]
      }
    ],
    "stats": [
      {
        "t": 423.5,
        "big": "3 → 5",
        "label": "QUALITY SCORE",
        "tone": "amber"
      },
      {
        "t": 426.0,
        "big": "20 HOURS",
        "label": "UNATTENDED TIME",
        "tone": "mint"
      }
    ]
  },
  {
    "t": 430.5,
    "mode": "full",
    "kicker": "TARGET SCORE: 8/10",
    "punch": [
      {
        "t": 435.0,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 438.86,
    "mode": "full",
    "kicker": "HARDWARE ACCELERATION",
    "punch": [
      {
        "t": 444.5,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 450.14,
    "mode": "pip",
    "media": "clip",
    "src": "yt_galaxies_sim",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "DGX SPARK CLUSTER",
    "headline": "จำลองดาราจักรชนกัน 500,000 ดวง",
    "sub": "เขียนโค้ดและรันแบบจำลองฟิสิกส์บนฮาร์ดแวร์จริง"
  },
  {
    "t": 458.5,
    "mode": "pip",
    "media": "broll",
    "src": "space_galaxy_stars",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "SYSTEM STABILITY TEST",
    "headline": "ทดสอบรันดาราจักรเดี่ยวก่อน",
    "sub": "โมเดลวางกลยุทธ์ตรวจความเสถียรก่อนเริ่มงานใหญ่"
  },
  {
    "t": 468.48,
    "mode": "pip",
    "media": "broll",
    "src": "robotics_automation_lab",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "REINFORCEMENT LEARNING",
    "headline": "หุ่นยนต์สี่ขาหัดวิ่งจากศูนย์",
    "sub": "เขียนอัลกอริทึมเสริมกำลังให้หุ่นยนต์เรียนรู้ด้วยตัวเอง"
  },
  {
    "t": 474.5,
    "mode": "pip",
    "media": "clip",
    "src": "yt_quadruped_rl",
    "origin": "source",
    "layout": "stage",
    "chrome": true,
    "kicker": "ROBOT RUNNING DEMO",
    "headline": "ตรวจพบหุ่นยนต์วิ่งตกขอบพื้น",
    "sub": "โมเดลตรวจคลิปวิดีโอแล้วพบจุดบกพร่องของฉาก"
  },
  {
    "t": 480.5,
    "mode": "pip",
    "media": "clip",
    "src": "yt_quadruped_expand",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "SCENE EXPANSION",
    "headline": "ขยายพื้นฉากแล้วเรนเดอร์ใหม่",
    "sub": "ปรับขนาดพื้นที่และสั่งเรนเดอร์วิดีโอซ้ำอัตโนมัติ"
  },
  {
    "t": 486.82,
    "mode": "full",
    "kicker": "MOST SURPRISING EXPERIMENT",
    "punch": [
      {
        "t": 492.0,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 497.06,
    "mode": "pip",
    "media": "clip",
    "src": "yt_breakout_weights",
    "origin": "source",
    "layout": "stage",
    "chrome": true,
    "kicker": "WEIGHT-SPACE PROGRAMMING",
    "headline": "เขียนค่าน้ำหนักนิวรัลเน็ตโดยตรง",
    "sub": "งานวิจัยจากสถาบัน MIT โดยไม่ต้องเทรนข้อมูล"
  },
  {
    "t": 504.22,
    "mode": "full",
    "kicker": "NO TRAINING REQUIRED"
  },
  {
    "t": 511.98,
    "mode": "pip",
    "media": "clip",
    "src": "yt_breakout_play",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "ZERO-SHOT WEIGHTS",
    "headline": "เขียนค่าน้ำหนัก 20,000 ค่าในคำตอบเดียว",
    "sub": "ส่งเพียงโค้ดเกม Breakout ให้โมเดลสร้างโครงข่าย"
  },
  {
    "t": 519.0,
    "mode": "full",
    "kicker": "SPARSE WEIGHT ACTIVATION"
  },
  {
    "t": 526.18,
    "mode": "pip",
    "media": "typo",
    "src": "typo_breakout",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "SCORE BENCHMARK",
    "headline": "ทำคะแนนเฉลี่ย 217 คะแนนต่อเกม",
    "sub": "เทียบกับโมเดลเทรนปกติของ MIT ที่ทำได้เพียง 25 คะแนน",
    "cards": [
      {
        "t": 526.18,
        "lines": [
          "Gemini 4 Carbon (Zero-shot): 217 คะแนน",
          "โมเดลเทรนปกติของ MIT: ~25 คะแนน"
        ]
      }
    ],
    "stats": [
      {
        "t": 527.5,
        "big": "217 PTS",
        "label": "CARBON WEIGHTS",
        "tone": "mint"
      },
      {
        "t": 530.0,
        "big": "25 PTS",
        "label": "TRAINED MIT NET",
        "tone": "amber"
      }
    ]
  },
  {
    "t": 535.28,
    "mode": "full",
    "kicker": "SPECTACULAR PERFORMANCE"
  },
  {
    "t": 541.74,
    "mode": "pip",
    "media": "clip",
    "src": "yt_seaquest_limit",
    "origin": "source",
    "layout": "stage",
    "chrome": true,
    "kicker": "MODEL LIMITATIONS",
    "headline": "ข้อจำกัดในเกมที่ยากขึ้น",
    "sub": "ทดสอบกับเกม Seaquest แล้วติดเพดานความยาวคำตอบทั้ง 4 ครั้ง"
  },
  {
    "t": 548.92,
    "mode": "full",
    "kicker": "EFFORT SETTING CAVEAT"
  },
  {
    "t": 557.0,
    "mode": "pip",
    "media": "typo",
    "src": "typo_caveats",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "KNOWN LIMITATIONS",
    "headline": "ข้อควรระวังในการตั้งค่า Effort",
    "sub": "การตั้งระดับการคิดสูงเกินไปอาจใช้โควตาโทเคนจนหมด",
    "cards": [
      {
        "t": 557.0,
        "lines": [
          "Effort Setting สูงเกินไปอาจกินโควตาคิดจนหมด",
          "ต้องควบคุมความยาวและจำนวนรอบการคิด"
        ]
      }
    ],
    "stats": [
      {
        "t": 558.5,
        "big": "EFFORT",
        "label": "THINKING BUDGET",
        "tone": "clay"
      },
      {
        "t": 561.0,
        "big": "TOKEN CAP",
        "label": "OUTPUT CEILING",
        "tone": "amber"
      }
    ]
  },
  {
    "t": 565.5,
    "mode": "full",
    "kicker": "PRICING & ROLLOUT"
  },
  {
    "t": 573.96,
    "mode": "pip",
    "media": "clip",
    "src": "yt_agentic_workflow",
    "origin": "source",
    "layout": "stage",
    "chrome": true,
    "kicker": "AGENTIC ENGINEERING",
    "headline": "สถาปัตยกรรมการทำงานระยะยาว",
    "sub": "การออกแบบระบบเอเจนต์ที่ทำงานต่อเนื่องอย่างมีแบบแผน"
  },
  {
    "t": 583.42,
    "mode": "full",
    "kicker": "4 PROMPTING RULES"
  },
  {
    "t": 589.18,
    "mode": "pip",
    "media": "clip",
    "src": "yt_prompt_rules_slide",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "RULES 1 & 2 · LOOPS & STATE",
    "headline": "กำหนดรอบขั้นต่ำ & บันทึกลงดิสก์",
    "sub": "บันทึกสถานะงานลงดิสก์แก้ปัญหา Context Window ล้น"
  },
  {
    "t": 597.0,
    "mode": "pip",
    "media": "typo",
    "src": "typo_rules",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "RULES 3 & 4 · VISION & HUMAN",
    "headline": "เอเจนต์ตัวใหม่ตรวจงาน & มนุษย์คุม",
    "sub": "การให้คะแนนตัวเองยังไม่สามารถแทนที่สายตามนุษย์ได้",
    "cards": [
      {
        "t": 597.0,
        "lines": [
          "1. กำหนดรอบแก้ไขขั้นต่ำตั้งแต่คำสั่งแรก",
          "2. บันทึกสถานะงานลงบนดิสก์กันบริบทล้น",
          "3. ใช้เอเจนต์ตัวใหม่มาประเมินผลงาน",
          "4. ใช้สายตามนุษย์ร่วมตรวจสอบเสมอ"
        ]
      }
    ],
    "stats": [
      {
        "t": 598.0,
        "big": "4 RULES",
        "label": "ENGINEERING PROMPTS",
        "tone": "amber"
      },
      {
        "t": 600.5,
        "big": "HUMAN",
        "label": "IN THE LOOP",
        "tone": "mint"
      }
    ]
  },
  {
    "t": 605.0,
    "mode": "full",
    "kicker": "HUMAN IN THE LOOP",
    "punch": [
      {
        "t": 610.0,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 613.68,
    "mode": "full",
    "kicker": "PARADIGM SHIFT",
    "punch": [
      {
        "t": 617.5,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 621.5,
    "mode": "pip",
    "media": "typo",
    "src": "typo_future",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "ENGINEERING ERA",
    "headline": "สู่การออกแบบระบบวิศวกรรม",
    "sub": "โมเดลตระกูล Fable และ Astra ถูกสร้างมาเพื่อการวนซ้ำหลายสิบรอบ",
    "cards": [
      {
        "t": 621.5,
        "lines": [
          "เปลี่ยนจากการถามตอบสั้นๆ",
          "สู่การออกแบบระบบวิศวกรรมแบบวนซ้ำ"
        ]
      }
    ],
    "stats": [
      {
        "t": 622.5,
        "big": "SYSTEM",
        "label": "ENGINEERING",
        "tone": "amber"
      },
      {
        "t": 625.0,
        "big": "FABLE/ASTRA",
        "label": "NEW FRONTIER",
        "tone": "mint"
      }
    ]
  },
  {
    "t": 629.5,
    "mode": "full",
    "kicker": "AUTONOMOUS FUTURE",
    "punch": [
      {
        "t": 634.0,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 637.7,
    "mode": "full",
    "kicker": "JOIN THE DISCUSSION",
    "punch": [
      {
        "t": 642.0,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  }
];

const CTA_T = 637.7;

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
    ensureFonts().then(() => continueRender(handle)).catch(cancelRender);
  }, [handle]);
};

// ---- Helpers --------------------------------------------------------------
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const easeInOutCos = (p: number) => (1 - Math.cos(Math.PI * clamp01(p))) / 2;
const easeOutCubic = (p: number) => 1 - Math.pow(1 - clamp01(p), 3);
const springIn = (frame: number, fps: number, damping = 16, stiffness = 130) =>
  spring({ frame: Math.max(0, frame), fps, config: { damping, stiffness } });

const boundedEntrance = (t:number,start:number,fps:number):React.CSSProperties => {
  const p=clamp01(springIn(Math.round((t-start)*fps),fps,18,130));
  return {opacity:p,transform:`translateY(${(1-p)*6}px)`};
};

const tone = (k?: string) => (k === "mint" ? MINT : k === "clay" ? CLAY : AMBER);

// ---- V3 presentation: explicit, non-overlapping text lanes -----------------
const TextField: React.FC<{id:string;role?:"read"|"label";style?:React.CSSProperties;children:React.ReactNode}> = ({id,role="read",style,children}) => <div data-qc-field={id} data-qc-role={role} style={{fontFamily:FONT,fontSize:role==="label"?24:30,fontWeight:700,lineHeight:1.55,color:CREAM,...style}}>{children}</div>;
const CaptionLane: React.FC<{t:number;lane:"top"|"bottom"}> = ({t,lane}) => {
  const page=CAPTION_PAGES.find(p=>t>=p.start&&t<p.end);
  if(!page)return null;
  return <div style={{position:"absolute",left:116,right:lane==="top"?undefined:116,width:lane==="top"?650:undefined,bottom:lane==="bottom"?66:undefined,top:lane==="top"?248:undefined,display:"flex",justifyContent:lane==="top"?"flex-start":"center",zIndex:60}}>
    <div data-qc-backing="solid" data-qc-occluder="caption-pill" data-qc-field="caption" data-qc-role="read" data-qc-caption-display={page.displayText} style={{fontFamily:FONT,fontSize:32,fontWeight:800,lineHeight:1.65,background:"rgba(11,14,23,.92)",padding:"6px 26px",borderRadius:18,maxWidth:lane==="top"?598:1500,textAlign:lane==="top"?"left":"center",whiteSpace:"pre-wrap",overflowWrap:"normal"}}>
      {page.chunks.map((chunk,i)=><React.Fragment key={i}>{chunk.displaySpaceBefore}<span style={{display:"inline-block",whiteSpace:"pre",color:t>=chunk.displayStart&&t<chunk.displayEnd?GOLD_LIGHT:CREAM,textShadow:t>=chunk.displayStart&&t<chunk.displayEnd?`0 0 12px ${GOLD}`:"none"}}>{chunk.text}</span></React.Fragment>)}
    </div>
  </div>;
};
const EndCard: React.FC = () => <div style={{position:"absolute",inset:0,background:NAVY,display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",gap:24,zIndex:90}}>
  <TextField id="end-label" role="label" style={{color:AMBER}}>{EPISODE.endcard.eyebrow}</TextField>
  <TextField id="end-title" style={{fontSize:64}}>{EPISODE.endcard.titleA}</TextField>
  <TextField id="end-sub" style={{fontSize:36,color:AMBER}}>{EPISODE.endcard.titleB}</TextField>
  <TextField id="end-cta" style={{marginTop:30}}>{EPISODE.endcard.cta}</TextField>
</div>;

// QC is observation-only: production has no layout injection or media substitution.
const QcProbe: React.FC<{enabled:boolean;plan:boolean;frame:number;beat:Beat}> = ({enabled,plan,frame,beat}) => {
  const {fps}=useVideoConfig();
  useLayoutEffect(() => {
    if (!enabled && !plan) return;
    const handle=delayRender("V3 DOM measurement");
    let live=true;
    ensureFonts().then(()=>document.fonts.ready).then(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())))).then(()=>{
      if(!live)return;
      if(plan){
        const times=new Set<number>([0,9,89,172,VO_END_SEC, TOTAL_DURATION_SEC-0.04]);
        BEATS.forEach((b,i)=>{const end=BEATS[i+1]?.t??VO_END_SEC; [b.t,b.t+0.12,b.t+0.36,b.t+0.56,(b.t+end)/2,end-0.04].forEach(t=>times.add(t)); b.stats?.forEach(st=>[st.t,st.t+0.12,st.t+0.32,st.t+0.64].forEach(t=>times.add(t))); b.cards?.forEach(c=>[c.t,c.t+0.12,c.t+0.36,c.t+0.64].forEach(t=>times.add(t))); b.punch?.forEach(p=>[p.t-0.04,p.t,p.t+0.04].forEach(t=>times.add(t)));if(b.lower)[b.lower.t??b.t,(b.lower.t??b.t)+0.32,(b.lower.t??b.t)+(b.lower.dur??6)-0.04].forEach(t=>times.add(t));});
        CAPTION_PAGES.forEach(p=>times.add((p.start+p.end)/2));
        [CTA_T,CTA_T+0.12,CTA_T+0.32,CTA_T+0.64].forEach(t=>times.add(t));
        const rectFor=(b:Beat)=>b.mode==="full"?[116,128,1688,744,1]:b.layout==="full"?[1340,128,464,690,0]:[1340,128,464,690,1];
        const sweepWindows=BEATS.flatMap((b,i)=>i&&JSON.stringify(rectFor(BEATS[i-1]))!==JSON.stringify(rectFor(b))?[{id:`avatar-${i}`,beatT:b.t,startFrame:Math.ceil(b.t*fps),endFrame:Math.min(Math.ceil(TOTAL_DURATION_SEC*fps)-1,Math.ceil((b.t+MODE_BLEND_SEC)*fps)+3)}]:[]);
        const frames=new Set([...times].filter(t=>t>=0&&t<TOTAL_DURATION_SEC).map(t=>Math.round(t*fps)));
        sweepWindows.forEach(w=>{for(let f=w.startFrame;f<=w.endFrame;f++)frames.add(f);});
        console.log("__QC_PLAN__"+JSON.stringify({frames:[...frames].sort((a,b)=>a-b),fps,sweepWindows,sweepVersion:"avatar-empty-backing-1"}));
      }
      if(enabled){
        const root=document.querySelector('[data-qc-root]') as HTMLElement;
        if(!root)throw Error('missing QC root');
        const groups=new Map<HTMLElement,Text[]>();
        const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
        while(walker.nextNode()){
          const n=walker.currentNode as Text;if(!n.textContent?.trim())continue;
          const parent=n.parentElement!;
          const el=(parent.closest('[data-qc-field]')??parent) as HTMLElement;
          groups.set(el,[...(groups.get(el)??[]),n]);
        }
        const rect=(r:DOMRect)=>({x:r.x,y:r.y,width:r.width,height:r.height});
        const opacityOf=(el:HTMLElement)=>{let opacity=1;for(let a:HTMLElement|null=el;a&&a!==root.parentElement;a=a.parentElement){const cs=getComputedStyle(a);opacity*=Number(cs.opacity);if(cs.visibility==='hidden'||cs.display==='none')return 0;}return opacity;};
        const canvas=document.createElement('canvas');const ctx=canvas.getContext('2d');if(!ctx)throw Error('missing ink canvas');
        const entries=[...groups];
        const fields=entries.map(([el,nodes],i)=>{
          const rects:{x:number;y:number;width:number;height:number}[]=[];
          const inkRects:typeof rects=[];const clipBoxes:typeof rects=[];
          nodes.forEach(n=>{
            const parent=n.parentElement!;const cs=getComputedStyle(parent);ctx.font=`${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
            // Measure grapheme ink rather than UTF-16 units, preserving Thai combining marks.
            const Segmenter=(Intl as unknown as {Segmenter:new(locale:string,options:{granularity:string})=>{segment(text:string):Iterable<{index:number;segment:string}>}}).Segmenter;
            if(!Segmenter)throw Error('missing grapheme segmenter');
            const segments=Array.from(new Segmenter('th',{granularity:'grapheme'}).segment(n.textContent??''));
            for(const segment of segments){
              const range=document.createRange();range.setStart(n,segment.index);range.setEnd(n,segment.index+segment.segment.length);
              for(const r of Array.from(range.getClientRects())){
                if(r.width<=0||r.height<=0||!segment.segment.trim())continue;rects.push(rect(r));
                const metrics=ctx.measureText(segment.segment);const fontPx=parseFloat(cs.fontSize);
                const fa=metrics.fontBoundingBoxAscent,fd=metrics.fontBoundingBoxDescent;
                if(![fa,fd,metrics.actualBoundingBoxAscent,metrics.actualBoundingBoxDescent].every(Number.isFinite))throw Error('missing font ink metrics');
                const sy=r.height/(fa+fd);const baseline=r.y+fa*sy;
                const sx=metrics.width>0?r.width/metrics.width:1;
                inkRects.push({x:r.x-metrics.actualBoundingBoxLeft*sx,y:baseline-metrics.actualBoundingBoxAscent*sy,width:Math.max(.01,(metrics.actualBoundingBoxLeft+metrics.actualBoundingBoxRight)*sx),height:Math.max(.01,(metrics.actualBoundingBoxAscent+metrics.actualBoundingBoxDescent)*sy)});
              }
            }
          });
          for(let a:HTMLElement|null=el;a&&a!==root.parentElement;a=a.parentElement){const cs=getComputedStyle(a);if(['hidden','clip','scroll','auto'].some(v=>cs.overflowX===v||cs.overflowY===v))clipBoxes.push(rect(a.getBoundingClientRect()));}
          const cs=getComputedStyle(el);let scale=1;
          const backing=el.closest<HTMLElement>('[data-qc-backing]');const bg=backing?getComputedStyle(backing).backgroundColor:'';const rgba=bg.match(/[\d.]+/g)?.map(Number)??[];const alpha=rgba.length===4?rgba[3]:rgba.length===3?1:0;const backingBox=backing?rect(backing.getBoundingClientRect()):null;const backingOpacity=backing?opacityOf(backing):0;const backed=!!backing&&alpha>=.9&&backingOpacity>0&&backing.contains(el)&&!!backingBox&&inkRects.length>0&&inkRects.every(r=>r.x>=backingBox.x-.5&&r.y>=backingBox.y-.5&&r.x+r.width<=backingBox.x+backingBox.width+.5&&r.y+r.height<=backingBox.y+backingBox.height+.5);
          for(let a:HTMLElement|null=el;a&&a!==root.parentElement;a=a.parentElement){const tr=getComputedStyle(a).transform;if(tr!=='none'){const m=new DOMMatrixReadOnly(tr);scale*=Math.hypot(m.a,m.b);}}
          const lineYs=[...new Set(rects.map(r=>Math.round(r.y)))];
          const firstTextY=Math.min(...rects.map(r=>r.y));
          const blankFirstLine=el.dataset.qcField==='caption'&&firstTextY-el.getBoundingClientRect().y>parseFloat(cs.lineHeight)*.8;
          return {captionBlankFirstLine:blankFirstLine,captionLineCount:lineYs.length,captionExpectedText:el.dataset.qcCaptionDisplay,id:el.dataset.qcField??'auto-'+i,role:el.dataset.qcRole??'read',layer:'current',text:el.textContent?.trim(),fontSize:parseFloat(cs.fontSize)*scale,opacity:opacityOf(el),rects,inkRects,box:rect(el.getBoundingClientRect()),clipBoxes,clipped:false,backed,backing:backingBox?{alpha,opacity:backingOpacity,sameVisibilityAncestry:backing!.contains(el),box:backingBox}:null};
        });
        const tagged=Array.from(root.querySelectorAll<HTMLElement>('[data-qc-occluder]'));
        const saved=tagged.map(el=>[el,el.style.pointerEvents] as const);
        // Geometry identifies every potential cover. Temporarily enabling pointer hit testing
        // reveals browser paint order even for pointer-events:none image/container layers.
        tagged.forEach(el=>el.style.pointerEvents='auto');
        const occluders=tagged.map(el=>{
          const box=rect(el.getBoundingClientRect());const frontOf:string[]=[];
          fields.forEach((f,i)=>{
            const target=entries[i][0];if(el.contains(target)||target.contains(el)||opacityOf(el)<.05)return;
            for(const ink of f.inkRects){
              const x1=Math.max(box.x,ink.x),y1=Math.max(box.y,ink.y),x2=Math.min(box.x+box.width,ink.x+ink.width),y2=Math.min(box.y+box.height,ink.y+ink.height);
              if(x2<=x1||y2<=y1)continue;
              const stack=document.elementsFromPoint((x1+x2)/2,(y1+y2)/2);
              const coverIndex=stack.findIndex(x=>x===el||el.contains(x));const textIndex=stack.findIndex(x=>x===target||target.contains(x));
              if(coverIndex>=0&&textIndex>=0&&coverIndex<textIndex){frontOf.push(f.id);break;}
            }
          });
          return {id:el.dataset.qcOccluder,kind:el.tagName.toLowerCase(),box,opacity:opacityOf(el),frontOf,pointerEvents:getComputedStyle(el).pointerEvents};
        });
        saved.forEach(([el,value])=>el.style.pointerEvents=value);
        const avatar=root.querySelector<HTMLElement>('[data-qc-occluder="avatar"]');
        if(!avatar&&frame/fps<VO_END_SEC)throw Error('missing avatar measurement');
        type MeasuredRect={x:number;y:number;width:number;height:number};
        const intersectRect=(a:MeasuredRect,b:MeasuredRect):MeasuredRect|null=>{const x=Math.max(a.x,b.x),y=Math.max(a.y,b.y),right=Math.min(a.x+a.width,b.x+b.width),bottom=Math.min(a.y+a.height,b.y+b.height);return right>x&&bottom>y?{x,y,width:right-x,height:bottom-y}:null;};
        const subtractRects=(box:MeasuredRect,protect:MeasuredRect[])=>{let regions=[box];for(const p of protect){const next:MeasuredRect[]=[];for(const r of regions){const overlap=intersectRect(r,p);if(!overlap){next.push(r);continue;}const right=overlap.x+overlap.width,bottom=overlap.y+overlap.height;for(const q of [{x:r.x,y:r.y,width:r.width,height:overlap.y-r.y},{x:r.x,y:bottom,width:r.width,height:r.y+r.height-bottom},{x:r.x,y:overlap.y,width:overlap.x-r.x,height:overlap.height},{x:right,y:overlap.y,width:r.x+r.width-right,height:overlap.height}])if(q.width>0&&q.height>0)next.push(q);}regions=next;}return regions;};
        const stablePath=(el:HTMLElement)=>{const parts:string[]=[];for(let a:HTMLElement|null=el;a&&a!==root;a=a.parentElement){const parent=a.parentElement;if(!parent)throw Error('detached candidate');parts.unshift(a.tagName.toLowerCase()+':'+(Array.from(parent.children).indexOf(a)+1));}return parts.join('/');};
        const all=Array.from(root.querySelectorAll<HTMLElement>('*'));
        const hitSaved=all.map(el=>[el,el.style.pointerEvents] as const);
        let avatarBacking:unknown={applicable:false,reason:'endcard',avatar:null,candidates:[]};
        if(avatar){
        try{
          all.forEach(el=>el.style.pointerEvents='auto');
          const avatarBox=rect(avatar.getBoundingClientRect()),avatarOpacity=opacityOf(avatar);
          const candidates=all.flatMap(el=>{
            if(el===avatar||avatar.contains(el)||el.contains(avatar))return [];
            const cs=getComputedStyle(el),rgba=cs.backgroundColor.match(/[\d.]+/g)?.map(Number)??[];
            const alpha=rgba.length===4?rgba[3]:rgba.length===3?1:0,opacity=opacityOf(el),image=cs.backgroundImage;
            if(!(alpha>.05||image!=='none')||opacity<.05||avatarOpacity<.05)return [];
            const box=rect(el.getBoundingClientRect());
            if(![box.x,box.y,box.width,box.height,opacity,alpha].every(Number.isFinite))throw Error('invalid background geometry');
            let intersection=intersectRect(box,avatarBox);
            for(let a=el.parentElement;a&&a!==root&&intersection;a=a.parentElement){const style=getComputedStyle(a);if(['hidden','clip','scroll','auto'].some(v=>style.overflowX===v||style.overflowY===v))intersection=intersectRect(intersection,rect(a.getBoundingClientRect()));}
            if(!intersection)return [];
            const padding={top:parseFloat(cs.paddingTop),right:parseFloat(cs.paddingRight),bottom:parseFloat(cs.paddingBottom),left:parseFloat(cs.paddingLeft)};
            if(!Object.values(padding).every(Number.isFinite))throw Error('missing background padding');
            const protectedRects=fields.flatMap((f,i)=>{
              if(!el.contains(entries[i][0])||f.opacity<.05)return [];
              if(!f.inkRects.length)throw Error('missing protected glyph ink');
              const x=Math.min(...f.inkRects.map(r=>r.x))-padding.left-4,y=Math.min(...f.inkRects.map(r=>r.y))-padding.top-4;
              const right=Math.max(...f.inkRects.map(r=>r.x+r.width))+padding.right+4,bottom=Math.max(...f.inkRects.map(r=>r.y+r.height))+padding.bottom+4;
              return [{x,y,width:right-x,height:bottom-y}];
            });
            const emptyRegions=subtractRects(intersection,protectedRects).map(region=>{
              const points=[[.5,.5],[.1,.1],[.9,.1],[.1,.9],[.9,.9]].map(([fx,fy])=>{
                const x=region.x+region.width*fx,y=region.y+region.height*fy,stack=document.elementsFromPoint(x,y);
                const candidateIndex=stack.indexOf(el),avatarIndex=stack.findIndex(x=>x===avatar||avatar.contains(x));
                return {x,y,candidateIndex,avatarIndex,above:candidateIndex>=0&&avatarIndex>=0&&candidateIndex<avatarIndex};
              });
              return {...region,paintOrderEvidence:{...(points.find(p=>p.above)??points[0]),samples:points}};
            });
            return [{id:stablePath(el),box,opacity,background:{color:cs.backgroundColor,alpha,image},padding,protectedRects,intersection,emptyRegions}];
          });
          avatarBacking={avatar:{box:avatarBox,opacity:avatarOpacity},candidates};
        }finally{hitSaved.forEach(([el,value])=>el.style.pointerEvents=value);}
        }
        const footageEl=root.querySelector<HTMLElement>('[data-qc-footage]');
        const actualSrc=footageEl?.dataset.qcFootage;
        console.log('__QC__'+JSON.stringify({schemaVersion:2,captionLane:beat.captionLane??'bottom',frame,width:1920,height:1080,fontsOk:document.fonts.check('800 28px KanitX')&&document.fonts.check('700 28px KanitX'),fields,occluders,avatarBacking,transition:frame/25-beat.t<MODE_BLEND_SEC,footage:{origin:frame/25>=VO_END_SEC?'endcard':beat.mode==='full'?'avatar':beat.media==='typo'?'typo':actualSrc?.startsWith('yt_')?'source':actualSrc?.startsWith('ai_')?'ai':'stock',layout:beat.layout,src:actualSrc,credit:false,chrome:false}}));
      }
      continueRender(handle);
    }).catch(cancelRender);
    return ()=>{live=false;continueRender(handle);};
  },[enabled,plan,frame,beat]);
  return null;
};

// ===========================================================================
// MAIN COMPOSITION
// ===========================================================================

export type Gemini4CarbonNewsV3Props = {
  durationSec?: number;
  qcPlan?: boolean;
  qcMeasure?: boolean;
};

export const calculateGemini4CarbonNewsV3Metadata: CalculateMetadataFunction<Gemini4CarbonNewsV3Props> = async () => ({
  durationInFrames: Math.ceil(TOTAL_DURATION_SEC * 25),
  fps: 25,
  width: W,
  height: H,
});

export const Gemini4CarbonNewsV3: React.FC<Gemini4CarbonNewsV3Props> = ({qcPlan=false,qcMeasure=false}) => {
  useThaiFonts();
  const frame=useCurrentFrame();const {fps}=useVideoConfig();const t=frame/fps;
  let index=0;BEATS.forEach((b,i)=>{if(t>=b.t)index=i;});const beat=BEATS[index];
  const punches=beat.punch?.filter(p=>t>=p.t)??[];const punch=punches[punches.length-1];const z=punch?.z??1;
  const beatStartFrame=Math.ceil(beat.t*fps); // Cutaway starts at first selected frame; avatar stays global.
  const isEnd=t>=VO_END_SEC;const source=beat.origin==="source";const full=beat.layout==="full";
  const showLower=beat.lower&&t>=(beat.lower.t??beat.t)&&t<(beat.lower.t??beat.t)+(beat.lower.dur??6);
  const activeStats=beat.stats?.filter(st=>t>=st.t)??[];
  const previous=BEATS[Math.max(0,index-1)];
  const blend=easeInOutCos((t-beat.t)/MODE_BLEND_SEC);
  const avatarRect=(b:Beat)=>b.mode==="full"?{x:116,y:128,w:1688,h:744,opacity:1}:b.layout==="full"?{x:1340,y:128,w:464,h:690,opacity:0}:{x:1340,y:128,w:464,h:690,opacity:1};
  const from=avatarRect(previous),to=avatarRect(beat);
  const card={x:interpolate(blend,[0,1],[from.x,to.x]),y:128,w:interpolate(blend,[0,1],[from.w,to.w]),h:interpolate(blend,[0,1],[from.h,to.h]),opacity:interpolate(blend,[0,1],[from.opacity,to.opacity])};
  const cardScale=card.h/H;const avatarWidth=W*cardScale;
  const avatarPunch=beat.mode==="full"?z:1;
  const cardList=beat.cards?.filter(c=>t>=c.t)??[];const typoCard=cardList[cardList.length-1];
  // Primary typography must wait until the full avatar has cleared its lane.
  const typoEntranceStart=Math.max(typoCard?.t??beat.t,beat.t+(previous.mode==="full"?MODE_BLEND_SEC:0));
  const delayPanelEntrance=(previous.mode==="full"&&beat.mode!=="full")||from.opacity>to.opacity;
  const panelEntranceStart=beat.t+(delayPanelEntrance?MODE_BLEND_SEC:0);
  const stageMotion={opacity:clamp01((t-beat.t)/.35),transform:`translateX(${(1-blend)*8}px)`};
  return <div data-qc-root style={{width:W,height:H,position:"relative",overflow:"hidden",background:NAVY}}>
    <QcProbe enabled={qcMeasure} plan={qcPlan} frame={frame} beat={beat}/>
    {!isEnd&&<>
      <div data-qc-backing="solid" data-qc-occluder="topbar-backing" style={{background:full?"rgba(11,14,23,.9)":undefined,borderRadius:8,position:"absolute",zIndex:30,left:116,right:116,top:58,display:"flex",justifyContent:"space-between",alignItems:"center",height:48}}>
        <TextField id="brand" role="label" style={{color:AMBER}}>{EPISODE.brand} · {EPISODE.dateLabel}</TextField>
        <TextField id="kicker" role="label">{beat.kicker??"AI NEWS"}</TextField>
      </div>
      {beat.mode!=="full"&&<>
        <div style={{position:"absolute",left:full?0:116,top:full?0:128,width:full?1920:1190,height:full?1080:520,overflow:"hidden",borderRadius:full?0:18,background:NAVY_2,...(full?{opacity:stageMotion.opacity}:stageMotion)}}>

          {beat.media!=="typo"&&beat.src&&<div data-qc-footage={beat.src} style={{position:"absolute",inset:0,top:!full&&source&&beat.chrome?52:0,overflow:"hidden"}}><div style={{position:"absolute",inset:0,transform:`scale(${z})`,transformOrigin:`${(punch?.fx??.5)*100}% ${(punch?.fy??.5)*100}%`}}><Sequence from={beatStartFrame} layout="none"><Loop durationInFrames={Math.max(1,Math.floor(((BROLL_DUR[beat.src]??10)-(beat.from??0))*fps)-2)} layout="none"><OffthreadVideo data-qc-footage={beat.src} muted src={staticFile(`${EPISODE.assetDir}/broll/${beat.src}.mp4`)} startFrom={Math.round((beat.from??0)*fps)} style={{width:"100%",height:"100%",objectFit:source&&!full?"contain":"cover"}}/></Loop></Sequence></div></div>}
          {beat.media==="typo"&&<div style={{position:"absolute",inset:0,display:"flex",flexDirection:"column",justifyContent:"center",gap:24,padding:"45px 85px",...boundedEntrance(t,typoEntranceStart,fps)}}>
            {(typoCard?.lines??[]).map((line,i)=><TextField id={`typo-${i}`} key={i} style={{fontSize:30,color:i%2?MINT:AMBER}}>{line}</TextField>)}
          </div>}
        </div>

          {source&&beat.chrome&&<div data-qc-chrome data-qc-backing="solid" data-qc-occluder="chrome" style={{position:"absolute",left:116,width:"max-content",maxWidth:full?1688:1190,top:full?112:128,height:52,background:NAVY_2,zIndex:32,padding:"6px 24px",...stageMotion,boxSizing:"border-box"}}><TextField id="source-url" role="label">{EPISODE.page.domain}{EPISODE.page.path}</TextField></div>}
        {beat.origin==="ai"&&<div data-qc-backing="solid" data-qc-occluder="ai-label-backing" style={{background:"rgba(11,14,23,.92)",padding:"0 12px",borderRadius:8,position:"absolute",left:116,zIndex:35,top:full?186:658}}><TextField id="ai-label" role="label" style={{color:AMBER}}>ภาพประกอบ AI</TextField></div>}
        {source&&<div data-qc-credit data-qc-backing="solid" data-qc-occluder="credit-backing" style={{background:full?"rgba(11,14,23,.9)":undefined,padding:full?"0 12px":undefined,borderRadius:8,position:"absolute",left:116,zIndex:35,top:full?186:658}}><TextField id="source-credit" role="label" style={{color:AMBER}}>{EPISODE.officialTag}</TextField></div>}
        <div data-qc-backing="solid" style={{position:"absolute",zIndex:30,left:116,top:full?704:712,width:full?1688:1190,display:"flex",flexDirection:"column",gap:6,background:full?"rgba(11,14,23,.95)":"linear-gradient(0deg,rgba(11,14,23,.95),rgba(11,14,23,.6),transparent)",padding:full?"0 12px 8px":"0 0 8px",boxSizing:"border-box",...(delayPanelEntrance?boundedEntrance(t,panelEntranceStart,fps):{})}}>
          <TextField id="headline" style={{fontSize:36,lineHeight:1.45}}>{beat.headline}</TextField>
          {!full&&<TextField id="description" style={{fontSize:28,lineHeight:1.5,color:CREAM_DIM}}>{beat.sub}</TextField>}
        </div>
        {<div style={{position:"absolute",zIndex:30,left:116,top:850,width:1688,display:"flex",gap:24}}>{activeStats.map((st,i)=><div data-qc-backing="solid" data-qc-occluder={`chip-${i}`} key={i} style={{background:full?"rgba(11,14,23,.92)":undefined,borderRadius:12,...boundedEntrance(t,Math.max(st.t,panelEntranceStart),fps)}}><TextField id={`stat-${i}`} role="label" key={i} style={{fontSize:24,padding:"8px 18px",border:`1px solid ${tone(st.tone)}`,borderRadius:12,color:tone(st.tone)}}>{st.big} · {st.label}</TextField></div>)}</div>}
      </>}
      <div data-qc-occluder="avatar" style={{position:"absolute",left:card.x,top:card.y,width:card.w,height:card.h,opacity:card.opacity,overflow:"hidden",borderRadius:22,zIndex:20}}>
        <OffthreadVideo muted src={staticFile(`${EPISODE.assetDir}/avatar_source.mp4`)} style={{position:"absolute",height:card.h,width:avatarWidth,left:(card.w-avatarWidth)/2,objectFit:"cover",transform:`scale(${avatarPunch})`,transformOrigin:`${(punch?.fx??.5)*100}% ${(punch?.fy??.5)*100}%`}}/>
      </div>
      {showLower&&beat.lower&&<div data-qc-occluder="lower-third" style={{position:"absolute",zIndex:40,left:140,top:670,background:"rgba(11,14,23,.94)",padding:"14px 24px",borderLeft:`5px solid ${AMBER}`,borderRadius:14,...boundedEntrance(t,beat.lower.t??beat.t,fps)}}>
        <TextField id="lower-label" role="label" style={{color:AMBER}}>{EPISODE.breakingLabel}</TextField>
        <TextField id="lower-title" style={{fontSize:36}}>{beat.lower.title}</TextField>
        <TextField id="lower-sub" style={{fontSize:28}}>{beat.lower.sub}</TextField>
      </div>}
      {t>=CTA_T&&<div style={{position:"absolute",zIndex:40,top:812,left:116,right:116,textAlign:"center",...boundedEntrance(t,CTA_T,fps)}}><TextField id="cta" style={{color:AMBER}}>{EPISODE.cta}</TextField></div>}
      <CaptionLane t={t} lane={beat.captionLane??"bottom"}/>
    </>}
    {isEnd&&<EndCard/>}
  </div>;
};
