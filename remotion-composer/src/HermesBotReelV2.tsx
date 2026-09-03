import React, { useEffect, useState } from "react";
import {
  OffthreadVideo,
  interpolate,
  spring,
  staticFile,
  continueRender,
  delayRender,
  useCurrentFrame,
  useVideoConfig,
  CalculateMetadataFunction,
} from "remotion";
import { CAPTION_PAGES } from "./hermesBotV2Captions";

// ===========================================================================
// HermesBotReelV2 — "Utterly Perfect" rebuild of the Hermes Bot Mode reel
// 1080x1920 @ 30fps native. 110.28s VO + 3.72s endcard = 114.0s
//
//  - Top zone (0–1030): browser-framed screen walkthrough, camera keyframes
//    re-timed to the real transcript, beat badges, Thai feature pills,
//    6-slot feature tracker, cold-open kinetic type, beat transition sweeps.
//  - Seam (1030): neon hairline + blend band; NameTag row.
//  - Bottom zone (1030–1920): scenic presenter in rounded glass card,
//    word-synced gold-glow karaoke captions (sentence-safe pages).
//  - Endcard (110.28–114.0): recap chips + CTA.
// ===========================================================================

// ---- Design Tokens --------------------------------------------------------
const CYAN = "#38BDF8";
const PURPLE = "#818CF8";
const GOLD = "#F59E0B";
const GOLD_LIGHT = "#FDE68A";
const GREEN = "#10B981";
const WHITE = "#F8FAFC";
const MUTE = "#94A3B8";
const FONT = '"KanitX", "Kanit", system-ui, -apple-system, sans-serif';

// ---- Timing ---------------------------------------------------------------
const VO_END_SEC = 110.28;
const TOTAL_DURATION_SEC = 114.0;

// ---- Beats (aligned to transcript.srt cue times) ---------------------------
interface BeatDef {
  t: number;
  kicker: string; // Thai seam-row label
  badge: string;
  icon: string;
  pill1: string;
  pill2: string;
  featureIdx: number;
}

const BEATS: BeatDef[] = [
  {
    t: 0.0,
    kicker: "แนะนำฟีเจอร์",
    badge: "1 AI → AI TEAM",
    icon: "🤖",
    pill1: "เปลี่ยน AI 1 ตัวเป็นทีมผู้ช่วย",
    pill2: "ทำงานร่วมกันได้หลายคน",
    featureIdx: 0,
  },
  {
    t: 7.8,
    kicker: "รายชื่อบอท",
    badge: "NAMED BOTS & ROLES",
    icon: "💬",
    pill1: "แต่ละตัวมีชื่อ · นิสัย · หน้าที่เฉพาะ",
    pill2: "ค้นข้อมูล · เขียนคอนเทนต์ · เขียนโค้ด",
    featureIdx: 0,
  },
  {
    t: 29.65,
    kicker: "รายชื่อบอท",
    badge: "CHAT-LIKE ROSTER",
    icon: "💬",
    pill1: "แสดงเป็นรายชื่อเหมือนแอปแชต",
    pill2: "กดเลือกคุยกับบอทแต่ละตัวได้ทันที",
    featureIdx: 0,
  },
  {
    t: 35.51,
    kicker: "ความจำแยกอิสระ",
    badge: "SEPARATE CHATS & MEMORY",
    icon: "🧠",
    pill1: "งานแต่ละประเภทจะไม่ปนกัน",
    pill2: "ห้องแชต · ประวัติ · ความจำของตัวเอง",
    featureIdx: 1,
  },
  {
    t: 42.75,
    kicker: "กลุ่ม & เวิร์กสเปซ",
    badge: "AI GROUP COLLABORATION",
    icon: "👥",
    pill1: "จัดบอทเป็นกลุ่มตามโปรเจกต์",
    pill2: "เปิดห้องกลุ่มให้บอทระดมความคิด",
    featureIdx: 2,
  },
  {
    t: 55.78,
    kicker: "กลุ่ม & เวิร์กสเปซ",
    badge: "AI TEAM MEETING",
    icon: "👥",
    pill1: "เหมือนมีทีม AI มาประชุมร่วมกัน",
    pill2: "งานใหญ่ให้บอทหลายตัวช่วยกันคิด",
    featureIdx: 2,
  },
  {
    t: 58.95,
    kicker: "ส่งงานต่ออัตโนมัติ",
    badge: "BOT-TO-BOT HANDOFF",
    icon: "🔄",
    pill1: "บอทส่งงานต่อให้กันได้อัตโนมัติ",
    pill2: "ไม่ต้องคัดลอกข้อความไปมาด้วยตัวเอง",
    featureIdx: 3,
  },
  {
    t: 72.76,
    kicker: "งานประจำอัตโนมัติ",
    badge: "SCHEDULED AUTOMATION",
    icon: "⏰",
    pill1: "ตั้งงานประจำให้บอททำตามเวลา",
    pill2: "สรุปอีเมลเช้า · เช็กข่าว · สรุปงานค้าง",
    featureIdx: 4,
  },
  {
    t: 83.75,
    kicker: "ทีมผู้ช่วยส่วนตัว",
    badge: "PERSONAL AI TEAM",
    icon: "✨",
    pill1: "มีคนช่วยคิด · ช่วยเขียน · ช่วยตรวจ",
    pill2: "จัดการงานให้เป็นระบบเหมือนทีมจริง",
    featureIdx: 5,
  },
  {
    t: 97.87,
    kicker: "สรุปมูลค่า",
    badge: "FAST · CLEAR · REAL",
    icon: "🚀",
    pill1: "ทำงานเร็วขึ้น แยกงานชัดขึ้น",
    pill2: "เอา AI ไปใช้กับธุรกิจได้จริง",
    featureIdx: 5,
  },
];

