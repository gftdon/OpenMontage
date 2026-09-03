import React, { useEffect, useState } from "react";
import {
  OffthreadVideo,
  Img,
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
import { CAPTION_PAGES } from "./googleFlowCaptions";

// ===========================================================================
// GoogleFlowYT — Frang × Google Flow tutorial, YouTube longform 1920x1080@25
// Format: reference-style presenter video — full-frame avatar morphs into a
// bottom-left PiP while a media stage (real Flow UI captures, official Google
// footage, typography cards) carries the visuals. Warm "Frang studio" palette:
// espresso stage, cream cards, amber + Google-blue/mint "flow ribbon" accent.
// VO 226.04s + 3.96s endcard = 230.0s
// ===========================================================================

// ---- Design tokens --------------------------------------------------------
const ESPRESSO = "#171009";
const ESPRESSO_2 = "#241708";
const CREAM = "#FAF3EA";
const INK = "#2A2018";
const AMBER = "#E8A13C";
const AMBER_LIGHT = "#F6C87B";
const GBLUE = "#4C8DF6";
const MINT = "#7FD1AE";
const WHITE = "#FDFBF7";
const MUTE = "#C9BCA8";
const GOLD = "#F59E0B"; // karaoke locked style
const GOLD_LIGHT = "#FDE68A"; // karaoke locked style
const FONT = '"KanitX", "Kanit", system-ui, -apple-system, sans-serif';
const RIBBON = `linear-gradient(90deg, ${GBLUE}, ${MINT}, ${AMBER})`;

// ---- Timing ---------------------------------------------------------------
const VO_END_SEC = 226.0;
const TOTAL_DURATION_SEC = 230.0;
const MODE_BLEND_SEC = 0.45;

// ---- Avatar geometry ------------------------------------------------------
// Source 1920x1080. PiP shows crop (535,10,880,495) in a 400x225 card (subject-centered).
const PIP = { x: 56, y: 791, w: 400, h: 225, r: 18 };
const PIP_CROP = { x: 535, y: 10, w: 880, h: 495 };

// ---- Beats ----------------------------------------------------------------
type MediaKind = "video" | "img" | "typo" | "none";

interface BeatDef {
  t: number;
  mode: "full" | "pip";
  kicker: string;
  media: MediaKind;
  src?: string;
  srcFrom?: number; // seconds into source video
  typo?:
    | "prompt_card"
    | "checklist4"
    | "start_end"
    | "shot_list"
    | "export"
    | "workflow";
  // still-image camera (kept ≤1.2 for dark UI)
  z1?: number;
  z2?: number;
  origin?: string;
  chip?: string;
  chip2?: string; // swaps in at chipSwapT
  chipSwapT?: number;
  ring?: { left: string; top: string }; // click-highlight ring on stills
}

const BEATS: BeatDef[] = [
  { t: 0.0, mode: "full", kicker: "", media: "none" },
  {
    t: 4.64, mode: "pip", kicker: "ครบจบในที่เดียว", media: "video",
    src: "google-flow-yt/flow_tools.mp4", srcFrom: 41.0,
    chip: "ไอเดีย → ภาพ → วิดีโอ → แก้ไข",
  },
  { t: 15.46, mode: "full", kicker: "", media: "none" },
  {
    t: 19.32, mode: "pip", kicker: "เริ่มต้นใช้งาน", media: "img",
    src: "google-flow-yt/flow_home.png", z1: 1.04, z2: 1.12, origin: "50% 40%",
    chip: "flow.google · Login ด้วย Google Account",
  },
  {
    t: 25.60, mode: "pip", kicker: "สร้างโปรเจกต์ใหม่", media: "img",
    src: "google-flow-yt/flow_home.png", z1: 1.16, z2: 1.22, origin: "49% 86%",
    ring: { left: "49.4%", top: "87%" },
  },
  {
    t: 27.84, mode: "pip", kicker: "พื้นที่ทำงานของ FLOW", media: "img",
    src: "google-flow-yt/flow_editor_empty.png", z1: 1.05, z2: 1.12, origin: "50% 45%",
    chip: "สร้างได้ทั้งภาพและวิดีโอ",
  },
  {
    t: 34.68, mode: "pip", kicker: "เขียน PROMPT", media: "img",
    src: "google-flow-yt/flow_editor_prompt.png", z1: 1.08, z2: 1.19, origin: "50% 88%",
  },
  {
    t: 40.64, mode: "pip", kicker: "ตัวอย่างโจทย์", media: "video",
    src: "google-flow-yt/poodle.mp4", srcFrom: 3.0,
    chip: "โจทย์: โฆษณาสินค้าสำหรับน้องหมา 🐩",
  },
  { t: 46.63, mode: "pip", kicker: "PROMPT ตัวอย่าง", media: "typo", typo: "prompt_card" },
  { t: 59.10, mode: "full", kicker: "", media: "none" },
  { t: 64.80, mode: "pip", kicker: "สูตร PROMPT 4 อย่าง", media: "typo", typo: "checklist4" },
  {
    t: 82.54, mode: "pip", kicker: "มุมกล้องสำเร็จรูป", media: "video",
    src: "google-flow-yt/flow_howto.mp4", srcFrom: 73.0,
    chip: "Dolly · Jib · Pan · Tilt · Truck",
  },
  {
    t: 88.96, mode: "pip", kicker: "GENERATE", media: "video",
    src: "google-flow-yt/flow_howto.mp4", srcFrom: 96.0,
    chip: "Flow สร้างมาให้เลือกหลายแบบ",
  },
  {
    t: 93.24, mode: "pip", kicker: "แก้ต่อได้ด้วยคำพูด", media: "video",
    src: "google-flow-yt/flow_tools.mp4", srcFrom: 24.0,
  },
  { t: 107.70, mode: "full", kicker: "", media: "none" },
  {
    t: 111.94, mode: "pip", kicker: "START & END FRAME", media: "video",
    src: "google-flow-yt/flow_howto.mp4", srcFrom: 50.0,
    chip: "ใส่ภาพแรก + ภาพสุดท้าย",
  },
  { t: 116.98, mode: "pip", kicker: "START & END FRAME", media: "typo", typo: "start_end" },
  { t: 131.38, mode: "full", kicker: "", media: "none" },
  {
    t: 137.68, mode: "pip", kicker: "INGREDIENTS · REFERENCE", media: "video",
    src: "google-flow-yt/flow_howto.mp4", srcFrom: 84.0,
    chip: "ตัวละครหน้าเดิม ทุก Scene",
  },
  { t: 148.84, mode: "pip", kicker: "แบ่งเป็น SHOT", media: "typo", typo: "shot_list" },
  {
    t: 162.62, mode: "pip", kicker: "ต่อ SHOT ในไทม์ไลน์", media: "video",
    src: "google-flow-yt/flow_howto.mp4", srcFrom: 141.5,
  },
  { t: 165.42, mode: "full", kicker: "", media: "none" },
  {
    t: 169.84, mode: "pip", kicker: "DRAFT ก่อน ประหยัดเครดิต", media: "img",
    src: "google-flow-yt/flow_model_picker.png", z1: 1.14, z2: 1.24, origin: "60% 78%",
    chip: "Draft ความละเอียดต่ำก่อน 💰", chip2: "เลือก Shot ที่ชอบ → Render / Upscale ทีหลัง", chipSwapT: 175.32,
  },
  { t: 183.44, mode: "pip", kicker: "EXPORT", media: "typo", typo: "export" },
  { t: 196.46, mode: "full", kicker: "", media: "none" },
  { t: 200.38, mode: "pip", kicker: "สรุป WORKFLOW", media: "typo", typo: "workflow" },
  {
    t: 209.02, mode: "pip", kicker: "จากไอเดีย → โฆษณา", media: "video",
    src: "google-flow-yt/flow_intro.mp4", srcFrom: 12.0,
    chip: "แทบไม่ต้องถ่ายทำจริงเลย",
  },
  { t: 218.06, mode: "full", kicker: "", media: "none" },
];

// Edit-request chat bubbles (beat แก้ต่อได้ด้วยคำพูด)
const EDIT_BUBBLES: { t: number; text: string }[] = [
  { t: 99.18, text: "“เปลี่ยนชุดเป็นสีฟ้า”" },
  { t: 100.89, text: "“เอาคนด้านหลังออก”" },
  { t: 102.58, text: "“เพิ่มดอกไม้บริเวณนี้”" },
  { t: 104.67, text: "“ปรับกล้องให้ช้าลง”" },
];

// ---- Font loader ----------------------------------------------------------
let fontReady: Promise<void> | null = null;
function ensureFonts(): Promise<void> {
  if (!fontReady) {
    const defs: [string, number][] = [
      ["fonts/Kanit-ExtraBold.ttf", 800],
      ["fonts/Kanit-Bold.ttf", 700],
    ];
    fontReady = Promise.all(
      defs.map(async ([path, weight]) => {
        const ff = new FontFace("KanitX", `url(${staticFile(path)})`, {
          weight: String(weight),
        });
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
    ensureFonts()
      .then(() => continueRender(handle))
      .catch(() => continueRender(handle));
  }, [handle]);
};

// ---- Props & metadata -----------------------------------------------------
export interface GoogleFlowYTProps {
  [key: string]: unknown;
  durationSec?: number;
}

export const calculateGoogleFlowYTMetadata: CalculateMetadataFunction<
  GoogleFlowYTProps
> = ({ props }) => {
  const fps = 25;
  const durationSec = props.durationSec || TOTAL_DURATION_SEC;
  return {
    durationInFrames: Math.ceil(durationSec * fps),
    fps,
    width: 1920,
    height: 1080,
  };
};

const springIn = (frame: number, fps: number, damping = 16, stiffness = 120) =>
  spring({ frame: Math.max(0, frame), fps, config: { damping, stiffness } });

const easeInOutCos = (p: number) => (1 - Math.cos(Math.PI * Math.min(1, Math.max(0, p)))) / 2;

// pip progress: 0 = avatar full-frame, 1 = avatar in PiP card
function pipProgress(t: number): number {
  let p = BEATS[0].mode === "pip" ? 1 : 0;
  for (let i = 1; i < BEATS.length; i++) {
    const b = BEATS[i];
    const target = b.mode === "pip" ? 1 : 0;
    if (t >= b.t) {
      const local = (t - b.t) / MODE_BLEND_SEC;
      p = local >= 1 ? target : p + (target - p) * easeInOutCos(local);
    } else {
      break;
    }
  }
  return p;
}

// ===========================================================================
// Shared bits
// ===========================================================================

const ProgressBar: React.FC<{ totalFrames: number }> = ({ totalFrames }) => {
  const frame = useCurrentFrame();
  const progress = Math.min(1, frame / totalFrames);
  return (
    <div
      style={{
        position: "absolute", top: 0, left: 0, width: "100%", height: 6,
        backgroundColor: "rgba(250,243,234,0.10)", zIndex: 60,
      }}
    >
      <div
        style={{
          width: `${progress * 100}%`, height: "100%",
          background: RIBBON, boxShadow: `0 0 10px ${AMBER}`,
        }}
      />
    </div>
  );
};

const BrandChip: React.FC = () => (
  <div
    style={{
      position: "absolute", top: 26, right: 40, zIndex: 55,
      display: "flex", alignItems: "center", gap: 10,
      background: "rgba(23,16,9,0.62)", backdropFilter: "blur(10px)",
      WebkitBackdropFilter: "blur(10px)",
      border: "1px solid rgba(250,243,234,0.22)", borderRadius: 999,
      padding: "8px 20px",
    }}
  >
    <div
      style={{
        width: 10, height: 10, borderRadius: "50%",
        background: RIBBON, boxShadow: `0 0 8px ${AMBER}`,
      }}
    />
    <span style={{ fontFamily: FONT, fontSize: 19, fontWeight: 700, color: WHITE, letterSpacing: 0.6 }}>
      ฟรัง · GOOGLE FLOW · EP.1
    </span>
  </div>
);

const Kicker: React.FC<{ text: string; localFrame: number; fps: number }> = ({
  text, localFrame, fps,
}) => {
  if (!text) return null;
  const enter = springIn(localFrame - 3, fps, 15, 120);
  return (
    <div
      key={text}
      style={{
        position: "absolute", top: 26, left: 40, zIndex: 55,
        display: "flex", alignItems: "center", gap: 9,
        background: "rgba(23,16,9,0.62)", backdropFilter: "blur(10px)",
        WebkitBackdropFilter: "blur(10px)",
        border: `1px solid rgba(232,161,60,0.55)`, borderRadius: 999,
        padding: "8px 20px", opacity: enter,
        transform: `translateY(${interpolate(enter, [0, 1], [-8, 0])}px)`,
      }}
    >
      <span style={{ fontFamily: FONT, fontSize: 19, fontWeight: 800, color: AMBER_LIGHT, letterSpacing: 0.8 }}>
        {text}
      </span>
    </div>
  );
};

// Secondary info pill, bottom-right above caption band
const InfoChip: React.FC<{ text: string; localFrame: number; fps: number }> = ({
  text, localFrame, fps,
}) => {
  const enter = springIn(localFrame - 8, fps, 14, 110);
  return (
    <div
      key={text}
      style={{
        position: "absolute", right: 44, bottom: 176, zIndex: 45,
        background: "rgba(23,16,9,0.72)", backdropFilter: "blur(10px)",
        WebkitBackdropFilter: "blur(10px)",
        border: "1.5px solid rgba(127,209,174,0.5)", borderRadius: 14,
        padding: "10px 20px", opacity: enter,
        transform: `translateY(${interpolate(enter, [0, 1], [12, 0])}px)`,
        display: "flex", alignItems: "center", gap: 10,
      }}
    >
      <div style={{ width: 9, height: 9, borderRadius: "50%", backgroundColor: MINT, boxShadow: `0 0 8px ${MINT}` }} />
      <span style={{ fontFamily: FONT, fontSize: 22, fontWeight: 700, color: WHITE }}>{text}</span>
    </div>
  );
};

// Beat transition sweep — warm light band
const BeatSweep: React.FC<{ sinceBeat: number }> = ({ sinceBeat }) => {
  if (sinceBeat > 0.5 || sinceBeat < 0) return null;
  const p = sinceBeat / 0.5;
  const x = interpolate(p, [0, 1], [-500, 2400]);
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", zIndex: 40, pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute", top: -100, left: x, width: 380, height: 1280,
          background: `linear-gradient(90deg, transparent, rgba(232,161,60,${0.14 * (1 - p)}), rgba(253,251,247,${0.09 * (1 - p)}), transparent)`,
          transform: "skewX(-16deg)",
        }}
      />
    </div>
  );
};

