import React, { useEffect, useState } from "react";
import {
  AbsoluteFill,
  OffthreadVideo,
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
// Claude Tag — Premium AI-product-ad motion-graphics overlay
// Composites neon kinetic Thai captions, a per-scene news lower-third bug,
// VO-synced highlight callouts, and transition cards OVER the existing 48s
// footage (audio preserved at mux stage). Premium-subtle intensity.
// ===========================================================================

// ---- design tokens --------------------------------------------------------
const CORAL = "#FF8E5E";
const CORAL2 = "#FFB37A";
const CYAN = "#6FE6FF";
const BLUE = "#7AA2F0";
const WHITE = "#F4F7FC";
const MUTE = "#A9B6CC";
const GLASS = "rgba(11,14,21,0.42)";
const GLASS_HI = "rgba(17,21,31,0.62)";
const BORDER = "rgba(255,255,255,0.14)";
const FONT = '"KanitX","Kanit",system-ui,-apple-system,sans-serif';

const KICKERS = ["AI NEWS", "HOW IT WORKS", "CAPABILITIES", "THE SHIFT", "PROOF", "TAKEAWAY"];

const CAPS = ["Summarize", "Track Metrics", "Support Tickets", "Bug Analysis", "Data & Code"];

// per-scene highlight lower-third (S3 handled specially as a cycle)
const LT: Record<number, { tag: string; msg: string; cta?: string; accent: string }> = {
  0: { tag: "● LIVE", msg: "แท็ก @Claude ในแชนเนล ให้ AI ช่วยงานทีมได้ทันที", accent: CORAL },
  1: { tag: "HOW IT WORKS", msg: "Tag @Claude → hand off any task in the channel", accent: CYAN },
  3: { tag: "THE SHIFT", msg: "It remembers each channel’s context — shared with the team", accent: BLUE },
  4: { tag: "PROOF", msg: "Real internal use — Anthropic runs on it", accent: CORAL },
  5: { tag: "NOW IN BETA", msg: "Enterprise & Team", cta: "ใครทำงานเป็นทีม ต้องจับตา 👀", accent: CYAN },
};

// ---- font loading (local Kanit TTF, headless-safe) ------------------------
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

// ---- props ----------------------------------------------------------------
export interface CaptionWord { tok: string; startMs: number; endMs: number }
export interface CaptionPhrase { tokens: string[]; words: CaptionWord[]; startMs: number; endMs: number }
export interface ClaudeTagReelProps {
  [key: string]: unknown;
  videoSrc: string;
  durationSec: number;
  sceneStarts: number[];
  sceneEnd: number;
  phrases: CaptionPhrase[];
  chipCues: (number | null)[];
  statCueMs: number;
}

export const calculateClaudeTagMetadata: CalculateMetadataFunction<ClaudeTagReelProps> = ({ props }) => {
  const fps = 30;
  const dur = props.durationSec || props.sceneEnd || 48;
  return { durationInFrames: Math.ceil(dur * fps), fps, width: 1080, height: 1920 };
};

// ---------------------------------------------------------------------------
// Frame polish — subtle vignettes + corner neon glows for legibility & mood
// ---------------------------------------------------------------------------
const FramePolish: React.FC = () => {
  const frame = useCurrentFrame();
  const breathe = 0.5 + 0.5 * Math.sin(frame / 34);
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      {/* top scrim for the news bug */}
      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(6,8,13,0.55) 0%, rgba(6,8,13,0) 18%)" }} />
      {/* bottom scrim for captions */}
      <AbsoluteFill style={{ background: "linear-gradient(0deg, rgba(6,8,13,0.62) 0%, rgba(6,8,13,0) 26%)" }} />
      {/* corner neon glows */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(120% 60% at -8% -6%, ${CORAL}1f 0%, transparent 42%), radial-gradient(120% 60% at 108% 106%, ${CYAN}1c 0%, transparent 42%)`,
          opacity: 0.7 + 0.3 * breathe,
        }}
      />
      {/* hairline safe frame */}
      <AbsoluteFill
        style={{
          margin: 22,
          border: "1.5px solid rgba(255,255,255,0.07)",
          borderRadius: 30,
        }}
      />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// Top news-bug bar (persistent) + per-scene kicker swap
// ---------------------------------------------------------------------------
const TopBugBar: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const intro = spring({ frame, fps, config: { damping: 20, stiffness: 90 } });
  const pulse = 0.55 + 0.45 * Math.sin(frame / 7);
  return (
    <div
      style={{
        position: "absolute",
        top: 52,
        left: 40,
        right: 40,
        height: 70,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        opacity: intro,
        transform: `translateY(${interpolate(intro, [0, 1], [-26, 0])}px)`,
      }}
    >
      {/* left: live dot + (kicker rendered separately, swapped per scene) */}
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div
          style={{
            width: 14,
            height: 14,
            borderRadius: 7,
            background: CORAL,
            boxShadow: `0 0 ${10 + 10 * pulse}px ${CORAL}, 0 0 4px ${CORAL}`,
            opacity: 0.7 + 0.3 * pulse,
          }}
        />
        <div id="kicker-anchor" style={{ width: 0, height: 0 }} />
      </div>
      {/* right: brand tag */}
      <div
        style={{
          fontFamily: FONT,
          fontWeight: 800,
          fontSize: 26,
          letterSpacing: 1,
          backgroundImage: `linear-gradient(90deg, ${CORAL2}, ${CYAN})`,
          WebkitBackgroundClip: "text",
          backgroundClip: "text",
          WebkitTextFillColor: "transparent",
          filter: `drop-shadow(0 0 10px ${CYAN}66)`,
        }}
      >
        CLAUDE&nbsp;TAG
      </div>
    </div>
  );
};

const TopBugKicker: React.FC<{ text: string; accent: string }> = ({ text, accent }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inn = spring({ frame, fps, config: { damping: 22, stiffness: 130 } });
  return (
    <div
      style={{
        position: "absolute",
        top: 52,
        left: 78,
        height: 70,
        display: "flex",
        alignItems: "center",
        opacity: inn,
        transform: `translateX(${interpolate(inn, [0, 1], [-18, 0])}px)`,
      }}
    >
      <span
        style={{
          fontFamily: FONT,
          fontWeight: 800,
          fontSize: 27,
          letterSpacing: 3,
          color: WHITE,
          textShadow: "0 2px 8px rgba(0,0,0,0.6)",
        }}
      >
        {text}
      </span>
      <div
        style={{
          marginLeft: 16,
          width: interpolate(inn, [0, 1], [0, 92]),
          height: 3,
          borderRadius: 2,
          background: `linear-gradient(90deg, ${accent}, transparent)`,
          boxShadow: `0 0 10px ${accent}aa`,
        }}
      />
    </div>
  );
};

// ---------------------------------------------------------------------------
// Lower-third highlight callout (glass card, neon edge) — premium-subtle
// ---------------------------------------------------------------------------
const LowerThird: React.FC<{ tag: string; msg: string; cta?: string; accent: string }> = ({
  tag,
  msg,
  cta,
  accent,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const inn = spring({ frame, fps, config: { damping: 18, stiffness: 95 } });
  const out = interpolate(frame, [durationInFrames - 12, durationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const op = Math.min(inn, out);
  return (
    <div
      style={{
        position: "absolute",
        left: 70,
        right: 70,
        top: 1150,
        display: "flex",
        justifyContent: "center",
        opacity: op,
        transform: `translateY(${interpolate(inn, [0, 1], [26, 0])}px)`,
      }}
    >
      <div
        style={{
          position: "relative",
          maxWidth: 880,
          background: GLASS_HI,
          backdropFilter: "blur(10px)",
          WebkitBackdropFilter: "blur(10px)",
          border: `1px solid ${BORDER}`,
          borderRadius: 20,
          padding: "20px 28px 20px 30px",
          boxShadow: `0 18px 50px rgba(0,0,0,0.45), 0 0 0 1px ${accent}22`,
          overflow: "hidden",
        }}
      >
        {/* neon left edge */}
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            bottom: 0,
            width: 6,
            background: `linear-gradient(180deg, ${CORAL2}, ${CYAN})`,
            boxShadow: `0 0 16px ${accent}aa`,
          }}
        />
        <div
          style={{
            fontFamily: FONT,
            fontWeight: 800,
            fontSize: 20,
            letterSpacing: 2.5,
            color: accent,
            marginBottom: 6,
            textTransform: "uppercase",
          }}
        >
          {tag}
        </div>
        <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 34, lineHeight: 1.18, color: WHITE }}>
          {msg}
        </div>
        {cta && (
          <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 28, marginTop: 8, color: CORAL2 }}>
            {cta}
          </div>
        )}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// S3 capability cycle — a single neon chip that swaps on each spoken capability
// ---------------------------------------------------------------------------
const CapabilityCycle: React.FC<{ cues: (number | null)[]; sceneStartMs: number }> = ({
  cues,
  sceneStartMs,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const tMs = sceneStartMs + (frame / fps) * 1000;
  // which capability is active
  let idx = 0;
  for (let i = 0; i < cues.length; i++) {
    if (cues[i] != null && tMs >= (cues[i] as number)) idx = i;
  }
  const activeCueMs = (cues[idx] as number) ?? sceneStartMs;
  const sincePop = ((tMs - activeCueMs) / 1000) * fps; // frames since this chip appeared
  const pop = spring({ frame: Math.max(0, sincePop), fps, config: { damping: 14, stiffness: 150 } });
  const inn = spring({ frame, fps, config: { damping: 18, stiffness: 95 } });
  const out = interpolate(frame, [durationInFrames - 12, durationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        top: 1180,
        display: "flex",
        justifyContent: "center",
        opacity: Math.min(inn, out),
        transform: `translateY(${interpolate(inn, [0, 1], [24, 0])}px)`,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
        {/* progress dots */}
        <div style={{ display: "flex", gap: 10 }}>
          {CAPS.map((_, i) => (
            <div
              key={i}
              style={{
                width: i === idx ? 26 : 9,
                height: 9,
                borderRadius: 5,
                background: i <= idx ? `linear-gradient(90deg, ${CORAL2}, ${CYAN})` : "rgba(255,255,255,0.25)",
                boxShadow: i === idx ? `0 0 10px ${CYAN}aa` : "none",
              }}
            />
          ))}
        </div>
        {/* the swapping chip */}
        <div
          style={{
            transform: `scale(${interpolate(pop, [0, 1], [0.82, 1])})`,
            background: GLASS_HI,
            backdropFilter: "blur(10px)",
            WebkitBackdropFilter: "blur(10px)",
            border: `1px solid ${BORDER}`,
            borderRadius: 18,
            padding: "16px 30px",
            display: "flex",
            alignItems: "center",
            gap: 14,
            boxShadow: `0 16px 44px rgba(0,0,0,0.45), 0 0 22px ${CYAN}22`,
          }}
        >
          <span
            style={{
              fontFamily: FONT,
              fontWeight: 800,
              fontSize: 30,
              backgroundImage: `linear-gradient(90deg, ${CORAL2}, ${CYAN})`,
              WebkitBackgroundClip: "text",
              backgroundClip: "text",
              WebkitTextFillColor: "transparent",
              filter: `drop-shadow(0 0 8px ${CYAN}66)`,
            }}
          >
            ▸
          </span>
          <span style={{ fontFamily: FONT, fontWeight: 700, fontSize: 34, color: WHITE }}>
            {CAPS[idx]}
          </span>
        </div>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Transition sweep — fast neon wipe carrying the next kicker (premium-subtle)
// ---------------------------------------------------------------------------
const TransitionSweep: React.FC<{ kicker: string }> = ({ kicker }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const p = frame / durationInFrames; // 0..1
  // a band that sweeps left->right then out
  const x = interpolate(p, [0, 0.5, 1], [-1.2, 0, 1.2]);
  const bandOpacity = interpolate(p, [0, 0.18, 0.7, 1], [0, 1, 1, 0], {
    extrapolateRight: "clamp",
  });
  const textOpacity = interpolate(p, [0.05, 0.3, 0.7, 0.95], [0, 1, 1, 0], {
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          top: "44%",
          left: 0,
          right: 0,
          height: 4,
          opacity: bandOpacity,
          background: `linear-gradient(90deg, transparent, ${CORAL2}, ${CYAN}, transparent)`,
          boxShadow: `0 0 22px ${CYAN}aa`,
          transform: `translateX(${x * 60}%)`,
        }}
      />
      <div
        style={{
          opacity: textOpacity,
          transform: `translateY(${interpolate(p, [0, 1], [10, -10])}px)`,
          fontFamily: FONT,
          fontWeight: 800,
          fontSize: 44,
          letterSpacing: 6,
          backgroundImage: `linear-gradient(90deg, ${CORAL2}, ${CYAN})`,
          WebkitBackgroundClip: "text",
          backgroundClip: "text",
          WebkitTextFillColor: "transparent",
          filter: `drop-shadow(0 0 16px ${CYAN}77) drop-shadow(0 0 10px ${CORAL}55)`,
        }}
      >
        {kicker}
      </div>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// Neon kinetic Thai captions — phrase at bottom, spoken word glows coral→cyan
// ---------------------------------------------------------------------------
const PhraseView: React.FC<{ phrase: CaptionPhrase }> = ({ phrase }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tMs = phrase.startMs + (frame / fps) * 1000;
  const inn = spring({ frame, fps, config: { damping: 20, stiffness: 130 } });
  // walk tokens (with whitespace) preserving original spacing; map each
  // non-space token to the next word-timing in order.
  let wordIdx = 0;
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: 250 }}>
      <div
        style={{
          maxWidth: 960,
          textAlign: "center",
          padding: "14px 32px",
          borderRadius: 22,
          background: "rgba(6,8,13,0.30)",
          backdropFilter: "blur(2px)",
          WebkitBackdropFilter: "blur(2px)",
          opacity: inn,
          transform: `translateY(${interpolate(inn, [0, 1], [18, 0])}px)`,
          fontFamily: FONT,
          fontWeight: 800,
          fontSize: 62,
          lineHeight: 1.22,
        }}
      >
        {phrase.tokens.map((tok, i) => {
          if (tok.trim() === "") {
            return <span key={i}>{" "}</span>;
          }
          const w = phrase.words[wordIdx];
          wordIdx += 1;
          const active = !!w && tMs >= w.startMs && tMs < w.endMs;
          const past = !!w && tMs >= w.endMs;
          return (
            <span
              key={i}
              style={{
                display: "inline-block",
                transform: active ? "scale(1.06)" : "scale(1)",
                transformOrigin: "center bottom",
                ...(active
                  ? {
                      backgroundImage: `linear-gradient(180deg, ${CORAL2} 0%, ${CYAN} 100%)`,
                      WebkitBackgroundClip: "text",
                      backgroundClip: "text",
                      WebkitTextFillColor: "transparent",
                      color: "transparent",
                      filter: `drop-shadow(0 0 16px ${CYAN}b0) drop-shadow(0 0 10px ${CORAL}88)`,
                    }
                  : {
                      color: past ? WHITE : "rgba(244,247,252,0.86)",
                      textShadow: "0 2px 8px rgba(0,0,0,0.78), 0 0 2px rgba(0,0,0,0.7)",
                    }),
              }}
            >
              {tok}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const NeonCaptions: React.FC<{ phrases: CaptionPhrase[] }> = ({ phrases }) => {
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill>
      {phrases.map((ph, i) => {
        const from = Math.round((ph.startMs / 1000) * fps);
        const nextStart = phrases[i + 1]?.startMs ?? ph.endMs + 300;
        const dur = Math.max(1, Math.round(((nextStart - ph.startMs) / 1000) * fps));
        return (
          <Sequence key={i} from={from} durationInFrames={dur}>
            <PhraseView phrase={ph} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// Main composition
// ---------------------------------------------------------------------------
export const ClaudeTagReel: React.FC<ClaudeTagReelProps> = ({
  videoSrc,
  sceneStarts,
  sceneEnd,
  phrases,
  chipCues,
  statCueMs,
}) => {
  useThaiFonts();
  const { fps } = useVideoConfig();
  const src = videoSrc.startsWith("http") || videoSrc.startsWith("/") ? videoSrc : staticFile(videoSrc);

  const sceneFrames = (i: number) => {
    const start = sceneStarts[i];
    const end = i + 1 < sceneStarts.length ? sceneStarts[i + 1] : sceneEnd;
    return { from: Math.round(start * fps), dur: Math.max(1, Math.round((end - start) * fps)) };
  };

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {/* base footage (muted; original audio re-muxed after render) */}
      <OffthreadVideo src={src} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />

      <FramePolish />
      <TopBugBar />

      {/* per-scene kicker swap in the top bug */}
      {KICKERS.map((k, i) => {
        const { from, dur } = sceneFrames(i);
        const accent = i % 2 === 0 ? CORAL : CYAN;
        return (
          <Sequence key={`kick-${i}`} from={from} durationInFrames={dur}>
            <TopBugKicker text={k} accent={accent} />
          </Sequence>
        );
      })}

      {/* per-scene highlight lower-third / capability cycle (delayed ~0.7s, holds ~4.6s) */}
      {sceneStarts.map((s, i) => {
        const ltFrom = Math.round((s + 0.7) * fps);
        const ltDur = Math.round(4.6 * fps);
        if (i === 2) {
          return (
            <Sequence key={`lt-${i}`} from={Math.round((s + 0.4) * fps)} durationInFrames={Math.round(6.4 * fps)}>
              <CapabilityCycle cues={chipCues} sceneStartMs={Math.round((s + 0.4) * 1000)} />
            </Sequence>
          );
        }
        const d = LT[i];
        if (!d) return null;
        return (
          <Sequence key={`lt-${i}`} from={ltFrom} durationInFrames={ltDur}>
            <LowerThird tag={d.tag} msg={d.msg} cta={d.cta} accent={d.accent} />
          </Sequence>
        );
      })}

      {/* transition cards at each scene cut (carry the NEXT kicker) */}
      {sceneStarts.slice(1).map((s, i) => {
        const at = Math.round((s - 0.28) * fps);
        return (
          <Sequence key={`tr-${i}`} from={at} durationInFrames={Math.round(0.62 * fps)}>
            <TransitionSweep kicker={KICKERS[i + 1]} />
          </Sequence>
        );
      })}

      {/* kinetic Thai captions on top */}
      <NeonCaptions phrases={phrases} />
    </AbsoluteFill>
  );
};
