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

// ===========================================================================
// Grok 4.6 Benchmark News Reel — split-zone presenter + motion graphics
// Presenter cropped half-body, anchored to the bottom half on seamless black.
// Top zone: b-roll image (Ken Burns) + per-beat motion graphics synced to VO
// word timings (projects/grok46-news-reel/artifacts/timing.json).
// Side chips flank the presenter on result beats. Silent render — original
// audio re-muxed at the ffmpeg stage.
// ===========================================================================

// ---- design tokens --------------------------------------------------------
const ORANGE = "#FF9D4D"; // grok
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

// ---- timing (seconds, from timing.json word alignment) --------------------
const BEATS = [0, 10.8, 12.79, 16.23, 35.37, 37.37, 53.37, 66.09, 82.01];
const END = 89.64;
const KICKERS = [
  "AI NEWS", "FACT CHECK", "FACT CHECK", "BENCHMARK", "RESULTS",
  "RESULT 1/2", "RESULT 2/2", "AGENT TEST", "DEBUG TEST",
];
// b-roll per beat index (B5 pivot shares the arena shot)
const BROLL = ["b1_hook", "b2_lab", "b2_lab", "b4_arena", "b4_arena", "b6_gpu", "b7_duel", "b8_treasure", "b9_debug"];

const CLAIM_CUES = [
  { t: 5.2, text: "เทียบเท่า FRONTIER", icon: "🧠" },
  { t: 7.76, text: "ถูกกว่ามาก", icon: "💰" },
  { t: 9.22, text: "เร็วกว่ามาก", icon: "⚡" },
];
const MODEL_CUES = [
  { t: 18.14, name: "GROK 4.6", icon: "⚡", accent: ORANGE },
  { t: 19.77, name: "GPT-56 SOUL", icon: "🟢", accent: GREEN },
  { t: 21.63, name: "FABLE 5", icon: "📗", accent: VIOLET },
];
const TEST_CUES = [
  { t: 25.64, icon: "🎢", label: "จำลองรถไฟเหาะ" },
  { t: 26.72, icon: "🍎", label: "สร้างเว็บ Apple ใหม่" },
  { t: 29.14, icon: "🗺️", label: "ล่าสมบัติจากไฟล์" },
  { t: 31.27, icon: "🐛", label: "debug โค้ด" },
  { t: 33.32, icon: "🐤", label: "เกม Flappy Birds" },
];

// ---- presenter crop geometry (source 720x1280) -----------------------------
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
export interface Grok46ReelProps {
  [key: string]: unknown;
  videoSrc: string;
  durationSec: number;
}
export const calculateGrok46Metadata: CalculateMetadataFunction<Grok46ReelProps> = ({ props }) => {
  const fps = 30;
  return {
    durationInFrames: Math.ceil((props.durationSec || END) * fps),
    fps,
    width: 1080,
    height: 1920,
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
// Presenter — cropped half-body, bottom-anchored, seamless on black
// ---------------------------------------------------------------------------
const Presenter: React.FC<{ src: string }> = ({ src }) => {
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
        }}
      />
    </div>
  );
};

