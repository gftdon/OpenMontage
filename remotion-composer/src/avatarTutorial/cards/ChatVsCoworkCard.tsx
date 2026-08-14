/**
 * ChatVsCoworkCard — S5 (26.819–31.800s). Mode-selection beat.
 * Two big pills; the CoWork pill switches to its selected state ~40% through
 * (scale pulse + coral fill + glow ring), then a hint fades in below.
 */
import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {THEME} from '../theme';
import {CardStage, CLAMP, MotionCardProps, riseStyle, useEnter} from './shared';

const TITLE = 'ที่ช่องพิมพ์ข้อความ';
const OPTION_A = 'Chat';
const OPTION_B = 'CoWork';
const HINT = 'กดเลือก CoWork';

const PILL_W = 300;
const PILL_H = 116;

export const ChatVsCoworkCard: React.FC<MotionCardProps> = ({durationInFrames}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames: configDuration} = useVideoConfig();
  // Prop is the source of truth; fall back to the surrounding Sequence length.
  const total = durationInFrames ?? configDuration;
  const selectAt = Math.round(total * 0.4);

  const title = useEnter(0);
  const pills = useEnter(4);
  const hint = useEnter(selectAt + 8);

  // Selection: quick fill, springy scale pulse, one expanding glow ring.
  const fill = interpolate(frame, [selectAt, selectAt + 8], [0, 1], CLAMP);
  const pulse = spring({
    frame: frame - selectAt,
    fps,
    config: {damping: 11, stiffness: 220, mass: 0.5},
  });
  const scale = 1 + 0.06 * pulse;
  const ringT = interpolate(frame, [selectAt, selectAt + 20], [0, 1], CLAMP);

  const pillBase: React.CSSProperties = {
    width: PILL_W,
    height: PILL_H,
    borderRadius: 999,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontFamily: THEME.fonts.heading,
    fontSize: 44,
    fontWeight: 600,
    position: 'relative',
  };

  return (
    <CardStage>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          paddingTop: 74,
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

        <div
          style={{
            display: 'flex',
            gap: 32,
            marginTop: 88,
            opacity: pills,
            transform: `translateY(${(1 - pills) * 30}px)`,
          }}
        >
          {/* Chat — stays neutral */}
          <div
            style={{
              ...pillBase,
              color: THEME.colors.textDim,
              border: '2px solid rgba(255,255,255,0.12)',
              background: 'rgba(255,255,255,0.04)',
            }}
          >
            {OPTION_A}
          </div>

          {/* CoWork — selected state animates in */}
          <div style={{position: 'relative'}}>
            {/* expanding glow ring */}
            <div
              style={{
                position: 'absolute',
                inset: 0,
                borderRadius: 999,
                border: `3px solid ${THEME.colors.accent}`,
                opacity: (1 - ringT) * 0.55 * fill,
                transform: `scale(${1 + ringT * 0.45})`,
                pointerEvents: 'none',
              }}
            />
            <div
              style={{
                ...pillBase,
                transform: `scale(${scale})`,
                border: `2px solid rgba(232,131,107,${0.25 + 0.75 * fill})`,
                background: 'rgba(255,255,255,0.04)',
                boxShadow: `0 14px 44px rgba(232,131,107,${0.32 * fill})`,
              }}
            >
              {/* coral fill washes in */}
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  borderRadius: 999,
                  background: THEME.colors.accent,
                  opacity: fill,
                }}
              />
              <span
                style={{
                  position: 'relative',
                  color: fill > 0.5 ? '#FFFFFF' : THEME.colors.textDim,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                }}
              >
                <svg
                  width={30}
                  height={30}
                  viewBox="0 0 30 30"
                  style={{opacity: fill}}
                >
                  <path
                    d="M7 15.5 L12.5 21 L23 9.5"
                    stroke="#FFFFFF"
                    strokeWidth={3.5}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    fill="none"
                    pathLength={1}
                    strokeDasharray={1}
                    strokeDashoffset={1 - fill}
                  />
                </svg>
                {OPTION_B}
              </span>
            </div>
          </div>
        </div>

        <div
          style={{
            marginTop: 64,
            opacity: hint,
            transform: `translateY(${(1 - hint) * 14}px)`,
            fontFamily: THEME.fonts.body,
            fontSize: THEME.type.cardSub.fontSize,
            fontWeight: THEME.type.cardSub.fontWeight,
            color: THEME.colors.textDim,
            display: 'flex',
            alignItems: 'center',
            gap: 12,
          }}
        >
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: 999,
              background: THEME.colors.accent,
              display: 'inline-block',
            }}
          />
          {HINT}
        </div>
      </div>
    </CardStage>
  );
};
