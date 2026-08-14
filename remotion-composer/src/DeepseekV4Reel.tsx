// ===========================================================================
// DeepseekV4Reel — split-zone news reel (skill: Frang-vdo-half-v1-1.2x)
// Source: วิดีโออวตาร_720p.mp4 (scenic park footage, NOT black-bg) — presenter
// sits in a rounded GLASS CARD in the bottom zone (user-approved treatment),
// replacing the template's seamless-black blend. All wave-11 devices kept:
//   · cold-open CLAIM card (claim spoken at 0–1.6s; benchmark answer withheld)
//   · 4-slot scorecard rail "V4 PRO x/4" (locked → active-pulse → lit) from 2.92s
//   · word-synced karaoke caption lane (gold-glow active word, never blanks)
//   · ghost bar tracks with pulsing "กำลังวัดผล…" pending labels
//   · dimmed LOSER bar on the price round (V4 PRO sliver wins: ถูกกว่า = สั้นกว่า)
//   · loud hero stat (57× at 200px) landing exactly on the spoken word
//   · stage-clearing climax burst "🏆 4/4!" when the rail completes (19.46s)
//   · verdict endcard (25.2 → 28.0) with completed rail + ฟรัง AI NEWS lockup
// Ties render in neutral silver, never winner gold (benchmark round = ใกล้กัน).
// ===========================================================================

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
import { CAPTION_PAGES } from "./reelCaptions";

// ---- design tokens --------------------------------------------------------
const ORANGE = "#FF9D4D"; // DeepSeek V4 Pro accent
const ORANGE2 = "#FFC37A";
const CYAN = "#6FE6FF";
const GREEN = "#7CE8A5";
const VIOLET = "#B98CFF"; // Claude Fable 5 accent
const SILVER_HI = "#DDE5F2"; // tie/neutral rendering — never winner gold
const SILVER_LO = "#9FB2D0";
const AMBER = "#FFC37A";
const WHITE = "#F4F7FC";
const MUTE = "#A9B6CC";
const GLASS = "rgba(11,14,21,0.46)";
const GLASS_HI = "rgba(15,19,28,0.66)";
const BORDER = "rgba(255,255,255,0.14)";
const FONT = '"KanitX","Kanit",system-ui,-apple-system,sans-serif';

// ---- timing (seconds, from artifacts/timing.json word alignment) ----------
const BEATS = [0, 2.92, 6.6, 10.9, 16.28, 20.9];
const VIDEO_END = 25.2; // presenter VO ends here
const END = 28.0; // + verdict endcard
const KICKERS = ["AI NEWS", "BENCHMARK", "PRICE", "AI AGENT", "ธุรกิจเล็ก", "สรุป"];
const BROLL_SCHEDULE: [number, string][] = [
  [0, "hook"], [2.92, "benchmark"], [6.6, "price"],
  [10.9, "agent"], [16.28, "smallbiz"], [20.2, "verdict"],
];

