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
import { CAPTION_PAGES } from "./hermesBotCaptions";

// ===========================================================================
// HermesBotReel — Split-Zone AI Avatar + Screen Recording Showcase
// Resolution: 720x1280 @ 30fps (Wrapped from 1080x1920 design space)
// Features:
//  - Top Zone (0–920px): macOS-style Window with recorded screen walkthrough,
//    synced feature badges, dynamic floating chips, and interactive feature tracker.
//  - Seam Divider (920px): Glowing neon hairline + seamless black blend.
//  - Bottom Zone (920–1920px): AI Avatar half-body anchored on pure black.
//  - Word-synced Karaoke Subtitles over presenter's chest.
// ===========================================================================

// ---- Design Tokens --------------------------------------------------------
const CYAN = "#38BDF8";
const BLUE = "#3B82F6";
const PURPLE = "#818CF8";
const GOLD = "#F59E0B";
const GOLD_LIGHT = "#FDE68A";
const GREEN = "#10B981";
const WHITE = "#F8FAFC";
const MUTE = "#94A3B8";
const GLASS_BG = "rgba(15, 23, 42, 0.75)";
const GLASS_BORDER = "rgba(56, 189, 248, 0.25)";
const FONT = '"KanitX", "Kanit", system-ui, -apple-system, sans-serif';

// ---- Timing & Beats (Seconds) ---------------------------------------------
const TOTAL_DURATION_SEC = 118.0; // 115.4s VO + 2.6s Endcard
const VIDEO_END_SEC = 115.38;

interface BeatDef {
  t: number;
  kicker: string;
  badge: string;
  icon: string;
  pill1: string;
  pill2: string;
  activeFeatureIdx: number;
}

const BEATS: BeatDef[] = [
  {
    t: 0.0,
    kicker: "HERMES BOT MODE",
    badge: "1 AI → MULTI-AGENT TEAM",
    icon: "🤖",
    pill1: "เปลี่ยน AI 1 ตัวเป็นทีมผู้ช่วย",
    pill2: "ทำงานร่วมกันหลายคน",
    activeFeatureIdx: 0,
  },
  {
    t: 11.54,
    kicker: "BOT ROSTER",
    badge: "NAMED BOTS & SEPARATE CHATS",
    icon: "💬",
    pill1: "แต่ละตัวมีห้องแชต & ความจำแยกกัน",
    pill2: "นิสัยและหน้าที่เฉพาะตัว",
    activeFeatureIdx: 0,
  },
  {
    t: 34.34,
    kicker: "GROUPS & WORKSPACES",
    badge: "AI GROUP COLLABORATION",
    icon: "👥",
    pill1: "จัดบอทเป็นกลุ่มตามโปรเจกต์",
    pill2: "เปิดห้องคุยระดมความคิดพร้อมกัน",
    activeFeatureIdx: 1,
  },
  {
    t: 60.88,
    kicker: "AGENT-TO-AGENT",
    badge: "AUTOMATIC TASK HANDOFF",
    icon: "🔄",
    pill1: "บอทส่งงานต่อให้กันได้อัตโนมัติ",
    pill2: "พิมพ์ @mention ส่งต่อข้อมูลทันที",
    activeFeatureIdx: 2,
  },
  {
    t: 76.36,
    kicker: "ROUTINES & SCHEDULE",
    badge: "HERMES CRON AUTOMATION",
    icon: "⏰",
    pill1: "ตั้งงานประจำทำตามเวลาอัตโนมัติ",
    pill2: "สรุปอีเมลเช้า · เช็กข่าว · รายงานงาน",
    activeFeatureIdx: 3,
  },
  {
    t: 88.66,
    kicker: "AI WORKFORCE",
    badge: "PERSONAL AI ASSISTANTS",
    icon: "✨",
    pill1: "มีคนช่วยคิด · ช่วยเขียน · ช่วยตรวจ",
    pill2: "จัดระบบงานแบบทีมงานมือโปร",
    activeFeatureIdx: 4,
  },
  {
    t: 102.34,
    kicker: "SUMMARY & VALUE",
    badge: "FAST · SYSTEMATIC · REAL BUSINESS",
    icon: "🚀",
    pill1: "ทำงานเร็วขึ้นและแยกงานชัดเจน",
    pill2: "นำ AI มาใช้งานกับธุรกิจได้จริง",
    activeFeatureIdx: 4,
  },
];