const FEATURES = [
  { label: "Roster", icon: "🤖" },
  { label: "Memory", icon: "🧠" },
  { label: "Groups", icon: "👥" },
  { label: "Handoff", icon: "🔄" },
  { label: "Routines", icon: "⏰" },
  { label: "AI Team", icon: "✨" },
];

const CLIMAX_T = 97.87;

// ---- Camera Keyframes (screen recording is 1920x1080 in a 990x676 window) --
interface CameraKeyframe {
  t: number;
  zoom: number;
  panX: number;
  panY: number;
}

const CAMERA_KEYFRAMES: CameraKeyframe[] = [
  { t: 0.0, zoom: 1.3, panX: 60, panY: 40 }, // README header
  { t: 7.8, zoom: 1.12, panX: 25, panY: 20 }, // roster intro (dark UI — stay wide)
  { t: 16.0, zoom: 1.16, panX: 35, panY: 15 }, // named-bots screenshot
  { t: 24.0, zoom: 1.18, panX: 40, panY: -5 }, // bots pane highlight
  { t: 29.65, zoom: 1.25, panX: 60, panY: 0 }, // chat-like roster
  { t: 35.51, zoom: 1.4, panX: 85, panY: -15 }, // separate memory
  { t: 42.75, zoom: 1.35, panX: 75, panY: -5 }, // groups
  { t: 51.0, zoom: 1.45, panX: 85, panY: -20 }, // group chats
  { t: 58.95, zoom: 1.48, panX: 90, panY: -15 }, // bot-to-bot
  { t: 63.0, zoom: 1.58, panX: 100, panY: -40 }, // A2A communications
  { t: 72.76, zoom: 1.48, panX: 90, panY: -10 }, // routines
  { t: 79.0, zoom: 1.58, panX: 100, panY: -30 }, // routines highlight
  { t: 83.75, zoom: 1.38, panX: 40, panY: 0 }, // avatars (centered modal)
  { t: 91.0, zoom: 1.52, panX: 30, panY: -20 }, // avatar picker
  { t: 97.87, zoom: 1.32, panX: 50, panY: 10 }, // summary
  { t: 105.0, zoom: 1.42, panX: 80, panY: 30 }, // back to README header
  { t: 110.28, zoom: 1.3, panX: 60, panY: 40 }, // outro settle
];