// ---- presenter glass-card geometry (source 720x1280, scenic) ---------------
// Crop window: source y 210–930 (head-top margin → mid-torso, above clasped hands)
const CARD_W = 840;
const CARD_H = 840;
const CARD_X = Math.round((1080 - CARD_W) / 2); // 120
const CARD_Y = 1040; // seam row (scoreboard + nametag) sits above the card
const VSCALE = CARD_W / 720; // 1.1667
const VID_H = Math.round(1280 * VSCALE); // 1493
const CROP_TOP_SRC = 210; // source y of visible window top

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
export interface DeepseekV4ReelProps {
  [key: string]: unknown;
  videoSrc: string;
  durationSec: number;
  assetDir?: string;
}
export const calculateDeepseekV4Metadata: CalculateMetadataFunction<DeepseekV4ReelProps> = ({ props }) => {
  const fps = 30;
  return {
    durationInFrames: Math.ceil((props.durationSec || END) * fps),
    fps,
    width: 720, // 720p rule — design space 1080x1920 scaled down by the root wrapper
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
        bottom: 300,
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
// Scoreboard rail — "V4 PRO x/4" claim tally (⚡ benchmark · 💰 price · ⏱ agent · 📇 SME)
// ---------------------------------------------------------------------------
const SCORE_TICKS = [6.5, 8.51, 14.5, 19.46]; // each claim's clinching word: "5" · "เท่า" · "บิล" · "ได้"
const ROUND_ICONS = ["⚡", "💰", "⏱", "📇"];
const ROUND_ACTIVE = [2.92, 6.6, 10.9, 16.28]; // when each round starts being contested
const Scoreboard: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  if (t < 2.92) return null; // appears as the cold-open hands off — slot 1 goes active instantly
  let score = 0;
  for (const c of SCORE_TICKS) if (t >= c) score++;
  const sinceTick = score === 0 ? Math.round((t - 2.92) * fps) : Math.round((t - SCORE_TICKS[score - 1]) * fps);
  const punch = springIn(Math.max(0, sinceTick), fps, 12, 170);
  return (
    <div
      style={{
        position: "absolute",
        left: 60,
        top: 952,
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
        V4 PRO <span style={{ color: score === 0 ? MUTE : ORANGE2 }}>{score}/4</span>
      </span>
      {ROUND_ICONS.map((icon, i) => {
        const won = i < score;
        const active = !won && t >= ROUND_ACTIVE[i];
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
// Cold-open CLAIM card (0–2.92s) — the number pops ON the spoken word "57";
// the benchmark answer is withheld (the rail + round 1 answer it)
// ---------------------------------------------------------------------------
const ColdOpen: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const inn = springIn(frame, fps, 13, 110);
  const out = fadeOut(frame, durationInFrames, 10);
  const num = springIn(Math.max(0, frame - Math.round(0.65 * fps)), fps, 12, 120); // "57" spoken at 0.647
  const teaser = springIn(Math.max(0, frame - Math.round(1.8 * fps)), fps, 13, 130);
  return (
    <AbsoluteFill style={{ justifyContent: "flex-start", alignItems: "center", pointerEvents: "none" }}>
      <div
        style={{
          marginTop: 280,
          textAlign: "center",
          fontFamily: FONT,
          opacity: Math.min(inn, out),
          transform: `scale(${interpolate(inn, [0, 1], [0.72, 1])})`,
        }}
      >
        <div style={{ fontSize: 46, fontWeight: 700, color: MUTE, textShadow: "0 3px 14px rgba(0,0,0,0.8)" }}>
          💰 ค่าใช้จ่าย AI
        </div>
        <div
          style={{
            fontSize: 150,
            fontWeight: 800,
            lineHeight: 1.08,
            marginTop: 8,
            opacity: num,
            transform: `scale(${interpolate(num, [0, 1], [0.6, 1])})`,
          }}
        >
          <GradientText from={ORANGE2} to={ORANGE} glow={`${ORANGE}88`}>ถูกลง 57×</GradientText>
        </div>
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            marginTop: 30,
            opacity: teaser,
            transform: `translateY(${interpolate(teaser, [0, 1], [20, 0])}px)`,
          }}
        >
          <span
            style={{
              fontFamily: FONT,
              fontWeight: 800,
              fontSize: 42,
              color: CYAN,
              background: GLASS_HI,
              border: `1.5px solid ${CYAN}66`,
              borderRadius: 16,
              padding: "12px 30px",
              boxShadow: `0 0 22px ${CYAN}33`,
            }}
          >
            แล้วคะแนนล่ะ…?
          </span>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// Climax flash — gold sweep when the tally hits 4/4 (19.46s)
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
      <AbsoluteFill style={{ opacity: dim, backgroundColor: "#04060A" }} />
      <AbsoluteFill
        style={{
          opacity: o,
          background: `radial-gradient(80% 50% at 50% 55%, ${ORANGE2}55 0%, ${ORANGE}22 45%, transparent 75%)`,
        }}
      />
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
        <div style={{ fontSize: 52, color: WHITE, marginTop: 10, textShadow: "0 3px 14px rgba(0,0,0,0.8)" }}>ครบทุกประเด็น</div>
      </div>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// Verdict endcard (25.2 → 28.0) — owns the reveal + completed rail + brand
// ---------------------------------------------------------------------------
const VerdictEndcard: React.FC<{ assetDir: string }> = ({ assetDir }) => {
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
          src={staticFile(`${assetDir}/verdict.png`)}
          style={{ width: "100%", height: "100%", objectFit: "cover", filter: "brightness(0.55) saturate(1.1)" }}
        />
        <AbsoluteFill style={{ background: "radial-gradient(90% 60% at 50% 42%, transparent 0%, rgba(5,7,12,0.88) 78%)" }} />
      </AbsoluteFill>
      <div
        style={{
          position: "absolute",
          top: 600,
          left: 0,
          right: 0,
          textAlign: "center",
          fontFamily: FONT,
          opacity: inn,
          transform: `scale(${interpolate(inn, [0, 1], [0.82, 1])})`,
        }}
      >
        <div style={{ fontSize: 96, fontWeight: 800, letterSpacing: 2, lineHeight: 1.05 }}>
          <GradientText glow={`${ORANGE}77`}>DEEPSEEK V4 PRO</GradientText>
        </div>
        <div style={{ fontSize: 54, fontWeight: 800, color: WHITE, marginTop: 14, textShadow: "0 3px 14px rgba(0,0,0,0.8)" }}>
          🏆 ครบ 4 ประเด็นสำคัญ
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          top: 950,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          gap: 22,
          opacity: chip,
          transform: `translateY(${interpolate(chip, [0, 1], [24, 0])}px)`,
        }}
      >
        <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 40, color: VIOLET, background: GLASS_HI, border: `1.5px solid ${VIOLET}66`, borderRadius: 16, padding: "14px 30px", width: 430, textAlign: "center", boxSizing: "border-box", boxShadow: `0 0 22px ${VIOLET}33` }}>⚡ ใกล้ Fable 5</span>
        <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 40, color: ORANGE2, background: GLASS_HI, border: `1.5px solid ${ORANGE}66`, borderRadius: 16, padding: "14px 30px", width: 430, textAlign: "center", boxSizing: "border-box", boxShadow: `0 0 22px ${ORANGE}33` }}>💰 ถูกกว่า 57×</span>
      </div>
      <div
        style={{
          position: "absolute",
          top: 1110,
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
          top: 1240,
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
          V4 PRO <span style={{ color: ORANGE2 }}>4/4</span>
        </span>
      </div>
      <div
        style={{
          position: "absolute",
          top: 1350,
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

// ---------------------------------------------------------------------------
// Presenter — scenic footage in a rounded glass card (bottom zone)
// ---------------------------------------------------------------------------
const Presenter: React.FC<{ src: string }> = ({ src }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  // slow cinematic push-in (1.00 → 1.05) so the presenter never reads as frozen
  const push = interpolate(frame, [0, durationInFrames], [1, 1.05], { extrapolateRight: "clamp" });
  return (
    <div
      style={{
        position: "absolute",
        left: CARD_X,
        top: CARD_Y,
        width: CARD_W,
        height: CARD_H,
        overflow: "hidden",
        borderRadius: 44,
        border: `1.5px solid ${BORDER}`,
        backgroundColor: "#000",
        boxShadow: "0 30px 80px rgba(0,0,0,0.65), 0 0 44px rgba(111,230,255,0.10)",
      }}
    >
      <OffthreadVideo
        src={src}
        muted
        style={{
          width: CARD_W,
          height: VID_H,
          marginTop: -Math.round(CROP_TOP_SRC * VSCALE),
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
      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(6,8,13,0.62) 0%, rgba(6,8,13,0) 20%)" }} />
      <AbsoluteFill style={{ background: "linear-gradient(0deg, #000 0%, rgba(0,0,0,0.85) 7%, rgba(0,0,0,0) 32%)" }} />
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
        <GradientText>DEEPSEEK&nbsp;V4&nbsp;PRO</GradientText>
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
// NameTag — presenter brand chip at the seam row (right side)
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
        right: 130,
        top: 952,
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
// Shared MG primitives
// ---------------------------------------------------------------------------
const BarRow: React.FC<{
  label: string;
  valueText: string;
  ratio: number;
  accent: string;
  cueLocal: number; // frames since cue (negative = ghost track, not yet revealed)
  dim?: boolean;
}> = ({ label, valueText, ratio, accent, cueLocal, dim = false }) => {
  const { fps } = useVideoConfig();
  const frame = useCurrentFrame();
  const live = cueLocal >= 0;
  const grow = springIn(Math.max(0, cueLocal), fps, 20, 60);
  const shimmerX = (frame * 6) % 400 - 100;
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

const CheckRow: React.FC<{ ok: boolean; text: string; cueLocal: number }> = ({ ok, text, cueLocal }) => {
  const { fps } = useVideoConfig();
  const pop = springIn(Math.max(0, cueLocal), fps, 14, 140);
  const accent = ok ? GREEN : "#FF6B6B";
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
        transform: `translateX(${interpolate(pop, [0, 1], [30, 0])}px)`,
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
      <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 42, color: WHITE }}>{text}</span>
    </div>
  );
};

const TitlePill: React.FC<{ icon: string; text: string; accent?: string }> = ({ icon, text, accent = CYAN }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = springIn(frame, fps, 14, 120);
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 14,
        background: GLASS_HI,
        backdropFilter: "blur(10px)",
        WebkitBackdropFilter: "blur(10px)",
        border: `1.5px solid ${accent}55`,
        borderRadius: 18,
        padding: "14px 30px",
        boxShadow: `0 14px 40px rgba(0,0,0,0.5), 0 0 20px ${accent}2e`,
        opacity: pop,
        transform: `translateY(${interpolate(pop, [0, 1], [18, 0])}px)`,
      }}
    >
      <span style={{ fontSize: 34 }}>{icon}</span>
      <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 42, color: WHITE }}>{text}</span>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Beat 1 — BENCHMARK (2.92–6.6): VS chips + ghost bars → near-equal fill + silver tie badge
// ---------------------------------------------------------------------------
const BeatBenchmark: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const tAbs = BEATS[1] + frame / fps;
  const out = fadeOut(frame, durationInFrames, 8);
  const dsLocal = frame; // DeepSeek chip pops at beat start (its name is spoken 2.92–4.37)
  const fableLocal = tAbs >= 5.2 ? Math.round((tAbs - 5.2) * fps) : -1; // "Claude" spoken at 5.20
  const barsLocal = tAbs >= 4.37 ? Math.round((tAbs - 4.37) * fps) : -1; // "ทำคะแนน" spoken at 4.367
  const badgeLocal = tAbs >= 4.84 ? Math.round((tAbs - 4.84) * fps) : -1; // "ใกล้" spoken at 4.84
  return (
    <AbsoluteFill style={{ opacity: out, pointerEvents: "none" }}>
      {/* model chips row */}
      <div style={{ position: "absolute", top: 180, left: 0, right: 0, display: "flex", justifyContent: "center", alignItems: "center", gap: 18 }}>
        <div
          style={{
            background: GLASS_HI,
            border: `1.5px solid ${ORANGE}55`,
            borderRadius: 18,
            padding: "14px 24px",
            display: "flex",
            alignItems: "center",
            gap: 10,
            boxShadow: `0 14px 36px rgba(0,0,0,0.5), 0 0 18px ${ORANGE}33`,
            opacity: springIn(dsLocal, fps, 13, 140),
            transform: `scale(${interpolate(springIn(dsLocal, fps, 13, 140), [0, 1], [0.7, 1])})`,
          }}
        >
          <span style={{ fontSize: 30 }}>⚡</span>
          <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 31, color: ORANGE }}>DEEPSEEK V4 PRO</span>
        </div>
        {fableLocal >= 0 && (
          <>
            <span
              style={{
                fontFamily: FONT,
                fontWeight: 800,
                fontSize: 24,
                color: "#0B0E15",
                background: `linear-gradient(90deg, ${ORANGE2}, ${CYAN})`,
                borderRadius: 10,
                padding: "4px 14px",
                opacity: springIn(fableLocal, fps, 13, 140),
              }}
            >
              VS
            </span>
            <div
              style={{
                background: GLASS_HI,
                border: `1.5px solid ${VIOLET}55`,
                borderRadius: 18,
                padding: "14px 24px",
                display: "flex",
                alignItems: "center",
                gap: 10,
                boxShadow: `0 14px 36px rgba(0,0,0,0.5), 0 0 18px ${VIOLET}33`,
                opacity: springIn(fableLocal, fps, 13, 140),
                transform: `scale(${interpolate(springIn(fableLocal, fps, 13, 140), [0, 1], [0.7, 1])})`,
              }}
            >
              <span style={{ fontSize: 30 }}>📗</span>
              <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 31, color: VIOLET }}>CLAUDE FABLE 5</span>
            </div>
          </>
        )}
      </div>
      {/* near-equal score bars — tie, so no winner gold, no loser dim */}
      <div
        style={{
          position: "absolute",
          top: 320,
          left: 74,
          right: 74,
          background: GLASS,
          backdropFilter: "blur(12px)",
          WebkitBackdropFilter: "blur(12px)",
          border: `1px solid ${BORDER}`,
          borderRadius: 26,
          padding: "26px 38px 32px",
          boxShadow: "0 22px 60px rgba(0,0,0,0.55)",
        }}
      >
        <div style={{ textAlign: "center", fontFamily: FONT, fontWeight: 700, fontSize: 26, color: MUTE, marginBottom: 6 }}>
          ⚡ คะแนนรวม
        </div>
        <BarRow label="V4 PRO" valueText="≈" ratio={0.96} accent={ORANGE} cueLocal={barsLocal} />
        <BarRow label="FABLE 5" valueText="≈" ratio={1} accent={VIOLET} cueLocal={barsLocal - 8} />
      </div>
      {/* tie badge — neutral silver, never winner gold */}
      {badgeLocal >= 0 && (
        <div style={{ position: "absolute", top: 640, left: 0, right: 0, display: "flex", justifyContent: "center" }}>
          <div
            style={{
              fontFamily: FONT,
              fontWeight: 800,
              fontSize: 40,
              background: GLASS_HI,
              border: `1.5px solid ${SILVER_LO}66`,
              borderRadius: 16,
              padding: "10px 30px",
              boxShadow: `0 14px 40px rgba(0,0,0,0.55), 0 0 24px ${SILVER_LO}2c`,
              opacity: springIn(badgeLocal, fps, 13, 140),
              transform: `scale(${interpolate(springIn(badgeLocal, fps, 13, 140), [0, 1], [0.75, 1])})`,
            }}
          >
            <GradientText from={SILVER_HI} to={SILVER_LO} glow={`${SILVER_LO}55`}>≈ คะแนนใกล้กัน</GradientText>
          </div>
        </div>
      )}
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// Beat 2 — PRICE (6.6–10.9): reversed-polarity bars + giant 57× on the word
// ---------------------------------------------------------------------------
const BeatPrice: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const tAbs = BEATS[2] + frame / fps;
  const out = fadeOut(frame, durationInFrames, 8);
  const barsLocal = tAbs >= 7.48 ? Math.round((tAbs - 7.48) * fps) : -1; // "ถูก" spoken at 7.48
  const statLocal = tAbs >= 8.13 ? Math.round((tAbs - 8.13) * fps) : -1; // "57" spoken at 8.127
  return (
    <AbsoluteFill style={{ opacity: out, pointerEvents: "none" }}>
      <div style={{ position: "absolute", top: 180, left: 0, right: 0, textAlign: "center" }}>
        <TitlePill icon="💰" text="ค่าใช้จ่าย" accent={ORANGE} />
      </div>
      <div
        style={{
          position: "absolute",
          top: 310,
          left: 74,
          right: 74,
          background: GLASS,
          backdropFilter: "blur(12px)",
          WebkitBackdropFilter: "blur(12px)",
          border: `1px solid ${BORDER}`,
          borderRadius: 26,
          padding: "26px 38px 32px",
          boxShadow: "0 22px 60px rgba(0,0,0,0.55)",
        }}
      >
        <div style={{ textAlign: "center", fontFamily: FONT, fontWeight: 700, fontSize: 26, color: MUTE, marginBottom: 6 }}>
          💰 ถูกกว่า = แท่งสั้นกว่า
        </div>
        <BarRow label="V4 PRO" valueText="$" ratio={0.03} accent={ORANGE} cueLocal={barsLocal} />
        <BarRow label="FABLE 5" valueText="$$$$$$" ratio={1} accent={VIOLET} cueLocal={barsLocal - 8} dim />
      </div>
      {statLocal >= 0 && (
        <div style={{ position: "absolute", top: 590, left: 0, right: 0, display: "flex", justifyContent: "center" }}>
          <BigStat big="57×" label="ถูกกว่า" cueLocal={statLocal} size={200} accent={ORANGE2} to={ORANGE} />
        </div>
      )}
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// Beat 3 — AGENT (10.9–16.28): all-day work + no bill worry
// ---------------------------------------------------------------------------
const BeatAgent: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const tAbs = BEATS[3] + frame / fps;
  const out = fadeOut(frame, durationInFrames, 8);
  const dayLocal = tAbs >= 12.46 ? Math.round((tAbs - 12.46) * fps) : -1; // "ทั้งวัน" spoken at 12.46
  const billLocal = tAbs >= 14.5 ? Math.round((tAbs - 14.5) * fps) : -1; // "บิล" spoken at 14.5
  return (
    <AbsoluteFill style={{ opacity: out, pointerEvents: "none" }}>
      <div style={{ position: "absolute", top: 185, left: 0, right: 0, textAlign: "center" }}>
        <TitlePill icon="⏱" text="ปล่อย AI Agent ทำงาน" accent={CYAN} />
      </div>
      {dayLocal >= 0 && (
        <div style={{ position: "absolute", top: 380, left: 0, right: 0, textAlign: "center", fontFamily: FONT }}>
          <div
            style={{
              fontSize: 96,
              fontWeight: 800,
              lineHeight: 1.1,
              textShadow: "0 4px 18px rgba(0,0,0,0.75)",
              opacity: springIn(dayLocal, fps, 13, 110),
              transform: `scale(${interpolate(springIn(dayLocal, fps, 13, 110), [0, 1], [0.7, 1])})`,
            }}
          >
            <GradientText from={CYAN} to={ORANGE2}>ทำงานทั้งวันได้</GradientText>
          </div>
        </div>
      )}
      {billLocal >= 0 && (
        <div style={{ position: "absolute", top: 620, left: 0, right: 0, display: "flex", justifyContent: "center" }}>
          <CheckRow ok text="ไม่ต้องห่วงบิล" cueLocal={billLocal} />
        </div>
      )}
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// Beat 4 — SMALLBIZ (16.28–20.9): same league — ducked while the climax owns the stage
// ---------------------------------------------------------------------------
const BeatSmallbiz: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const tAbs = BEATS[4] + frame / fps;
  const inn = springIn(frame, fps, 17, 100);
  const out = fadeOut(frame, durationInFrames, 8);
  const chipsLocal = tAbs >= 16.84 ? Math.round((tAbs - 16.84) * fps) : -1; // "เล็ก" spoken at 16.84
  const badgeLocal = tAbs >= 18.19 ? Math.round((tAbs - 18.19) * fps) : -1; // "ระดับ" spoken at 18.19
  const dip = interpolate(tAbs, [19.46, 19.74, 20.54, 20.84], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const chipStyle = (accent: string): React.CSSProperties => ({
    fontFamily: FONT,
    fontWeight: 800,
    fontSize: 46,
    color: accent,
    background: GLASS_HI,
    border: `1.5px solid ${accent}66`,
    borderRadius: 18,
    padding: "16px 30px",
    boxShadow: `0 14px 36px rgba(0,0,0,0.5), 0 0 20px ${accent}33`,
  });
  return (
    <AbsoluteFill style={{ opacity: Math.min(inn, out) * (1 - dip), pointerEvents: "none" }}>
      <div style={{ position: "absolute", top: 185, left: 0, right: 0, textAlign: "center" }}>
        <TitlePill icon="📇" text="AI สำหรับทุกธุรกิจ" accent={ORANGE} />
      </div>
      {chipsLocal >= 0 && (
        <div
          style={{
            position: "absolute",
            top: 350,
            left: 0,
            right: 0,
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            gap: 26,
            opacity: springIn(chipsLocal, fps, 13, 130),
            transform: `scale(${interpolate(springIn(chipsLocal, fps, 13, 130), [0, 1], [0.8, 1])})`,
          }}
        >
          <span style={chipStyle(CYAN)}>ธุรกิจเล็ก</span>
          <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 96, lineHeight: 1 }}>
            <GradientText from={SILVER_HI} to={SILVER_LO} glow={`${SILVER_LO}55`}>=</GradientText>
          </span>
          <span style={chipStyle(ORANGE)}>บริษัทใหญ่</span>
        </div>
      )}
      {badgeLocal >= 0 && (
        <div style={{ position: "absolute", top: 580, left: 0, right: 0, display: "flex", justifyContent: "center" }}>
          <CheckRow ok text="ใช้ Agent ระดับเดียวกัน" cueLocal={badgeLocal} />
        </div>
      )}
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// Beat 5 — SUMMARY (20.9–25.2): ฟรังสรุป — details + caveats delivered
// ---------------------------------------------------------------------------
const BeatSummary: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const tAbs = BEATS[5] + frame / fps;
  const out = fadeOut(frame, durationInFrames, 8);
  const titleLocal = tAbs >= 21.9 ? Math.round((tAbs - 21.9) * fps) : -1; // "สรุป" spoken at 21.9
  const detLocal = tAbs >= 22.7 ? Math.round((tAbs - 22.7) * fps) : -1; // "รายละเอียด" at 22.7
  const warnLocal = tAbs >= 23.6 ? Math.round((tAbs - 23.6) * fps) : -1; // "ข้อควรระวัง" at 23.6
  const doneLocal = tAbs >= 24.42 ? Math.round((tAbs - 24.42) * fps) : -1; // "ไว้" at 24.42
  const sumChip = (accent: string, cueLocal: number): React.CSSProperties => ({
    display: "flex",
    alignItems: "center",
    gap: 14,
    fontFamily: FONT,
    fontWeight: 800,
    fontSize: 44,
    color: WHITE,
    background: GLASS_HI,
    border: `1.5px solid ${accent}66`,
    borderRadius: 18,
    padding: "18px 30px",
    boxShadow: `0 14px 36px rgba(0,0,0,0.5), 0 0 20px ${accent}33`,
    opacity: springIn(Math.max(0, cueLocal), fps, 13, 140),
    transform: `scale(${interpolate(springIn(Math.max(0, cueLocal), fps, 13, 140), [0, 1], [0.75, 1])})`,
  });
  return (
    <AbsoluteFill style={{ opacity: out, pointerEvents: "none" }}>
      {titleLocal >= 0 && (
        <div style={{ position: "absolute", top: 220, left: 0, right: 0, textAlign: "center", fontFamily: FONT }}>
          <div
            style={{
              fontSize: 110,
              fontWeight: 800,
              lineHeight: 1.1,
              textShadow: "0 4px 18px rgba(0,0,0,0.75)",
              opacity: springIn(titleLocal, fps, 13, 110),
              transform: `scale(${interpolate(springIn(titleLocal, fps, 13, 110), [0, 1], [0.72, 1])})`,
            }}
          >
            <GradientText glow={`${ORANGE}77`}>ฟรังสรุป</GradientText>
          </div>
        </div>
      )}
      <div style={{ position: "absolute", top: 460, left: 0, right: 0, display: "flex", justifyContent: "center", gap: 24 }}>
        {detLocal >= 0 && (
          <span style={sumChip(CYAN, detLocal)}>
            <span style={{ fontSize: 38 }}>🔍</span> รายละเอียด
          </span>
        )}
        {warnLocal >= 0 && (
          <span style={sumChip(AMBER, warnLocal)}>
            <span
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: 40,
                height: 40,
                borderRadius: 20,
                background: `${AMBER}1e`,
                border: `1.5px solid ${AMBER}`,
                color: AMBER,
                fontSize: 26,
                fontWeight: 800,
              }}
            >
              !
            </span>
            ข้อควรระวัง
          </span>
        )}
      </div>
      {doneLocal >= 0 && (
        <div
          style={{
            position: "absolute",
            top: 640,
            left: 0,
            right: 0,
            textAlign: "center",
            fontFamily: FONT,
            fontWeight: 800,
            fontSize: 48,
            color: WHITE,
            textShadow: "0 3px 14px rgba(0,0,0,0.8)",
            opacity: springIn(doneLocal, fps, 13, 130),
            transform: `translateY(${interpolate(springIn(doneLocal, fps, 13, 130), [0, 1], [18, 0])}px)`,
          }}
        >
          ไว้ให้แล้ว <span style={{ color: GREEN }}>✓</span>
        </div>
      )}
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// Main composition
// ---------------------------------------------------------------------------
export const DeepseekV4Reel: React.FC<DeepseekV4ReelProps> = ({ videoSrc, assetDir = "deepseek-v4-pro-reel" }) => {
  useThaiFonts();
  const { fps, durationInFrames } = useVideoConfig();
  const frame = useCurrentFrame();
  const src = videoSrc.startsWith("http") || videoSrc.startsWith("/") ? videoSrc : staticFile(videoSrc);

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
      {/* presenter glass card (bottom zone; fades out for the endcard) */}
      <AbsoluteFill
        style={{
          opacity: interpolate(frame, [Math.round(24.8 * fps), Math.round(25.3 * fps)], [1, 0], {
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
        const b = beatSeq(0, 0, 2.92);
        return <Sequence from={b.from} durationInFrames={b.dur}><ColdOpen /></Sequence>;
      })()}
      {(() => {
        const b = beatSeq(1);
        return <Sequence from={b.from} durationInFrames={b.dur}><BeatBenchmark /></Sequence>;
      })()}
      {(() => {
        const b = beatSeq(2);
        return <Sequence from={b.from} durationInFrames={b.dur}><BeatPrice /></Sequence>;
      })()}
      {(() => {
        const b = beatSeq(3);
        return <Sequence from={b.from} durationInFrames={b.dur}><BeatAgent /></Sequence>;
      })()}
      {(() => {
        const b = beatSeq(4);
        return <Sequence from={b.from} durationInFrames={b.dur}><BeatSmallbiz /></Sequence>;
      })()}
      {(() => {
        const b = beatSeq(5);
        return <Sequence from={b.from} durationInFrames={b.dur}><BeatSummary /></Sequence>;
      })()}
      {(() => {
        const b = beatSeq(1, 0.5, 5.6);
        return <Sequence from={b.from} durationInFrames={b.dur}><NameTag /></Sequence>;
      })()}

      {/* word-synced karaoke captions — the bottom-zone second info channel */}
      <CaptionLane />
      {/* accumulating scoreboard rail */}
      <Scoreboard />
      {/* gold sweep when the tally completes */}
      <Sequence from={Math.round(19.46 * fps)} durationInFrames={Math.round(1.5 * fps)}>
        <ClimaxFlash />
      </Sequence>

      <FramePolish />
      <TopBugBar />

      {/* verdict endcard (25.2 → 28.0) — the reel's ending */}
      <Sequence from={Math.round(25.2 * fps)} durationInFrames={Math.max(1, Math.round((END - 25.2) * fps))}>
        <VerdictEndcard assetDir={assetDir} />
      </Sequence>
      </div>
    </AbsoluteFill>
  );
};
