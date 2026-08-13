import React, { useEffect, useState } from "react";
import {
  AbsoluteFill,
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
import { CAPTION_PAGES } from "./frangV5Captions";

// ===========================================================================
// TEMPLATE — SplitZoneReel (skill: Frang-vdo-half-v1-1.2x)
// Split-zone news reel: presenter half-body bottom on seamless black, b-roll +
// word-synced motion graphics top, side chips on result beats.
// Copy to <Name>Reel.tsx and edit every block marked "EDIT:".
// The root already wraps the 1080x1920 design space in a scale(2/3) wrapper —
// register the composition at width 720, height 1280 (the 720p rule).
// Render is SILENT — re-mux audio with the skill's finish.sh.
// ===========================================================================

// ---- design tokens --------------------------------------------------------
const ORANGE = "#FF9D4D"; // EDIT: subject/brand accent
const ORANGE2 = "#FFC37A";
const CYAN = "#6FE6FF";
const GREEN = "#7CE8A5"; // gpt
const VIOLET = "#B98CFF"; // fable
const RED = "#FF6B6B";
const WHITE = "#F4F7FC";
const MUTE = "#A9B6CC";
const GLASS = "rgba(11,14,21,0.46)";
const GLASS_HI = "rgba(15,19,28,0.66)";
const BORDER = "rgba(255,255,255,0.14)";
const FONT = '"KanitX","Kanit",system-ui,-apple-system,sans-serif';

// ---- EDIT: timing (seconds, from timing.json word alignment) ---------------
const BEATS = [0, 10.82, 12.8, 16.24, 35.38, 37.38, 53.38, 66.1, 82.02];
const VIDEO_END = 89.64; // presenter footage ends here
const END = 92.4; // + verdict endcard
const KICKERS = [
  "AI NEWS", "FACT CHECK", "FACT CHECK", "BENCHMARK", "RESULTS",
  "VS GPT-5.6 SOL", "VS FABLE 5", "AGENT TEST", "DEBUG TEST",
];
// b-roll schedule (time, image) — supports sub-beat splits so no stage sits frozen
const BROLL_SCHEDULE: [number, string][] = [
  [0, "b1_hook"], [10.82, "b2_lab"], [12.8, "b2_lab"], [16.24, "b4_arena"],
  [26.0, "b35_tests"], [35.38, "b5_verdict"], [37.38, "b6_gpu"], [53.38, "b7_duel"],
  [66.1, "b8_treasure"], [82.02, "b9_debug"],
];

const CLAIM_CUES = [
  { t: 5.84, text: "เทียบเท่า FRONTIER", icon: "🧠" },
  { t: 8.42, text: "ถูกกว่ามาก", icon: "💰" },
  { t: 9.54, text: "เร็วกว่ามาก", icon: "⚡" },
];
const MODEL_CUES = [
  { t: 18.14, name: "GROK 4.6", icon: "⚡", accent: ORANGE },
  { t: 19.77, name: "GPT-5.6 SOL", icon: "🟢", accent: GREEN },
  { t: 21.63, name: "FABLE 5", icon: "📗", accent: VIOLET },
];
const TEST_CUES = [
  { t: 25.64, icon: "🚂", label: "จำลองรถไฟ" },
  { t: 26.72, icon: "🍎", label: "สร้างเว็บ Apple ใหม่" },
  { t: 29.4, icon: "📇", label: "สกัดบัตรจากไฟล์" },
  { t: 31.42, icon: "🐛", label: "debug โค้ด" },
  { t: 33.32, icon: "🐤", label: "เกม Flappy Bird" },
];

// ---- EDIT: presenter crop geometry (sample frames first; source 720x1280) ---
const CROP_TOP = 60; // keep head margin
const CROP_H = 980; // cut at mid-torso (above clasped hands)
const ZONE_H = 1000; // presenter zone height on canvas
const SCALE = ZONE_H / CROP_H; // 1.0204
const VID_W = Math.round(720 * SCALE); // 735
const VID_H = Math.round(1280 * SCALE); // 1306
const ZONE_Y = 1920 - ZONE_H; // 920
const ZONE_X = Math.round((1080 - VID_W) / 2); // 172

// ---- font loading (local Kanit TTF, headless-safe) -------------------------
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

// ---- props -----------------------------------------------------------------
export interface FrangV5ReelProps {
  [key: string]: unknown;
  videoSrc: string;
  durationSec: number;
  assetDir?: string; // dir under remotion-composer/public/ holding the b-roll images
}
export const calculateFrangV5Metadata: CalculateMetadataFunction<FrangV5ReelProps> = ({ props }) => {
  const fps = 30;
  return {
    durationInFrames: Math.ceil((props.durationSec || END) * fps),
    fps,
    width: 720,   // 720p rule — design space 1080x1920 is scaled down by the root wrapper
    height: 1280,
  };
};

// ---- shared bits -----------------------------------------------------------
const GradientText: React.FC<{ children: React.ReactNode; from?: string; to?: string; glow?: string }> = ({
  children,
  from = ORANGE2,
  to = CYAN,
  glow = `${CYAN}66`,
}) => (
  <span
    style={{
      backgroundImage: `linear-gradient(90deg, ${from}, ${to})`,
      WebkitBackgroundClip: "text",
      backgroundClip: "text",
      WebkitTextFillColor: "transparent",
      filter: `drop-shadow(0 0 12px ${glow})`,
    }}
  >
    {children}
  </span>
);

const springIn = (frame: number, fps: number, damping = 18, stiffness = 110) =>
  spring({ frame, fps, config: { damping, stiffness } });

const fadeOut = (frame: number, total: number, tail = 10) =>
  interpolate(frame, [total - tail, total], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

// ---------------------------------------------------------------------------
// Karaoke caption lane — word-synced, bottom zone (the second info channel)
// ---------------------------------------------------------------------------
const isLatin = (s: string) => /^[A-Za-z0-9]/.test(s) || /[A-Za-z0-9]$/.test(s);
const captionTokens = (words: readonly { w: string; s: number; e: number }[]) => {
  // join Thai tokens without spaces; keep spaces around Latin/number tokens
  const out: { text: string; s: number; e: number }[] = [];
  words.forEach((w, i) => {
    const prev = i > 0 ? words[i - 1].w : "";
    const sep = i > 0 && (isLatin(prev) || isLatin(w.w)) ? " " : "";
    out.push({ text: sep + w.w, s: w.s, e: w.e });
  });
  return out;
};

const CaptionLane: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  let pageIdx = -1;
  for (let i = 0; i < CAPTION_PAGES.length; i++) {
    const p = CAPTION_PAGES[i];
    if (t >= p.start) pageIdx = i; // persist through speech gaps — the lane never blanks
  }
  if (pageIdx < 0 || t > VIDEO_END) return null;
  const page = CAPTION_PAGES[pageIdx];
  const enter = springIn(Math.max(0, Math.round((t - page.start) * fps)), fps, 18, 160);
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 260,
        display: "flex",
        justifyContent: "center",
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          minWidth: 560,
          maxWidth: 880,
          background: GLASS_HI,
          backdropFilter: "blur(10px)",
          WebkitBackdropFilter: "blur(10px)",
          border: `1px solid ${BORDER}`,
          borderRadius: 18,
          padding: "12px 28px",
          boxShadow: "0 14px 40px rgba(0,0,0,0.55)",
          opacity: enter,
          transform: `translateY(${interpolate(enter, [0, 1], [12, 0])}px)`,
        }}
      >
        {captionTokens(page.words).map((w, i) => {
          const active = t >= w.s && t < w.e;
          const spoken = t >= w.e;
          return (
            <span
              key={i}
              style={{
                fontFamily: FONT,
                fontWeight: 800,
                fontSize: 42,
                lineHeight: 1.35,
                whiteSpace: "pre",
                color: spoken ? WHITE : "rgba(244,247,252,0.45)",
                ...(active
                  ? {
                      backgroundImage: "linear-gradient(90deg, #FFD66B, #FF9D4D)",
                      WebkitBackgroundClip: "text",
                      backgroundClip: "text",
                      WebkitTextFillColor: "transparent",
                      filter: "drop-shadow(0 0 10px rgba(255,214,107,0.55))",
                    }
                  : {}),
              }}
            >
              {w.text}
            </span>
          );
        })}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Scoreboard — accumulating tally, bottom-left of presenter zone
