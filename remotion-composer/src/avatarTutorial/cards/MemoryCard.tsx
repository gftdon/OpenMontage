/**
 * MemoryCard — S13 (77.439–82.500s). Persistent-context beat.
 * Iconographic treatment: coral folder with a bookmark ribbon, a soft ring,
 * and a single dot orbiting on a slow ellipse. Sub line + coral-outline tag.
 */
import React from 'react';
import {useCurrentFrame} from 'remotion';
import {THEME} from '../theme';
import {CardStage, MotionCardProps, riseStyle, useEnter} from './shared';

const TITLE = 'Claude จำบริบทของ Project ไว้';
const SUB = 'เปิดกลับมาใช้ใหม่ได้ทุกเมื่อ';
const TAG = 'ไม่ต้องอธิบายซ้ำ';

export const MemoryCard: React.FC<MotionCardProps> = () => {
  const frame = useCurrentFrame();
  const title = useEnter(0);
  const icon = useEnter(2, {damping: 13, stiffness: 150, mass: 0.6});
  const sub = useEnter(8);
  const tag = useEnter(14);

  // Orbiting dot — deterministic slow ellipse around the folder.
  const t = frame * 0.045;
  const dotX = 100 + 84 * Math.cos(t);
  const dotY = 100 + 30 * Math.sin(t);

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
          gap: 18,
        }}
      >
        <div
          style={{
            ...riseStyle(title),
            maxWidth: 800,
            textAlign: 'center',
            fontFamily: THEME.fonts.heading,
            fontSize: THEME.type.cardTitle.fontSize,
            fontWeight: THEME.type.cardTitle.fontWeight,
            color: THEME.colors.text,
            lineHeight: 1.3,
          }}
        >
          {TITLE}
        </div>

        <svg
          width={200}
          height={200}
          viewBox="0 0 200 200"
          style={{
            opacity: icon,
            transform: `scale(${0.82 + 0.18 * icon})`,
          }}
        >
          {/* soft ring */}
          <circle
            cx={100}
            cy={100}
            r={62}
            fill="none"
            stroke="rgba(232,131,107,0.18)"
            strokeWidth={2}
          />
          {/* orbit path */}
          <ellipse
            cx={100}
            cy={100}
            rx={84}
            ry={30}
            fill="none"
            stroke="rgba(255,255,255,0.10)"
            strokeWidth={1.5}
          />
          {/* folder */}
          <path
            d="M60 82 c0-5 4-9 9-9 h22 l8 10 h32 c5 0 9 4 9 9 v30 c0 5-4 9-9 9 H69 c-5 0-9-4-9-9 z"
            fill="rgba(232,131,107,0.10)"
            stroke={THEME.colors.accent}
            strokeWidth={4}
            strokeLinejoin="round"
          />
          {/* bookmark ribbon over the folder's top edge */}
          <path
            d="M114 64 h17 v32 l-8.5-6.5 L114 96 z"
            fill={THEME.colors.accent}
          />
          {/* orbiting dot */}
          <circle cx={dotX} cy={dotY} r={7} fill={THEME.colors.accent} />
        </svg>

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
            opacity: tag,
            transform: `translateY(${(1 - tag) * 14}px) scale(${0.94 + 0.06 * tag})`,
            fontFamily: THEME.fonts.heading,
            fontSize: 26,
            fontWeight: 500,
            color: THEME.colors.accent,
            padding: '12px 26px',
            borderRadius: 999,
            border: '1.5px solid rgba(232,131,107,0.55)',
            background: 'rgba(232,131,107,0.08)',
          }}
        >
          {TAG}
        </div>
      </div>
    </CardStage>
  );
};