// ---------------------------------------------------------------------------
// Top zone — b-roll with slow Ken Burns + crossfade + scrims + neon divider
// ---------------------------------------------------------------------------
const BrollLayer: React.FC = () => {
  const { fps } = useVideoConfig();
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 960, overflow: "hidden", backgroundColor: "#000" }}>
      {BEATS.map((s, i) => {
        const e = i + 1 < BEATS.length ? BEATS[i + 1] : END;
        const from = Math.round(s * fps);
        const dur = Math.max(1, Math.round((e - s) * fps));
        return (
          <Sequence key={i} from={from} durationInFrames={dur}>
            <BrollShot name={BROLL[i]} durFrames={dur} />
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

const BrollShot: React.FC<{ name: string; durFrames: number }> = ({ name, durFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const zoom = interpolate(frame, [0, durFrames], [1.02, 1.12]);
  const drift = interpolate(frame, [0, durFrames], [0, -14]);
  const inn = interpolate(frame, [0, Math.round(0.45 * fps)], [0, 1], { extrapolateRight: "clamp" });
  const out = fadeOut(frame, durFrames, Math.round(0.4 * fps));
  return (
    <AbsoluteFill style={{ opacity: Math.min(inn, out) }}>
      <Img
        src={staticFile(`grok46/${name}.png`)}
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
  const inn = springIn(frame, fps, 16, 90);
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
      <div style={{ position: "absolute", top: 520, left: 0, right: 0, display: "flex", flexDirection: "column", alignItems: "center", gap: 18 }}>
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
        left: 60,
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
        transform: `translateX(${interpolate(inn, [0, 1], [-30, 0])}px)`,
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
        </div>
      )}
      {idx >= 0 && (
        <>
          <div style={{ display: "flex", gap: 10 }}>
            {TEST_CUES.map((_, i) => (
              <div
                key={i}
                style={{
                  width: i === idx ? 26 : 9,
                  height: 9,
                  borderRadius: 5,
                  background: i <= idx ? `linear-gradient(90deg, ${ORANGE2}, ${CYAN})` : "rgba(255,255,255,0.25)",
                  boxShadow: i === idx ? `0 0 10px ${CYAN}aa` : "none",
                }}
              />
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
  cueLocal: number; // frames since cue
}> = ({ label, valueText, ratio, accent, cueLocal }) => {
  const { fps } = useVideoConfig();
  const grow = springIn(Math.max(0, cueLocal), fps, 20, 60);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16, marginTop: 18 }}>
      <div style={{ width: 250, textAlign: "right", fontFamily: FONT, fontWeight: 800, fontSize: 32, color: accent }}>{label}</div>
      <div style={{ flex: 1, height: 44, background: "rgba(255,255,255,0.07)", borderRadius: 12, overflow: "hidden" }}>
        <div
          style={{
            width: `${ratio * grow * 100}%`,
            height: "100%",
            borderRadius: 12,
            background: `linear-gradient(90deg, ${accent}bb, ${accent})`,
            boxShadow: `0 0 18px ${accent}66`,
          }}
        />
      </div>
      <div style={{ width: 190, fontFamily: FONT, fontWeight: 800, fontSize: 34, color: WHITE }}>{valueText}</div>
    </div>
  );
};

// big rolling counter
const BigStat: React.FC<{ big: string; label: string; accent?: string; cueLocal: number; size?: number }> = ({
  big,
  label,
  accent = ORANGE2,
  cueLocal,
  size = 120,
}) => {
  const { fps } = useVideoConfig();
  const pop = springIn(Math.max(0, cueLocal), fps, 12, 120);
  return (
    <div style={{ textAlign: "center", opacity: pop, transform: `scale(${interpolate(pop, [0, 1], [0.6, 1])})` }}>
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: size, lineHeight: 1.05 }}>
        <GradientText from={accent} to={CYAN}>{big}</GradientText>
      </div>
      <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 36, color: WHITE, marginTop: 2 }}>{label}</div>
    </div>
  );
};

const BeatVsGpt: React.FC = () => {
  const { fps } = useVideoConfig();
  const tAbs = BEATS[5] + useCurrentFrame() / fps;
  const barsLocal = tAbs >= 45.37 ? Math.round((tAbs - 45.37) * fps) : -1;
  const costLocal = tAbs >= 51.68 ? Math.round((tAbs - 51.68) * fps) : -1;
  return (
    <VsCard right="GPT-56 SOUL" rightAccent={GREEN} winnerCue={41.36} winnerText="GROK ชนะคะแนนรวม" beatStart={BEATS[5]}>
      {barsLocal >= 0 && (
        <div style={{ marginTop: 24 }}>
          <BarRow label="GROK 4.6" valueText="18 นาที" ratio={18 / 24} accent={ORANGE} cueLocal={barsLocal} />
          <BarRow label="GPT-56 SOUL" valueText="24 นาที" ratio={1} accent={GREEN} cueLocal={Math.max(0, barsLocal - 8)} />
        </div>
      )}
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
        <div style={{ display: "flex", justifyContent: "center", gap: 70, marginTop: 18 }}>
          <BigStat big="10×" label="ถูกกว่า" cueLocal={costLocal} accent={VIOLET} />
          {speedLocal >= 0 && <BigStat big="+1 นาที" label="เร็วกว่า" cueLocal={speedLocal} size={88} />}
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
          🗺️ ล่าสมบัติจากไฟล์หลายประเภท
        </div>
      </div>
      <div style={{ position: "absolute", top: 290, left: 0, right: 0, display: "flex", justifyContent: "center", gap: 90 }}>
        {speedLocal >= 0 && <BigStat big="6×" label="เร็วกว่า GPT" cueLocal={speedLocal} size={110} />}
        {costLocal >= 0 && <BigStat big="6×" label="ต้นทุนน้อยกว่า" cueLocal={costLocal} size={110} />}
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
        background: GLASS_HI,
        border: `1.5px solid ${accent}55`,
        borderRadius: 18,
        padding: "16px 34px",
        boxShadow: `0 14px 40px rgba(0,0,0,0.5), 0 0 18px ${accent}2e`,
        opacity: pop,
        transform: `translateX(${interpolate(pop, [0, 1], [ok ? 30 : -30, 0])}px)`,
      }}
    >
      <span style={{ fontSize: 36 }}>{ok ? "✅" : "❌"}</span>
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
  const bugLocal = tAbs >= 84.92 ? Math.round((tAbs - 84.92) * fps) : -1;
  const fastLocal = tAbs >= 86.52 ? Math.round((tAbs - 86.52) * fps) : -1;
  const cheapLocal = tAbs >= 88.3 ? Math.round((tAbs - 88.3) * fps) : -1;
  return (
    <AbsoluteFill style={{ opacity: Math.min(inn, out), pointerEvents: "none" }}>
      <div style={{ position: "absolute", top: 180, left: 0, right: 0, textAlign: "center", fontFamily: FONT }}>
        <div style={{ fontSize: 56, fontWeight: 800, color: WHITE, textShadow: "0 2px 12px rgba(0,0,0,0.7)" }}>🐛 debug โค้ด</div>
        {bugLocal >= 0 && (
          <div style={{ marginTop: 14 }}>
            <BigStat big="13/13" label="บั๊กเจอครบ — ทั้งคู่" cueLocal={bugLocal} size={104} />
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
        padding: "14px 28px",
        boxShadow: `0 14px 36px rgba(0,0,0,0.5), 0 0 20px ${accent}33`,
        opacity: pop,
        transform: `scale(${interpolate(pop, [0, 1], [0.7, 1])})`,
      }}
    >
      <span style={{ fontSize: 34 }}>{icon}</span>
      <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 36, color: accent }}>{text}</span>
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
        [side]: 22,
        writingMode: "horizontal-tb",
        display: "flex",
        alignItems: "center",
        background: GLASS_HI,
        backdropFilter: "blur(8px)",
        WebkitBackdropFilter: "blur(8px)",
        border: `1.5px solid ${accent}66`,
        borderRadius: 16,
        padding: "14px 16px",
        maxWidth: 168,
        textAlign: "center",
        boxShadow: `0 12px 32px rgba(0,0,0,0.5), 0 0 16px ${accent}2c`,
        opacity: Math.min(inn, out),
        transform: `translateX(${interpolate(inn, [0, 1], [side === "left" ? -24 : 24, 0])}px)`,
      }}
    >
      <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 27, lineHeight: 1.25, color: accent }}>{text}</span>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Main composition
