/**
 * WhatIsCard — S3 (11.500–16.960s). Positioning beat.
 * "Not just a chat" (dims, strikethrough draws) -> arrow -> "actually does
 * the work" (bright, coral check draws on) -> tag pill.
 */
import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {THEME} from '../theme';
import {CardStage, CLAMP, MotionCardProps, riseStyle, useEnter} from './shared';

const TITLE = 'Claude CoWork คืออะไร?';
const ROW_A = 'ไม่ใช่แค่แชทตอบคำถาม';
const ROW_B = 'ลงมือทำงานให้เราได้จริง';
const TAG = 'เหมือนมีผู้ช่วยส่วนตัว';

const STRIKE_START = 34;
const STRIKE_END = 46;
const ARROW_AT = 44;
const ROW_B_AT = 52;
const CHECK_AT = 60;
const TAG_AT = 76;

export const WhatIsCard: React.FC<MotionCardProps> = () => {
  const frame = useCurrentFrame();
  const title = useEnter(0);
  const rowA = useEnter(4);
  const arrow = useEnter(ARROW_AT, {damping: 12, stiffness: 200, mass: 0.5});
  const rowB = useEnter(ROW_B_AT);
  const check = useEnter(CHECK_AT, {damping: 11, stiffness: 220, mass: 0.5});
  const tag = useEnter(TAG_AT);

  const strike = interpolate(frame, [STRIKE_START, STRIKE_END], [0, 1], CLAMP);
  const rowADim = interpolate(frame, [STRIKE_START, STRIKE_END], [1, 0.45], CLAMP);

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
          gap: 22,
        }}
      >
        <div
          style={{
            ...riseStyle(title),
            fontFamily: THEME.fonts.heading,
            fontSize: THEME.type.cardTitle.fontSize,
            fontWeight: THEME.type.cardTitle.fontWeight,
            color: THEME.colors.text,
          }}
        >
          {TITLE}
        </div>

        {/* row A — the old way, gets struck through */}
        <div
          style={{
            position: 'relative',
            marginTop: 14,
            opacity: rowA * rowADim,
            transform: `translateY(${(1 - rowA) * 20}px)`,
            fontFamily: THEME.fonts.heading,
            fontSize: THEME.type.cardBody.fontSize,
            fontWeight: THEME.type.cardBody.fontWeight,
            color: THEME.colors.textDim,
            padding: '0 10px',
          }}
        >
          {ROW_A}
          <div
            style={{
              position: 'absolute',
              left: -4,
              right: -4,
              top: '54%',
              height: 3,
              borderRadius: 2,
              background: 'rgba(184,172,164,0.6)',
              transform: `scaleX(${strike})`,
              transformOrigin: 'left center',
            }}
          />
        </div>

        {/* transition arrow */}
        <svg
          width={34}
          height={44}
          viewBox="0 0 34 44"
          style={{
            opacity: arrow,
            transform: `translateY(${(1 - arrow) * -10}px) scale(${0.7 + 0.3 * arrow})`,
          }}
        >
          <path
            d="M17 4 V32 M8 24 L17 34 L26 24"
            stroke={THEME.colors.accent}
            strokeWidth={4}
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
          />
        </svg>

        {/* row B — the new way, bright with coral check */}
        <div
          style={{
            ...riseStyle(rowB, 22),
            display: 'flex',
            alignItems: 'center',
            gap: 16,
          }}
        >
          <svg
            width={44}
            height={44}
            viewBox="0 0 44 44"
            style={{transform: `scale(${0.6 + 0.4 * check})`, opacity: check}}
          >
            <circle cx={22} cy={22} r={20} fill={THEME.colors.accent} />
            <path
              d="M13 22.5 L19.5 29 L31 16.5"
              stroke="#FFFFFF"
              strokeWidth={4}
              strokeLinecap="round"
              strokeLinejoin="round"
              fill="none"
              pathLength={1}
              strokeDasharray={1}
              strokeDashoffset={1 - check}
            />
          </svg>
          <span
            style={{
              fontFamily: THEME.fonts.heading,
              fontSize: THEME.type.cardBody.fontSize,
              fontWeight: 600,
              color: THEME.colors.text,
            }}
          >
            {ROW_B}
          </span>
        </div>

        {/* tag pill */}
        <div
          style={{
            marginTop: 12,
            opacity: tag,
            transform: `translateY(${(1 - tag) * 14}px) scale(${0.94 + 0.06 * tag})`,
            fontFamily: THEME.fonts.heading,
            fontSize: 26,
            fontWeight: 500,
            color: THEME.colors.text,
            padding: '12px 26px',
            borderRadius: 999,
            border: `1px solid ${THEME.colors.cardBorder}`,
            background: 'rgba(255,255,255,0.05)',
          }}
        >
          {TAG}
        </div>
      </div>
    </CardStage>
  );
};