// ===========================================================================
// Media stage renderers
// ===========================================================================

const BrowserCard: React.FC<{
  src: string; z1: number; z2: number; origin: string; beatP: number;
  ring?: { left: string; top: string }; localFrame: number; fps: number;
}> = ({ src, z1, z2, origin, beatP, ring, localFrame, fps }) => {
  const enter = springIn(localFrame, fps, 17, 140);
  const zoom = z1 + (z2 - z1) * beatP;
  const pulse = 0.5 + 0.5 * Math.sin((localFrame / fps) * Math.PI * 2 * 1.1);
  const W = 1500, TITLE = 46, IMGH = 844;
  return (
    <div
      style={{
        position: "absolute", left: (1920 - W) / 2, top: 64, width: W, height: TITLE + IMGH,
        borderRadius: 20, overflow: "hidden",
        border: "1.5px solid rgba(250,243,234,0.16)",
        boxShadow: "0 24px 70px rgba(0,0,0,0.55), 0 0 40px rgba(232,161,60,0.10)",
        backgroundColor: "#100B06",
        transform: `scale(${interpolate(enter, [0, 1], [0.965, 1])})`,
        opacity: enter,
      }}
    >
      <div
        style={{
          height: TITLE, display: "flex", alignItems: "center", padding: "0 18px",
          background: "linear-gradient(180deg, #2E2115, #1D1409)",
          borderBottom: "1px solid rgba(250,243,234,0.08)", position: "relative",
        }}
      >
        <div style={{ display: "flex", gap: 8 }}>
          <div style={{ width: 12, height: 12, borderRadius: "50%", backgroundColor: "#E8695A" }} />
          <div style={{ width: 12, height: 12, borderRadius: "50%", backgroundColor: AMBER }} />
          <div style={{ width: 12, height: 12, borderRadius: "50%", backgroundColor: MINT }} />
        </div>
        <div
          style={{
            position: "absolute", left: "50%", transform: "translateX(-50%)",
            display: "flex", alignItems: "center", gap: 8,
            background: "rgba(250,243,234,0.08)", borderRadius: 999, padding: "5px 22px",
          }}
        >
          <span style={{ fontSize: 15, color: MINT }}>🔒</span>
          <span style={{ fontFamily: FONT, fontSize: 16, fontWeight: 600, color: MUTE, letterSpacing: 0.5 }}>
            flow.google
          </span>
        </div>
      </div>
      <div style={{ width: "100%", height: IMGH, overflow: "hidden", position: "relative" }}>
        <Img
          src={staticFile(src)}
          style={{
            width: "100%", height: "100%", objectFit: "cover", objectPosition: "top",
            transform: `scale(${zoom})`, transformOrigin: origin,
          }}
        />
        {ring ? (
          <div
            style={{
              position: "absolute", left: ring.left, top: ring.top,
              width: 210, height: 74, transform: "translate(-50%, -50%)",
              border: `3px solid ${AMBER_LIGHT}`, borderRadius: 999,
              boxShadow: `0 0 ${18 + 14 * pulse}px rgba(246,200,123,${0.55 + 0.3 * pulse}), inset 0 0 18px rgba(246,200,123,0.25)`,
            }}
          />
        ) : null}
      </div>
    </div>
  );
};