const FEATURES = [
  { label: "Bot Roster", icon: "🤖" },
  { label: "Groups", icon: "👥" },
  { label: "Bot-to-Bot", icon: "🔄" },
  { label: "Routines", icon: "⏰" },
  { label: "Avatars", icon: "🎨" },
];

// ---- Camera Keyframes for Dynamic Zoom & Pan on Screen Recording -----------
interface CameraKeyframe {
  t: number;      // timestamp in seconds
  zoom: number;   // scale factor (1.4 - 2.2)
  panX: number;   // px offset X in container
  panY: number;   // px offset Y in container
}

const CAMERA_KEYFRAMES: CameraKeyframe[] = [
  // Focus peaks land exactly on beat starts (BEATS[i].t) so the tightest framing
  // coincides with each badge/pill switch; hold pairs let the camera settle on
  // the feature instead of drifting continuously.
  { t: 0.0,    zoom: 1.55, panX: 0,   panY: 100 },  // Beat 1: Intro & Hero Overview
  { t: 10.0,   zoom: 1.60, panX: 0,   panY: 80 },   // Pre-transition drift
  { t: 11.54,  zoom: 1.95, panX: 60,  panY: 40 },   // Beat 2 @ start: Bot Roster & Individual Bots (12-24s)
  { t: 18.0,   zoom: 2.05, panX: 50,  panY: 30 },   // Sustained micro-push on bot roles
  { t: 24.0,   zoom: 2.05, panX: 40,  panY: 20 },   // Hold focus on bot roles (code/write/summarize)
  { t: 33.0,   zoom: 1.90, panX: 20,  panY: 10 },   // Pull back before groups
  { t: 34.34,  zoom: 2.10, panX: -40, panY: -20 },  // Beat 3 @ start: Group Chats & Workspaces (35-58s)
  { t: 48.0,   zoom: 2.05, panX: -35, panY: -15 },  // Hold on workspace collaboration UI
  { t: 58.0,   zoom: 2.00, panX: -30, panY: -10 },  // Ease toward bot-to-bot
  { t: 60.88,  zoom: 2.15, panX: -20, panY: -50 },  // Beat 4 @ start: Bot-to-Bot Collaboration & Handoffs (61-74s)
  { t: 68.0,   zoom: 2.15, panX: -20, panY: -55 },  // Hold on handoff thread
  { t: 74.5,   zoom: 1.90, panX: 0,   panY: -30 },  // Pull back before routines
  { t: 76.36,  zoom: 1.95, panX: 40,  panY: -70 },  // Beat 5 @ start: Routines & Scheduled Automation / Cron (77-87s)
  { t: 82.0,   zoom: 1.95, panX: 35,  panY: -65 },  // Hold on cron schedule panel
  { t: 87.0,   zoom: 1.80, panX: 20,  panY: -40 },  // Ease out toward summary
  { t: 88.66,  zoom: 1.65, panX: 0,   panY: -10 },  // Beat 6 @ start: AI Workforce Summary
  { t: 102.34, zoom: 1.50, panX: 0,   panY: 30 },   // Beat 7 @ start: Summary & Business Value (89-118s)
  { t: 115.38, zoom: 1.45, panX: 0,   panY: 40 },   // Outro / Endcard settle
];

function getCameraTransform(t: number): { zoom: number; panX: number; panY: number } {
  if (t <= CAMERA_KEYFRAMES[0].t) {
    return CAMERA_KEYFRAMES[0];
  }
  const last = CAMERA_KEYFRAMES[CAMERA_KEYFRAMES.length - 1];
  if (t >= last.t) {
    return last;
  }

  // Find surrounding keyframes
  for (let i = 0; i < CAMERA_KEYFRAMES.length - 1; i++) {
    const kf1 = CAMERA_KEYFRAMES[i];
    const kf2 = CAMERA_KEYFRAMES[i + 1];
    if (t >= kf1.t && t <= kf2.t) {
      const progress = (t - kf1.t) / (kf2.t - kf1.t);
      // Smooth cosine interpolation
      const smoothProgress = (1 - Math.cos(progress * Math.PI)) / 2;
      return {
        zoom: kf1.zoom + (kf2.zoom - kf1.zoom) * smoothProgress,
        panX: kf1.panX + (kf2.panX - kf1.panX) * smoothProgress,
        panY: kf1.panY + (kf2.panY - kf1.panY) * smoothProgress,
      };
    }
  }

  return CAMERA_KEYFRAMES[0];
}