// ---------------------------------------------------------------------------
const SCORE_TICKS = [43.07, 58.06, 72.85, 86.82]; // each confirmed win (round 3 lands on "6 เท่า")
const ROUND_ICONS = ["⏱", "💰", "📇", "🐛"]; // time vs GPT · cost vs Fable · agent · debug
const ROUND_ACTIVE = [3.35, 53.38, 66.1, 82.02]; // when each round starts being contested
const Scoreboard: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  if (t < 3.35) return null; // on screen from the cold-open's tail — the open loop
  let score = 0;
  for (const c of SCORE_TICKS) if (t >= c) score++;
  const sinceTick = score === 0 ? Math.round((t - 3.35) * fps) : Math.round((t - SCORE_TICKS[score - 1]) * fps);
  const punch = springIn(Math.max(0, sinceTick), fps, 12, 170);
  return (
    <div
      style={{
        position: "absolute",
        left: 60,
        top: 1000,
        display: "flex",
        alignItems: "center",
        gap: 14,
        background: GLASS_HI,
        backdropFilter: "blur(8px)",
        WebkitBackdropFilter: "blur(8px)",
        border: `1.5px solid ${score === 0 ? "rgba(255,255,255,0.22)" : `${ORANGE}66`}`,
        borderRadius: 16,
        padding: "12px 20px",
        boxShadow: score === 0 ? "0 12px 32px rgba(0,0,0,0.5)" : `0 12px 32px rgba(0,0,0,0.5), 0 0 18px ${ORANGE}2c`,
        transform: `scale(${interpolate(punch, [0, 1], [1.22, 1])})`,
        pointerEvents: "none",
      }}
    >
      <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 30, color: score === 0 ? MUTE : WHITE }}>
        GROK <span style={{ color: score === 0 ? MUTE : ORANGE2 }}>{score}/4</span>
      </span>
      {ROUND_ICONS.map((icon, i) => {
        const won = i < score;
        const active = !won && t >= ROUND_ACTIVE[i]; // currently being measured
        const justWon = i === score - 1 && sinceTick < Math.round(0.6 * fps);
        const slotPop = justWon ? springIn(Math.max(0, sinceTick), fps, 10, 200) : 1;
        const pulse = 0.55 + 0.45 * Math.sin(frame / 5);
        return (
          <span
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 52,
              height: 52,
              borderRadius: 14,
              fontSize: 28,
              background: won ? "rgba(255,157,77,0.20)" : active ? "rgba(111,230,255,0.12)" : "rgba(255,255,255,0.06)",
              border: `1.5px solid ${won ? ORANGE : active ? CYAN : "rgba(255,255,255,0.14)"}`,
              boxShadow: won ? `0 0 14px ${ORANGE}55` : active ? `0 0 ${8 + 10 * pulse}px ${CYAN}66` : "none",
              opacity: won ? 1 : active ? 0.7 + 0.3 * pulse : 0.4,
              filter: won || active ? "none" : "grayscale(0.8)",
              transform: `scale(${interpolate(slotPop, [0, 1], [1.35, 1])})`,
            }}
          >
            {icon}
          </span>
        );
      })}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Cold-open verdict card (0–3.35s) — the payoff IS the hook; the rest is proof
// ---------------------------------------------------------------------------
const ColdOpen: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const inn = springIn(frame, fps, 13, 110);
  const out = fadeOut(frame, durationInFrames, 10);
  const chips = springIn(Math.max(0, frame - Math.round(0.5 * fps)), fps, 13, 130);
  return (
    <AbsoluteFill style={{ justifyContent: "flex-start", alignItems: "center", pointerEvents: "none" }}>
      <div
        style={{
          marginTop: 300,
          textAlign: "center",
          fontFamily: FONT,
          opacity: Math.min(inn, out),
          transform: `scale(${interpolate(inn, [0, 1], [0.72, 1])})`,
        }}
      >
        <div style={{ fontSize: 70, fontWeight: 800, lineHeight: 1.15, maxWidth: 980, textShadow: "0 4px 20px rgba(0,0,0,0.8)" }}>
          🏆 <GradientText glow={`${ORANGE}88`}>GROK 4.6 เคลมชนะทุกรอบ</GradientText>
        </div>
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            gap: 20,
            marginTop: 26,
            opacity: chips,
            transform: `translateY(${interpolate(chips, [0, 1], [20, 0])}px)`,
          }}
        >
          <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 36, color: ORANGE2, background: GLASS_HI, border: `1.5px solid ${ORANGE}66`, borderRadius: 16, padding: "12px 26px", width: 430, textAlign: "center", boxSizing: "border-box", boxShadow: `0 0 20px ${ORANGE}33` }}>⚡ เร็วกว่า</span>
          <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 36, color: CYAN, background: GLASS_HI, border: `1.5px solid ${CYAN}66`, borderRadius: 16, padding: "12px 26px", width: 430, textAlign: "center", boxSizing: "border-box", boxShadow: `0 0 20px ${CYAN}33` }}>💰 ถูกกว่าแบบไม่น่าเชื่อ</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// Beat 2 filler — fact-check card (kills the 12.8–16.2s dead air)
