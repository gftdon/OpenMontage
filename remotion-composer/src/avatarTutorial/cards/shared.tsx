/**
 * Shared building blocks for the avatar-tutorial motion cards.
 * Every card renders inside THEME.layout.media (920x620); the parent rounds
 * the corners (overflow hidden), so cards must NOT add an outer radius.
 */
import React from 'react';
import {AbsoluteFill, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {THEME} from '../theme';
import '../fonts';

export interface MotionCardProps {
  durationInFrames: number;
}

export const CLAMP = {
  extrapolateLeft: 'clamp',
  extrapolateRight: 'clamp',
} as const;

/** Spring 0 -> 1 entrance, deterministic by frame. `delay` in frames. */
export const useEnter = (
  delay = 0,
  config: {damping: number; stiffness: number; mass: number} = THEME.motion.spring,
): number => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return spring({frame: frame - delay, fps, config});
};

/** Fade + rise style from a 0 -> 1 progress value. */
export const riseStyle = (v: number, dy = 26): React.CSSProperties => ({
  opacity: v,
  transform: `translateY(${(1 - v) * dy}px)`,
});

/**
 * Card background: mediaBg with a subtle coral radial glow.
 * The media window's rounded corners come from the parent — no radius here.
 */
export const CardStage: React.FC<{children: React.ReactNode}> = ({children}) => (
  <AbsoluteFill style={{backgroundColor: THEME.colors.mediaBg}}>
    <div
      style={{
        position: 'absolute',
        inset: 0,
        background:
          'radial-gradient(ellipse 72% 56% at 18% 0%, rgba(216,119,87,0.15), transparent 65%),' +
          'radial-gradient(ellipse 56% 46% at 88% 100%, rgba(216,119,87,0.07), transparent 70%)',
      }}
    />
    {children}
  </AbsoluteFill>
);

/**
 * Split a Thai string into grapheme-ish clusters (base char + combining
 * marks) so character-by-character typing never detaches a combining mark
 * (็ ่ ้ ๊ ๋ ิ ี ฯลฯ) from its base character.
 */
// MAI HAN-AKAT, SARA I..SARA UUE, MAITAIKHU..YAMAKKAN — explicit code points.
const THAI_COMBINING = new RegExp('[\\u0E31\\u0E34-\\u0E3A\\u0E47-\\u0E4E]', 'u');
export const thaiClusters = (text: string): string[] => {
  const clusters: string[] = [];
  for (const ch of Array.from(text)) {
    if (clusters.length > 0 && THAI_COMBINING.test(ch)) {
      clusters[clusters.length - 1] += ch;
    } else {
      clusters.push(ch);
    }
  }
  return clusters;
};
