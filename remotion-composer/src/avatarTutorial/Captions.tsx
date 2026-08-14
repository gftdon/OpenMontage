import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { THEME } from "./theme";
import { CAPTIONS_TH, CaptionPhrase, CaptionWord } from "./captionsData";
import "./fonts"; // side effect: register Prompt/Sarabun faces at module scope

/**
 * Thai word-highlighted kinetic captions for the Claude CoWork avatar tutorial.
 *
 * Fills its parent (the 920x168 caption band — the parent owns positioning)
 * and centers the active phrase. The word being spoken at the current frame
 * renders in THEME.colors.highlight; the rest in THEME.colors.text. Between
 * phrases nothing renders — the band falls back to the clean background.
 */
export interface CaptionsProps {
  /** Phrase data override; defaults to CAPTIONS_TH (from captions_th.json). */
  phrases?: CaptionPhrase[];
}

// Thai is unspaced — keep spaces only around Latin/number tokens
// ("สร้าง Project บน Claude CoWork"). Mirrors captionTokens in FrangV5Reel.
const isLatin = (s: string) => /^[A-Za-z0-9]/.test(s) || /[A-Za-z0-9]$/.test(s);

const captionTokens = (words: CaptionWord[]) => {
  const out: { text: string; start: number; end: number }[] = [];
  words.forEach((w, i) => {
    const prev = i > 0 ? words[i - 1].w : "";
    const sep = i > 0 && (isLatin(prev) || isLatin(w.w)) ? " " : "";
    out.push({ text: sep + w.w, start: w.start, end: w.end });
  });
  return out;
};

export const Captions: React.FC<CaptionsProps> = ({
  phrases = CAPTIONS_TH.phrases,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  const phrase = phrases.find((p) => t >= p.start && t < p.end);
  if (!phrase) {
    return null; // speech gap — clean background, no caption
  }

  // Pop-in: scale 0.92->1 + opacity 0->1 over THEME.motion.popFrames frames.
  const enter = spring({
    frame: Math.max(0, frame - Math.round(phrase.start * fps)),
    fps,
    config: THEME.motion.spring,
    durationInFrames: THEME.motion.popFrames,
  });
  const scale = interpolate(enter, [0, 1], [0.92, 1]);

  // Active word = the latest word whose start <= t, so the last spoken word
  // holds its highlight through intra-phrase pauses instead of dropping to
  // all-white until the next word begins.
  const activeIdx = phrase.words.reduce(
    (acc, w, i) => (t >= w.start ? i : acc),
    -1,
  );

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          maxWidth: THEME.layout.captionBand.w,
          maxHeight: "100%", // clips anything past 2 lines within the band
          fontFamily: THEME.fonts.heading,
          fontSize: THEME.type.caption.fontSize,
          fontWeight: THEME.type.caption.fontWeight,
          lineHeight: 1.35,
          textAlign: "center",
          textShadow: "0 2px 8px rgba(0,0,0,0.5)",
          color: THEME.colors.text,
          opacity: enter,
          transform: `scale(${scale})`,
        }}
      >
        {captionTokens(phrase.words).map((w, i) => {
          const spoken = i === activeIdx;
          return (
            <span
              key={i}
              style={{
                whiteSpace: "pre",
                color: spoken ? THEME.colors.highlight : THEME.colors.text,
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