function getCameraTransform(t: number): CameraKeyframe {
  if (t <= CAMERA_KEYFRAMES[0].t) return CAMERA_KEYFRAMES[0];
  const last = CAMERA_KEYFRAMES[CAMERA_KEYFRAMES.length - 1];
  if (t >= last.t) return last;
  for (let i = 0; i < CAMERA_KEYFRAMES.length - 1; i++) {
    const kf1 = CAMERA_KEYFRAMES[i];
    const kf2 = CAMERA_KEYFRAMES[i + 1];
    if (t >= kf1.t && t <= kf2.t) {
      const p = (t - kf1.t) / (kf2.t - kf1.t);
      const s = (1 - Math.cos(p * Math.PI)) / 2;
      return {
        t,
        zoom: kf1.zoom + (kf2.zoom - kf1.zoom) * s,
        panX: kf1.panX + (kf2.panX - kf1.panX) * s,
        panY: kf1.panY + (kf2.panY - kf1.panY) * s,
      };
    }
  }
  return CAMERA_KEYFRAMES[0];
}

// ---- Layout constants ------------------------------------------------------
const TOP_H = 1030; // top zone height
const WIN_X = 45;
const WIN_Y = 96;
const WIN_W = 990;
const WIN_H = 716;
const TITLEBAR_H = 40;
const SCREEN_H = WIN_H - TITLEBAR_H; // 676

// Presenter card (avatar_source.mp4 is 1280x720 landscape, scenic room)
const CARD_W = 780;
const CARD_H = 780;
const CARD_X = (1080 - CARD_W) / 2; // 150
const CARD_Y = 1112;
const CROP_X = 330; // source-space crop (640x640 centered on presenter)
const CROP_Y = 60;
const CROP_S = 640;
const P_SCALE = CARD_W / CROP_S; // 1.21875

// ---- Font Loader -----------------------------------------------------------
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

// ---- Props & Metadata ------------------------------------------------------
export interface HermesBotReelV2Props {
  [key: string]: unknown;
  durationSec?: number;
}

export const calculateHermesBotV2Metadata: CalculateMetadataFunction<
  HermesBotReelV2Props
> = ({ props }) => {
  const fps = 30;
  const durationSec = props.durationSec || TOTAL_DURATION_SEC;
  return {
    durationInFrames: Math.ceil(durationSec * fps),
    fps,
    width: 1080,
    height: 1920,
  };
};

const springIn = (frame: number, fps: number, damping = 16, stiffness = 120) =>
  spring({ frame, fps, config: { damping, stiffness } });

// ===========================================================================
// Sub-Components
// ===========================================================================

const ProgressBar: React.FC<{ totalFrames: number }> = ({ totalFrames }) => {
  const frame = useCurrentFrame();
  const progress = Math.min(1, frame / totalFrames);
  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        width: "100%",
        height: 6,
        backgroundColor: "rgba(255,255,255,0.08)",
        zIndex: 60,
      }}
    >
      <div
        style={{
          width: `${progress * 100}%`,
          height: "100%",
          background: `linear-gradient(90deg, ${CYAN}, ${PURPLE}, ${GOLD})`,
          boxShadow: `0 0 12px ${CYAN}`,
        }}
      />
    </div>
  );
};

