/**
 * AvatarTutorial — master composition for the Claude CoWork avatar tutorial.
 * 1080x1920 @ 30fps, 2729 frames (90.944s). Assembles the verified piece
 * components (motion cards, captions, tutorial/b-roll media) per
 * projects/claude-cowork-avatar-tutorial/artifacts/edit_decisions.json:
 *
 *   background gradient + coral glow + grain
 *   progress bar (frame/2729)
 *   content card: header chip row + media window (segments) + caption band
 *   avatar zone (cropped 720:544:0:368, cover, persistent)
 *   final_mix.wav from frame 0; fade to #0D0B0F over the last 8 frames
 *
 * Segment timeline (frame-quantized at 30fps, hard cuts only):
 *   S1  hook card      0–188    S6  broll02        954–1112   S11 broll04  1935–2131
 *   S2  broll01      188–332    S7  composite     1112–1450   S12 typing   2131–2323
 *   S3  whatis card  332–509    S8  upload card   1450–1620   S13 memory   2323–2475
 *   S4  step01       509–805    S9  broll03       1620–1780   S14 broll05  2475–2606
 *   S5  chat-vs      805–954    S10 instructions  1780–1935   S15 end card 2606–2729
 */
import React from 'react';
import {
  AbsoluteFill,
  Audio,
  OffthreadVideo,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import {THEME} from './theme';
import {Captions} from './Captions';
import {CLAMP} from './cards/shared';
import {
  HookCard,
  WhatIsCard,
  ChatVsCoworkCard,
  UploadFilesCard,
  InstructionsCard,
  MemoryCard,
  EndCard,
} from './cards';
import {
  ProjectsOverviewSeg,
  CreateProjectSeg,
  TypePromptSeg,
} from './segments';
import './fonts';

const L = THEME.layout;
const C = THEME.colors;
const TOTAL = THEME.canvas.durationFrames; // 2729

// ---------------------------------------------------------------------------
// Chip track — chips hard-swap with segments (null = no chip shown).
// S5+S6 share STEP 2, S8+S9 share STEP 4, S10+S11 share STEP 5.
// ---------------------------------------------------------------------------
interface ChipDef {
  label: string;
  accent: boolean;
}
const CHIP_SEGMENTS: {from: number; to: number; chip: ChipDef | null}[] = [
  {from: 0, to: 188, chip: null}, // S1
  {from: 188, to: 332, chip: null}, // S2
  {from: 332, to: 509, chip: {label: 'เกริ่นก่อน', accent: false}}, // S3
  {from: 509, to: 805, chip: {label: 'STEP 1 · เปิด Claude', accent: true}}, // S4
  {from: 805, to: 1112, chip: {label: 'STEP 2 · เลือกโหมด CoWork', accent: true}}, // S5+S6
  {from: 1112, to: 1450, chip: {label: 'STEP 3 · สร้าง Project', accent: true}}, // S7
  {from: 1450, to: 1780, chip: {label: 'STEP 4 · อัปโหลดไฟล์', accent: true}}, // S8+S9
  {from: 1780, to: 2131, chip: {label: 'STEP 5 · คำสั่งพิเศษ', accent: true}}, // S10+S11
  {from: 2131, to: 2323, chip: {label: 'ขั้นสุดท้าย · พิมพ์สั่งงาน', accent: true}}, // S12
  {from: 2323, to: 2475, chip: {label: 'จุดที่ดีที่สุด', accent: false}}, // S13
  {from: 2475, to: 2606, chip: null}, // S14
  {from: 2606, to: TOTAL, chip: null}, // S15
];

const Chip: React.FC<{chip: ChipDef}> = ({chip}) => (
  <div
    style={{
      display: 'inline-block',
      padding: '10px 22px',
      borderRadius: 999,
      backgroundColor: chip.accent ? C.accentDeep : C.chipNeutral,
      color: chip.accent ? C.chipText : C.textDim,
      fontFamily: THEME.fonts.heading,
      fontSize: THEME.type.chip.fontSize,
      fontWeight: THEME.type.chip.fontWeight,
      letterSpacing: THEME.type.chip.letterSpacing,
      lineHeight: 1.2,
      boxShadow: THEME.shadows.chip,
    }}
  >
    {chip.label}
  </div>
);

// ---------------------------------------------------------------------------
// Chrome — grain, progress bar, avatar zone
// ---------------------------------------------------------------------------
const Grain: React.FC = () => (
  <svg
    width={THEME.canvas.width}
    height={THEME.canvas.height}
    style={{position: 'absolute', inset: 0, opacity: 0.025, pointerEvents: 'none'}}
  >
    <filter id="avatarTutorialGrain">
      <feTurbulence
        type="fractalNoise"
        baseFrequency={0.9}
        numOctaves={2}
        stitchTiles="stitch"
      />
      <feColorMatrix type="saturate" values="0" />
    </filter>
    <rect width="100%" height="100%" filter="url(#avatarTutorialGrain)" />
  </svg>
);

const ProgressBar: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <div
      style={{
        position: 'absolute',
        left: L.progress.x,
        top: L.progress.y,
        width: L.progress.w,
        height: L.progress.h,
        borderRadius: L.progress.h / 2,
        backgroundColor: C.progressTrack,
      }}
    >
      <div
        style={{
          width: (frame / TOTAL) * L.progress.w,
          height: '100%',
          borderRadius: L.progress.h / 2,
          backgroundColor: C.accent,
        }}
      />
    </div>
  );
};