const FootageLayer: React.FC<{
  src: string; srcFrom: number; beatStart: number; beatEnd: number; fps: number;
}> = ({ src, srcFrom, beatStart, beatEnd, fps }) => {
  const from = Math.round(beatStart * fps);
  const dur = Math.max(1, Math.round((beatEnd - beatStart) * fps));
  return (
    <Sequence from={from} durationInFrames={dur} layout="none">
      <OffthreadVideo
        muted
        src={staticFile(src)}
        trimBefore={Math.round(srcFrom * fps)}
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }}
      />
    </Sequence>
  );
};

// ===========================================================================
// Typography scenes (espresso stage, cream cards)
// ===========================================================================

const TypoStage: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div
    style={{
      position: "absolute", inset: 0,
      background: `radial-gradient(ellipse at 50% 20%, rgba(232,161,60,0.13), transparent 62%), radial-gradient(ellipse at 12% 90%, rgba(76,141,246,0.08), transparent 55%), linear-gradient(180deg, ${ESPRESSO_2}, ${ESPRESSO})`,
    }}
  >
    {children}
  </div>
);

const PROMPT_TEXT =
  "น้องหมาพุดเดิ้ลสีขาว ใส่ชุดเดรสสีชมพู เดินอยู่ในสวนดอกไม้ แสงช่วง Golden Hour กล้องค่อยๆ เคลื่อนเข้าหาน้องหมา สไตล์โฆษณาแฟชั่นระดับ Luxury";