// ---- Presenter Crop & Placement -------------------------------------------
const CROP_TOP = 40;
const CROP_H = 1000;
const ZONE_H = 1000;
const SCALE = ZONE_H / CROP_H;
const VID_W = Math.round(720 * SCALE);
const VID_H = Math.round(1280 * SCALE);
const ZONE_Y = 1920 - ZONE_H; // 920px
const ZONE_X = Math.round((1080 - VID_W) / 2);

// ---- Font Loader ----------------------------------------------------------
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

// ---- Props & Metadata -----------------------------------------------------
export interface HermesBotReelProps {
  [key: string]: unknown;
  durationSec?: number;
}

export const calculateHermesBotMetadata: CalculateMetadataFunction<HermesBotReelProps> = ({
  props,
}) => {
  const fps = 30;
  const durationSec = props.durationSec || TOTAL_DURATION_SEC;
  return {
    durationInFrames: Math.ceil(durationSec * fps),
    fps,
    width: 720,
    height: 1280,
  };
};

// ---- Helper Springs & Interpolations --------------------------------------
const springIn = (frame: number, fps: number, damping = 16, stiffness = 120) =>
  spring({ frame, fps, config: { damping, stiffness } });

// ===========================================================================
// Sub-Components
// ===========================================================================

// Top Progress Bar
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
        height: 5,
        backgroundColor: "rgba(255,255,255,0.08)",
        zIndex: 50,
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

// Karaoke Caption Lane (Bottom Chest Overlay)
const isLatin = (s: string) => /^[A-Za-z0-9]/.test(s) || /[A-Za-z0-9]$/.test(s);