// Karaoke Caption Lane — gold glow word highlight, sentence-safe pages
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

  const enter = springIn(Math.max(0, Math.round((t - page.start) * fps)), fps, 18, 160);

  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 300,
        display: "flex",
        justifyContent: "center",
        pointerEvents: "none",
        zIndex: 50,
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          alignItems: "center",
          maxWidth: 900,
          background: "rgba(11, 15, 25, 0.82)",
          backdropFilter: "blur(16px)",
          WebkitBackdropFilter: "blur(16px)",
          border: "1.5px solid rgba(56, 189, 248, 0.35)",
          borderRadius: 22,
          padding: "14px 30px",
          boxShadow: "0 8px 32px rgba(0,0,0,0.6), 0 0 20px rgba(56, 189, 248, 0.25)",
          transform: `scale(${interpolate(enter, [0, 1], [0.94, 1])})`,
          opacity: enter,
        }}
      >
        {page.words.map((w, i) => {
          const active = t >= w.s && t < w.e;
          const spoken = t >= w.e;
          const prev = i > 0 ? page.words[i - 1].w : "";
          const sep = i > 0 && (isLatin(prev) || isLatin(w.w)) ? " " : "";

          let color = "rgba(248, 250, 252, 0.45)";
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
                fontFamily: FONT,
                fontSize: 40,
                fontWeight: active ? 800 : 700,
                color,
                textShadow: shadow,
                transform,
                margin: "0 2px",
                display: "inline-block",
                lineHeight: 1.35,
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

// Feature Tracker — 6 slots: locked → active-pulse → lit
const FeatureTracker: React.FC<{ activeIdx: number; climax: boolean }> = ({
  activeIdx,
  climax,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pulse = 0.5 + 0.5 * Math.sin((frame / fps) * Math.PI * 2 * 1.4);
  return (
    <div
      style={{
        position: "absolute",
        top: 842,
        left: WIN_X,
        right: WIN_X,
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        background: "rgba(15, 23, 42, 0.8)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        border: "1px solid rgba(255,255,255,0.12)",
        borderRadius: 16,
        padding: "8px 16px",
        boxShadow: "0 4px 20px rgba(0,0,0,0.4)",
        zIndex: 35,
      }}
    >
      {FEATURES.map((f, i) => {
        const isActive = i === activeIdx;
        const lit = climax || i < activeIdx;
        const borderColor = isActive ? CYAN : lit ? "rgba(245,158,11,0.6)" : "transparent";
        const glow = isActive
          ? `0 0 ${12 + 8 * pulse}px rgba(56, 189, 248, ${0.4 + 0.3 * pulse})`
          : lit
            ? "0 0 8px rgba(245, 158, 11, 0.3)"
            : "none";
        return (
          <div
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 7,
              padding: "6px 13px",
              borderRadius: 12,
              background: isActive
                ? "linear-gradient(135deg, rgba(56,189,248,0.25), rgba(129,140,248,0.25))"
                : lit
                  ? "rgba(245, 158, 11, 0.10)"
                  : "transparent",
              border: `1px solid ${borderColor}`,
              boxShadow: glow,
              opacity: isActive || lit ? 1 : 0.55,
            }}
          >
            <span style={{ fontSize: 19 }}>{f.icon}</span>
            <span
              style={{
                fontFamily: FONT,
                fontSize: 17,
                fontWeight: isActive ? 800 : 600,
                color: isActive ? CYAN : lit ? GOLD_LIGHT : MUTE,
                letterSpacing: 0.4,
              }}
            >
              {f.label}
            </span>
          </div>
        );
      })}
    </div>
  );
};

// Floating Thai feature pills (swap per beat with spring)
const FloatingPills: React.FC<{
  pill1: string;
  pill2: string;
  frame: number;
  fps: number;
}> = ({ pill1, pill2, frame, fps }) => {
  const enter = springIn(frame, fps, 14, 100);
  const pill = (
    text: string,
    color: string,
    glow: string,
    flex: number
  ): React.ReactNode => (
    <div
      style={{
        flex,
        background: `linear-gradient(135deg, ${color}26, rgba(15, 23, 42, 0.88))`,
        border: `1.5px solid ${color}`,
        borderRadius: 14,
        padding: "12px 20px",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 10,
        boxShadow: `0 4px 16px rgba(0,0,0,0.5), 0 0 12px ${glow}`,
      }}
    >
      <div
        style={{
          width: 10,
          height: 10,
          borderRadius: "50%",
          backgroundColor: color,
          boxShadow: `0 0 8px ${color}`,
          flexShrink: 0,
        }}
      />
      <span
        style={{
          fontFamily: FONT,
          fontSize: 21,
          fontWeight: 700,
          color: WHITE,
          lineHeight: 1.25,
          textAlign: "center",
        }}
      >
        {text}
      </span>
    </div>
  );
  return (
    <div
      style={{
        position: "absolute",
        top: 926,
        left: WIN_X,
        right: WIN_X,
        display: "flex",
        gap: 16,
        justifyContent: "center",
        zIndex: 35,
        opacity: enter,
        transform: `translateY(${interpolate(enter, [0, 1], [15, 0])}px)`,
      }}
    >
      {pill(pill1, CYAN, "rgba(56, 189, 248, 0.25)", 1)}
      {pill(pill2, GOLD, "rgba(245, 158, 11, 0.25)", 1)}
    </div>
  );
};

// Beat transition sweep — diagonal light band across the top zone
const BeatSweep: React.FC<{ sinceBeat: number }> = ({ sinceBeat }) => {
  if (sinceBeat > 0.55) return null;
  const p = sinceBeat / 0.55;
  const x = interpolate(p, [0, 1], [-500, 1500]);
  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        width: 1080,
        height: TOP_H,
        overflow: "hidden",
        zIndex: 40,
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          position: "absolute",
          top: -100,
          left: x,
          width: 340,
          height: TOP_H + 200,
          background: `linear-gradient(90deg, transparent, rgba(56,189,248,${0.16 * (1 - p)}), rgba(255,255,255,${0.10 * (1 - p)}), transparent)`,
          transform: "skewX(-18deg)",
        }}
      />
    </div>
  );
};