const PromptCard: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  const local = t - 46.63;
  const enter = springIn(Math.round(local * fps) - 2, fps, 15, 110);
  const chars = Math.round(
    interpolate(t, [47.1, 56.8], [0, PROMPT_TEXT.length], {
      extrapolateLeft: "clamp", extrapolateRight: "clamp",
    })
  );
  const caretOn = Math.floor(t * 2.4) % 2 === 0 && t < 57.0;
  const polaroidIn = springIn(Math.round((t - 48.6) * fps), fps, 13, 90);
  return (
    <TypoStage>
      <div
        style={{
          position: "absolute", left: 190, top: 150, width: 1080,
          background: "linear-gradient(180deg, rgba(250,243,234,0.985), rgba(244,232,216,0.97))",
          border: `1.5px solid rgba(232,161,60,0.5)`, borderRadius: 26,
          boxShadow: "0 30px 80px rgba(0,0,0,0.5)",
          padding: "38px 46px 42px",
          transform: `translateY(${interpolate(enter, [0, 1], [30, 0])}px)`,
          opacity: enter,
        }}
      >
        <div style={{ height: 6, width: 240, background: RIBBON, borderRadius: 3, marginBottom: 26 }} />
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
          <div
            style={{
              fontFamily: FONT, fontSize: 21, fontWeight: 800, color: WHITE,
              background: INK, borderRadius: 999, padding: "6px 20px", letterSpacing: 1,
            }}
          >
            PROMPT
          </div>
          <span style={{ fontFamily: FONT, fontSize: 21, fontWeight: 700, color: "#8A7458" }}>
            โฆษณาน้องหมา 🐩
          </span>
        </div>
        <div
          style={{
            fontFamily: FONT, fontSize: 42, fontWeight: 700, color: INK,
            lineHeight: 1.55, minHeight: 320,
          }}
        >
          {PROMPT_TEXT.slice(0, chars)}
          <span style={{ opacity: caretOn ? 1 : 0, color: AMBER }}>▍</span>
        </div>
      </div>
      <div
        style={{
          position: "absolute", right: 150, top: 250, width: 430,
          background: CREAM, borderRadius: 18, padding: "16px 16px 22px",
          boxShadow: "0 24px 60px rgba(0,0,0,0.55)",
          transform: `rotate(4deg) scale(${interpolate(polaroidIn, [0, 1], [0.8, 1])})`,
          opacity: polaroidIn,
        }}
      >
        <Img
          src={staticFile("google-flow-yt/poodle_still_a.jpg")}
          style={{ width: "100%", borderRadius: 10, display: "block" }}
        />
        <div style={{ fontFamily: FONT, fontSize: 20, fontWeight: 700, color: "#8A7458", textAlign: "center", marginTop: 12 }}>
          Subject: น้องหมาพุดเดิ้ล ⭐
        </div>
      </div>
    </TypoStage>
  );
};

const CHECK_ITEMS: { t: number; num: string; head: string; sub: string; color: string }[] = [
  { t: 69.42, num: "1", head: "ตัวละคร / Subject", sub: "คือใคร ลักษณะยังไง", color: GBLUE },
  { t: 72.59, num: "2", head: "กำลังทำอะไร", sub: "แอ็กชันในซีน", color: MINT },
  { t: 76.21, num: "3", head: "อยู่ที่ไหน", sub: "ฉาก · บรรยากาศ · แสง", color: AMBER },
  { t: 79.58, num: "4", head: "กล้องเคลื่อนยังไง", sub: "Close-up · Wide · Dolly · Pan", color: "#E8695A" },
];

const Checklist4: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  const local = t - 64.80;
  const enter = springIn(Math.round(local * fps) - 2, fps, 15, 110);
  return (
    <TypoStage>
      <div
        style={{
          position: "absolute", left: 0, right: 0, top: 108,
          display: "flex", flexDirection: "column", alignItems: "center",
          opacity: enter, transform: `translateY(${interpolate(enter, [0, 1], [26, 0])}px)`,
        }}
      >
        <div style={{ fontFamily: FONT, fontSize: 56, fontWeight: 800, color: WHITE, marginBottom: 8 }}>
          Prompt ที่ดี มีครบ <span style={{ color: AMBER_LIGHT }}>4 อย่าง</span>
        </div>
        <div style={{ height: 6, width: 300, background: RIBBON, borderRadius: 3 }} />
      </div>
      <div
        style={{
          position: "absolute", left: 330, right: 330, top: 268,
          display: "flex", flexDirection: "column", gap: 22,
        }}
      >
        {CHECK_ITEMS.map((it) => {
          const on = t >= it.t;
          const pop = springIn(Math.round((t - it.t) * fps), fps, 14, 120);
          return (
            <div
              key={it.num}
              style={{
                display: "flex", alignItems: "center", gap: 26,
                background: on ? "rgba(250,243,234,0.97)" : "rgba(250,243,234,0.10)",
                border: `1.5px solid ${on ? it.color : "rgba(250,243,234,0.14)"}`,
                borderRadius: 20, padding: "20px 32px",
                boxShadow: on ? `0 14px 40px rgba(0,0,0,0.45), 0 0 24px ${it.color}33` : "none",
                transform: on ? `scale(${interpolate(pop, [0, 1], [0.96, 1])})` : "scale(1)",
              }}
            >
              <div
                style={{
                  width: 62, height: 62, borderRadius: 18, flexShrink: 0,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  background: on ? it.color : "rgba(250,243,234,0.10)",
                  color: on ? "#FFFFFF" : MUTE,
                  fontFamily: FONT, fontSize: 32, fontWeight: 800,
                  boxShadow: on ? `0 0 18px ${it.color}66` : "none",
                }}
              >
                {it.num}
              </div>
              <div style={{ display: "flex", flexDirection: "column" }}>
                <span style={{ fontFamily: FONT, fontSize: 34, fontWeight: 800, color: on ? INK : MUTE, lineHeight: 1.2 }}>
                  {it.head}
                </span>
                <span style={{ fontFamily: FONT, fontSize: 22, fontWeight: 600, color: on ? "#8A7458" : "rgba(201,188,168,0.5)" }}>
                  {it.sub}
                </span>
              </div>
              {on ? (
                <span style={{ marginLeft: "auto", fontSize: 34, opacity: pop }}>✅</span>
              ) : null}
            </div>
          );
        })}
      </div>
    </TypoStage>
  );
};

const StartEndDiagram: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  const aIn = springIn(Math.round((t - 117.5) * fps), fps, 13, 95);
  const bIn = springIn(Math.round((t - 119.9) * fps), fps, 13, 95);
  const arcP = interpolate(t, [124.0, 126.6], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const chipIn = springIn(Math.round((t - 124.9) * fps), fps, 14, 100);
  const frameCard = (src: string, label: string, sub: string, prog: number, rot: number) => (
    <div
      style={{
        width: 560, background: CREAM, borderRadius: 20, padding: "16px 16px 20px",
        boxShadow: "0 26px 60px rgba(0,0,0,0.55)",
        transform: `rotate(${rot}deg) scale(${interpolate(prog, [0, 1], [0.82, 1])})`,
        opacity: prog,
      }}
    >
      <div style={{ position: "relative" }}>
        <Img src={staticFile(src)} style={{ width: "100%", borderRadius: 12, display: "block" }} />
        <div
          style={{
            position: "absolute", top: 12, left: 12,
            fontFamily: FONT, fontSize: 20, fontWeight: 800, color: WHITE,
            background: "rgba(23,16,9,0.78)", borderRadius: 999, padding: "5px 18px",
          }}
        >
          {label}
        </div>
      </div>
      <div style={{ fontFamily: FONT, fontSize: 22, fontWeight: 700, color: "#8A7458", textAlign: "center", marginTop: 12 }}>
        {sub}
      </div>
    </div>
  );
  return (
    <TypoStage>
      <div style={{ position: "absolute", left: 130, top: 260 }}>
        {frameCard("google-flow-yt/poodle_still_a.jpg", "START FRAME", "ภาพแรก: น้องหมาอยู่หน้าร้าน", aIn, -3)}
      </div>
      <div style={{ position: "absolute", right: 130, top: 300 }}>
        {frameCard("google-flow-yt/poodle_still_b.jpg", "END FRAME", "ภาพสุดท้าย: เดินเข้ามาในร้าน", bIn, 3)}
      </div>
      <svg
        width={1920} height={1080}
        style={{ position: "absolute", inset: 0, pointerEvents: "none" }}
      >
        <defs>
          <linearGradient id="flowArc" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor={GBLUE} />
            <stop offset="50%" stopColor={MINT} />
            <stop offset="100%" stopColor={AMBER} />
          </linearGradient>
        </defs>
        <path
          d="M 700 330 C 880 150, 1040 150, 1230 330"
          fill="none" stroke="url(#flowArc)" strokeWidth={9} strokeLinecap="round"
          strokeDasharray={720} strokeDashoffset={720 * (1 - arcP)}
          opacity={arcP > 0 ? 1 : 0}
        />
        {arcP > 0.97 ? (
          <polygon points="1230,330 1196,296 1186,330" fill={AMBER} />
        ) : null}
      </svg>
      <div
        style={{
          position: "absolute", left: 0, right: 0, top: 84, display: "flex", justifyContent: "center",
          opacity: chipIn, transform: `translateY(${interpolate(chipIn, [0, 1], [14, 0])}px)`,
        }}
      >
        <div
          style={{
            fontFamily: FONT, fontSize: 34, fontWeight: 800, color: INK,
            background: `linear-gradient(135deg, ${AMBER_LIGHT}, ${AMBER})`,
            borderRadius: 999, padding: "14px 40px",
            boxShadow: `0 10px 34px rgba(232,161,60,0.4)`,
          }}
        >
          ✨ Flow สร้างวิดีโอ “เชื่อม” สองภาพให้เอง
        </div>
      </div>
    </TypoStage>
  );
};

