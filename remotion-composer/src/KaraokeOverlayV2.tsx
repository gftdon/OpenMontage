import React, { useEffect, useState } from "react";
import {
  AbsoluteFill,
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
import { CAPTION_PAGES as CAPTION_PAGES_HERMES } from "./hermesFinalCaptions";

const GOLD = "#F59E0B";
const GOLD_LIGHT = "#FDE68A";
const WHITE = "#F8FAFC";
const FONT = '"KanitX", "Kanit", system-ui, -apple-system, sans-serif';

export interface CaptionWord {
  w: string;
  s: number;
  e: number;
}
export interface CaptionPage {
  start: number;
  end: number;
  words: CaptionWord[];
}

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

export const useThaiFonts = () => {
  const [handle] = useState(() => delayRender("thai-fonts"));
  useEffect(() => {
    ensureFonts()
      .then(() => continueRender(handle))
      .catch(() => continueRender(handle));
  }, [handle]);
};

export interface KaraokeOverlayV2Props {
  videoSrc: string;
  pages?: CaptionPage[];
  durationSec?: number;
  bottomPx?: number;
}

export const calculateKaraokeOverlayV2Metadata: CalculateMetadataFunction<
  KaraokeOverlayV2Props
> = ({ props }) => {
  const fps = 25;
  const durationSec = props.durationSec || 110.12;
  return {
    durationInFrames: Math.ceil(durationSec * fps),
    fps,
    width: 1080,
    height: 1920,
  };
};

const isLatin = (s: string) => /^[A-Za-z0-9]/.test(s) || /[A-Za-z0-9]$/.test(s);

export const KaraokeOverlayV2: React.FC<KaraokeOverlayV2Props> = ({
  videoSrc,
  pages = CAPTION_PAGES_HERMES,
  bottomPx = 300,
}) => {
  useThaiFonts();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;

  let pageIdx = -1;
  for (let i = 0; i < pages.length; i++) {
    if (t >= pages[i].start) pageIdx = i;
  }

  const page = pageIdx >= 0 ? pages[pageIdx] : null;

  const enter = page
    ? spring({
        frame: Math.max(0, Math.round((t - page.start) * fps)),
        fps,
        config: { damping: 18, stiffness: 160 },
      })
    : 0;

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      {videoSrc && (
        <OffthreadVideo
          src={videoSrc.startsWith("http") || videoSrc.startsWith("/") ? videoSrc : staticFile(videoSrc)}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />
      )}

      {page && (
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            bottom: bottomPx,
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
              boxShadow:
                "0 8px 32px rgba(0,0,0,0.6), 0 0 20px rgba(56, 189, 248, 0.25)",
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
      )}
    </AbsoluteFill>
  );
};