// Cold-open kinetic typography (0–7.4s), synced to the VO's first sentence
const ColdOpen: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  if (t > 7.4) return null;

  const titleIn = springIn(Math.max(0, Math.round((t - 0.25) * fps)), fps, 13, 90);
  const chipAIn = springIn(Math.max(0, Math.round((t - 2.86) * fps)), fps, 14, 110);
  const chipBIn = springIn(Math.max(0, Math.round((t - 4.58) * fps)), fps, 14, 110);
  const out = interpolate(t, [6.7, 7.4], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        width: 1080,
        height: TOP_H,
        zIndex: 45,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        background: `rgba(5, 8, 17, ${0.66 * out})`,
        opacity: out,
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          fontFamily: FONT,
          fontSize: 64,
          fontWeight: 800,
          color: WHITE,
          letterSpacing: 2,
          textShadow: `0 0 30px rgba(56,189,248,0.8), 0 4px 20px rgba(0,0,0,0.8)`,
          transform: `scale(${interpolate(titleIn, [0, 1], [0.7, 1])})`,
          opacity: titleIn,
          marginBottom: 44,
        }}
      >
        HERMES <span style={{ color: CYAN }}>BOT MODE</span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 26 }}>
        <div
          style={{
            fontFamily: FONT,
            fontSize: 46,
            fontWeight: 800,
            color: WHITE,
            background: "rgba(56,189,248,0.15)",
            border: `2px solid ${CYAN}`,
            borderRadius: 18,
            padding: "14px 34px",
            boxShadow: `0 0 24px rgba(56,189,248,0.4)`,
            transform: `scale(${interpolate(chipAIn, [0, 1], [0.6, 1])})`,
            opacity: chipAIn,
          }}
        >
          AI 1 ตัว
        </div>
        <div
          style={{
            fontFamily: FONT,
            fontSize: 52,
            fontWeight: 800,
            color: GOLD_LIGHT,
            opacity: Math.min(chipAIn, chipBIn * 0.4 + 0.6),
            transform: `translateX(${interpolate(chipBIn, [0, 1], [-12, 0])}px)`,
            textShadow: `0 0 18px ${GOLD}`,
          }}
        >
          →
        </div>
        <div
          style={{
            fontFamily: FONT,
            fontSize: 46,
            fontWeight: 800,
            color: "#0F172A",
            background: `linear-gradient(135deg, ${GOLD_LIGHT}, ${GOLD})`,
            borderRadius: 18,
            padding: "14px 34px",
            boxShadow: `0 0 34px rgba(245,158,11,0.55)`,
            transform: `scale(${interpolate(chipBIn, [0, 1], [0.6, 1])})`,
            opacity: chipBIn,
          }}
        >
          ทีมผู้ช่วย AI
        </div>
      </div>
    </div>
  );
};