const SHOTS: { t: number; label: string; desc: string; icon: string }[] = [
  { t: 155.38, label: "SHOT 1", desc: "Establishing Shot — เปิดฉากเห็นภาพรวม", icon: "🏞️" },
  { t: 158.32, label: "SHOT 2", desc: "Medium Shot — เข้าใกล้ตัวละคร", icon: "🎯" },
  { t: 159.91, label: "SHOT 3", desc: "Close-up สินค้า — ชูของให้ชัด", icon: "🔍" },
];

const ShotList: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  const local = t - 148.84;
  const enter = springIn(Math.round(local * fps) - 2, fps, 15, 110);
  return (
    <TypoStage>
      <div
        style={{
          position: "absolute", left: 0, right: 0, top: 120,
          display: "flex", flexDirection: "column", alignItems: "center",
          opacity: enter, transform: `translateY(${interpolate(enter, [0, 1], [24, 0])}px)`,
        }}
      >
        <div style={{ fontFamily: FONT, fontSize: 54, fontWeight: 800, color: WHITE }}>
          อย่าสร้างยาวทีเดียว — <span style={{ color: AMBER_LIGHT }}>แบ่งเป็น Shot</span> 🎬
        </div>
        <div style={{ height: 6, width: 300, background: RIBBON, borderRadius: 3, marginTop: 14 }} />
      </div>
      <div style={{ position: "absolute", left: 360, right: 360, top: 300, display: "flex", flexDirection: "column", gap: 26 }}>
        {SHOTS.map((s, i) => {
          const on = t >= s.t;
          const pop = springIn(Math.round((t - s.t) * fps), fps, 13, 110);
          return (
            <div
              key={s.label}
              style={{
                display: "flex", alignItems: "center", gap: 26,
                background: on ? "rgba(250,243,234,0.97)" : "rgba(250,243,234,0.10)",
                border: `1.5px solid ${on ? AMBER : "rgba(250,243,234,0.14)"}`,
                borderRadius: 22, padding: "24px 34px",
                boxShadow: on ? "0 16px 44px rgba(0,0,0,0.45)" : "none",
                transform: `translateX(${on ? interpolate(pop, [0, 1], [i % 2 === 0 ? -36 : 36, 0]) : 0}px) scale(${on ? interpolate(pop, [0, 1], [0.97, 1]) : 1})`,
              }}
            >
              <span style={{ fontSize: 44 }}>{s.icon}</span>
              <span
                style={{
                  fontFamily: FONT, fontSize: 26, fontWeight: 800,
                  color: on ? WHITE : MUTE,
                  background: on ? INK : "rgba(250,243,234,0.08)",
                  borderRadius: 12, padding: "8px 22px", letterSpacing: 1.2,
                }}
              >
                {s.label}
              </span>
              <span style={{ fontFamily: FONT, fontSize: 30, fontWeight: 700, color: on ? INK : MUTE }}>
                {s.desc}
              </span>
            </div>
          );
        })}
      </div>
    </TypoStage>
  );
};

const EXPORTS: { t: number; label: string; color: string }[] = [
  { t: 190.0, label: "CapCut", color: "#22D3EE" },
  { t: 191.3, label: "Premiere Pro", color: "#9A6BFF" },
  { t: 192.6, label: "TikTok", color: "#FF3B5C" },
  { t: 193.9, label: "Reels", color: "#F02E65" },
  { t: 195.2, label: "YouTube", color: "#FF4E45" },
];

const ExportOverlay: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  const local = t - 183.44;
  const enter = springIn(Math.round(local * fps) - 2, fps, 15, 110);
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      <FootageLayer
        src="google-flow-yt/flow_intro.mp4" srcFrom={83.0}
        beatStart={183.44} beatEnd={196.46} fps={fps}
      />
      <div style={{ position: "absolute", inset: 0, background: "linear-gradient(180deg, rgba(23,16,9,0.82), rgba(23,16,9,0.55) 45%, rgba(23,16,9,0.85))" }} />
      <div
        style={{
          position: "absolute", left: 0, right: 0, top: 150,
          display: "flex", flexDirection: "column", alignItems: "center",
          opacity: enter, transform: `translateY(${interpolate(enter, [0, 1], [22, 0])}px)`,
        }}
      >
        <div style={{ fontFamily: FONT, fontSize: 58, fontWeight: 800, color: WHITE }}>
          ได้วิดีโอแล้ว <span style={{ color: MINT }}>Export</span> ไปใช้ต่อได้เลย
        </div>
        <div style={{ height: 6, width: 320, background: RIBBON, borderRadius: 3, marginTop: 16 }} />
      </div>
      <div
        style={{
          position: "absolute", left: 0, right: 0, top: 420,
          display: "flex", justifyContent: "center", gap: 26, flexWrap: "wrap", padding: "0 200px",
        }}
      >
        {EXPORTS.map((e) => {
          const pop = springIn(Math.round((t - e.t) * fps), fps, 12, 130);
          if (t < e.t) return null;
          return (
            <div
              key={e.label}
              style={{
                fontFamily: FONT, fontSize: 36, fontWeight: 800, color: WHITE,
                background: "rgba(23,16,9,0.72)", backdropFilter: "blur(8px)",
                WebkitBackdropFilter: "blur(8px)",
                border: `2.5px solid ${e.color}`, borderRadius: 999,
                padding: "16px 40px",
                boxShadow: `0 0 30px ${e.color}55`,
                transform: `scale(${interpolate(pop, [0, 1], [0.6, 1])}) translateY(${interpolate(pop, [0, 1], [18, 0])}px)`,
                opacity: pop,
              }}
            >
              {e.label}
            </div>
          );
        })}
      </div>
    </div>
  );
};