// Avatar: 720x1280 @25fps; crop 720:544:0:368 (white letterbox removed),
// cover-scaled to 1080 wide (x1.5 → 816 tall), translateY(-24px) so the eyes
// sit ~180px below the zone top. Muted — final_mix.wav is the only audio.
const AVATAR_SCALE = 1080 / 720; // 1.5
const AvatarZone: React.FC = () => (
  <div
    style={{
      position: 'absolute',
      left: L.avatar.x,
      top: L.avatar.y,
      width: L.avatar.w,
      height: L.avatar.h,
      overflow: 'hidden',
      boxShadow: '0 -16px 40px rgba(0,0,0,0.35)',
    }}
  >
    <div
      style={{
        position: 'absolute',
        left: 0,
        top: 0,
        width: L.avatar.w,
        height: 544 * AVATAR_SCALE, // 816
        transform: 'translateY(-24px)',
      }}
    >
      <OffthreadVideo
        muted
        src={staticFile('avatar-tutorial/avatar.mp4')}
        style={{
          position: 'absolute',
          left: 0,
          top: -368 * AVATAR_SCALE, // -552
          width: L.avatar.w,
          height: 1280 * AVATAR_SCALE, // 1920
          objectFit: 'fill',
        }}
      />
    </div>
    <div
      style={{
        position: 'absolute',
        left: 0,
        right: 0,
        top: 0,
        height: 1,
        background:
          'linear-gradient(90deg, rgba(255,255,255,0.10), rgba(255,255,255,0.03) 55%, transparent)',
      }}
    />
  </div>
);

// ---------------------------------------------------------------------------
// Media window content — one Sequence per segment, hard cuts.
// ---------------------------------------------------------------------------
const Broll: React.FC<{name: string; frames: number}> = ({name, frames}) => (
  <OffthreadVideo
    muted
    src={staticFile(`avatar-tutorial/broll/${name}.mp4`)}
    startFrom={0}
    endAt={frames}
    style={{width: L.media.w, height: L.media.h, objectFit: 'cover'}}
  />
);