// Endcard — owns the reveal: brand, recap chips, CTA
const Endcard: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = springIn(frame, fps, 14, 90);
  const chips = [
    { icon: "🤖", text: "บอทหลายตัวในที่เดียว" },
    { icon: "👥", text: "จัดกลุ่มทำงานเป็นทีม" },
    { icon: "🔄", text: "ส่งต่องานอัตโนมัติ" },
    { icon: "⏰", text: "ตั้งเวลาสั่งการล่วงหน้า" },
  ];
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        background:
          "radial-gradient(ellipse at 50% 35%, rgba(56,189,248,0.16), transparent 65%), rgba(8, 11, 20, 0.97)",
        zIndex: 100,
        opacity: pop,
      }}
    >
      <div
        style={{
          width: 920,
          background: "linear-gradient(180deg, rgba(24, 33, 54, 0.95), rgba(15, 23, 42, 0.98))",
          border: `2px solid ${CYAN}`,
          borderRadius: 30,
          padding: "52px 44px",
          boxShadow: `0 20px 60px rgba(0,0,0,0.8), 0 0 40px rgba(56, 189, 248, 0.4)`,
          textAlign: "center",
          transform: `scale(${interpolate(pop, [0, 1], [0.92, 1])})`,
        }}
      >
        <div
          style={{
            display: "inline-block",
            padding: "8px 26px",
            borderRadius: 999,
            background: "linear-gradient(135deg, #38BDF8, #818CF8)",
            color: "#0F172A",
            fontFamily: FONT,
            fontSize: 22,
            fontWeight: 800,
            marginBottom: 24,
            letterSpacing: 1.5,
            boxShadow: "0 4px 16px rgba(56, 189, 248, 0.5)",
          }}
        >
          HERMES BOT MODE
        </div>

        <h1
          style={{
            fontFamily: FONT,
            fontSize: 52,
            fontWeight: 800,
            color: WHITE,
            margin: "0 0 14px 0",
            lineHeight: 1.25,
          }}
        >
          ทีมผู้ช่วย AI ประจำตัวของคุณ
        </h1>
        <p
          style={{
            fontFamily: FONT,
            fontSize: 25,
            fontWeight: 600,
            color: MUTE,
            margin: "0 0 40px 0",
            lineHeight: 1.5,
          }}
        >
          คิด · เขียน · ตรวจ · จัดระบบ — ครบในทีมเดียว
        </p>

        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "center",
            gap: 16,
            marginBottom: 44,
          }}
        >
          {chips.map((c, idx) => {
            const chipIn = springIn(Math.max(0, frame - 6 - idx * 4), fps, 15, 120);
            return (
              <div
                key={idx}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "13px 22px",
                  borderRadius: 14,
                  background: "rgba(56, 189, 248, 0.10)",
                  border: "1px solid rgba(56, 189, 248, 0.35)",
                  color: WHITE,
                  fontFamily: FONT,
                  fontSize: 22,
                  fontWeight: 700,
                  opacity: chipIn,
                  transform: `translateY(${interpolate(chipIn, [0, 1], [14, 0])}px)`,
                }}
              >
                <span style={{ fontSize: 24 }}>{c.icon}</span>
                {c.text}
              </div>
            );
          })}
        </div>

        <div
          style={{
            display: "inline-block",
            padding: "17px 44px",
            borderRadius: 16,
            background: `linear-gradient(135deg, ${GOLD}, #EA580C)`,
            color: WHITE,
            fontFamily: FONT,
            fontSize: 27,
            fontWeight: 800,
            boxShadow: "0 8px 24px rgba(245, 158, 11, 0.45)",
          }}
        >
          📦 ใช้ได้เลยใน Hermes Desktop
        </div>
        <div
          style={{
            marginTop: 26,
            fontFamily: FONT,
            fontSize: 19,
            fontWeight: 600,
            color: MUTE,
            letterSpacing: 1,
          }}
        >
          AI CHATBOT WIZARDRY
        </div>
      </div>
    </div>
  );
};