const FLOW_STEPS: { label: string; icon: string }[] = [
  { label: "คิด Scene", icon: "💡" },
  { label: "ภาพ / Reference", icon: "🖼️" },
  { label: "Generate", icon: "⚡" },
  { label: "ปรับด้วย Prompt", icon: "✏️" },
  { label: "ต่อ Shot", icon: "🎞️" },
  { label: "Export", icon: "🚀" },
];

const WorkflowPipeline: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  const local = t - 200.38;
  const enter = springIn(Math.round(local * fps) - 2, fps, 15, 110);
  return (
    <TypoStage>
      <div
        style={{
          position: "absolute", left: 0, right: 0, top: 170,
          display: "flex", flexDirection: "column", alignItems: "center",
          opacity: enter,
        }}
      >
        <div style={{ fontFamily: FONT, fontSize: 54, fontWeight: 800, color: WHITE }}>
          สรุป <span style={{ color: AMBER_LIGHT }}>Workflow</span> ของ Google Flow
        </div>
        <div style={{ height: 6, width: 320, background: RIBBON, borderRadius: 3, marginTop: 16 }} />
      </div>
      <div
        style={{
          position: "absolute", left: 120, right: 120, top: 420,
          display: "flex", alignItems: "center", justifyContent: "center", gap: 14,
        }}
      >
        {FLOW_STEPS.map((s, i) => {
          const st = 200.9 + i * 1.15;
          const pop = springIn(Math.round((t - st) * fps), fps, 13, 120);
          const on = t >= st;
          return (
            <React.Fragment key={s.label}>
              {i > 0 ? (
                <div
                  style={{
                    fontFamily: FONT, fontSize: 40, fontWeight: 800,
                    color: on ? AMBER_LIGHT : "rgba(201,188,168,0.3)",
                    transform: `translateX(${on ? interpolate(pop, [0, 1], [-8, 0]) : 0}px)`,
                  }}
                >
                  →
                </div>
              ) : null}
              <div
                style={{
                  display: "flex", flexDirection: "column", alignItems: "center", gap: 12,
                  background: on ? "rgba(250,243,234,0.97)" : "rgba(250,243,234,0.08)",
                  border: `1.5px solid ${on ? AMBER : "rgba(250,243,234,0.14)"}`,
                  borderRadius: 20, padding: "26px 24px", width: 218,
                  boxShadow: on ? "0 16px 40px rgba(0,0,0,0.45)" : "none",
                  transform: `scale(${on ? interpolate(pop, [0, 1], [0.8, 1]) : 1})`,
                  opacity: on ? 1 : 0.55,
                }}
              >
                <span style={{ fontSize: 44 }}>{s.icon}</span>
                <span
                  style={{
                    fontFamily: FONT, fontSize: 24, fontWeight: 800, textAlign: "center",
                    color: on ? INK : MUTE, lineHeight: 1.25,
                  }}
                >
                  {s.label}
                </span>
              </div>
            </React.Fragment>
          );
        })}
      </div>
    </TypoStage>
  );
};

// ===========================================================================
// Overlays on full-frame beats
// ===========================================================================

const HookTitle: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  if (t > 5.6) return null;
  const titleIn = springIn(Math.round((t - 0.5) * fps), fps, 14, 95);
  const subIn = springIn(Math.round((t - 1.7) * fps), fps, 14, 105);
  const out = interpolate(t, [4.2, 4.8], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const ribbonW = interpolate(t, [1.2, 2.4], [0, 560], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div style={{ position: "absolute", left: 90, bottom: 200, zIndex: 46, opacity: out }}>
      <div
        style={{
          fontFamily: FONT, fontSize: 26, fontWeight: 800, color: AMBER_LIGHT,
          letterSpacing: 3, marginBottom: 6,
          opacity: titleIn, transform: `translateY(${interpolate(titleIn, [0, 1], [16, 0])}px)`,
        }}
      >
        TUTORIAL · EP.1
      </div>
      <div
        style={{
          fontFamily: FONT, fontSize: 108, fontWeight: 800, color: WHITE, lineHeight: 1.02,
          textShadow: "0 6px 30px rgba(0,0,0,0.55)",
          opacity: titleIn, transform: `translateY(${interpolate(titleIn, [0, 1], [22, 0])}px)`,
        }}
      >
        GOOGLE <span style={{ color: AMBER_LIGHT }}>FLOW</span>
      </div>
      <div style={{ height: 8, width: ribbonW, background: RIBBON, borderRadius: 4, margin: "16px 0 14px" }} />
      <div
        style={{
          fontFamily: FONT, fontSize: 34, fontWeight: 700, color: WHITE,
          textShadow: "0 4px 18px rgba(0,0,0,0.6)",
          opacity: subIn, transform: `translateY(${interpolate(subIn, [0, 1], [14, 0])}px)`,
        }}
      >
        สร้างภาพ · วิดีโอ AI ครบจบในที่เดียว
      </div>
    </div>
  );
};

const TeaserChip: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  if (t < 219.3 || t > VO_END_SEC) return null;
  const enter = springIn(Math.round((t - 219.3) * fps), fps, 14, 100);
  return (
    <div
      style={{
        position: "absolute", right: 60, bottom: 200, zIndex: 46,
        background: "rgba(23,16,9,0.78)", backdropFilter: "blur(10px)",
        WebkitBackdropFilter: "blur(10px)",
        border: `1.5px solid ${AMBER}`, borderRadius: 18, padding: "18px 28px",
        boxShadow: `0 14px 40px rgba(0,0,0,0.5), 0 0 26px rgba(232,161,60,0.25)`,
        opacity: enter, transform: `translateX(${interpolate(enter, [0, 1], [30, 0])}px)`,
      }}
    >
      <div style={{ fontFamily: FONT, fontSize: 20, fontWeight: 800, color: AMBER_LIGHT, letterSpacing: 1.6, marginBottom: 4 }}>
        ตอนหน้า · EP.2
      </div>
      <div style={{ fontFamily: FONT, fontSize: 28, fontWeight: 800, color: WHITE }}>
        ลงมือทำจริง ตั้งแต่ Prompt แรก → โฆษณา 1 ตัว 🎬
      </div>
    </div>
  );
};

// ===========================================================================
// Karaoke caption lane — locked gold-glow style (karaoke_subtitle_v2)
// ===========================================================================
const isLatin = (s: string) => /^[A-Za-z0-9]/.test(s) || /[A-Za-z0-9]$/.test(s);