const MediaContent: React.FC = () => (
  <>
    <Sequence from={0} durationInFrames={188}>
      <HookCard durationInFrames={188} />
    </Sequence>
    <Sequence from={188} durationInFrames={144}>
      <Broll name="broll01" frames={144} />
    </Sequence>
    <Sequence from={332} durationInFrames={177}>
      <WhatIsCard durationInFrames={177} />
    </Sequence>
    <Sequence from={509} durationInFrames={296}>
      <ProjectsOverviewSeg />
    </Sequence>
    <Sequence from={805} durationInFrames={149}>
      <ChatVsCoworkCard durationInFrames={149} />
    </Sequence>
    <Sequence from={954} durationInFrames={158}>
      <Broll name="broll02" frames={158} />
    </Sequence>
    <Sequence from={1112} durationInFrames={338}>
      <CreateProjectSeg />
    </Sequence>
    <Sequence from={1450} durationInFrames={170}>
      <UploadFilesCard durationInFrames={170} />
    </Sequence>
    <Sequence from={1620} durationInFrames={160}>
      <Broll name="broll03" frames={160} />
    </Sequence>
    <Sequence from={1780} durationInFrames={155}>
      <InstructionsCard durationInFrames={155} />
    </Sequence>
    <Sequence from={1935} durationInFrames={196}>
      <Broll name="broll04" frames={196} />
    </Sequence>
    <Sequence from={2131} durationInFrames={192}>
      <TypePromptSeg />
    </Sequence>
    <Sequence from={2323} durationInFrames={152}>
      <MemoryCard durationInFrames={152} />
    </Sequence>
    <Sequence from={2475} durationInFrames={131}>
      <Broll name="broll05" frames={131} />
    </Sequence>
    <Sequence from={2606} durationInFrames={123}>
      <EndCard durationInFrames={123} />
    </Sequence>
  </>
);

// ---------------------------------------------------------------------------
// Master
// ---------------------------------------------------------------------------
export const AvatarTutorial: React.FC = () => {
  const frame = useCurrentFrame();
  const chip = CHIP_SEGMENTS.find((s) => frame >= s.from && frame < s.to)?.chip ?? null;
  const outroFade = interpolate(frame, [TOTAL - 8, TOTAL - 1], [0, 1], CLAMP);

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(180deg, ${C.bgTop} 0%, ${C.bgBottom} 100%)`,
      }}
    >
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: `radial-gradient(ellipse 60% 40% at 12% 6%, ${C.glowCoral}, transparent 70%)`,
        }}
      />
      <Grain />
      <ProgressBar />

      {/* Content card chrome */}
      <div
        style={{
          position: 'absolute',
          left: L.card.x,
          top: L.card.y,
          width: L.card.w,
          height: L.card.h,
          borderRadius: L.card.radius,
          backgroundColor: C.card,
          border: `1px solid ${C.cardBorder}`,
          boxShadow: THEME.shadows.card,
          boxSizing: 'border-box',
        }}
      />

      {/* Header chip row */}
      <div
        style={{
          position: 'absolute',
          left: L.header.x,
          top: L.header.y,
          height: L.header.h,
          display: 'flex',
          alignItems: 'center',
        }}
      >
        {chip ? <Chip chip={chip} /> : null}
      </div>

      {/* Media window */}
      <div
        style={{
          position: 'absolute',
          left: L.media.x,
          top: L.media.y,
          width: L.media.w,
          height: L.media.h,
          borderRadius: L.media.radius,
          overflow: 'hidden',
          backgroundColor: C.mediaBg,
          boxShadow: THEME.shadows.media,
        }}
      >
        <MediaContent />
      </div>

      {/* Caption band */}
      <div
        style={{
          position: 'absolute',
          left: L.captionBand.x,
          top: L.captionBand.y,
          width: L.captionBand.w,
          height: L.captionBand.h,
        }}
      >
        <Captions />
      </div>

      <AvatarZone />

      <Audio src={staticFile('avatar-tutorial/final_mix.wav')} />

      {/* Outro fade — last 8 frames to #0D0B0F */}
      <AbsoluteFill
        style={{
          backgroundColor: '#0D0B0F',
          opacity: outroFade,
          pointerEvents: 'none',
        }}
      />
    </AbsoluteFill>
  );
};