// ---------------------------------------------------------------------------
const FactCheckCard: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const inn = springIn(frame, fps, 14, 110);
  const out = fadeOut(frame, durationInFrames, 8);
  return (
    <AbsoluteFill style={{ justifyContent: "flex-start", alignItems: "center", pointerEvents: "none" }}>
      <div
        style={{
          marginTop: 300,
          textAlign: "center",
          fontFamily: FONT,
          opacity: Math.min(inn, out),
          transform: `scale(${interpolate(inn, [0, 1], [0.75, 1])})`,
        }}
      >
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 18,
            background: GLASS_HI,
            backdropFilter: "blur(10px)",
            WebkitBackdropFilter: "blur(10px)",
            border: `1px solid ${BORDER}`,
            borderRadius: 22,
            padding: "24px 44px",
            boxShadow: `0 18px 50px rgba(0,0,0,0.55), 0 0 24px ${CYAN}22`,
          }}
        >
          <span style={{ fontSize: 52 }}>🔍</span>
          <div style={{ textAlign: "left" }}>
            <div style={{ fontWeight: 800, fontSize: 52, lineHeight: 1.1 }}>
              <GradientText from={CYAN} to={ORANGE2}>ผลทดสอบจริง</GradientText>
            </div>
            <div style={{ fontWeight: 700, fontSize: 30, color: MUTE, marginTop: 4 }}>ลองใช้งานจริง ทุกโจทย์ ไม่ใช่ตัวเลขอวด</div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// Climax flash — gold sweep when the tally hits 4/4
// ---------------------------------------------------------------------------
const ClimaxFlash: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const o = interpolate(frame, [0, Math.round(0.8 * fps)], [0.7, 0], { extrapolateRight: "clamp" });
  const burst = springIn(frame, fps, 11, 130);
  const burstOut = interpolate(frame, [Math.round(1.0 * fps), Math.round(1.45 * fps)], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const dim = interpolate(frame, [0, Math.round(0.25 * fps), Math.round(1.0 * fps), Math.round(1.45 * fps)], [0, 0.78, 0.78, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {/* clear the stage: darken everything behind the burst */}
      <AbsoluteFill style={{ opacity: dim, backgroundColor: "#04060A" }} />
      <AbsoluteFill
        style={{
          opacity: o,
          background: `radial-gradient(80% 50% at 50% 55%, ${ORANGE2}55 0%, ${ORANGE}22 45%, transparent 75%)`,
        }}
      />
      {/* the 4/4 resolution OWNS the stage — the open loop's payoff is an EVENT */}
      <div
        style={{
          position: "absolute",
          top: 370,
          left: 0,
          right: 0,
          textAlign: "center",
          fontFamily: FONT,
          fontWeight: 800,
          opacity: Math.min(burst, burstOut),
          transform: `scale(${interpolate(burst, [0, 1], [0.4, 1])}) rotate(${interpolate(burst, [0, 1], [-6, 0])}deg)`,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 26,
            fontSize: 240,
            lineHeight: 1.05,
            filter: "drop-shadow(0 0 34px rgba(255,157,77,0.65))",
          }}
        >
          <span>🏆</span>
          <GradientText glow={`${ORANGE}99`}>4/4!</GradientText>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// Verdict endcard — the reel gets an ending (89.64 → 92.4)
// ---------------------------------------------------------------------------
const VerdictEndcard: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inn = springIn(frame, fps, 15, 90);
  const chip = springIn(Math.max(0, frame - Math.round(0.35 * fps)), fps, 13, 120);
  const cta = springIn(Math.max(0, frame - Math.round(0.5 * fps)), fps, 14, 120);
  const bgZoom = interpolate(frame, [0, 84], [1, 1.14], { extrapolateRight: "clamp" });
  const ctaPulse = 1 + 0.035 * Math.sin(frame / 8);
  return (
    <AbsoluteFill style={{ backgroundColor: "#05070C", pointerEvents: "none" }}>
      <AbsoluteFill style={{ opacity: 0.5 * inn, transform: `scale(${bgZoom})` }}>
        <Img
          src={staticFile("frang-v5-reel/b5_verdict.png")}
          style={{ width: "100%", height: "100%", objectFit: "cover", filter: "brightness(0.55) saturate(1.1)" }}
        />
        <AbsoluteFill style={{ background: "radial-gradient(90% 60% at 50% 42%, transparent 0%, rgba(5,7,12,0.88) 78%)" }} />
      </AbsoluteFill>
      <div
        style={{
          position: "absolute",
          top: 620,
          left: 0,
          right: 0,
          textAlign: "center",
          fontFamily: FONT,
          opacity: inn,
          transform: `scale(${interpolate(inn, [0, 1], [0.82, 1])})`,
        }}
      >
        <div style={{ fontSize: 120, fontWeight: 800, letterSpacing: 2, lineHeight: 1.05 }}>
          <GradientText glow={`${ORANGE}77`}>GROK 4.6</GradientText>
        </div>
        <div style={{ fontSize: 62, fontWeight: 800, color: WHITE, marginTop: 10, textShadow: "0 3px 14px rgba(0,0,0,0.8)" }}>
          🏆 ชนะครบ 4/4 รอบ
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          top: 965,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          gap: 22,
          opacity: chip,
          transform: `translateY(${interpolate(chip, [0, 1], [24, 0])}px)`,
        }}
      >
        <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 40, color: ORANGE2, background: GLASS_HI, border: `1.5px solid ${ORANGE}66`, borderRadius: 16, padding: "14px 30px", width: 430, textAlign: "center", boxSizing: "border-box", boxShadow: `0 0 22px ${ORANGE}33` }}>⚡ เร็วกว่าทุกรอบ</span>
        <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 40, color: CYAN, background: GLASS_HI, border: `1.5px solid ${CYAN}66`, borderRadius: 16, padding: "14px 30px", width: 430, textAlign: "center", boxSizing: "border-box", boxShadow: `0 0 22px ${CYAN}33` }}>💰 ถูกกว่าสูงสุด 10×</span>
      </div>
      <div
        style={{
          position: "absolute",
          top: 1130,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          opacity: cta,
          transform: `scale(${ctaPulse})`,
        }}
      >
        <span
          style={{
            fontFamily: FONT,
            fontWeight: 800,
            fontSize: 40,
            color: WHITE,
            background: GLASS_HI,
            border: `1.5px solid ${ORANGE}88`,
            borderRadius: 999,
            padding: "14px 38px",
            boxShadow: `0 0 26px ${ORANGE}44`,
          }}
        >
          กดติดตาม เพื่อไม่พลาดข่าว AI ถัดไป 🔔
        </span>
      </div>
      <div
        style={{
          position: "absolute",
          top: 1260,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          gap: 12,
          opacity: cta,
        }}
      >
        {ROUND_ICONS.map((icon, i) => (
          <span
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 56,
              height: 56,
              borderRadius: 15,
              fontSize: 30,
              background: "rgba(255,157,77,0.20)",
              border: `1.5px solid ${ORANGE}`,
              boxShadow: `0 0 14px ${ORANGE}55`,
            }}
          >
            {icon}
          </span>
        ))}
        <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 38, color: WHITE, marginLeft: 8 }}>
          GROK <span style={{ color: ORANGE2 }}>4/4</span>
        </span>
      </div>
      <div
        style={{
          position: "absolute",
          top: 1360,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          gap: 12,
          opacity: cta,
        }}
      >
        <span style={{ width: 10, height: 10, borderRadius: 5, background: ORANGE, boxShadow: `0 0 10px ${ORANGE}` }} />
        <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 36, letterSpacing: 3, color: MUTE }}>ฟรัง&nbsp;&nbsp;AI NEWS</span>
      </div>
    </AbsoluteFill>
  );
};
const Presenter: React.FC<{ src: string }> = ({ src }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  // slow cinematic push-in (1.00 → 1.05) so the presenter never reads as a frozen cutout
  const push = interpolate(frame, [0, durationInFrames], [1, 1.05], { extrapolateRight: "clamp" });
  return (
    <div
      style={{
        position: "absolute",
        left: ZONE_X,
        top: ZONE_Y,
        width: VID_W,
        height: ZONE_H,
        overflow: "hidden",
        backgroundColor: "#000",
      }}
    >
      <OffthreadVideo
        src={src}
        muted
        style={{
          width: VID_W,
          height: VID_H,
          marginTop: -Math.round(CROP_TOP * SCALE),
          objectFit: "fill",
          transform: `scale(${push})`,
          transformOrigin: "center top",
        }}
      />
    </div>
  );
};

