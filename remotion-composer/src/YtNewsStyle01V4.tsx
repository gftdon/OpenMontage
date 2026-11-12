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
import { CAPTION_PAGES } from "./ytNewsStyle01V4Captions";
type WebRect = {x:number;y:number;w:number;h:number};

// ===========================================================================
// YtNewsStyle01V4 — 16:9 AI-news report (1920x1080@25)
// Format "Youtube-YT-News-Style01-V4":
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
  assetDir: "ytNewsV3BrollTest", // public/<assetDir>/{avatar_source.mp4, broll/, web/}
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
  "ai_layout_draft_final": 9.2,
  "artist_drawing_notebook": 15.04,
  "boutique_customer_sale": 19.44,
  "coding_developer_illustration": 10.0,
  "content_editor_workflow": 26.32,
  "developer_api_integration": 12.32,
  "developer_new_function": 30.0,
  "drinking_water_glass": 30.0,
  "hourglass_waiting": 14.88,
  "painter_detail_brush": 9.0,
  "photographer_for_images": 10.04,
  "printing_posters_press": 11.44,
  "product_shot_milk": 27.48,
  "rough_layout_pencil": 17.48,
  "tablet_photo_editing": 12.4,
  "team_brainstorming_board": 14.48,
  "yt_complexity_variants": 7.68,
  "yt_intro_title": 4.52,
  "yt_markup_experiment": 6.6,
  "yt_prompt_create": 5.52,
  "yt_prompt_iteration": 5.68,
  "yt_table_texture": 3.2
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
    "lower": {
      "title": "GPT-IMAGE-2.6 IS HERE",
      "sub": "GPT-Image-2.6",
      "t": 1.0,
      "dur": 5.5
    }
  },
  {
    "t": 6.84,
    "mode": "pip",
    "media": "broll",
    "src": "photographer_for_images",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "ILLUSTRATIVE FOOTAGE",
    "headline": "หารูปภาพไปประกอบงาน",
    "sub": "เลือกรูปให้เหมาะกับงานที่ต้องการสื่อ"
  },
  {
    "t": 14.34,
    "mode": "pip",
    "media": "broll",
    "src": "artist_drawing_notebook",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "ILLUSTRATIVE FOOTAGE",
    "headline": "งานวาดภาพด้วยมือ",
    "sub": "เริ่มลงมือวาดภาพด้วยดินสอ"
  },
  {
    "t": 17.98,
    "mode": "full"
  },
  {
    "t": 23.48,
    "mode": "pip",
    "media": "clip",
    "src": "yt_prompt_create",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "SOURCE DEMO",
    "headline": "จากข้อความสู่ภาพ",
    "sub": "พิมพ์สิ่งที่อยากเห็น แล้วดูภาพที่ได้"
  },
  {
    "t": 28.76,
    "mode": "pip",
    "media": "broll",
    "src": "hourglass_waiting",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "ILLUSTRATIVE FOOTAGE",
    "headline": "ช่วงเวลาที่ต้องรอภาพ",
    "sub": "การรอภาพเป็นส่วนหนึ่งของการทำงาน"
  },
  {
    "t": 36.76,
    "mode": "full",
    "punch": [
      {
        "t": 44.76,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 47.82,
    "mode": "pip",
    "media": "clip",
    "src": "yt_intro_title",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "SOURCE DEMO",
    "headline": "GPT-Image-2.6",
    "sub": "ทำความรู้จัก Flare และ Sunburst"
  },
  {
    "t": 52.14,
    "mode": "pip",
    "media": "broll",
    "src": "developer_api_integration",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "ILLUSTRATIVE FOOTAGE",
    "headline": "API และเครื่องมือเขียนโปรแกรม",
    "sub": "เชื่อมงานภาพเข้ากับเครื่องมือพัฒนา"
  },
  {
    "t": 59.78,
    "mode": "pip",
    "media": "typo",
    "src": "speed_overview",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "IDEA TO IMAGE",
    "headline": "จากไอเดียสู่ภาพ",
    "sub": "ลองเปลี่ยนความคิดให้เป็นภาพ",
    "cards": [
      {
        "t": 59.78,
        "lines": [
          "พิมพ์สิ่งที่อยากเห็น",
          "ดูภาพ แล้วทดลองต่อ"
        ]
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
    "media": "typo",
    "src": "model_names",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "IDEA TO IMAGE",
    "headline": "Flare และ Sunburst",
    "sub": "ระบบสร้างภาพในตระกูล GPT-Image",
    "cards": [
      {
        "t": 74.68,
        "lines": [
          "GPT-Image-2.6",
          "Flare · Sunburst"
        ]
      }
    ]
  },
  {
    "t": 82.2,
    "mode": "full"
  },
  {
    "t": 88.62,
    "mode": "pip",
    "media": "broll",
    "src": "rough_layout_pencil",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "ILLUSTRATIVE FOOTAGE",
    "headline": "เริ่มจากภาพร่างและองค์ประกอบ",
    "sub": "ลองตำแหน่งและองค์ประกอบก่อนลงรายละเอียด"
  },
  {
    "t": 96.62,
    "mode": "full"
  },
  {
    "t": 104.68,
    "mode": "pip",
    "media": "broll",
    "src": "painter_detail_brush",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "ILLUSTRATIVE FOOTAGE",
    "headline": "รายละเอียดในงานภาพ",
    "sub": "ค่อยๆ เติมสีและเก็บรายละเอียดของภาพ"
  },
  {
    "t": 108.64,
    "mode": "pip",
    "media": "clip",
    "src": "yt_table_texture",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "SOURCE DEMO",
    "headline": "พื้นผิว แสง และองค์ประกอบ",
    "sub": "มองแสงเงาและพื้นผิวในภาพให้ชัดขึ้น"
  },
  {
    "t": 111.64,
    "mode": "full"
  },
  {
    "t": 114.66,
    "mode": "pip",
    "media": "typo",
    "typo": "vs",
    "src": "workflow_cards",
    "kicker": "WORKFLOW COMPARISON",
    "headline": "มองภาพรวม แล้วพิจารณารายละเอียด",
    "sub": "เริ่มจากภาพรวม แล้วค่อยปรับส่วนต่างๆ",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "cards": [
      {
        "t": 114.66,
        "lines": [
          "ภาพร่างและองค์ประกอบ",
          "เริ่มจากสิ่งที่อยากสื่อ"
        ]
      },
      {
        "t": 122,
        "lines": [
          "พื้นผิวและแสงเงา",
          "พิจารณารายละเอียดของภาพ"
        ]
      },
      {
        "t": 129,
        "lines": [
          "ทดลอง แล้วปรับไอเดีย",
          "เลือกภาพที่สื่อสารงานได้"
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
    "media": "typo",
    "src": "speed_neutral",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "IDEA TO IMAGE",
    "headline": "จากไอเดียสู่ภาพได้เร็วขึ้น",
    "sub": "ทดลองภาพ แล้วปรับไอเดียต่อ",
    "cards": [
      {
        "t": 143.62,
        "lines": [
          "ทดลองภาพจากข้อความ",
          "ปรับไอเดียแล้วดูผล"
        ]
      }
    ]
  },
  {
    "t": 153.02,
    "mode": "full"
  },
  {
    "t": 156.84,
    "mode": "pip",
    "media": "clip",
    "src": "yt_prompt_iteration",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "SOURCE DEMO",
    "headline": "ลองสร้างภาพจาก prompt",
    "sub": "พิมพ์คำอธิบายเพื่อทดลองภาพที่ต้องการ"
  },
  {
    "t": 162.34,
    "mode": "full"
  },
  {
    "t": 166.26,
    "mode": "pip",
    "media": "broll",
    "src": "drinking_water_glass",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "ILLUSTRATIVE FOOTAGE",
    "headline": "ภาพเปรียบในชีวิตประจำวัน",
    "sub": "นึกถึงจังหวะสั้นๆ ในชีวิตประจำวัน"
  },
  {
    "t": 171.8,
    "mode": "pip",
    "media": "clip",
    "src": "yt_markup_experiment",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "SOURCE DEMO",
    "headline": "ทดลองปรับภาพด้วย markup",
    "sub": "เลือกจุดที่ต้องการแก้ แล้วดูผลลัพธ์"
  },
  {
    "t": 178.2,
    "mode": "full",
    "punch": [
      {
        "t": 186.2,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      },
      {
        "t": 194.2,
        "z": 1,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 197.12,
    "mode": "pip",
    "media": "clip",
    "src": "yt_complexity_variants",
    "origin": "source",
    "layout": "full",
    "chrome": true,
    "captionLane": "top",
    "kicker": "SOURCE DEMO",
    "headline": "ลองตัวเลือกภาพหลายแบบ",
    "sub": "เปรียบเทียบภาพจากตัวเลือกที่ต่างกัน"
  },
  {
    "t": 204.6,
    "mode": "full",
    "punch": [
      {
        "t": 212.6,
        "z": 1.2,
        "fx": 0.5,
        "fy": 0.5
      },
      {
        "t": 220.6,
        "z": 1,
        "fx": 0.5,
        "fy": 0.5
      }
    ]
  },
  {
    "t": 222.76,
    "mode": "pip",
    "media": "broll",
    "src": "product_shot_milk",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "ILLUSTRATIVE FOOTAGE",
    "headline": "ภาพสินค้าและการจัดฉาก",
    "sub": "ลองคิดฉากและองค์ประกอบสำหรับสินค้า"
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
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "ILLUSTRATIVE FOOTAGE",
    "headline": "งานพิมพ์และสื่อประชาสัมพันธ์",
    "sub": "เตรียมภาพไปใช้กับสื่อสิ่งพิมพ์"
  },
  {
    "t": 250.96,
    "mode": "pip",
    "media": "broll",
    "src": "ai_layout_draft_final",
    "origin": "ai",
    "layout": "stage",
    "chrome": false,
    "kicker": "ILLUSTRATIVE CONCEPT",
    "headline": "ภาพร่างสำหรับจัดวางข้อความ",
    "sub": "เห็นพื้นที่ว่างสำหรับเติมข้อความ"
  },
  {
    "t": 259.4,
    "mode": "pip",
    "media": "broll",
    "src": "team_brainstorming_board",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "ILLUSTRATIVE FOOTAGE",
    "headline": "นำภาพมาคุยร่วมกันในทีม",
    "sub": "ใช้ภาพช่วยแลกเปลี่ยนไอเดียในทีม"
  },
  {
    "t": 267.4,
    "mode": "full"
  },
  {
    "t": 277.1,
    "mode": "pip",
    "media": "broll",
    "src": "coding_developer_illustration",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "ILLUSTRATIVE FOOTAGE",
    "headline": "นำระบบภาพไปใช้ในงานพัฒนา",
    "sub": "ต่อยอดระบบภาพในงานเขียนโปรแกรม"
  },
  {
    "t": 285.86,
    "mode": "pip",
    "media": "broll",
    "src": "developer_new_function",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "ILLUSTRATIVE FOOTAGE",
    "headline": "พัฒนาฟังก์ชันเกี่ยวกับภาพ",
    "sub": "สร้างเครื่องมือให้ทำงานกับภาพได้"
  },
  {
    "t": 294.66,
    "mode": "pip",
    "media": "broll",
    "src": "tablet_photo_editing",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "ILLUSTRATIVE FOOTAGE",
    "headline": "งานปรับแต่งภาพในแอป",
    "sub": "ปรับส่วนต่างๆ ของภาพบนหน้าจอ"
  },
  {
    "t": 303.3,
    "mode": "full"
  },
  {
    "t": 306.46,
    "mode": "pip",
    "media": "broll",
    "src": "content_editor_workflow",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "ILLUSTRATIVE FOOTAGE",
    "headline": "เวิร์กโฟลว์ของคนทำคอนเทนต์",
    "sub": "เตรียมสื่อสำหรับงานคอนเทนต์"
  },
  {
    "t": 311.92,
    "mode": "full"
  },
  {
    "t": 316.54,
    "mode": "pip",
    "media": "broll",
    "src": "boutique_customer_sale",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "kicker": "ILLUSTRATIVE FOOTAGE",
    "headline": "งานขายและการดูแลร้าน",
    "sub": "แบ่งเวลาไปดูแลงานขายและร้านค้า"
  },
  {
    "t": 322.68,
    "mode": "pip",
    "media": "typo",
    "typo": "summary3",
    "src": "summary_cards",
    "kicker": "FINAL RECAP",
    "headline": "GPT-Image-2.6 กับงานภาพ",
    "sub": "ทดลองไอเดียและสร้างสื่อประกอบ",
    "origin": "stock",
    "layout": "stage",
    "chrome": false,
    "cards": [
      {
        "t": 322.68,
        "lines": [
          "Flare · Sunburst",
          "ชื่อโมเดลจากต้นทาง"
        ]
      },
      {
        "t": 329.5,
        "lines": [
          "ภาพประกอบในงานประจำวัน",
          "ทดลองไอเดียและสื่อสารร่วมกัน"
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
            if(![box.x,box.y,box.width,box.height,opacity,alpha].every(Number.isFinite)||box.width<=0||box.height<=0)throw Error('invalid background geometry');
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

export type YtNewsStyle01V4Props = {
  durationSec?: number;
  qcPlan?: boolean;
  qcMeasure?: boolean;
};

export const calculateYtNewsStyle01V4Metadata: CalculateMetadataFunction<YtNewsStyle01V4Props> = async () => ({
  durationInFrames: Math.ceil(TOTAL_DURATION_SEC * 25),
  fps: 25,
  width: W,
  height: H,
});

export const YtNewsStyle01V4: React.FC<YtNewsStyle01V4Props> = ({qcPlan=false,qcMeasure=false}) => {
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
