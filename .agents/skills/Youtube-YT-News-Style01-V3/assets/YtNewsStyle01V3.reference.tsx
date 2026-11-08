import React, { useEffect, useLayoutEffect, useState } from "react";
import {
  OffthreadVideo,
  Loop,
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
import { CAPTION_PAGES } from "./ytNewsStyle01V3Captions";
type WebRect = {x:number;y:number;w:number;h:number};

// ===========================================================================
// YtNewsStyle01V3 — 16:9 AI-news report (1920x1080@25)
// Format "Youtube-YT-News-Style01-V3":
// Report subject: YOUTUBE VIDEO ("GPT-Image-2.6: Faster image generation with Flare and Sunburst")
// Left stage: YouTube cuts in museum cards / full-bleed + fresh stock b-roll + typography scenes
// Right stage: Continuous avatar morphing between full-frame and 9:16 vertical card
// Timing spine: Whisper word-level timestamps + SRT calibrated
// Regression media is reused; production freshness is NOT asserted.
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
  assetDir: "REPLACE_MEDIA_DIR", // public/<assetDir>/{avatar_source.mp4, broll/, web/}
  brand: "AI TECH NEWS",
  dateLabel: "7 พ.ย. 2026",
  page: { domain: "youtube.com", path: "/watch?v=9ZxCOHkfn_8" },
  officialTag: "SOURCE · OPENAI",
  breakingLabel: "BREAKING NEWS",
  cta: "คุณจะนำ AI ไปใช้งานอะไร?",
  endcard: {
    eyebrow: "AI TECH NEWS · NOVEMBER 2026",
    titleA: "GPT-Image-2.6",
    titleB: "Faster with Flare & Sunburst",
    cta: "คุณจะนำ AI ไปใช้งานอะไร?",
  },
};