// ---------------------------------------------------------------------------
// Top zone — b-roll with slow Ken Burns + crossfade + scrims + neon divider
// ---------------------------------------------------------------------------
const BrollLayer: React.FC<{ assetDir: string }> = ({ assetDir }) => {
  const { fps } = useVideoConfig();
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 960, overflow: "hidden", backgroundColor: "#000" }}>
      {BROLL_SCHEDULE.map(([s, name], i) => {
        const e = i + 1 < BROLL_SCHEDULE.length ? BROLL_SCHEDULE[i + 1][0] : END;
        const from = Math.round(s * fps);
        const dur = Math.max(1, Math.round((e - s) * fps));
        return (
          <Sequence key={i} from={from} durationInFrames={dur}>
            <BrollShot name={name} durFrames={dur} assetDir={assetDir} />
          </Sequence>
        );
      })}
      {/* scrims: top for bug bar, bottom fade into presenter black */}
      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(6,8,13,0.62) 0%, rgba(6,8,13,0) 20%)" }} />
      <AbsoluteFill style={{ background: "linear-gradient(0deg, #000 0%, rgba(0,0,0,0.85) 7%, rgba(0,0,0,0) 32%)" }} />
      {/* neon divider at the seam */}
      <div
        style={{
          position: "absolute",
          top: 916,
          left: 60,
          right: 60,
          height: 3,
          background: `linear-gradient(90deg, transparent, ${ORANGE}66, ${CYAN}66, transparent)`,
          boxShadow: `0 0 14px ${CYAN}55`,
        }}
      />
    </div>
  );
};

