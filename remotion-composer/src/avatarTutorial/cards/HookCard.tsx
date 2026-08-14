/**
 * HookCard — S1 (0.000–6.259s). Opening hook.
 * Big two-line title with a coral marker-highlight word, staggered per-line
 * spring entrances (first line starts at frame 0), sub line, and a slowly
 * drifting dot grid + coral orbs for ambient energy.
 */
import React from 'react';
import {Img, staticFile, useCurrentFrame} from 'remotion';
import {THEME} from '../theme';
import {CardStage, MotionCardProps, useEnter} from './shared';

const TITLE_A = 'สร้าง Project';
const TITLE_B = 'บน Claude CoWork';
const HIGHLIGHT = 'แบบง่ายๆ';
const SUB = 'สอนทีละขั้นตอน ทำตามได้เลย';

// Visual-proof PiP: the finished project home slides in ~3.5s (f105) at the
// media window's bottom-right. Sized/positioned to clear every text band
// (measured: sub line ends at media x640, highlight box at ~x582).
const PIP = {w: 240, h: 164, right: 24, bottom: 24, at: 105};

const lineStyle = (v: number): React.CSSProperties => ({
  opacity: v,
  transform: `translateY(${(1 - v) * 40}px) scale(${0.96 + 0.04 * v})`,
});

export const HookCard: React.FC<MotionCardProps> = () => {
  const frame = useCurrentFrame();
  const a = useEnter(0); // first element is already moving by frame 1
  const b = useEnter(3);
  const hl = useEnter(6);
  const sub = useEnter(10);
  const pip = useEnter(PIP.at); // proof preview springs in ~3.5s

  // Ambient drift — deterministic functions of frame.
  const driftX = Math.sin(frame / 50) * 10;
  const driftY = frame * 0.12;
  const orb1X = Math.sin(frame / 70) * 26;
  const orb1Y = Math.cos(frame / 85) * 18;
  const orb2X = Math.cos(frame / 90) * 22;

  return (
    <CardStage>
      {/* drifting dot grid, edges masked out */}
      <div
        style={{
          position: 'absolute',
          inset: -60,
          backgroundImage:
            'radial-gradient(circle, rgba(255,255,255,0.07) 1.5px, transparent 1.5px)',
          backgroundSize: '34px 34px',
          backgroundPosition: `${driftX}px ${driftY}px`,
          maskImage:
            'radial-gradient(ellipse 72% 66% at 50% 44%, black 25%, transparent 78%)',
          WebkitMaskImage:
            'radial-gradient(ellipse 72% 66% at 50% 44%, black 25%, transparent 78%)',
        }}
      />
      {/* soft coral orbs */}
      <div
        style={{
          position: 'absolute',
          left: 90 + orb1X,
          top: 70 + orb1Y,
          width: 240,
          height: 240,
          borderRadius: 999,
          background: 'rgba(232,131,107,0.10)',
          filter: 'blur(70px)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          right: 60 + orb2X,
          bottom: 40,
          width: 200,
          height: 200,
          borderRadius: 999,
          background: 'rgba(232,131,107,0.07)',
          filter: 'blur(60px)',
        }}
      />

      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 18,
        }}
      >
        <div
          style={{
            ...lineStyle(a),
            fontFamily: THEME.fonts.heading,
            fontSize: 92,
            fontWeight: 700,
            color: THEME.colors.text,
            lineHeight: 1.15,
          }}
        >
          {TITLE_A}
        </div>
        <div
          style={{
            ...lineStyle(b),
            fontFamily: THEME.fonts.heading,
            fontSize: 92,
            fontWeight: 700,
            color: THEME.colors.text,
            lineHeight: 1.15,
          }}
        >
          {TITLE_B}
        </div>

        {/* coral marker-highlight word */}
        <div
          style={{
            position: 'relative',
            marginTop: 10,
            opacity: hl,
            transform: `translateY(${(1 - hl) * 20}px)`,
          }}
        >
          <div
            style={{
              position: 'absolute',
              inset: '-6px -22px',
              borderRadius: 14,
              background: 'rgba(232,131,107,0.16)',
              transform: `scaleX(${hl})`,
              transformOrigin: 'left center',
            }}
          />
          <span
            style={{
              position: 'relative',
              fontFamily: THEME.fonts.heading,
              fontSize: 54,
              fontWeight: 700,
              color: THEME.colors.accent,
              lineHeight: 1.3,
            }}
          >
            {HIGHLIGHT}
          </span>
        </div>

        <div
          style={{
            marginTop: 12,
            opacity: sub,
            transform: `translateY(${(1 - sub) * 18}px)`,
            fontFamily: THEME.fonts.body,
            fontSize: THEME.type.cardSub.fontSize,
            fontWeight: THEME.type.cardSub.fontWeight,
            color: THEME.colors.textDim,
          }}
        >
          {SUB}
        </div>
      </div>

      {/* proof PiP — finished project home, bottom-right; -2deg settles to 0.
          The right-edge sliver of the source's parked-cursor glyph is masked
          inside the card (same tone as the app background). */}
      <div
        style={{
          position: 'absolute',
          right: PIP.right,
          bottom: PIP.bottom,
          width: PIP.w,
          height: PIP.h,
          borderRadius: 16,
          overflow: 'hidden',
          border: '1px solid rgba(255,255,255,0.14)',
          boxShadow: '0 12px 32px rgba(0,0,0,0.45)',
          opacity: pip,
          transform: `translateY(${(1 - pip) * 24}px) rotate(${-2 * (1 - pip)}deg)`,
        }}
      >
        <Img
          src={staticFile('avatar-tutorial/step07_last.png')}
          style={{width: '100%', height: '100%', objectFit: 'cover'}}
        />
        <div
          style={{
            position: 'absolute',
            right: -4,
            top: 140,
            width: 10,
            height: 22,
            backgroundColor: '#151515',
          }}
        />
      </div>
    </CardStage>
  );
};