const CaptionLane: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  let pageIdx = -1;
  for (let i = 0; i < CAPTION_PAGES.length; i++) {
    const p = CAPTION_PAGES[i];
    if (t >= p.start) pageIdx = i;
  }

  if (pageIdx < 0 || t > VIDEO_END_SEC) return null;
  const page = CAPTION_PAGES[pageIdx];

  const enter = springIn(Math.max(0, Math.round((t - page.start) * fps)), fps, 18, 160);

  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 240,
        display: "flex",
        justifyContent: "center",
        pointerEvents: "none",
        zIndex: 40,
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          alignItems: "center",
          minWidth: 540,
          maxWidth: 920,
          background: "rgba(11, 15, 25, 0.82)",
          backdropFilter: "blur(16px)",
          WebkitBackdropFilter: "blur(16px)",
          border: `1.5px solid rgba(56, 189, 248, 0.35)`,
          borderRadius: 22,
          padding: "14px 32px",
          boxShadow: `0 8px 32px rgba(0,0,0,0.6), 0 0 20px rgba(56, 189, 248, 0.25)`,
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
            transform = "scale(1.08)";
          } else if (spoken) {
            color = WHITE;
            shadow = "0 2px 4px rgba(0,0,0,0.4)";
          }

          return (
            <span
              key={i}
              style={{
                fontFamily: FONT,
                fontSize: 38,
                fontWeight: active ? 800 : 700,
                color,
                textShadow: shadow,
                transform,
                transition: "all 0.1s ease-out",
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

// Feature Timeline Tracker
const FeatureTracker: React.FC<{ activeIdx: number }> = ({ activeIdx }) => {
  return (
    <div
      style={{
        position: "absolute",
        top: 740,
        left: 45,
        right: 45,
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        background: "rgba(15, 23, 42, 0.8)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        border: "1px solid rgba(255,255,255,0.12)",
        borderRadius: 16,
        padding: "8px 18px",
        boxShadow: "0 4px 20px rgba(0,0,0,0.4)",
        zIndex: 35,
      }}
    >
      {FEATURES.map((f, i) => {
        const isActive = i === activeIdx;
        return (
          <div
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "6px 14px",
              borderRadius: 12,
              background: isActive
                ? "linear-gradient(135deg, rgba(56,189,248,0.25), rgba(129,140,248,0.25))"
                : "transparent",
              border: isActive
                ? `1px solid ${CYAN}`
                : "1px solid transparent",
              boxShadow: isActive ? `0 0 14px rgba(56, 189, 248, 0.4)` : "none",
              transition: "all 0.3s ease",
            }}
          >
            <span style={{ fontSize: 20 }}>{f.icon}</span>
            <span
              style={{
                fontFamily: FONT,
                fontSize: 18,
                fontWeight: isActive ? 800 : 600,
                color: isActive ? CYAN : MUTE,
                letterSpacing: 0.5,
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

// Dynamic Floating Feature Pills
const FloatingPills: React.FC<{ pill1: string; pill2: string; frame: number; fps: number }> = ({
  pill1,
  pill2,
  frame,
  fps,
}) => {
  const enter = springIn(frame, fps, 14, 100);
  return (
    <div
      style={{
        position: "absolute",
        top: 815,
        left: 45,
        right: 45,
        display: "flex",
        gap: 16,
        justifyContent: "center",
        zIndex: 35,
        opacity: enter,
        transform: `translateY(${interpolate(enter, [0, 1], [15, 0])}px)`,
      }}
    >
      <div
        style={{
          flex: 1,
          background: "linear-gradient(135deg, rgba(56, 189, 248, 0.15), rgba(15, 23, 42, 0.85))",
          border: `1.5px solid ${CYAN}`,
          borderRadius: 14,
          padding: "10px 18px",
          display: "flex",
          alignItems: "center",
          gap: 10,
          boxShadow: `0 4px 16px rgba(0,0,0,0.5), 0 0 12px rgba(56, 189, 248, 0.25)`,
        }}
      >
        <div
          style={{
            width: 10,
            height: 10,
            borderRadius: "50%",
            backgroundColor: CYAN,
            boxShadow: `0 0 8px ${CYAN}`,
          }}
        />
        <span
          style={{
            fontFamily: FONT,
            fontSize: 20,
            fontWeight: 700,
            color: WHITE,
            lineHeight: 1.2,
          }}
        >
          {pill1}
        </span>
      </div>

      <div
        style={{
          flex: 1,
          background: "linear-gradient(135deg, rgba(245, 158, 11, 0.15), rgba(15, 23, 42, 0.85))",
          border: `1.5px solid ${GOLD}`,
          borderRadius: 14,
          padding: "10px 18px",
          display: "flex",
          alignItems: "center",
          gap: 10,
          boxShadow: `0 4px 16px rgba(0,0,0,0.5), 0 0 12px rgba(245, 158, 11, 0.25)`,
        }}
      >
        <div
          style={{
            width: 10,
            height: 10,
            borderRadius: "50%",
            backgroundColor: GOLD,
            boxShadow: `0 0 8px ${GOLD}`,
          }}
        />
        <span
          style={{
            fontFamily: FONT,
            fontSize: 20,
            fontWeight: 700,
            color: WHITE,
            lineHeight: 1.2,
          }}
        >
          {pill2}
        </span>
      </div>
    </div>
  );
};

// Endcard Card Component
const Endcard: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = springIn(frame, fps, 14, 90);

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        background: "rgba(10, 14, 23, 0.94)",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        zIndex: 100,
        opacity: pop,
      }}
    >
      <div
        style={{
          width: 900,
          background: "linear-gradient(180deg, rgba(24, 33, 54, 0.95), rgba(15, 23, 42, 0.98))",
          border: `2px solid ${CYAN}`,
          borderRadius: 28,
          padding: "48px 40px",
          boxShadow: `0 20px 60px rgba(0,0,0,0.8), 0 0 40px rgba(56, 189, 248, 0.4)`,
          textAlign: "center",
          transform: `scale(${interpolate(pop, [0, 1], [0.9, 1])})`,
        }}
      >
        <div
          style={{
            display: "inline-block",
            padding: "8px 24px",
            borderRadius: 999,
            background: "linear-gradient(135deg, #38BDF8, #818CF8)",
            color: "#0F172A",
            fontFamily: FONT,
            fontSize: 22,
            fontWeight: 800,
            marginBottom: 20,
            letterSpacing: 1,
            boxShadow: `0 4px 16px rgba(56, 189, 248, 0.5)`,
          }}
        >
          HERMES BOT MODE
        </div>

        <h1
          style={{
            fontFamily: FONT,
            fontSize: 48,
            fontWeight: 800,
            color: WHITE,
            margin: "0 0 16px 0",
            lineHeight: 1.25,
          }}
        >
          ทีมผู้ช่วย AI ประจำตัวของคุณ
        </h1>

        <p
          style={{
            fontFamily: FONT,
            fontSize: 26,
            fontWeight: 600,
            color: MUTE,
            margin: "0 0 36px 0",
            lineHeight: 1.5,
          }}
        >
          สร้างบอทหลายตัว · จัดกลุ่มทำงาน · ส่งต่องานอัตโนมัติ · ตั้งเวลาสั่งการ
        </p>

        <div
          style={{
            display: "flex",
            justifyContent: "center",
            gap: 20,
            marginBottom: 36,
          }}
        >
          {["⚡ ทำงานเร็วขึ้น", "🎯 แยกงานชัดเจน", "🏢 ใช้กับธุรกิจจริง"].map((t, idx) => (
            <div
              key={idx}
              style={{
                padding: "12px 20px",
                borderRadius: 14,
                background: "rgba(56, 189, 248, 0.12)",
                border: "1px solid rgba(56, 189, 248, 0.3)",
                color: CYAN,
                fontFamily: FONT,
                fontSize: 22,
                fontWeight: 700,
              }}
            >
              {t}
            </div>
          ))}
        </div>

        <div
          style={{
            display: "inline-block",
            padding: "16px 40px",
            borderRadius: 16,
            background: `linear-gradient(135deg, ${GOLD}, #EA580C)`,
            color: WHITE,
            fontFamily: FONT,
            fontSize: 26,
            fontWeight: 800,
            boxShadow: `0 8px 24px rgba(245, 158, 11, 0.45)`,
          }}
        >
          📦 Built into Hermes Desktop
        </div>
      </div>
    </div>
  );
};

// ===========================================================================
// Main Reel Component
// ===========================================================================
export const HermesBotReel: React.FC<HermesBotReelProps> = ({ durationSec = TOTAL_DURATION_SEC }) => {
  useThaiFonts();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const totalFrames = Math.ceil(durationSec * fps);

  // Active Beat Selection
  let currentBeat = BEATS[0];
  let beatStartFrame = 0;
  for (let i = 0; i < BEATS.length; i++) {
    if (t >= BEATS[i].t) {
      currentBeat = BEATS[i];
      beatStartFrame = Math.round(BEATS[i].t * fps);
    }
  }

  const beatLocalFrame = Math.max(0, frame - beatStartFrame);

  // Dynamic Camera Zoom & Pan on screen recording
  const camera = getCameraTransform(t);

  // Push-in Zoom on Presenter (subtle 1.00 -> 1.04)
  const presenterScale = interpolate(frame, [0, totalFrames], [1.0, 1.04], {
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        width: 720,
        height: 1280,
        backgroundColor: "#000000",
        overflow: "hidden",
      }}
    >
      {/* Design-Space Scale Wrapper (1080x1920 scaled to 720x1280) */}
      <div
        style={{
          width: 1080,
          height: 1920,
          transform: "scale(0.666667)",
          transformOrigin: "top left",
          position: "relative",
          backgroundColor: "#050811",
          overflow: "hidden",
        }}
      >
        <ProgressBar totalFrames={totalFrames} />

        {/* ================================================================= */}
        {/* TOP ZONE: Screen Walkthrough & UI Showcase Stage (0 - 920px)      */}
        {/* ================================================================= */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: 1080,
            height: ZONE_Y,
            background: "radial-gradient(ellipse at 50% 25%, rgba(56, 189, 248, 0.14), transparent 70%), #0A0F1D",
            overflow: "hidden",
            zIndex: 10,
          }}
        >
          {/* Header Bar */}
          <div
            style={{
              position: "absolute",
              top: 24,
              left: 45,
              right: 45,
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
                backdropFilter: "blur(10px)",
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
                  fontFamily: FONT,
                  fontSize: 18,
                  fontWeight: 800,
                  color: WHITE,
                  letterSpacing: 1,
                }}
              >
                NOUS RESEARCH · BOT MODE
              </span>
            </div>

            {/* Kicker Pill */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                background: "linear-gradient(135deg, rgba(56,189,248,0.2), rgba(129,140,248,0.2))",
                border: `1px solid ${CYAN}`,
                borderRadius: 999,
                padding: "8px 22px",
                boxShadow: `0 0 16px rgba(56, 189, 248, 0.35)`,
              }}
            >
              <span style={{ fontSize: 20, filter: "drop-shadow(0 1px 4px rgba(0,0,0,0.5))" }}>{currentBeat.icon}</span>
              <span
                style={{
                  fontFamily: FONT,
                  fontSize: 18,
                  fontWeight: 800,
                  color: CYAN,
                  letterSpacing: 0.5,
                  textShadow: "0 1px 8px rgba(0,0,0,0.6)",
                }}
              >
                {currentBeat.badge}
              </span>
            </div>
          </div>

          {/* Screen Recording Video in macOS Window Frame */}
          <div
            style={{
              position: "absolute",
              top: 80,
              left: 45,
              width: 990,
              height: 640,
              borderRadius: 22,
              overflow: "hidden",
              border: `2px solid rgba(56, 189, 248, 0.35)`,
              boxShadow: `0 16px 48px rgba(0,0,0,0.7), 0 0 30px rgba(56, 189, 248, 0.25)`,
              backgroundColor: "#0D1117",
              zIndex: 20,
            }}
          >
            {/* Window Titlebar */}
            <div
              style={{
                height: 38,
                background: "linear-gradient(180deg, #1E293B, #0F172A)",
                display: "flex",
                alignItems: "center",
                padding: "0 16px",
                borderBottom: "1px solid rgba(255,255,255,0.08)",
                position: "relative",
              }}
            >
              {/* Traffic Lights */}
              <div style={{ display: "flex", gap: 8 }}>
                <div style={{ width: 12, height: 12, borderRadius: "50%", backgroundColor: "#EF4444" }} />
                <div style={{ width: 12, height: 12, borderRadius: "50%", backgroundColor: "#F59E0B" }} />
                <div style={{ width: 12, height: 12, borderRadius: "50%", backgroundColor: "#10B981" }} />
              </div>

              {/* URL / Window Title */}
              <div
                style={{
                  position: "absolute",
                  left: 0,
                  right: 0,
                  textAlign: "center",
                  fontFamily: FONT,
                  fontSize: 14,
                  fontWeight: 600,
                  color: MUTE,
                  letterSpacing: 0.5,
                  pointerEvents: "none",
                }}
              >
                🔒 github.com/NousResearch/Hermes-Bot-Mode
              </div>
            </div>

            {/* Actual Screen Recording Walkthrough with Dynamic Camera Zoom & Pan */}
            <div
              style={{
                width: "100%",
                height: 602,
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
                  transform: `scale(${camera.zoom}) translate(${camera.panX}px, ${camera.panY}px)`,
                  transformOrigin: "center center",
                }}
              />
            </div>
          </div>

          {/* Feature Timeline Tracker */}
          <FeatureTracker activeIdx={currentBeat.activeFeatureIdx} />

          {/* Floating Action Pills */}
          <FloatingPills
            pill1={currentBeat.pill1}
            pill2={currentBeat.pill2}
            frame={beatLocalFrame}
            fps={fps}
          />
        </div>

        {/* ================================================================= */}
        {/* SEAM DIVIDER & BLEND BAND (At 920px)                               */}
        {/* ================================================================= */}
        <div
          style={{
            position: "absolute",
            top: ZONE_Y - 1,
            left: 0,
            width: 1080,
            height: 2,
            background: `linear-gradient(90deg, transparent, ${CYAN}, ${PURPLE}, transparent)`,
            boxShadow: `0 0 16px ${CYAN}`,
            zIndex: 45,
          }}
        />

        {/* Soft Radial Vignette Seam Blend */}
        <div
          style={{
            position: "absolute",
            top: ZONE_Y - 40,
            left: 0,
            width: 1080,
            height: 80,
            background: "linear-gradient(180deg, transparent, #000000 70%)",
            zIndex: 25,
            pointerEvents: "none",
          }}
        />

        {/* ================================================================= */}
        {/* BOTTOM ZONE: AI Presenter Avatar on Pure Black (920 - 1920px)    */}
        {/* ================================================================= */}
        <div
          style={{
            position: "absolute",
            top: ZONE_Y,
            left: 0,
            width: 1080,
            height: ZONE_H,
            backgroundColor: "#000000",
            overflow: "hidden",
            zIndex: 15,
          }}
        >
          <div
            style={{
              position: "absolute",
              top: -CROP_TOP * SCALE,
              left: ZONE_X,
              width: VID_W,
              height: VID_H,
              transform: `scale(${presenterScale})`,
              transformOrigin: "50% 30%",
            }}
          >
            <OffthreadVideo
              src={staticFile("hermes-bot-mode-reel/avatar_source.mp4")}
              style={{
                width: "100%",
                height: "100%",
                objectFit: "cover",
              }}
            />
          </div>

          {/* Left/Right Black Edge Maskers for Seamless Framing */}
          <div
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              width: ZONE_X,
              height: "100%",
              backgroundColor: "#000000",
            }}
          />
          <div
            style={{
              position: "absolute",
              top: 0,
              right: 0,
              width: ZONE_X,
              height: "100%",
              backgroundColor: "#000000",
            }}
          />
        </div>

        {/* Word-Synced Karaoke Subtitles Over Presenter */}
        <CaptionLane />

        {/* Verdict / Climax Endcard */}
        {t > VIDEO_END_SEC && <Endcard />}
      </div>
    </div>
  );
};