// ===========================================================================
// Main Reel Component
// ===========================================================================
export const HermesBotReelV2: React.FC<HermesBotReelV2Props> = ({
  durationSec = TOTAL_DURATION_SEC,
}) => {
  useThaiFonts();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const totalFrames = Math.ceil(durationSec * fps);

  // Active beat
  let currentBeat = BEATS[0];
  let beatStart = 0;
  for (const b of BEATS) {
    if (t >= b.t) {
      currentBeat = b;
      beatStart = b.t;
    }
  }
  const beatLocalFrame = Math.max(0, Math.round((t - beatStart) * fps));
  const sinceBeat = t - beatStart;

  const camera = getCameraTransform(t);
  const climax = t >= CLIMAX_T && t <= VO_END_SEC;

  // Presenter push-in 1.00 → 1.05
  const presenterScale = interpolate(frame, [0, totalFrames], [1.0, 1.05], {
    extrapolateRight: "clamp",
  });

  // Climax: dim the top zone slightly so the summary lands on the presenter
  const topDim = climax ? 0.82 : 1;

  return (
    <div
      style={{
        width: 1080,
        height: 1920,
        backgroundColor: "#050811",
        overflow: "hidden",
        position: "relative",
        fontFamily: FONT,
      }}
    >
      <ProgressBar totalFrames={totalFrames} />

      {/* ============================================================== */}
      {/* TOP ZONE: Screen Walkthrough Stage (0–1030)                    */}
      {/* ============================================================== */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: 1080,
          height: TOP_H,
          background:
            "radial-gradient(ellipse at 50% 22%, rgba(56, 189, 248, 0.13), transparent 70%), #0A0F1D",
          overflow: "hidden",
          zIndex: 10,
          opacity: topDim,
        }}
      >
        {/* Header */}
        <div
          style={{
            position: "absolute",
            top: 26,
            left: WIN_X,
            right: WIN_X,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            zIndex: 30,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              background: "rgba(15, 23, 42, 0.75)",
              border: "1px solid rgba(255,255,255,0.12)",
              borderRadius: 999,
              padding: "8px 20px",
            }}
          >
            <div
              style={{
                width: 10,
                height: 10,
                borderRadius: "50%",
                backgroundColor: GREEN,
                boxShadow: `0 0 8px ${GREEN}`,
              }}
            />
            <span
              style={{
                fontSize: 18,
                fontWeight: 800,
                color: WHITE,
                letterSpacing: 1,
              }}
            >
              HERMES DESKTOP · BOT MODE
            </span>
          </div>

          {/* Beat badge (spring swap per beat) */}
          <div
            key={currentBeat.badge}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              background: "linear-gradient(135deg, rgba(56,189,248,0.2), rgba(129,140,248,0.2))",
              border: `1px solid ${CYAN}`,
              borderRadius: 999,
              padding: "8px 22px",
              boxShadow: `0 0 16px rgba(56, 189, 248, 0.35)`,
              transform: `scale(${interpolate(springIn(beatLocalFrame, fps, 15, 110), [0, 1], [0.85, 1])})`,
            }}
          >
            <span style={{ fontSize: 20 }}>{currentBeat.icon}</span>
            <span
              style={{
                fontSize: 18,
                fontWeight: 800,
                color: CYAN,
                letterSpacing: 0.5,
              }}
            >
              {currentBeat.badge}
            </span>
          </div>
        </div>

        {/* Browser window with the screen recording */}
        <div
          style={{
            position: "absolute",
            top: WIN_Y,
            left: WIN_X,
            width: WIN_W,
            height: WIN_H,
            borderRadius: 22,
            overflow: "hidden",
            border: "2px solid rgba(56, 189, 248, 0.35)",
            boxShadow: `0 16px 48px rgba(0,0,0,0.7), 0 0 30px rgba(56, 189, 248, 0.25)`,
            backgroundColor: "#0D1117",
            zIndex: 20,
          }}
        >
          <div
            style={{
              height: TITLEBAR_H,
              background: "linear-gradient(180deg, #1E293B, #0F172A)",
              display: "flex",
              alignItems: "center",
              padding: "0 16px",
              borderBottom: "1px solid rgba(255,255,255,0.08)",
              position: "relative",
            }}
          >
            <div style={{ display: "flex", gap: 8 }}>
              <div style={{ width: 12, height: 12, borderRadius: "50%", backgroundColor: "#EF4444" }} />
              <div style={{ width: 12, height: 12, borderRadius: "50%", backgroundColor: "#F59E0B" }} />
              <div style={{ width: 12, height: 12, borderRadius: "50%", backgroundColor: "#10B981" }} />
            </div>
            <div
              style={{
                position: "absolute",
                left: 0,
                right: 0,
                textAlign: "center",
                fontSize: 14,
                fontWeight: 600,
                color: MUTE,
                letterSpacing: 0.5,
                pointerEvents: "none",
              }}
            >
              🔒 github.com/NousResearch/hermes-agent
            </div>
          </div>

          <div
            style={{
              width: "100%",
              height: SCREEN_H,
              overflow: "hidden",
              position: "relative",
              backgroundColor: "#0D1117",
            }}
          >
            <OffthreadVideo
              src={staticFile("hermes-bot-mode-reel/screen_recording.mp4")}
              style={{
                width: "100%",
                height: "100%",
                objectFit: "cover",
                filter: "brightness(1.1) saturate(1.05)",
                transform: `scale(${camera.zoom}) translate(${camera.panX}px, ${camera.panY}px)`,
                transformOrigin: "center center",
              }}
            />
          </div>
        </div>

        <FeatureTracker activeIdx={currentBeat.featureIdx} climax={climax} />
        <FloatingPills
          key={currentBeat.pill1}
          pill1={currentBeat.pill1}
          pill2={currentBeat.pill2}
          frame={beatLocalFrame}
          fps={fps}
        />
        <BeatSweep sinceBeat={sinceBeat} />
        <ColdOpen />
      </div>

      {/* ============================================================== */}
      {/* SEAM (1030)                                                    */}
      {/* ============================================================== */}
      <div
        style={{
          position: "absolute",
          top: TOP_H - 1,
          left: 0,
          width: 1080,
          height: 2,
          background: `linear-gradient(90deg, transparent, ${CYAN}, ${PURPLE}, transparent)`,
          boxShadow: `0 0 16px ${CYAN}`,
          zIndex: 45,
        }}
      />
      <div
        style={{
          position: "absolute",
          top: TOP_H - 40,
          left: 0,
          width: 1080,
          height: 80,
          background: "linear-gradient(180deg, transparent, #050811 70%)",
          zIndex: 25,
          pointerEvents: "none",
        }}
      />

      {/* ============================================================== */}
      {/* BOTTOM ZONE: Presenter (1030–1920)                             */}
      {/* ============================================================== */}
      <div
        style={{
          position: "absolute",
          top: TOP_H,
          left: 0,
          width: 1080,
          height: 1920 - TOP_H,
          background:
            "radial-gradient(ellipse at 50% 85%, rgba(129, 140, 248, 0.10), transparent 60%), #050811",
          overflow: "hidden",
          zIndex: 15,
        }}
      >
        {/* Seam row: Thai kicker + NameTag */}
        <div
          style={{
            position: "absolute",
            top: 16,
            left: 45,
            right: 45,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            zIndex: 30,
          }}
        >
          <div
            key={currentBeat.kicker}
            style={{
              fontSize: 19,
              fontWeight: 700,
              color: GOLD_LIGHT,
              background: "rgba(245, 158, 11, 0.10)",
              border: "1px solid rgba(245, 158, 11, 0.35)",
              borderRadius: 999,
              padding: "7px 18px",
              opacity: springIn(beatLocalFrame, fps, 16, 120),
            }}
          >
            {currentBeat.kicker}
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 9,
              fontSize: 19,
              fontWeight: 700,
              color: WHITE,
              background: "rgba(15, 23, 42, 0.75)",
              border: "1px solid rgba(255,255,255,0.14)",
              borderRadius: 999,
              padding: "7px 18px",
            }}
          >
            <div
              style={{
                width: 9,
                height: 9,
                borderRadius: "50%",
                backgroundColor: CYAN,
                boxShadow: `0 0 8px ${CYAN}`,
              }}
            />
            ฟรัง · AI Chatbot Wizardry
          </div>
        </div>

        {/* Presenter glass card */}
        <div
          style={{
            position: "absolute",
            top: CARD_Y - TOP_H,
            left: CARD_X,
            width: CARD_W,
            height: CARD_H,
            borderRadius: 30,
            overflow: "hidden",
            border: "2px solid rgba(56, 189, 248, 0.30)",
            boxShadow:
              "0 18px 50px rgba(0,0,0,0.65), 0 0 34px rgba(56, 189, 248, 0.18)",
            backgroundColor: "#0A0F1D",
          }}
        >
          <div
            style={{
              position: "absolute",
              top: -CROP_Y * P_SCALE,
              left: -CROP_X * P_SCALE,
              width: 1280 * P_SCALE,
              height: 720 * P_SCALE,
              transform: `scale(${presenterScale})`,
              transformOrigin: "50% 35%",
            }}
          >
            <OffthreadVideo
              src={staticFile("hermes-bot-mode-reel/avatar_source.mp4")}
              style={{ width: "100%", height: "100%", objectFit: "cover" }}
            />
          </div>
          {/* subtle inner vignette for caption legibility */}
          <div
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              bottom: 0,
              height: 260,
              background: "linear-gradient(180deg, transparent, rgba(5,8,17,0.55))",
              pointerEvents: "none",
            }}
          />
        </div>
      </div>

      {/* Karaoke captions over presenter chest */}
      <CaptionLane />

      {/* Endcard */}
      {t > VO_END_SEC && <Endcard />}
    </div>
  );
};
