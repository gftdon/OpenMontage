import React from "react";
import { AbsoluteFill, OffthreadVideo, staticFile, CalculateMetadataFunction } from "remotion";
import { KaraokeCaptionLane, useThaiFonts } from "./KaraokeCaptionLane";
import { CAPTION_PAGES } from "./v260821Captions";

export interface V260821ReelProps {
  videoSrc?: string;
  bottomPx?: number;
}

export const calculateV260821Metadata: CalculateMetadataFunction<V260821ReelProps> = () => {
  const fps = 25;
  const durationSec = 105.88;
  return {
    durationInFrames: Math.ceil(durationSec * fps),
    fps,
    width: 1080,
    height: 1920,
  };
};

export const V260821Reel: React.FC<V260821ReelProps> = ({
  videoSrc = "V260821_001_30_Merged.mp4",
  bottomPx = 300,
}) => {
  useThaiFonts();

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      {videoSrc && (
        <OffthreadVideo
          src={videoSrc.startsWith("http") || videoSrc.startsWith("/") ? videoSrc : staticFile(videoSrc)}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />
      )}
      <KaraokeCaptionLane pages={CAPTION_PAGES} bottomPx={bottomPx} />
    </AbsoluteFill>
  );
};