const BrollShot: React.FC<{ name: string; durFrames: number; assetDir: string }> = ({ name, durFrames, assetDir }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const zoom = interpolate(frame, [0, durFrames], [1.02, 1.12]);
  const drift = interpolate(frame, [0, durFrames], [0, -14]);
  const inn = interpolate(frame, [0, Math.round(0.45 * fps)], [0, 1], { extrapolateRight: "clamp" });
  const out = fadeOut(frame, durFrames, Math.round(0.4 * fps));
  return (
    <AbsoluteFill style={{ opacity: Math.min(inn, out) }}>
      <Img
        src={staticFile(`${assetDir}/${name}.png`)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `scale(${zoom}) translateY(${drift}px)`,
          filter: "brightness(0.62) saturate(1.08)",
        }}
      />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// Frame polish — vignette glows + hairline safe frame
// ---------------------------------------------------------------------------
const FramePolish: React.FC = () => {
  const frame = useCurrentFrame();
  const breathe = 0.5 + 0.5 * Math.sin(frame / 34);
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <AbsoluteFill
        style={{
          background: `radial-gradient(120% 55% at -8% -6%, ${ORANGE}1c 0%, transparent 42%), radial-gradient(120% 55% at 108% -4%, ${CYAN}18 0%, transparent 42%)`,
          opacity: 0.65 + 0.35 * breathe,
        }}
      />
      <AbsoluteFill style={{ margin: 22, border: "1.5px solid rgba(255,255,255,0.07)", borderRadius: 30 }} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// Top bug bar — live dot + per-beat kicker + brand tag
// ---------------------------------------------------------------------------
const TopBugBar: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const intro = springIn(frame, fps, 20, 90);
  const pulse = 0.55 + 0.45 * Math.sin(frame / 7);
  return (
    <div
      style={{
        position: "absolute",
        top: 52,
        left: 44,
        right: 44,
        height: 70,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        opacity: intro,
        transform: `translateY(${interpolate(intro, [0, 1], [-24, 0])}px)`,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div
          style={{
            width: 14,
            height: 14,
            borderRadius: 7,
            background: ORANGE,
            boxShadow: `0 0 ${10 + 10 * pulse}px ${ORANGE}, 0 0 4px ${ORANGE}`,
            opacity: 0.7 + 0.3 * pulse,
          }}
        />
        <KickerSlot />
      </div>
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 27, letterSpacing: 1.5 }}>
        <GradientText>GROK&nbsp;4.6</GradientText>
      </div>
    </div>
  );
};

const KickerSlot: React.FC = () => {
  const { fps } = useVideoConfig();
  const t = useCurrentFrame() / fps;
  let idx = 0;
  for (let i = 0; i < BEATS.length; i++) if (t >= BEATS[i]) idx = i;
  return (
    <span
      style={{
        fontFamily: FONT,
        fontWeight: 800,
        fontSize: 26,
        letterSpacing: 3,
        color: WHITE,
        textShadow: "0 2px 8px rgba(0,0,0,0.6)",
      }}
    >
      {KICKERS[idx]}
    </span>
  );
};

// ---------------------------------------------------------------------------
// B1 — headline + claim chips
// ---------------------------------------------------------------------------
const BeatHook: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const t = frame / fps;
  const inn = springIn(Math.max(0, frame - Math.round(3.2 * fps)), fps, 16, 90);
  const out = fadeOut(frame, durationInFrames, 9);
  return (
    <AbsoluteFill style={{ opacity: Math.min(inn, out), pointerEvents: "none" }}>
      {/* headline */}
      <div
        style={{
          position: "absolute",
          top: 210,
          left: 0,
          right: 0,
          textAlign: "center",
          fontFamily: FONT,
          fontWeight: 800,
          transform: `scale(${interpolate(inn, [0, 1], [0.86, 1])})`,
        }}
      >
        <div style={{ fontSize: 118, letterSpacing: 2, lineHeight: 1.05 }}>
          <GradientText glow={`${ORANGE}77`}>GROK 4.6</GradientText>
        </div>
        <div style={{ fontSize: 44, fontWeight: 700, color: WHITE, marginTop: 6, textShadow: "0 2px 10px rgba(0,0,0,0.7)" }}>
          เปิดตัวอย่างเป็นทางการ
        </div>
      </div>
      {/* claim chips */}
      <div style={{ position: "absolute", top: 610, left: 0, right: 0, display: "flex", flexDirection: "column", alignItems: "center", gap: 26 }}>
        {CLAIM_CUES.map((c, i) => {
          const local = t >= c.t ? Math.round((t - c.t) * fps) : -1;
          if (local < 0) return null;
          const pop = springIn(local, fps, 14, 150);
          return (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 16,
                background: GLASS_HI,
                backdropFilter: "blur(10px)",
                WebkitBackdropFilter: "blur(10px)",
                border: `1px solid ${BORDER}`,
                borderRadius: 18,
                padding: "16px 34px",
                boxShadow: `0 14px 40px rgba(0,0,0,0.45), 0 0 20px ${ORANGE}22`,
                opacity: pop,
                transform: `translateY(${interpolate(pop, [0, 1], [22, 0])}px) scale(${interpolate(pop, [0, 1], [0.9, 1])})`,
              }}
            >
              <span style={{ fontSize: 36 }}>{c.icon}</span>
              <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 40, color: WHITE }}>{c.text}</span>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// B2/B5 — giant kinetic line
// ---------------------------------------------------------------------------
const GiantLine: React.FC<{ text: string; sub?: string }> = ({ text, sub }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const inn = springIn(frame, fps, 13, 100);
  const out = fadeOut(frame, durationInFrames, 8);
  return (
    <AbsoluteFill style={{ justifyContent: "flex-start", alignItems: "center", pointerEvents: "none" }}>
      <div
        style={{
          marginTop: 330,
          textAlign: "center",
          fontFamily: FONT,
          fontWeight: 800,
          padding: "34px 70px",
          borderRadius: 34,
          background: "radial-gradient(72% 100% at 50% 50%, rgba(4,6,10,0.85) 0%, rgba(4,6,10,0) 100%)",
          opacity: Math.min(inn, out),
          transform: `scale(${interpolate(inn, [0, 1], [0.7, 1])})`,
        }}
      >
        <div style={{ fontSize: 96, lineHeight: 1.12, textShadow: "0 4px 18px rgba(0,0,0,0.75)" }}>
          <GradientText>{text}</GradientText>
        </div>
        {sub && (
          <div style={{ fontSize: 42, fontWeight: 700, color: MUTE, marginTop: 14 }}>{sub}</div>
        )}
      </div>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// B3 — presenter name tag at the seam
// ---------------------------------------------------------------------------
const NameTag: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const inn = springIn(frame, fps, 18, 100);
  const out = fadeOut(frame, durationInFrames, 10);
  return (
    <div
      style={{
        position: "absolute",
        right: 60,
        top: 990,
        display: "flex",
        alignItems: "center",
        gap: 14,
        background: GLASS_HI,
        backdropFilter: "blur(10px)",
        WebkitBackdropFilter: "blur(10px)",
        border: `1px solid ${BORDER}`,
        borderLeft: `6px solid ${ORANGE}`,
        borderRadius: 16,
        padding: "14px 26px",
        boxShadow: "0 14px 40px rgba(0,0,0,0.5)",
        opacity: Math.min(inn, out),
        transform: `translateX(${interpolate(inn, [0, 1], [30, 0])}px)`,
      }}
    >
      <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 38, color: WHITE }}>ฟรัง</span>
      <span style={{ fontFamily: FONT, fontWeight: 700, fontSize: 26, letterSpacing: 2, color: ORANGE2 }}>AI NEWS</span>
    </div>
  );
};

// ---------------------------------------------------------------------------
// B4 — model chips + 5-test cycler
// ---------------------------------------------------------------------------
const BeatBenchmark: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const tAbs = BEATS[3] + frame / fps;
  const out = fadeOut(frame, durationInFrames, 8);
  return (
    <AbsoluteFill style={{ opacity: out, pointerEvents: "none" }}>
      {/* model chips row */}
      <div style={{ position: "absolute", top: 190, left: 0, right: 0, display: "flex", justifyContent: "center", gap: 20 }}>
        {MODEL_CUES.map((m, i) => {
          const local = tAbs >= m.t ? Math.round((tAbs - m.t) * fps) : -1;
          if (local < 0) return null;
          const pop = springIn(local, fps, 13, 140);
          return (
            <div
              key={i}
              style={{
                background: GLASS_HI,
                border: `1.5px solid ${m.accent}55`,
                borderRadius: 18,
                padding: "16px 24px",
                display: "flex",
                alignItems: "center",
                gap: 10,
                boxShadow: `0 14px 36px rgba(0,0,0,0.5), 0 0 18px ${m.accent}33`,
                opacity: pop,
                transform: `scale(${interpolate(pop, [0, 1], [0.7, 1])})`,
              }}
            >
              <span style={{ fontSize: 30 }}>{m.icon}</span>
              <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 31, color: m.accent }}>{m.name}</span>
            </div>
          );
        })}
      </div>
      {/* 5-test cycler */}
      <TestCycler tAbs={tAbs} />
    </AbsoluteFill>
  );
};

const TestCycler: React.FC<{ tAbs: number }> = ({ tAbs }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const labelCue = 23.05;
  let idx = -1;
  for (let i = 0; i < TEST_CUES.length; i++) if (tAbs >= TEST_CUES[i].t) idx = i;
  const labelLocal = tAbs >= labelCue ? Math.round((tAbs - labelCue) * fps) : -1;
  return (
    <div style={{ position: "absolute", top: 430, left: 0, right: 0, display: "flex", flexDirection: "column", alignItems: "center", gap: 22 }}>
      {labelLocal >= 0 && (
        <div
          style={{
            fontFamily: FONT,
            fontWeight: 800,
            fontSize: 42,
            color: WHITE,
            background: GLASS_HI,
            backdropFilter: "blur(8px)",
            WebkitBackdropFilter: "blur(8px)",
            border: `1px solid ${BORDER}`,
            borderRadius: 16,
            padding: "10px 30px",
            boxShadow: "0 12px 32px rgba(0,0,0,0.5)",
            opacity: springIn(labelLocal, fps, 16, 120),
          }}
        >
          <GradientText from={CYAN} to={ORANGE2}>5 การทดสอบ</GradientText>
          <span style={{ fontFamily: FONT, fontWeight: 700, fontSize: 28, color: MUTE }}>&nbsp; → ชี้ขาด 4 รอบ</span>
        </div>
      )}
      {idx >= 0 && (
        <>
          <div style={{ display: "flex", gap: 12 }}>
            {TEST_CUES.map((c, i) => (
              <div
                key={i}
                style={{
                  width: 62,
                  height: 62,
                  borderRadius: 16,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 32,
                  background: GLASS_HI,
                  border: i === idx ? `1.5px solid ${CYAN}` : `1px solid ${BORDER}`,
                  boxShadow: i === idx ? `0 0 16px ${CYAN}66` : "none",
                  opacity: i <= idx ? 1 : 0.28,
                }}
              >
                {c.icon}
              </div>
            ))}
          </div>
          <TestChip key={idx} icon={TEST_CUES[idx].icon} label={TEST_CUES[idx].label} sinceMs={(tAbs - TEST_CUES[idx].t) * 1000} />
        </>
      )}
    </div>
  );
};