// ---------------------------------------------------------------------------
export const Grok46Reel: React.FC<Grok46ReelProps> = ({ videoSrc }) => {
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
    const e = len != null ? s + len : i + 1 < BEATS.length ? BEATS[i + 1] : END;
    return { from: Math.round(s * fps), dur: Math.max(1, Math.round((e - s) * fps)) };
  };

  return (
    <AbsoluteFill style={{ backgroundColor: "#000", opacity: Math.min(fadeIn, fadeEnd) }}>
      {/* presenter (bottom zone, seamless black) */}
      <Presenter src={src} />

      {/* top zone b-roll */}
      <BrollLayer />

      {/* per-beat motion graphics */}
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
        const b = beatSeq(3);
        return <Sequence from={b.from} durationInFrames={b.dur}><BeatBenchmark /></Sequence>;
      })()}
      {(() => {
        const b = beatSeq(4);
        return <Sequence from={b.from} durationInFrames={b.dur}><GiantLine text="ผลลัพธ์เป็นยังไง? 👇" /></Sequence>;
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

      {/* side chips flanking presenter (result beats) */}
      {(() => {
        const b = beatSeq(5, 45.37 - BEATS[5], 7.9);
        return (
          <>
            <Sequence from={b.from} durationInFrames={b.dur}><SideChip side="left" text="⏱ GROK 18 นาที" accent={ORANGE} /></Sequence>
            <Sequence from={b.from} durationInFrames={b.dur}><SideChip side="right" text="⏱ GPT 24 นาที" accent={GREEN} /></Sequence>
          </>
        );
      })()}
      {(() => {
        const b = beatSeq(6, 61.63 - BEATS[6], 4.4);
        return <Sequence from={b.from} durationInFrames={b.dur}><SideChip side="left" text="💰 ถูกกว่า 10×" accent={VIOLET} /></Sequence>;
      })()}
      {(() => {
        const b = beatSeq(8, 86.52 - BEATS[8], 3.0);
        return <Sequence from={b.from} durationInFrames={b.dur}><SideChip side="right" text="🐛 13/13 ครบ" accent={CYAN} /></Sequence>;
      })()}

      <FramePolish />
      <TopBugBar />
    </AbsoluteFill>
  );
};
