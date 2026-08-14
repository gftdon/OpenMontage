/**
 * App-window crop + zoom machinery for the Claude CoWork tutorial screen
 * recordings (S4, S7, S12 of edit_decisions.json).
 *
 * The raw step clips are 1280x720 desktop recordings with a pink desktop
 * around the app window (rect x=112, y=4, w=1056, h=714). We scale the full
 * frame by 920/1056 so the app window exactly fills the 920-wide media
 * window (its 714px height lands at ~622px — the bottom ~2px is clipped by
 * the media window's overflow, same as the edit spec's ≈0.871 fit) and shift
 * it so the app window's top-left sits at (0,0).
 */
import React from 'react';
import {AbsoluteFill, Img, OffthreadVideo, staticFile} from 'remotion';
import {THEME} from './theme';

export const APP_SCALE = 920 / 1056;
export const APP_W = 1280 * APP_SCALE; // 1115.15
export const APP_H = 720 * APP_SCALE; // 627.27
export const APP_L = -112 * APP_SCALE; // -97.58
export const APP_T = -4 * APP_SCALE; // -3.49

/** Media-window (920x620) center — default zoom origin. */
export const STAGE_CX = 460;
export const STAGE_CY = 310;

/** Map a 1280x720 source-space point to 920x620 media-window space. */
export const sourceToStage = (sx: number, sy: number) => ({
  x: sx * APP_SCALE + APP_L,
  y: sy * APP_SCALE + APP_T,
});

export interface AppWindowProps {
  /** staticFile() path of the step clip. Omit to render a freeze image. */
  videoSrc?: string;
  /** staticFile() path of a freeze frame (same 1280x720 geometry). */
  imgSrc?: string;
  startFrom?: number;
  endAt?: number;
  playbackRate?: number;
  /** Zoom applied around (originX, originY) in media-window space. */
  scale?: number;
  originX?: number;
  originY?: number;
  /** Fill tone for the parked-cursor mask patch — must match the app
   *  background at the right edge: #151515 normally, #0A0A0A while the
   *  create-project dialog backdrop dims the window (S7 sub-cuts). */
  cursorTone?: string;
  /** Overlays (e.g. synthetic typing) live in media-window space so they
   *  scale with the zoom and stay glued to the UI. */
  children?: React.ReactNode;
}

// A parked I-beam cursor sits at src x1157-1183, y635-701 in every step
// recording; the crop's right edge (src 1168) slices it in half, leaving a
// bright half-glyph flush against the media edge. Mask it with a patch that
// lives INSIDE the transform layer so it follows the S7/S12 zooms.
// Stage rect = sourceToStage of src ~x1151.6+, y627.3-710.2 (with margin).
const CURSOR_PATCH = {left: 905, top: 543, width: 30, height: 72};

export const AppWindow: React.FC<AppWindowProps> = ({
  videoSrc,
  imgSrc,
  startFrom,
  endAt,
  playbackRate,
  scale = 1,
  originX = STAGE_CX,
  originY = STAGE_CY,
  cursorTone = '#151515',
  children,
}) => (
  <AbsoluteFill
    style={{overflow: 'hidden', backgroundColor: THEME.colors.mediaBg}}
  >
    <div
      style={{
        position: 'absolute',
        inset: 0,
        transform: `scale(${scale})`,
        transformOrigin: `${originX}px ${originY}px`,
      }}
    >
      {videoSrc ? (
        <OffthreadVideo
          muted
          src={staticFile(videoSrc)}
          startFrom={startFrom}
          endAt={endAt}
          playbackRate={playbackRate}
          style={{
            position: 'absolute',
            left: APP_L,
            top: APP_T,
            width: APP_W,
            height: APP_H,
            objectFit: 'fill',
          }}
        />
      ) : (
        <Img
          src={staticFile(imgSrc ?? '')}
          style={{
            position: 'absolute',
            left: APP_L,
            top: APP_T,
            width: APP_W,
            height: APP_H,
            objectFit: 'fill',
          }}
        />
      )}
      {/* parked-cursor mask — above the media, below any overlay children */}
      <div
        style={{
          position: 'absolute',
          left: CURSOR_PATCH.left,
          top: CURSOR_PATCH.top,
          width: CURSOR_PATCH.width,
          height: CURSOR_PATCH.height,
          backgroundColor: cursorTone,
        }}
      />
      {children}
    </div>
  </AbsoluteFill>
);