const TestChip: React.FC<{ icon: string; label: string; sinceMs: number }> = ({ icon, label, sinceMs }) => {
  const { fps } = useVideoConfig();
  const pop = springIn(Math.max(0, Math.round((sinceMs / 1000) * fps)), fps, 14, 150);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 18,
        background: GLASS_HI,
        backdropFilter: "blur(10px)",
        WebkitBackdropFilter: "blur(10px)",
        border: `1px solid ${BORDER}`,
        borderRadius: 20,
        padding: "20px 40px",
        boxShadow: `0 16px 44px rgba(0,0,0,0.5), 0 0 22px ${CYAN}22`,
        transform: `scale(${interpolate(pop, [0, 1], [0.8, 1])})`,
        opacity: pop,
      }}
    >
      <span style={{ fontSize: 52 }}>{icon}</span>
      <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 44, color: WHITE }}>{label}</span>
    </div>
  );
};

// ---------------------------------------------------------------------------
// VS card (B6/B7) — header, winner badge, animated content rows
// ---------------------------------------------------------------------------
const VsCard: React.FC<{
  right: string;
  rightAccent: string;
  winnerCue: number;
  winnerText: string;
  beatStart: number;
  children: React.ReactNode;
}> = ({ right, rightAccent, winnerCue, winnerText, beatStart, children }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const tAbs = beatStart + frame / fps;
  const inn = springIn(frame, fps, 17, 100);
  const out = fadeOut(frame, durationInFrames, 9);
  const wLocal = tAbs >= winnerCue ? Math.round((tAbs - winnerCue) * fps) : -1;
  return (
    <div
      style={{
        position: "absolute",
        top: 180,
        left: 74,
        right: 74,
        background: GLASS,
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        border: `1px solid ${BORDER}`,
        borderRadius: 26,
        padding: "30px 38px 34px",
        boxShadow: "0 22px 60px rgba(0,0,0,0.55)",
        opacity: Math.min(inn, out),
        transform: `translateY(${interpolate(inn, [0, 1], [30, 0])}px)`,
        pointerEvents: "none",
      }}
    >
      {/* header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 22 }}>
        <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 44, color: ORANGE, textShadow: `0 0 16px ${ORANGE}66` }}>GROK 4.6</span>
        <span
          style={{
            fontFamily: FONT,
            fontWeight: 800,
            fontSize: 26,
            color: "#0B0E15",
            background: `linear-gradient(90deg, ${ORANGE2}, ${CYAN})`,
            borderRadius: 10,
            padding: "4px 14px",
          }}
        >
          VS
        </span>
        <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 44, color: rightAccent, textShadow: `0 0 16px ${rightAccent}55` }}>{right}</span>
      </div>
      {/* winner badge */}
      {wLocal >= 0 && (
        <div style={{ display: "flex", justifyContent: "center", marginTop: 20 }}>
          <div
            style={{
              fontFamily: FONT,
              fontWeight: 800,
              fontSize: 38,
              color: WHITE,
              background: "rgba(255,157,77,0.14)",
              border: `1.5px solid ${ORANGE}66`,
              borderRadius: 16,
              padding: "10px 28px",
              boxShadow: `0 0 24px ${ORANGE}33`,
              opacity: springIn(wLocal, fps, 13, 140),
              transform: `scale(${interpolate(springIn(wLocal, fps, 13, 140), [0, 1], [0.75, 1])})`,
            }}
          >
            🏆 {winnerText}
          </div>
        </div>
      )}
      {children}
    </div>
  );
};

// animated bar row (B6 time comparison)
const BarRow: React.FC<{
  label: string;
  valueText: string;
  ratio: number; // 0..1 of full width
  accent: string;
  cueLocal: number; // frames since cue (negative = ghost track, not yet revealed)
  dim?: boolean; // losing bar — never let the loser outshine the winner
}> = ({ label, valueText, ratio, accent, cueLocal, dim = false }) => {
  const { fps } = useVideoConfig();
  const frame = useCurrentFrame();
  const live = cueLocal >= 0;
  const grow = springIn(Math.max(0, cueLocal), fps, 20, 60);
  const shimmerX = (frame * 6) % 400 - 100; // "กำลังวัดผล" sweep on pending tracks
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16, marginTop: 18, opacity: live ? (dim ? 0.62 : 1) : 0.6 }}>
      <div style={{ width: 250, textAlign: "right", fontFamily: FONT, fontWeight: 800, fontSize: 32, color: accent }}>{label}</div>
      <div style={{ flex: 1, position: "relative", height: 44, background: "rgba(255,255,255,0.07)", borderRadius: 12, overflow: "hidden" }}>
        {!live && (
          <>
            <div
              style={{
                position: "absolute",
                top: 0,
                bottom: 0,
                left: shimmerX,
                width: 100,
                background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.13), transparent)",
              }}
            />
            <div
              style={{
                position: "absolute",
                inset: 0,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontFamily: FONT,
                fontWeight: 700,
                fontSize: 22,
                letterSpacing: 1,
                color: `rgba(244,247,252,${0.45 + 0.25 * Math.sin(frame / 6)})`,
              }}
            >
              กำลังวัดผล…
            </div>
          </>
        )}
        <div
          style={{
            width: `${ratio * grow * 100}%`,
            height: "100%",
            borderRadius: 12,
            background: `linear-gradient(90deg, ${accent}bb, ${accent})`,
            boxShadow: dim ? "none" : `0 0 22px ${accent}88`,
            filter: dim ? "saturate(0.55) brightness(0.8)" : "none",
          }}
        />
      </div>
      <div style={{ width: 190, fontFamily: FONT, fontWeight: 800, fontSize: 44, color: WHITE }}>{live ? valueText : "—"}</div>
    </div>
  );
};

// big rolling counter
const BigStat: React.FC<{ big: string; label: string; accent?: string; to?: string; cueLocal: number; size?: number }> = ({
  big,
  label,
  accent = ORANGE2,
  to = CYAN,
  cueLocal,
  size = 120,
}) => {
  const { fps } = useVideoConfig();
  const pop = springIn(Math.max(0, cueLocal), fps, 12, 120);
  return (
    <div style={{ textAlign: "center", opacity: pop, transform: `scale(${interpolate(pop, [0, 1], [0.6, 1])})` }}>
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: size, lineHeight: 1.05 }}>
        <GradientText from={accent} to={to}>{big}</GradientText>
      </div>
      <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 36, color: WHITE, marginTop: 2, textShadow: "0 2px 12px rgba(0,0,0,0.85)" }}>{label}</div>
    </div>
  );
};