// ---- Stage geometry (locked) ----------------------------------------------
const W = 1920;
const H = 1080;
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
  captionLane?: "top" | "bottom";
  cards?: {t:number;lines:string[]}[];
  origin?: "source" | "stock";
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
    "lower": {
      "title": "GPT-IMAGE-2.6 IS HERE",
      "sub": "FASTER IMAGE GENERATION WITH FLARE & SUNBURST",
      "t": 1.0,
      "dur": 5.5
    }
  },
  {
    "t": 6.84,
    "mode": "pip",
    "media": "broll",
    "src": "ecommerce_package_order",
    "kicker": "IMAGE PROBLEM",
    "headline": "อยากได้รูปภาพไปใช้งาน",
    "sub": "ขายของออนไลน์ ทำโปสเตอร์ หรืองานนำเสนอ",
    "stats": [
      {
        "t": 8.4,
        "big": "COMMERCE",
        "label": "ใช้ลงขายของ",
        "tone": "amber"
      },
      {
        "t": 9.5,
        "big": "POSTER",
        "label": "ทำโปสเตอร์งาน",
        "tone": "mint"
      }
    ],
    "origin": "stock",
    "layout": "stage",
    "chrome": false
  },
  {
    "t": 14.34,
    "mode": "pip",
    "media": "broll",
    "src": "artist_pencil_sketch",
    "kicker": "TRADITIONAL DRAWING",
    "headline": "ถ้าจ้างคนวาดก็รอนาน",
    "sub": "ต้องใช้เวลาหลายวันหรือสัปดาห์กว่าจะได้รูป",
    "stats": [
      {
        "t": 15.1,
        "big": "HIRE ARTIST",
        "label": "จ้างคนวาด",
        "tone": "clay"
      },
      {
        "t": 16.1,
        "big": "WAIT TIME",
        "label": "ต้องใช้เวลารอ",
        "tone": "amber"
      }
    ],
    "origin": "stock",
    "layout": "stage",
    "chrome": false
  },
  {
    "t": 17.98,
    "mode": "pip",
    "media": "broll",
    "src": "digital_art_creative",
    "kicker": "AI IMAGE ERA",
    "headline": "AI วาดรูปเข้ามามีบทบาท",
    "sub": "แค่พิมพ์ข้อความสั่ง ตัวระบบก็สร้างภาพออกมาให้",
    "stats": [
      {
        "t": 19.2,
        "big": "AI ART",
        "label": "ปัญญาประดิษฐ์วาดรูป",
        "tone": "amber"
      },
      {
        "t": 24.3,
        "big": "PROMPT",
        "label": "พิมพ์ข้อความสั่งงาน",
        "tone": "mint"
      }
    ],
    "origin": "stock",
    "layout": "stage",
    "chrome": false
  },
  {
    "t": 25.98,
    "mode": "full"
  },
  {
    "t": 28.76,
    "mode": "pip",
    "media": "broll",
    "src": "hourglass_sand_time",
    "kicker": "THE WAITING PROBLEM",
    "headline": "ปัญหาที่เจอบ่อยคือ การรอคอย",
    "sub": "บางครั้งต้องนั่งจ้องหน้าจอรอนาทีสองนาทีกว่าภาพจะขึ้น",
    "stats": [
      {
        "t": 30.9,
        "big": "WAITING",
        "label": "ปัญหาการรอคอย",
        "tone": "clay"
      },
      {
        "t": 35.8,
        "big": "1-2 MIN",
        "label": "รอนาทีสองนาทีต่อภาพ",
        "tone": "amber"
      }
    ],
    "origin": "stock",
    "layout": "stage",
    "chrome": false
  },
  {
    "t": 36.76,
    "mode": "full"
  },
  {
    "t": 44.18,
    "mode": "full",
    "punch": [{"t":44.76,"z":1.2,"fx":0.5,"fy":0.5}]
  },
  {
    "t": 47.82,
    "mode": "pip",
    "media": "clip",
    "src": "yt_intro_banner",
    "clipFit": "contain",
    "kicker": "NEW ANNOUNCEMENT",
    "headline": "เปิดตัว GPT-Image-2.6",
    "sub": "ระบบสร้างภาพรุ่นใหม่ล่าสุดจาก OpenAI",
    "stats": [
      {
        "t": 49.5,
        "big": "GPT-IMAGE 2.6",
        "label": "โมเดลรุ่นใหม่ล่าสุด",
        "tone": "amber"
      }
    ],
    "captionLane": "top",
    "origin": "source",
    "layout": "full",
    "chrome": true
  },
  {
    "t": 52.14,
    "mode": "pip",
    "media": "clip",
    "src": "yt_prompt_koi",
    "clipFit": "contain",
    "kicker": "API & CODEX RELEASE",
    "headline": "นำมาใส่ใน API และ Codex",
    "sub": "ความเร็วสร้างภาพเพิ่มขึ้นจากเดิมถึง 50%",
    "stats": [
      {
        "t": 56.2,
        "big": "API + CODEX",
        "label": "เชื่อมต่อในระบบ",
        "tone": "mint"
      },
      {
        "t": 63.9,
        "big": "+50% FASTER",
        "label": "ความเร็วเพิ่มขึ้น",
        "tone": "amber"
      }
    ],
    "captionLane": "top",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "punch": [
      {
        "t": 60.14,
        "z": 1.2,
        "fx": 0.65,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 65.2,
    "mode": "full",
    "punch": [
      {
        "t": 73.2,
        "z": 1.2,
        "fx": 0.65,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 74.68,
    "mode": "pip",
    "media": "clip",
    "src": "yt_complexity_levels",
    "clipFit": "contain",
    "kicker": "TWO NEW ENGINES",
    "headline": "2 เครื่องมือใหม่: Flare & Sunburst",
    "sub": "ออกแบบมาเพื่อทำหน้าที่คนละบทบาทอย่างชัดเจน",
    "stats": [
      {
        "t": 79.2,
        "big": "FLARE",
        "label": "ตัวแรกชื่อ Flare",
        "tone": "amber"
      },
      {
        "t": 81.0,
        "big": "SUNBURST",
        "label": "อีกตัวชื่อ Sunburst",
        "tone": "mint"
      }
    ],
    "captionLane": "top",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "punch": [
      {
        "t": 82.68,
        "z": 1.2,
        "fx": 0.65,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 88.62,
    "mode": "pip",
    "media": "broll",
    "src": "architect_concept_draft",
    "kicker": "FLARE · CONCEPT SKETCH",
    "headline": "Flare: ช่างสเก็ตช์ภาพร่าง",
    "sub": "ขึ้นโครงสร้างคร่าวๆ เพื่อดูแสง องค์ประกอบ และตำแหน่ง",
    "stats": [
      {
        "t": 90.2,
        "big": "SKETCH",
        "label": "ช่างสเก็ตช์ภาพ",
        "tone": "amber"
      }
    ],
    "origin": "stock",
    "layout": "stage",
    "chrome": false
  },
  {
    "t": 96.62,
    "mode": "full"
  },
  {
    "t": 104.68,
    "mode": "pip",
    "media": "broll",
    "src": "fine_oil_painter",
    "kicker": "SUNBURST · FINE DETAILS",
    "headline": "Sunburst: ช่างลงสีรายละเอียดสูง",
    "sub": "รับหน้าที่เก็บพื้นผิว แสงเงา และความคมชัดของภาพ",
    "stats": [
      {
        "t": 107.1,
        "big": "COLORIST",
        "label": "ช่างลงสีละเอียด",
        "tone": "mint"
      },
      {
        "t": 111.0,
        "big": "TEXTURE",
        "label": "เก็บแสงเงาพื้นผิว",
        "tone": "amber"
      }
    ],
    "origin": "stock",
    "layout": "stage",
    "chrome": false
  },
  {
    "t": 114.66,
    "mode": "pip",
    "media": "typo",
    "typo": "vs",
    "src": "creative_vision_light",
    "kicker": "WORKFLOW COMPARISON",
    "headline": "Flare vs Sunburst: ผสานพลัง 2 ขั้นตอน",
    "sub": "วาดโครงร่างรอบแรกด้วย Flare แล้วส่งต่อให้ Sunburst จัดการความสวยงาม",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "cards": [
      {
        "t": 114.66,
        "lines": [
          "FLARE · ช่างสเก็ตช์ร่าง",
          "ขึ้นโครงสร้าง แสง และองค์ประกอบ"
        ]
      },
      {
        "t": 122.0,
        "lines": [
          "SUNBURST · เก็บรายละเอียด",
          "พื้นผิว แสงเงา และความคมชัด"
        ]
      },
      {
        "t": 129.0,
        "lines": [
          "FLARE → SUNBURST",
          "ร่างโครงสร้าง แล้วเก็บรายละเอียด"
        ]
      }
    ]
  },
  {
    "t": 136.86,
    "mode": "full"
  },
  {
    "t": 143.62,
    "mode": "pip",
    "media": "broll",
    "src": "fast_city_traffic",
    "kicker": "SPEED MATTERS",
    "headline": "ความเร็วเพิ่ม 50% ลดเวลารอครึ่งหนึ่ง",
    "sub": "จากเดิม 10 วินาทีต่อภาพ ลดลงเหลือเพียง 5 วินาที",
    "stats": [
      {
        "t": 146.0,
        "big": "10 SEC",
        "label": "ระบบเดิม 10 วินาที",
        "tone": "clay"
      },
      {
        "t": 152.2,
        "big": "5 SEC",
        "label": "ระบบใหม่เหลือ 5 วิ",
        "tone": "mint"
      }
    ],
    "origin": "stock",
    "layout": "stage",
    "chrome": false
  },
  {
    "t": 153.02,
    "mode": "pip",
    "media": "clip",
    "src": "yt_markup_refine",
    "clipFit": "contain",
    "kicker": "6-SECOND GENERATION",
    "headline": "Flare คุณภาพเริ่มต้น เสร็จใน 6 วินาที",
    "sub": "ทดลองสร้างและแก้ไขภาพได้ในเสี้ยวเวลา",
    "stats": [
      {
        "t": 158.0,
        "big": "FLARE FAST",
        "label": "ระดับคุณภาพเริ่มต้น",
        "tone": "amber"
      },
      {
        "t": 164.3,
        "big": "6 SECONDS",
        "label": "เสร็จในเวลา 6 วินาที",
        "tone": "mint"
      }
    ],
    "captionLane": "top",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "punch": [
      {
        "t": 161.02,
        "z": 1.2,
        "fx": 0.65,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 166.26,
    "mode": "pip",
    "media": "broll",
    "src": "drinking_water_glass",
    "kicker": "BLINK OF AN EYE",
    "headline": "เร็วเท่าเวลาก้มหยิบแก้วน้ำ",
    "sub": "เวลาระดับ 6 วินาที แทบจะเท่ากับเวลาที่เรากะพริบตา",
    "stats": [
      {
        "t": 167.1,
        "big": "6 SEC",
        "label": "สปีดระดับกะพริบตา",
        "tone": "amber"
      },
      {
        "t": 171.1,
        "big": "NO DELAY",
        "label": "ก้มหยิบแก้วน้ำก็ได้ภาพ",
        "tone": "mint"
      }
    ],
    "origin": "stock",
    "layout": "stage",
    "chrome": false
  },
  {
    "t": 171.8,
    "mode": "pip",
    "media": "broll",
    "src": "graphic_designer_ui",
    "kicker": "CREATIVE TESTING",
    "headline": "ประโยชน์สูงสุดช่วงทดลองไอเดีย",
    "sub": "ลองเปลี่ยนสีพื้นหลังหรือมุมกล้องของสินค้าได้ทันที",
    "stats": [
      {
        "t": 176.5,
        "big": "EXPERIMENT",
        "label": "ทดลองไอเดียใหม่ๆ",
        "tone": "amber"
      }
    ],
    "origin": "stock",
    "layout": "stage",
    "chrome": false
  },
  {
    "t": 179.8,
    "mode": "full",
    "punch": [
      {
        "t": 187.8,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 192.46,
    "mode": "pip",
    "media": "clip",
    "src": "yt_svg_origami",
    "clipFit": "contain",
    "kicker": "RAPID ITERATION",
    "headline": "ได้ภาพตัวอย่างหลายแบบใน 1 นาที",
    "sub": "ระยะเวลาเหลือหลักวินาที ความคิดสร้างสรรค์ไม่สะดุด",
    "stats": [
      {
        "t": 197.1,
        "big": "NO BLOCK",
        "label": "ไอเดียไม่สะดุด",
        "tone": "mint"
      },
      {
        "t": 202.6,
        "big": "< 1 MIN",
        "label": "ได้หลายแบบใน 1 นาที",
        "tone": "amber"
      }
    ],
    "captionLane": "top",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "punch": [
      {
        "t": 200.46,
        "z": 1.2,
        "fx": 0.65,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 207.86,
    "mode": "full",
    "punch": [
      {
        "t": 215.86,
        "z": 1.2,
        "fx": 0.65,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 222.76,
    "mode": "pip",
    "media": "broll",
    "src": "photo_studio_lights",
    "kicker": "PRODUCT PHOTOGRAPHY",
    "headline": "ภาพถ่ายสินค้าและโปรดักต์ช็อต",
    "sub": "พ่อค้าแม่ค้าออนไลน์จำลองฉากหลังใหม่ได้ทันใจตามเทศกาล",
    "stats": [
      {
        "t": 228.2,
        "big": "PRODUCT SHOT",
        "label": "ภาพถ่ายสินค้า",
        "tone": "amber"
      }
    ],
    "origin": "stock",
    "layout": "stage",
    "chrome": false
  },
  {
    "t": 230.76,
    "mode": "full",
    "punch": [
      {
        "t": 238.76,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 243.52,
    "mode": "pip",
    "media": "broll",
    "src": "printing_posters_press",
    "kicker": "POSTERS & MEDIA",
    "headline": "งานโปสเตอร์ ใบปลิว และสื่อประชาสัมพันธ์",
    "sub": "ขึ้นภาพร่างแล้วเห็นตำแหน่งสำหรับจัดวางตัวหนังสือได้ทันที",
    "stats": [
      {
        "t": 247.6,
        "big": "POSTER/FLYER",
        "label": "แผ่นพับ ใบปลิว นำเสนอ",
        "tone": "amber"
      }
    ],
    "origin": "stock",
    "layout": "stage",
    "chrome": false
  },
  {
    "t": 250.96,
    "mode": "pip",
    "media": "clip",
    "src": "yt_svg_icons",
    "clipFit": "contain",
    "kicker": "VECTOR & ICONS",
    "headline": "ขึ้นภาพร่างสำหรับจัดวางตัวหนังสือ",
    "sub": "เห็นตำแหน่งว่างสำหรับใส่ข้อความและไอคอนทันที",
    "stats": [
      {
        "t": 255.5,
        "big": "TEXT LAYOUT",
        "label": "เห็นตำแหน่งวางข้อความ",
        "tone": "mint"
      },
      {
        "t": 258.0,
        "big": "SVG ICONS",
        "label": "ไอคอนคมชัดทุกขนาด",
        "tone": "amber"
      }
    ],
    "captionLane": "top",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "punch": [
      {
        "t": 258.96,
        "z": 1.2,
        "fx": 0.65,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 259.4,
    "mode": "pip",
    "media": "broll",
    "src": "team_brainstorming_board",
    "kicker": "TEAM COLLABORATION",
    "headline": "ประชุมกลุ่ม ทุกคนเห็นภาพตรงกันทันที",
    "sub": "สั่งสร้างภาพขึ้นมาดูพร้อมกันในไม่กี่วินาที ไม่ต้องอธิบายยืดยาว",
    "stats": [
      {
        "t": 263.1,
        "big": "BRAINSTORM",
        "label": "ประชุมงานเป็นกลุ่ม",
        "tone": "mint"
      }
    ],
    "origin": "stock",
    "layout": "stage",
    "chrome": false
  },
  {
    "t": 267.4,
    "mode": "full"
  },
  {
    "t": 277.1,
    "mode": "pip",
    "media": "broll",
    "src": "software_engineer_code",
    "kicker": "CODEX INTEGRATION",
    "headline": "นำระบบเข้าไปใส่ใน Codex",
    "sub": "เครื่องมือช่วยเขียนโค้ด ทำให้นักพัฒนาสร้างฟังก์ชันใหม่ๆ ได้ง่ายขึ้น",
    "stats": [
      {
        "t": 281.6,
        "big": "CODEX",
        "label": "เครื่องมือช่วยเขียนโค้ด",
        "tone": "amber"
      },
      {
        "t": 288.5,
        "big": "DEV SPEED",
        "label": "สร้างฟังก์ชันใหม่ได้ง่ายขึ้น",
        "tone": "mint"
      }
    ],
    "origin": "stock",
    "layout": "stage",
    "chrome": false
  },
  {
    "t": 285.86,
    "mode": "pip",
    "media": "clip",
    "src": "yt_api_docs",
    "clipFit": "contain",
    "kicker": "API DEVELOPERS",
    "headline": "นักพัฒนาสร้างฟังก์ชันภาพในแอปได้ทันที",
    "sub": "รองรับการเชื่อมต่อผ่าน API พารามิเตอร์ใหม่ใช้งานได้แล้ววันนี้",
    "stats": [
      {
        "t": 288.0,
        "big": "API INTEGRATION",
        "label": "เชื่อมต่อง่าย",
        "tone": "mint"
      }
    ],
    "captionLane": "top",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "punch": [
      {
        "t": 293.86,
        "z": 1.2,
        "fx": 0.65,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 294.66,
    "mode": "pip",
    "media": "clip",
    "src": "yt_sprite_sheet",
    "clipFit": "contain",
    "kicker": "FASTER APPS",
    "headline": "แอปแต่งรูปโหลดเร็วขึ้นอย่างเห็นได้ชัด",
    "sub": "หน้าจอหมุนรอประมวลผลสั้นลง รองรับ Sprite Sheet แอนิเมชัน",
    "stats": [
      {
        "t": 298.2,
        "big": "SPEED UP",
        "label": "แอปโหลดเร็วขึ้น",
        "tone": "mint"
      },
      {
        "t": 303.3,
        "big": "NO WAITING",
        "label": "หน้าจอหมุนรอสั้นลง",
        "tone": "amber"
      }
    ],
    "captionLane": "top",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "punch": [
      {
        "t": 302.66,
        "z": 1.2,
        "fx": 0.65,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 306.46,
    "mode": "pip",
    "media": "clip",
    "src": "yt_looping_gif",
    "clipFit": "contain",
    "kicker": "CONTENT CREATORS",
    "headline": "ทำคอนเทนต์ลงสื่อสังคมออนไลน์ได้ไวขึ้น",
    "sub": "เตรียมภาพประกอบบทความหรือโปรโมชันเสร็จไว มีลูกเล่น GIF",
    "stats": [
      {
        "t": 311.9,
        "big": "CONTENT",
        "label": "คนทำคอนเทนต์ประหยัดเวลา",
        "tone": "mint"
      },
      {
        "t": 316.0,
        "big": "LOOP GIF",
        "label": "แอนิเมชันลูปต่อเนื่อง",
        "tone": "amber"
      }
    ],
    "captionLane": "top",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "punch": [
      {
        "t": 314.46,
        "z": 1.2,
        "fx": 0.65,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 316.54,
    "mode": "pip",
    "media": "broll",
    "src": "boutique_customer_sale",
    "kicker": "MORE TIME FOR BUSINESS",
    "headline": "มีเวลาเหลือไปดูแลการขายและลูกค้า",
    "sub": "ไม่ต้องเสียเวลากับงานภาพ เอาเวลาไปสร้างรายได้และพูดคุยกับลูกค้า",
    "stats": [
      {
        "t": 318.0,
        "big": "BUSINESS",
        "label": "โฟกัสเรื่องการขาย",
        "tone": "amber"
      },
      {
        "t": 320.5,
        "big": "CUSTOMERS",
        "label": "ดูแลลูกค้าได้เต็มที่",
        "tone": "mint"
      }
    ],
    "origin": "stock",
    "layout": "stage",
    "chrome": false
  },
  {
    "t": 322.68,
    "mode": "pip",
    "media": "typo",
    "typo": "summary3",
    "src": "social_creator_workspace",
    "kicker": "FINAL RECAP",
    "headline": "3 จุดเปลี่ยนสำคัญของ GPT-Image-2.6",
    "sub": "ลดระยะเวลารอ เปลี่ยนความคิดในหัวเป็นภาพได้อย่างลื่นไหล",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "cards": [
      {
        "t": 322.68,
        "lines": [
          "Flare + Sunburst",
          "แยกการร่างภาพและเก็บรายละเอียด"
        ]
      },
      {
        "t": 329.5,
        "lines": [
          "การสร้างภาพในงานประจำวัน",
          "ทดลองไอเดีย และสร้างสื่อประกอบ"
        ]
      }
    ]
  },
  {
    "t": 334.14,
    "mode": "full"
  }
];

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
    <div data-qc-backing="solid" data-qc-occluder="caption-pill" data-qc-field="caption" data-qc-role="read" style={{fontFamily:FONT,fontSize:32,fontWeight:800,lineHeight:1.65,background:"rgba(11,14,23,.92)",padding:"6px 26px",borderRadius:18,maxWidth:lane==="top"?598:1500,display:"flex",flexWrap:"wrap",justifyContent:lane==="top"?"flex-start":"center",gap:6}}>
      {page.words.map((w,i)=><span key={i} style={{color:t>=w.s&&t<w.e?GOLD_LIGHT:CREAM,textShadow:t>=w.s&&t<w.e?`0 0 12px ${GOLD}`:"none"}}>{w.w}</span>)}
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
        console.log("__QC_PLAN__"+JSON.stringify({frames:[...new Set([...times].filter(t=>t>=0&&t<TOTAL_DURATION_SEC).map(t=>Math.round(t*25)))].sort((a,b)=>a-b)}));
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
          return {id:el.dataset.qcField??'auto-'+i,role:el.dataset.qcRole??'read',layer:'current',text:el.textContent?.trim(),fontSize:parseFloat(cs.fontSize)*scale,opacity:opacityOf(el),rects,inkRects,box:rect(el.getBoundingClientRect()),clipBoxes,clipped:false,backed,backing:backingBox?{alpha,opacity:backingOpacity,sameVisibilityAncestry:backing!.contains(el),box:backingBox}:null};
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
        const footageEl=root.querySelector<HTMLElement>('[data-qc-footage]');
        const actualSrc=footageEl?.dataset.qcFootage;
        console.log('__QC__'+JSON.stringify({schemaVersion:2,captionLane:beat.captionLane??'bottom',frame,width:1920,height:1080,fontsOk:document.fonts.check('800 28px KanitX')&&document.fonts.check('700 28px KanitX'),fields,occluders,transition:frame/25-beat.t<MODE_BLEND_SEC,footage:{origin:frame/25>=VO_END_SEC?'endcard':beat.mode==='full'?'avatar':beat.media==='typo'?'typo':actualSrc?.startsWith('yt_')?'source':'stock',layout:beat.layout,src:actualSrc,credit:false,chrome:false}}));
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

export type YtNewsStyle01V3Props = {
  durationSec?: number;
  qcPlan?: boolean;
  qcMeasure?: boolean;
};

export const calculateYtNewsStyle01V3Metadata: CalculateMetadataFunction<YtNewsStyle01V3Props> = async () => ({
  durationInFrames: Math.ceil(TOTAL_DURATION_SEC * 25),
  fps: 25,
  width: W,
  height: H,
});

export const YtNewsStyle01V3: React.FC<YtNewsStyle01V3Props> = ({qcPlan=false,qcMeasure=false}) => {
  useThaiFonts();
  const frame=useCurrentFrame();const {fps}=useVideoConfig();const t=frame/fps;
  let index=0;BEATS.forEach((b,i)=>{if(t>=b.t)index=i;});const beat=BEATS[index];
  const punches=beat.punch?.filter(p=>t>=p.t)??[];const punch=punches[punches.length-1];const z=punch?.z??1;
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

          {beat.media!=="typo"&&beat.src&&<div data-qc-footage={beat.src} style={{position:"absolute",inset:0,top:!full&&source&&beat.chrome?52:0,overflow:"hidden"}}><div style={{position:"absolute",inset:0,transform:`scale(${z})`,transformOrigin:`${(punch?.fx??.5)*100}% ${(punch?.fy??.5)*100}%`}}><Loop durationInFrames={Math.max(1,Math.floor(((BROLL_DUR[beat.src]??10)-(beat.from??0))*fps)-2)} layout="none"><OffthreadVideo data-qc-footage={beat.src} muted src={staticFile(`${EPISODE.assetDir}/broll/${beat.src}.mp4`)} startFrom={Math.round((beat.from??0)*fps)} style={{width:"100%",height:"100%",objectFit:source&&!full?"contain":"cover"}}/></Loop></div></div>}
          {beat.media==="typo"&&<div style={{position:"absolute",inset:0,display:"flex",flexDirection:"column",justifyContent:"center",gap:24,padding:"45px 85px",...boundedEntrance(t,typoCard?.t??beat.t,fps)}}>
            {(typoCard?.lines??[]).map((line,i)=><TextField id={`typo-${i}`} key={i} style={{fontSize:30,color:i%2?MINT:AMBER}}>{line}</TextField>)}
          </div>}
        </div>

          {source&&beat.chrome&&<div data-qc-chrome data-qc-backing="solid" data-qc-occluder="chrome" style={{position:"absolute",left:116,right:full?116:614,top:full?112:128,height:52,background:NAVY_2,zIndex:32,padding:"6px 24px",...stageMotion,boxSizing:"border-box"}}><TextField id="source-url" role="label">{EPISODE.page.domain}{EPISODE.page.path}</TextField></div>}
        {source&&<div data-qc-credit data-qc-backing="solid" data-qc-occluder="credit-backing" style={{background:full?"rgba(11,14,23,.9)":undefined,padding:full?"0 12px":undefined,borderRadius:8,position:"absolute",left:116,zIndex:35,top:full?186:658}}><TextField id="source-credit" role="label" style={{color:AMBER}}>{EPISODE.officialTag}</TextField></div>}
        <div data-qc-backing="solid" style={{position:"absolute",zIndex:30,left:116,top:full?704:712,width:full?1688:1190,display:"flex",flexDirection:"column",gap:6,background:full?"rgba(11,14,23,.95)":"linear-gradient(0deg,rgba(11,14,23,.95),rgba(11,14,23,.6),transparent)",padding:full?"0 12px 8px":"0 0 8px",boxSizing:"border-box"}}>
          <TextField id="headline" style={{fontSize:36,lineHeight:1.45}}>{beat.headline}</TextField>
          {!full&&<TextField id="description" style={{fontSize:28,lineHeight:1.5,color:CREAM_DIM}}>{beat.sub}</TextField>}
        </div>
        {<div style={{position:"absolute",zIndex:30,left:116,top:850,width:1688,display:"flex",gap:24}}>{activeStats.map((st,i)=><div data-qc-backing="solid" data-qc-occluder={`chip-${i}`} key={i} style={{background:full?"rgba(11,14,23,.92)":undefined,borderRadius:12,...boundedEntrance(t,st.t,fps)}}><TextField id={`stat-${i}`} role="label" key={i} style={{fontSize:24,padding:"8px 18px",border:`1px solid ${tone(st.tone)}`,borderRadius:12,color:tone(st.tone)}}>{st.big} · {st.label}</TextField></div>)}</div>}
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