const CaptionLane: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  let pageIdx = -1;
  for (let i = 0; i < CAPTION_PAGES.length; i++) {
    if (t >= CAPTION_PAGES[i].start) pageIdx = i;
  }
  if (pageIdx < 0 || t > VO_END_SEC) return null;
  const page = CAPTION_PAGES[pageIdx];

  const enter = springIn(Math.round((t - page.start) * fps), fps, 18, 160);

  return (
    <div
      style={{
        position: "absolute", left: 0, right: 0, bottom: 42,
        display: "flex", justifyContent: "center", pointerEvents: "none", zIndex: 50,
      }}
    >
      <div
        style={{
          display: "flex", flexWrap: "wrap", justifyContent: "center", alignItems: "center",
          maxWidth: 980,
          background: "rgba(20, 13, 6, 0.82)",
          backdropFilter: "blur(16px)", WebkitBackdropFilter: "blur(16px)",
          border: "1.5px solid rgba(232, 161, 60, 0.38)",
          borderRadius: 22, padding: "12px 30px",
          boxShadow: "0 8px 32px rgba(0,0,0,0.6), 0 0 20px rgba(232, 161, 60, 0.22)",
          transform: `scale(${interpolate(enter, [0, 1], [0.94, 1])})`,
          opacity: enter,
        }}
      >
        {page.words.map((w, i) => {
          const active = t >= w.s && t < w.e;
          const spoken = t >= w.e;
          const prev = i > 0 ? page.words[i - 1].w : "";
          const sep = i > 0 && (isLatin(prev) || isLatin(w.w)) ? " " : "";

          let color = "rgba(253, 251, 247, 0.45)";
          let shadow = "none";
          let transform = "scale(1)";
          if (active) {
            color = GOLD_LIGHT;
            shadow = `0 0 16px ${GOLD}, 0 0 30px rgba(245, 158, 11, 0.7)`;
            transform = "scale(1.1)";
          } else if (spoken) {
            color = WHITE;
            shadow = "0 2px 4px rgba(0,0,0,0.4)";
          }

          return (
            <span
              key={i}
              style={{
                fontFamily: FONT, fontSize: 38, fontWeight: active ? 800 : 700,
                color, textShadow: shadow, transform,
                margin: "0 2px", display: "inline-block", lineHeight: 1.35,
              }}
            >
              {sep + w.w}
            </span>
          );
        })}
      </div>
    </div>
  );
};

// ===========================================================================
// Endcard
// ===========================================================================
const Endcard: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = springIn(frame, fps, 14, 90);
  const chips = [
    { icon: "🧩", text: "Prompt ครบ 4 อย่าง" },
    { icon: "💬", text: "แก้ได้ด้วยคำพูด" },
    { icon: "🎬", text: "แบ่งเป็น Shot" },
    { icon: "💰", text: "Draft ก่อน ประหยัดเครดิต" },
  ];
  return (
    <div
      style={{
        position: "absolute", inset: 0, zIndex: 100,
        display: "flex", alignItems: "center", justifyContent: "center",
        background: `radial-gradient(ellipse at 50% 30%, rgba(232,161,60,0.16), transparent 60%), linear-gradient(180deg, #FBF5EC, #F2E6D4)`,
        opacity: pop,
      }}
    >
      <div style={{ textAlign: "center", transform: `scale(${interpolate(pop, [0, 1], [0.94, 1])})` }}>
        <div
          style={{
            display: "inline-block", padding: "10px 30px", borderRadius: 999,
            background: INK, color: CREAM,
            fontFamily: FONT, fontSize: 22, fontWeight: 800, letterSpacing: 2,
            marginBottom: 26,
          }}
        >
          ฟรัง · AI TUTORIAL
        </div>
        <div style={{ fontFamily: FONT, fontSize: 92, fontWeight: 800, color: INK, lineHeight: 1.05 }}>
          GOOGLE <span style={{ background: RIBBON, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }}>FLOW</span>
        </div>
        <div style={{ height: 8, width: 380, background: RIBBON, borderRadius: 4, margin: "22px auto 18px" }} />
        <div style={{ fontFamily: FONT, fontSize: 32, fontWeight: 700, color: "#6B5940", marginBottom: 40 }}>
          เปลี่ยนไอเดียธรรมดา → วิดีโอระดับโฆษณา ด้วย AI
        </div>
        <div style={{ display: "flex", justifyContent: "center", gap: 18, flexWrap: "wrap", maxWidth: 1100, margin: "0 auto 44px" }}>
          {chips.map((c, idx) => {
            const chipIn = springIn(frame - 8 - idx * 5, fps, 15, 120);
            return (
              <div
                key={idx}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "14px 26px", borderRadius: 16,
                  background: "rgba(42,32,24,0.06)",
                  border: "1.5px solid rgba(42,32,24,0.28)",
                  fontFamily: FONT, fontSize: 24, fontWeight: 700, color: INK,
                  opacity: chipIn, transform: `translateY(${interpolate(chipIn, [0, 1], [14, 0])}px)`,
                }}
              >
                <span style={{ fontSize: 26 }}>{c.icon}</span>
                {c.text}
              </div>
            );
          })}
        </div>
        <div
          style={{
            display: "inline-block", padding: "18px 46px", borderRadius: 18,
            background: `linear-gradient(135deg, ${AMBER}, #D97B1F)`,
            color: WHITE, fontFamily: FONT, fontSize: 30, fontWeight: 800,
            boxShadow: "0 12px 34px rgba(217,123,31,0.4)",
          }}
        >
          🎬 EP.2 — ทำโฆษณาจริงตั้งแต่ Prompt แรก
        </div>
      </div>
    </div>
  );
};