const BeatVsGpt: React.FC = () => {
  const { fps } = useVideoConfig();
  const tAbs = BEATS[5] + useCurrentFrame() / fps;
  const barsLocal = tAbs >= 45.37 ? Math.round((tAbs - 45.37) * fps) : -1;
  const costLocal = tAbs >= 51.68 ? Math.round((tAbs - 51.68) * fps) : -1;
  return (
    <VsCard right="GPT-5.6 SOL" rightAccent={GREEN} winnerCue={43.07} winnerText="GROK ชนะคะแนนรวม" beatStart={BEATS[5]}>
      <div style={{ marginTop: 24 }}>
        <div style={{ textAlign: "center", fontFamily: FONT, fontWeight: 700, fontSize: 26, color: MUTE, marginBottom: 6 }}>
          ⏱ เวลาที่ใช้ — น้อยกว่า = ชนะ
        </div>
        <BarRow label="GROK 4.6" valueText="18 นาที ✓" ratio={18 / 24} accent={ORANGE} cueLocal={barsLocal} />
        <BarRow label="GPT-5.6 SOL" valueText="24 นาที" ratio={1} accent={GREEN} cueLocal={barsLocal - 8} dim />
      </div>
      {costLocal >= 0 && (
        <div style={{ display: "flex", justifyContent: "center", marginTop: 26 }}>
          <BigStat big="≈3×" label="ถูกกว่า" cueLocal={costLocal} size={96} />
        </div>
      )}
    </VsCard>
  );
};

const BeatVsFable: React.FC = () => {
  const { fps } = useVideoConfig();
  const tAbs = BEATS[6] + useCurrentFrame() / fps;
  const costLocal = tAbs >= 61.63 ? Math.round((tAbs - 61.63) * fps) : -1;
  const speedLocal = tAbs >= 63.4 ? Math.round((tAbs - 63.4) * fps) : -1;
  return (
    <VsCard right="FABLE 5" rightAccent={VIOLET} winnerCue={58.06} winnerText="GROK ชนะเช่นกัน" beatStart={BEATS[6]}>
      {costLocal >= 0 && (
        <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 60, marginTop: 10 }}>
          <BigStat big="10×" label="ถูกกว่า" cueLocal={costLocal} size={210} />
          {speedLocal >= 0 && <BigStat big="+1 นาที" label="เร็วกว่า" cueLocal={speedLocal} size={104} />}
        </div>
      )}
    </VsCard>
  );
};

// ---------------------------------------------------------------------------
// B8 — agent test: twin counters + checklist
// ---------------------------------------------------------------------------
const BeatAgent: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const tAbs = BEATS[7] + frame / fps;
  const inn = springIn(frame, fps, 17, 100);
  const out = fadeOut(frame, durationInFrames, 9);
  const speedLocal = tAbs >= 72.68 ? Math.round((tAbs - 72.68) * fps) : -1;
  const costLocal = tAbs >= 75.32 ? Math.round((tAbs - 75.32) * fps) : -1;
  const missLocal = tAbs >= 77.18 ? Math.round((tAbs - 77.18) * fps) : -1;
  const foundLocal = tAbs >= 80.02 ? Math.round((tAbs - 80.02) * fps) : -1;
  return (
    <AbsoluteFill style={{ opacity: Math.min(inn, out), pointerEvents: "none" }}>
      <div style={{ position: "absolute", top: 175, left: 0, right: 0, textAlign: "center", fontFamily: FONT }}>
        <div style={{ fontSize: 58, fontWeight: 800, color: WHITE, textShadow: "0 2px 12px rgba(0,0,0,0.7)" }}>
          📇 สกัดบัตรจากไฟล์หลายประเภท
        </div>
      </div>
      <div style={{ position: "absolute", top: 290, left: 0, right: 0, display: "flex", justifyContent: "center", gap: 90 }}>
        {speedLocal >= 0 && <BigStat big="6×" label="⚡ เร็วกว่า GPT" cueLocal={speedLocal} accent="#FFB35C" to={ORANGE} size={150} />}
        {costLocal >= 0 && <BigStat big="6×" label="💰 ต้นทุนน้อยกว่า" cueLocal={costLocal} accent="#5CD8FF" to="#3D9BFF" size={150} />}
      </div>
      <div style={{ position: "absolute", top: 590, left: 0, right: 0, display: "flex", flexDirection: "column", alignItems: "center", gap: 16 }}>
        {missLocal >= 0 && <CheckRow ok={false} text="GPT — หาไม่เจอ 2 รายการ" cueLocal={missLocal} />}
        {foundLocal >= 0 && <CheckRow ok text="GROK — หาเจอครบทุกรายการ" cueLocal={foundLocal} />}
      </div>
    </AbsoluteFill>
  );
};

const CheckRow: React.FC<{ ok: boolean; text: string; cueLocal: number }> = ({ ok, text, cueLocal }) => {
  const { fps } = useVideoConfig();
  const pop = springIn(Math.max(0, cueLocal), fps, 14, 140);
  const accent = ok ? GREEN : RED;
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        width: 740,
        background: GLASS_HI,
        border: `1.5px solid ${accent}55`,
        borderRadius: 18,
        padding: "16px 34px",
        boxShadow: `0 14px 40px rgba(0,0,0,0.5), 0 0 18px ${accent}2e`,
        opacity: pop,
        transform: `translateX(${interpolate(pop, [0, 1], [ok ? 30 : -30, 0])}px)`,
      }}
    >
      <span
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          width: 46,
          height: 46,
          borderRadius: 23,
          flexShrink: 0,
          background: `${accent}1e`,
          border: `1.5px solid ${accent}`,
          color: accent,
          fontSize: 27,
          fontWeight: 800,
          fontFamily: FONT,
        }}
      >
        {ok ? "✓" : "✕"}
      </span>
      <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 38, color: WHITE }}>{text}</span>
    </div>
  );
};

// ---------------------------------------------------------------------------
// B9 — debug: bug counter + verdict chips
// ---------------------------------------------------------------------------
const BeatDebug: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const tAbs = BEATS[8] + frame / fps;
  const inn = springIn(frame, fps, 17, 100);
  const out = fadeOut(frame, durationInFrames, 8);
  const bugLocal = tAbs >= 85.23 ? Math.round((tAbs - 85.23) * fps) : -1;
  const fastLocal = tAbs >= 86.82 ? Math.round((tAbs - 86.82) * fps) : -1;
  const cheapLocal = tAbs >= 88.1 ? Math.round((tAbs - 88.1) * fps) : -1;
  // duck the whole beat while the 4/4 burst owns the stage
  const dip = interpolate(tAbs, [86.82, 87.1, 87.9, 88.2], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ opacity: Math.min(inn, out) * (1 - dip), pointerEvents: "none" }}>
      <div style={{ position: "absolute", top: 180, left: 0, right: 0, textAlign: "center", fontFamily: FONT }}>
        <div style={{ fontSize: 56, fontWeight: 800, color: WHITE, textShadow: "0 2px 12px rgba(0,0,0,0.7)" }}>🐛 debug โค้ด</div>
        {bugLocal >= 0 && (
          <div style={{ marginTop: 14 }}>
            <BigStat big="13/13" label="บั๊กเจอครบ — ทั้งคู่ (เสมอที่คะแนน)" cueLocal={bugLocal} accent="#DDE5F2" to="#9FB2D0" size={150} />
          </div>
        )}
      </div>
      <div style={{ position: "absolute", top: 560, left: 0, right: 0, display: "flex", justifyContent: "center", gap: 24 }}>
        {fastLocal >= 0 && <VerdictChip icon="⚡" text="GROK เร็วกว่า" accent={ORANGE} cueLocal={fastLocal} />}
        {cheapLocal >= 0 && <VerdictChip icon="💰" text="ถูกกว่า ~2×" accent={CYAN} cueLocal={cheapLocal} />}
      </div>
    </AbsoluteFill>
  );
};

