/**
 * InstructionsCard — S10 (59.319–64.500s). Custom-instructions beat.
 * Mock text field gains a coral focus ring, then the example instruction
 * types in cluster-by-cluster (Thai combining marks stay attached to their
 * base char) with a blinking caret. Dim "optional" note fades in last.
 */
import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {THEME} from '../theme';
import {
  CardStage,
  CLAMP,
  MotionCardProps,
  riseStyle,
  thaiClusters,
  useEnter,
} from './shared';

const TITLE_TH = 'ใส่คำสั่งพิเศษ';
const TITLE_EN = '(Custom Instructions)';
const FIELD_TEXT = 'ตอบเป็นภาษาไทยเสมอ';
const NOTE = 'ไม่ใส่ก็ได้';

const FIELD_AT = 7;
const FOCUS_AT = 15;
const TYPE_START = 20;
const TYPE_FRAMES = 45; // ~1.5s at 30fps
const NOTE_AT = 73;

const CLUSTERS = thaiClusters(FIELD_TEXT);

export const InstructionsCard: React.FC<MotionCardProps> = () => {
  const frame = useCurrentFrame();
  const title = useEnter(0);
  const field = useEnter(FIELD_AT);
  const note = useEnter(NOTE_AT);

  const focus = interpolate(frame, [FOCUS_AT, FOCUS_AT + 6], [0, 1], CLAMP);
  const charCount = Math.floor(
    interpolate(frame, [TYPE_START, TYPE_START + TYPE_FRAMES], [0, CLUSTERS.length], CLAMP),
  );
  const typed = CLUSTERS.slice(0, charCount).join('');
  // Blinking caret — deterministic, 8 frames on / 8 frames off.
  const caretOn = Math.floor(frame / 8) % 2 === 0;

  return (
    <CardStage>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          paddingTop: 64,
        }}
      >
        <div
          style={{
            ...riseStyle(title),
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <div
            style={{
              fontFamily: THEME.fonts.heading,
              fontSize: THEME.type.cardTitle.fontSize,
              fontWeight: THEME.type.cardTitle.fontWeight,
              color: THEME.colors.text,
            }}
          >
            {TITLE_TH}
          </div>
          <div
            style={{
              fontFamily: THEME.fonts.heading,
              fontSize: THEME.type.cardSub.fontSize,
              fontWeight: THEME.type.cardSub.fontWeight,
              color: THEME.colors.textDim,
            }}
          >
            {TITLE_EN}
          </div>
        </div>

        {/* mock text field */}
        <div
          style={{
            marginTop: 72,
            position: 'relative',
            width: 660,
            height: 100,
            borderRadius: 18,
            background: 'rgba(255,255,255,0.045)',
            border: '2px solid rgba(255,255,255,0.10)',
            display: 'flex',
            alignItems: 'center',
            padding: '0 30px',
            opacity: field,
            transform: `translateY(${(1 - field) * 24}px)`,
          }}
        >
          {/* focus ring */}
          <div
            style={{
              position: 'absolute',
              inset: -2,
              borderRadius: 18,
              border: `2px solid ${THEME.colors.accent}`,
              boxShadow: '0 0 32px rgba(232,131,107,0.25)',
              opacity: focus,
              pointerEvents: 'none',
            }}
          />
          <span
            style={{
              fontFamily: THEME.fonts.body,
              fontSize: 32,
              fontWeight: 500,
              color: THEME.colors.text,
              whiteSpace: 'pre',
            }}
          >
            {typed}
          </span>
          <span
            style={{
              width: 3,
              height: 40,
              marginLeft: 3,
              borderRadius: 2,
              background: THEME.colors.accent,
              opacity: caretOn ? 1 : 0,
            }}
          />
        </div>

        <div
          style={{
            marginTop: 44,
            opacity: note,
            transform: `translateY(${(1 - note) * 12}px)`,
            fontFamily: THEME.fonts.body,
            fontSize: 26,
            fontWeight: 400,
            color: THEME.colors.textDim,
          }}
        >
          {NOTE}
        </div>
      </div>
    </CardStage>
  );
};
