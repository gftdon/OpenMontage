/**
 * EndCard — S15 (86.879–90.944s). Outro beat.
 * Coral check draws on (SVG stroke), big line, sub, and a CTA pill with a
 * gentle scale-pulse loop. The outro fade is handled by the parent — this
 * card stays fully visible until the cut.
 */
import React from 'react';
import {useCurrentFrame} from 'remotion';
import {THEME} from '../theme';
import {CardStage, MotionCardProps, riseStyle, useEnter} from './shared';

const BIG = 'ง่ายมากๆ เลย';
const SUB = 'ลองไปทำตามกันดูนะคะ';
const CTA = 'ทำตามได้เลยใน Claude';

const CTA_AT = 14;

export const EndCard: React.FC<MotionCardProps> = () => {
  const frame = useCurrentFrame();
  const ring = useEnter(0, {damping: 16, stiffness: 140, mass: 0.7});
  const check = useEnter(4, {damping: 14, stiffness: 180, mass: 0.6});
  const big = useEnter(4);
  const sub = useEnter(10);
  const cta = useEnter(CTA_AT, {damping: 12, stiffness: 200, mass: 0.5});

  // Gentle pulse loop, kicks in once the entrance has settled.
  const pulseT = Math.max(0, frame - (CTA_AT + 18));
  const pulse = 1 + 0.022 * Math.sin(pulseT * 0.22);

  return (
    <CardStage>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 24,
        }}
      >
        <svg width={110} height={110} viewBox="0 0 110 110">
          <circle
            cx={55}
            cy={55}
            r={46}
            fill="none"
            stroke={THEME.colors.accent}
            strokeWidth={5}
            strokeLinecap="round"
            pathLength={1}
            strokeDasharray={1}
            strokeDashoffset={1 - ring}
            transform="rotate(-90 55 55)"
          />
          <path
            d="M36 57 L50 71 L76 42"
            fill="none"
            stroke={THEME.colors.accent}
            strokeWidth={7}
            strokeLinecap="round"
            strokeLinejoin="round"
            pathLength={1}
            strokeDasharray={1}
            strokeDashoffset={1 - check}
          />
        </svg>

        <div
          style={{
            ...riseStyle(big, 34),
            fontFamily: THEME.fonts.heading,
            fontSize: 88,
            fontWeight: 700,
            color: THEME.colors.text,
            lineHeight: 1.15,
          }}
        >
          {BIG}
        </div>

        <div
          style={{
            ...riseStyle(sub, 18),
            fontFamily: THEME.fonts.body,
            fontSize: THEME.type.cardSub.fontSize,
            fontWeight: THEME.type.cardSub.fontWeight,
            color: THEME.colors.textDim,
          }}
        >
          {SUB}
        </div>

        <div
          style={{
            marginTop: 14,
            opacity: cta,
            transform: `scale(${(0.9 + 0.1 * cta) * pulse})`,
            fontFamily: THEME.fonts.heading,
            fontSize: 30,
            fontWeight: 600,
            color: '#FFFFFF',
            padding: '18px 40px',
            borderRadius: 999,
            background: THEME.colors.accent,
            boxShadow: '0 14px 44px rgba(232,131,107,0.35)',
          }}
        >
          {CTA}
        </div>
      </div>
    </CardStage>
  );
};