const VerdictChip: React.FC<{ icon: string; text: string; accent: string; cueLocal: number }> = ({ icon, text, accent, cueLocal }) => {
  const { fps } = useVideoConfig();
  const pop = springIn(Math.max(0, cueLocal), fps, 13, 150);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        background: GLASS_HI,
        border: `1.5px solid ${accent}66`,
        borderRadius: 16,
        padding: "18px 34px",
        boxShadow: `0 14px 36px rgba(0,0,0,0.5), 0 0 20px ${accent}33`,
        opacity: pop,
        transform: `scale(${interpolate(pop, [0, 1], [0.7, 1])})`,
      }}
    >
      <span style={{ fontSize: 44 }}>{icon}</span>
      <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 48, color: accent }}>{text}</span>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Side chips — flank the presenter on result beats
// ---------------------------------------------------------------------------
const SideChip: React.FC<{ side: "left" | "right"; text: string; accent: string }> = ({ side, text, accent }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const inn = springIn(frame, fps, 15, 120);
  const out = fadeOut(frame, durationInFrames, 8);
  return (
    <div
      style={{
        position: "absolute",
        top: 1150,
        [side]: side === "right" ? 130 : 60,
        writingMode: "horizontal-tb",
        display: "flex",
        alignItems: "center",
        background: GLASS_HI,
        backdropFilter: "blur(8px)",
        WebkitBackdropFilter: "blur(8px)",
        border: `1.5px solid ${accent}66`,
        borderRadius: 16,
        padding: "14px 16px",
        textAlign: "center",
        boxShadow: `0 12px 32px rgba(0,0,0,0.5), 0 0 16px ${accent}2c`,
        opacity: Math.min(inn, out),
        transform: `translateX(${interpolate(inn, [0, 1], [side === "left" ? -24 : 24, 0])}px)`,
      }}
    >
      <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 26, lineHeight: 1.25, whiteSpace: "nowrap", color: accent }}>{text}</span>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Main composition
// ---------------------------------------------------------------------------
export const FrangV5Reel: React.FC<FrangV5ReelProps> = ({ videoSrc, assetDir = "frang-v5-reel" }) => {
  useThaiFonts();
  const { fps, durationInFrames } = useVideoConfig();
  const frame = useCurrentFrame();
  const src = videoSrc.startsWith("http") || videoSrc.startsWith("/") ? videoSrc : staticFile(videoSrc);

  // global fade in/out
  const fadeIn = interpolate(frame, [0, Math.round(0.3 * fps)], [0, 1], { extrapolateRight: "clamp" });
  const fadeEnd = interpolate(frame, [durationInFrames - Math.round(0.4 * fps), durationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const beatSeq = (i: number, offset = 0, len?: number) => {
    const s = BEATS[i] + offset;
    const e = len != null ? s + len : i + 1 < BEATS.length ? BEATS[i + 1] : VIDEO_END;
    return { from: Math.round(s * fps), dur: Math.max(1, Math.round((e - s) * fps)) };
  };

  return (
    <AbsoluteFill style={{ backgroundColor: "#000", opacity: Math.min(fadeIn, fadeEnd) }}>
      {/* 720p RULE: 1080x1920 design space scaled into the 720x1280 canvas */}
      <div style={{ position: "absolute", left: 0, top: 0, width: 1080, height: 1920, transform: "scale(0.666667)", transformOrigin: "top left" }}>
      {/* presenter (bottom zone, seamless black; fades out for the endcard) */}
      <AbsoluteFill
        style={{
          opacity: interpolate(frame, [Math.round(89.25 * fps), Math.round(89.85 * fps)], [1, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        <Presenter src={src} />
      </AbsoluteFill>

      {/* top zone b-roll */}
      <BrollLayer assetDir={assetDir} />

      {/* per-beat motion graphics */}
      {(() => {
        const b = beatSeq(0, 0, 3.35);
        return <Sequence from={b.from} durationInFrames={b.dur}><ColdOpen /></Sequence>;
      })()}
      {(() => {
        const b = beatSeq(0);
        return <Sequence from={b.from} durationInFrames={b.dur}><BeatHook /></Sequence>;
      })()}
      {(() => {
        const b = beatSeq(1);
        return <Sequence from={b.from} durationInFrames={b.dur}><GiantLine text="ดีเกินจริง? 🤔" /></Sequence>;
      })()}
      {(() => {
        const b = beatSeq(2, 0.1, 4.8);
        return <Sequence from={b.from} durationInFrames={b.dur}><NameTag /></Sequence>;
      })()}
      {(() => {
        const b = beatSeq(2, 0.34);
        return <Sequence from={b.from} durationInFrames={b.dur}><FactCheckCard /></Sequence>;
      })()}
      {(() => {
        const b = beatSeq(3);
        return <Sequence from={b.from} durationInFrames={b.dur}><BeatBenchmark /></Sequence>;
      })()}
      {(() => {
        const b = beatSeq(4);
        return <Sequence from={b.from} durationInFrames={b.dur}><GiantLine text="ผลลัพธ์เป็นยังไง?" /></Sequence>;
      })()}
      {(() => {
        const b = beatSeq(5);
        return <Sequence from={b.from} durationInFrames={b.dur}><BeatVsGpt /></Sequence>;
      })()}
      {(() => {
        const b = beatSeq(6);
        return <Sequence from={b.from} durationInFrames={b.dur}><BeatVsFable /></Sequence>;
      })()}
      {(() => {
        const b = beatSeq(7);
        return <Sequence from={b.from} durationInFrames={b.dur}><BeatAgent /></Sequence>;
      })()}
      {(() => {
        const b = beatSeq(8);
        return <Sequence from={b.from} durationInFrames={b.dur}><BeatDebug /></Sequence>;
      })()}

      {/* side chips removed — every channel carries a distinct fact (critics: no duplicate numbers) */}

      {/* word-synced karaoke captions — the bottom-zone second info channel */}
      <CaptionLane />
      {/* accumulating scoreboard */}
      <Scoreboard />
      {/* gold sweep when the tally completes */}
      <Sequence from={Math.round(86.82 * fps)} durationInFrames={Math.round(1.5 * fps)}>
        <ClimaxFlash />
      </Sequence>

      <FramePolish />
      <TopBugBar />

      {/* verdict endcard (89.64 → 92.4) — the reel's ending */}
      <Sequence from={Math.round(89.64 * fps)} durationInFrames={Math.max(1, Math.round((END - 89.64) * fps))}>
        <VerdictEndcard />
      </Sequence>
      </div>
    </AbsoluteFill>
  );
};
