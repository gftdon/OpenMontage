/**
 * UploadFilesCard — S8 (48.319–54.000s). File-upload beat.
 * Three doc chips (Word / Excel / PDF) pop in scattered, then spring-fly one
 * by one into a dashed drop zone with a folder glyph; the zone bumps on each
 * landing. Tag pill fades in last.
 */
import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {THEME} from '../theme';
import {CardStage, CLAMP, MotionCardProps, riseStyle, useEnter} from './shared';

const TITLE = 'อัปโหลดไฟล์ที่เกี่ยวข้อง';
const TAG = 'ให้ Claude มีข้อมูลไว้ทำงาน';

const CHIP_W = 96;
const CHIP_H = 128;

interface ChipSpec {
  label: string;
  x0: number; // px offset from horizontal center
  rot0: number; // degrees
  flyAt: number; // frame the flight starts
}

const CHIPS: ChipSpec[] = [
  {label: 'Word', x0: -250, rot0: -9, flyAt: 13},
  {label: 'Excel', x0: 0, rot0: 5, flyAt: 21},
  {label: 'PDF', x0: 250, rot0: 9, flyAt: 29},
];

const CHIP_TOP = 150; // start row (top edge of chips)
const ZONE_TOP = 330;
const ZONE_H = 190;
const ZONE_W = 400;
const FLY_FRAMES = 16; // spring lead time so it lands ~flyAt+16

const DocChip: React.FC<{label: string}> = ({label}) => (
  <div
    style={{
      width: CHIP_W,
      height: CHIP_H,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: 8,
    }}
  >
    <svg width={76} height={96} viewBox="0 0 76 96">
      {/* sheet */}
      <path
        d="M8 10 a8 8 0 0 1 8-8 h30 l22 22 v62 a8 8 0 0 1-8 8 H16 a8 8 0 0 1-8-8 z"
        fill="rgba(247,242,236,0.94)"
      />
      {/* folded corner */}
      <path d="M46 2 l22 22 H50 a4 4 0 0 1-4-4 z" fill="rgba(13,11,15,0.22)" />
      {/* text lines */}
      {[34, 46, 58].map((y) => (
        <rect
          key={y}
          x={18}
          y={y}
          width={40}
          height={5}
          rx={2.5}
          fill="rgba(13,11,15,0.22)"
        />
      ))}
    </svg>
    <div
      style={{
        fontFamily: THEME.fonts.heading,
        fontSize: 22,
        fontWeight: 600,
        color: THEME.colors.text,
        padding: '4px 14px',
        borderRadius: 8,
        background: 'rgba(255,255,255,0.07)',
        border: `1px solid ${THEME.colors.cardBorder}`,
      }}
    >
      {label}
    </div>
  </div>
);

export const UploadFilesCard: React.FC<MotionCardProps> = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const title = useEnter(0);
  const tag = useEnter(53);

  // Zone scale bumps once per landing (up then back down, clamped).
  const bump = CHIPS.reduce((acc, c) => {
    const land = c.flyAt + FLY_FRAMES;
    const b = interpolate(frame, [land, land + 5, land + 16], [0, 1, 0], CLAMP);
    return Math.max(acc, b);
  }, 0);

  return (
    <CardStage>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          paddingTop: 56,
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
      </div>

      {/* drop zone */}
      <div
        style={{
          position: 'absolute',
          left: '50%',
          top: ZONE_TOP,
          width: ZONE_W,
          height: ZONE_H,
          marginLeft: -ZONE_W / 2,
          borderRadius: 24,
          border: '2px dashed rgba(255,255,255,0.20)',
          background: 'rgba(255,255,255,0.03)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          transform: `scale(${1 + 0.045 * bump})`,
        }}
      >
        <svg width={92} height={72} viewBox="0 0 96 72">
          <path
            d="M8 20 c0-5 4-9 9-9 h20 l8 10 h34 c5 0 9 4 9 9 v24 c0 5-4 9-9 9 H17 c-5 0-9-4-9-9 z"
            fill="rgba(232,131,107,0.10)"
            stroke={THEME.colors.accent}
            strokeWidth={3.5}
            strokeLinejoin="round"
          />
        </svg>
      </div>

      {/* flying file chips */}
      {CHIPS.map((c, i) => {
        const enter = spring({
          frame: frame - (3 + i * 3),
          fps,
          config: THEME.motion.spring,
        });
        const fly = spring({
          frame: frame - c.flyAt,
          fps,
          config: {damping: 17, stiffness: 110, mass: 0.7},
        });
        const gone = interpolate(
          frame,
          [c.flyAt + FLY_FRAMES + 2, c.flyAt + FLY_FRAMES + 12],
          [1, 0],
          CLAMP,
        );
        // start center -> drop-zone center (x: 0 offset, y: zone middle)
        const dx = -c.x0 * fly;
        const dy = (ZONE_TOP + ZONE_H / 2 - (CHIP_TOP + CHIP_H / 2)) * fly;
        return (
          <div
            key={c.label}
            style={{
              position: 'absolute',
              left: '50%',
              top: CHIP_TOP,
              marginLeft: -CHIP_W / 2 + c.x0,
              opacity: enter * gone,
              transform: `translate(${dx}px, ${dy}px) rotate(${
                (1 - fly) * c.rot0
              }deg) scale(${(0.7 + 0.3 * enter) * (1 - 0.45 * fly)})`,
            }}
          >
            <DocChip label={c.label} />
          </div>
        );
      })}

      {/* tag pill */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 26,
          display: 'flex',
          justifyContent: 'center',
        }}
      >
        <div
          style={{
            opacity: tag,
            transform: `translateY(${(1 - tag) * 14}px)`,
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