// ===========================================================================
// Main composition
// ===========================================================================
export const GoogleFlowYT: React.FC<GoogleFlowYTProps> = ({
  durationSec = TOTAL_DURATION_SEC,
}) => {
  useThaiFonts();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const totalFrames = Math.ceil(durationSec * fps);

  // active beat
  let beatIdx = 0;
  for (let i = 0; i < BEATS.length; i++) {
    if (t >= BEATS[i].t) beatIdx = i;
  }
  const beat = BEATS[beatIdx];
  const beatStart = beat.t;
  const beatEnd = beatIdx + 1 < BEATS.length ? BEATS[beatIdx + 1].t : VO_END_SEC;
  const beatLocalFrame = Math.max(0, Math.round((t - beatStart) * fps));
  const sinceBeat = t - beatStart;
  const beatP = beatEnd > beatStart ? Math.min(1, (t - beatStart) / (beatEnd - beatStart)) : 0;

  // avatar full <-> pip morph
  const p = pipProgress(t);
  const cardX = interpolate(p, [0, 1], [0, PIP.x]);
  const cardY = interpolate(p, [0, 1], [0, PIP.y]);
  const cardW = interpolate(p, [0, 1], [1920, PIP.w]);
  const cardH = interpolate(p, [0, 1], [1080, PIP.h]);
  const radius = interpolate(p, [0, 1], [0, PIP.r]);
  const visibleW = interpolate(p, [0, 1], [1920, PIP_CROP.w]);
  const scale = cardW / visibleW;
  const cropX = interpolate(p, [0, 1], [0, PIP_CROP.x]);
  const cropY = interpolate(p, [0, 1], [0, PIP_CROP.y]);

  // media visibility follows pip progress (media lives "behind" avatar morph)
  const mediaOpacity = interpolate(p, [0, 0.55, 1], [0, 0.85, 1]);

  const showEndcard = t >= VO_END_SEC;

  return (
    <div
      style={{
        width: 1920, height: 1080, position: "relative", overflow: "hidden",
        backgroundColor: ESPRESSO, fontFamily: FONT,
      }}
    >
      {/* ===== MEDIA STAGE (pip beats) ===== */}
      <div style={{ position: "absolute", inset: 0, opacity: mediaOpacity, zIndex: 10 }}>
        <div
          style={{
            position: "absolute", inset: 0,
            background: `radial-gradient(ellipse at 50% 18%, rgba(232,161,60,0.10), transparent 62%), linear-gradient(180deg, ${ESPRESSO_2}, ${ESPRESSO})`,
          }}
        />
        {BEATS.map((b, i) => {
          if (b.mode !== "pip" || b.media === "none") return null;
          const bStart = b.t;
          const bEnd = i + 1 < BEATS.length ? BEATS[i + 1].t : VO_END_SEC;
          if (t < bStart - 0.02 || t >= bEnd + 0.02) return null;
          const localFrame = Math.max(0, Math.round((t - bStart) * fps));
          const localP = Math.min(1, (t - bStart) / (bEnd - bStart));

          if (b.media === "video" && b.src) {
            return (
              <div key={`m${i}`} style={{ position: "absolute", inset: 0 }}>
                <FootageLayer src={b.src} srcFrom={b.srcFrom || 0} beatStart={bStart} beatEnd={bEnd} fps={fps} />
                <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 240, background: "linear-gradient(180deg, transparent, rgba(23,16,9,0.72))" }} />
              </div>
            );
          }
          if (b.media === "img" && b.src) {
            return (
              <BrowserCard
                key={`m${i}`} src={b.src}
                z1={b.z1 || 1.04} z2={b.z2 || 1.12} origin={b.origin || "50% 50%"}
                beatP={localP} ring={b.ring} localFrame={localFrame} fps={fps}
              />
            );
          }
          if (b.media === "typo") {
            if (b.typo === "prompt_card") return <PromptCard key={`m${i}`} t={t} fps={fps} />;
            if (b.typo === "checklist4") return <Checklist4 key={`m${i}`} t={t} fps={fps} />;
            if (b.typo === "start_end") return <StartEndDiagram key={`m${i}`} t={t} fps={fps} />;
            if (b.typo === "shot_list") return <ShotList key={`m${i}`} t={t} fps={fps} />;
            if (b.typo === "export") return <ExportOverlay key={`m${i}`} t={t} fps={fps} />;
            if (b.typo === "workflow") return <WorkflowPipeline key={`m${i}`} t={t} fps={fps} />;
          }
          return null;
        })}

        {/* edit-request chat bubbles */}
        {t >= 93.24 && t < 107.70 ? (
          <div style={{ position: "absolute", right: 60, bottom: 190, display: "flex", flexDirection: "column-reverse", gap: 16, zIndex: 44 }}>
            {EDIT_BUBBLES.filter((bb) => t >= bb.t).map((bb, idx, arr) => {
              const pop = springIn(Math.round((t - bb.t) * fps), fps, 13, 130);
              const newest = idx === arr.length - 1;
              return (
                <div
                  key={bb.t}
                  style={{
                    alignSelf: "flex-end",
                    fontFamily: FONT, fontSize: 27, fontWeight: 700,
                    color: newest ? INK : "rgba(42,32,24,0.72)",
                    background: newest ? CREAM : "rgba(250,243,234,0.8)",
                    border: `1.5px solid ${newest ? AMBER : "rgba(232,161,60,0.35)"}`,
                    borderRadius: "20px 20px 4px 20px", padding: "12px 26px",
                    boxShadow: newest ? "0 12px 34px rgba(0,0,0,0.45)" : "0 6px 18px rgba(0,0,0,0.3)",
                    opacity: pop * (newest ? 1 : 0.85),
                    transform: `translateX(${interpolate(pop, [0, 1], [40, 0])}px) scale(${interpolate(pop, [0, 1], [0.9, 1])})`,
                  }}
                >
                  {bb.text}
                </div>
              );
            })}
          </div>
        ) : null}

        <BeatSweep sinceBeat={sinceBeat} />
      </div>

      {/* ===== AVATAR (continuous, morphs full <-> pip) ===== */}
      <Sequence from={0} durationInFrames={Math.ceil(VO_END_SEC * fps)} layout="none">
        <div
          style={{
            position: "absolute", left: cardX, top: cardY, width: cardW, height: cardH,
            borderRadius: radius, overflow: "hidden", zIndex: 30,
            border: p > 0.15 ? `2px solid rgba(232,161,60,${0.55 * p})` : "none",
            boxShadow: p > 0.15 ? `0 14px 40px rgba(0,0,0,${0.55 * p}), 0 0 26px rgba(232,161,60,${0.22 * p})` : "none",
            backgroundColor: ESPRESSO,
          }}
        >
          <div
            style={{
              position: "absolute",
              left: -cropX * scale, top: -cropY * scale,
              width: 1920 * scale, height: 1080 * scale,
            }}
          >
            <OffthreadVideo
              muted
              src={staticFile("google-flow-yt/avatar_source.mp4")}
              style={{ width: "100%", height: "100%" }}
            />
          </div>
          {/* caption legibility vignette on full-frame only */}
          <div
            style={{
              position: "absolute", left: 0, right: 0, bottom: 0, height: 230,
              background: "linear-gradient(180deg, transparent, rgba(10,6,3,0.6))",
              opacity: 1 - p, pointerEvents: "none",
            }}
          />
        </div>
      </Sequence>

      {/* ===== Overlays ===== */}
      <HookTitle t={t} fps={fps} />
      <TeaserChip t={t} fps={fps} />
      {!showEndcard && beat.mode === "pip" ? (
        <Kicker text={beat.kicker} localFrame={beatLocalFrame} fps={fps} />
      ) : null}
      {!showEndcard ? <BrandChip /> : null}
      {!showEndcard && beat.mode === "pip" && beat.chip ? (
        <InfoChip
          text={beat.chipSwapT && beat.chip2 && t >= beat.chipSwapT ? beat.chip2 : beat.chip}
          localFrame={beat.chipSwapT && t >= beat.chipSwapT ? Math.round((t - beat.chipSwapT) * fps) + 8 : beatLocalFrame}
          fps={fps}
        />
      ) : null}

      <ProgressBar totalFrames={totalFrames} />
      <CaptionLane />

      {showEndcard ? <Endcard /> : null}
    </div>
  );
};
