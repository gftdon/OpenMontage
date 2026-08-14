/**
 * Bespoke tutorial segments for the Claude CoWork avatar tutorial:
 * S4 (projects overview w/ slow push), S7 (create-project composite with
 * dead-air removed, zoom cuts + freeze hold) and S12 (message-input zoom
 * with synthetic Thai typing). Frame math mirrors edit_decisions.json;
 * startFrom/endAt are in comp-fps units and account for playbackRate
 * (Remotion v4 semantics): source frame = (startFrom + f) * playbackRate.
 */
import React from 'react';
import {Sequence, interpolate, useCurrentFrame} from 'remotion';
import {THEME} from './theme';
import {CLAMP, thaiClusters} from './cards/shared';
import {APP_SCALE, AppWindow, STAGE_CX, STAGE_CY, sourceToStage} from './AppWindow';

const STEPS = 'avatar-tutorial/steps';
const STEP07_FREEZE = 'avatar-tutorial/step07_last.png';

// Zoom focus points measured from assets/images/tutorial_refs/*.png
// (1280x720 source space), mapped into the 920x620 media window.
const NAME_FIELD = sourceToStage(642, 315); // step04 "What are you working on?"
const DESC_FIELD = sourceToStage(642, 407); // step05 "What are you trying to achieve?"
const INPUT_BOX = sourceToStage(591, 177); // step07 message input box

// ---------------------------------------------------------------------------
// S4 — step01 projects overview, src 0.433–9.933s @0.96, slow push 1.0→1.07.
// A pulsing coral ring marks the "New project" button (sets up S7's dialog).
// ---------------------------------------------------------------------------
const S4_FRAMES = 296;
const S4_RING_AT = 30; // ring fades in ~1s into the segment
const S4_RING_PERIOD = 22; // slow pulse, frames per cycle

// "New project" button: src x989-1068, y47-69 (+~4px padding) → stage space.
const NEW_PROJECT_RING = (() => {
  const tl = sourceToStage(985, 43);
  const br = sourceToStage(1072, 73);
  return {left: tl.x, top: tl.y, width: br.x - tl.x, height: br.y - tl.y};
})();

export const ProjectsOverviewSeg: React.FC = () => {
  const frame = useCurrentFrame();
  const scale = interpolate(frame, [0, S4_FRAMES - 1], [1.0, 1.07], CLAMP);
  const ringIn = interpolate(frame, [S4_RING_AT, S4_RING_AT + 8], [0, 1], CLAMP);
  const pulse = 0.5 + 0.5 * Math.sin(((frame - S4_RING_AT) * Math.PI * 2) / S4_RING_PERIOD);
  return (
    <AppWindow
      videoSrc={`${STEPS}/step01_projects_overview.mp4`}
      startFrom={(0.433 * 30) / 0.96}
      endAt={(9.933 * 30) / 0.96}
      playbackRate={0.96}
      scale={scale}
      originX={STAGE_CX}
      originY={STAGE_CY}
    >
      {/* lives in the transform layer so the slow push keeps it glued */}
      <div
        style={{
          position: 'absolute',
          left: NEW_PROJECT_RING.left,
          top: NEW_PROJECT_RING.top,
          width: NEW_PROJECT_RING.width,
          height: NEW_PROJECT_RING.height,
          borderRadius: 8,
          border: `2.5px solid ${THEME.colors.accent}`,
          opacity: ringIn * (0.5 + 0.5 * pulse),
          transform: `scale(${1 + 0.05 * pulse})`,
          transformOrigin: 'center center',
          pointerEvents: 'none',
        }}
      />
    </AppWindow>
  );
};

// ---------------------------------------------------------------------------
// S7 — create-project composite (37.079–48.319s). Cut list from the JSON:
//   step02 0.0–1.1 @1.0 (33f) | step04 0.0–1.2 @1.0 (36f, name zoom 1.25)
//   step05 0.7–2.7 @1.0 (60f, desc zoom 1.18) | step06 0.0–0.967 @1.0 (29f)
//   step07 0.0–2.1 @0.7 (90f) + freeze hold, slow push 1.0→1.05
// The JSON cuts sum to 329f vs the 338f segment — the final freeze hold is
// extended by 9 frames (2.7s → 3.0s) to fill; invisible since it is static.
// ---------------------------------------------------------------------------
const C5_PLAY = 90; // 2.1s src / 0.7 speed
const C5_TOTAL = 180;

const ProjectHomeHold: React.FC = () => {
  const frame = useCurrentFrame();
  const scale = interpolate(frame, [0, C5_TOTAL - 1], [1.0, 1.05], CLAMP);
  return (
    <>
      <Sequence from={0} durationInFrames={C5_PLAY}>
        <AppWindow
          videoSrc={`${STEPS}/step07_project_home_loaded.mp4`}
          startFrom={0}
          endAt={C5_PLAY}
          playbackRate={0.7}
          scale={scale}
        />
      </Sequence>
      <Sequence from={C5_PLAY} durationInFrames={C5_TOTAL - C5_PLAY}>
        <AppWindow imgSrc={STEP07_FREEZE} scale={scale} />
      </Sequence>
    </>
  );
};

export const CreateProjectSeg: React.FC = () => (
  <>
    <Sequence from={0} durationInFrames={33}>
      <AppWindow
        videoSrc={`${STEPS}/step02_open_create_dialog.mp4`}
        startFrom={0}
        endAt={33}
        cursorTone="#0A0A0A"
      />
    </Sequence>
    <Sequence from={33} durationInFrames={36}>
      <AppWindow
        videoSrc={`${STEPS}/step04_fill_project_form.mp4`}
        startFrom={0}
        endAt={36}
        scale={1.25}
        originX={NAME_FIELD.x}
        originY={NAME_FIELD.y}
        cursorTone="#0A0A0A"
      />
    </Sequence>
    <Sequence from={69} durationInFrames={60}>
      <AppWindow
        videoSrc={`${STEPS}/step05_review_filled_form.mp4`}
        startFrom={21}
        endAt={81}
        scale={1.18}
        originX={DESC_FIELD.x}
        originY={DESC_FIELD.y}
        cursorTone="#0A0A0A"
      />
    </Sequence>
    <Sequence from={129} durationInFrames={29}>
      <AppWindow
        videoSrc={`${STEPS}/step06_submit_create_project.mp4`}
        startFrom={0}
        endAt={29}
        cursorTone="#0A0A0A"
      />
    </Sequence>
    <Sequence from={158} durationInFrames={C5_TOTAL}>
      <ProjectHomeHold />
    </Sequence>
  </>
);

// ---------------------------------------------------------------------------
// S12 — step07 project home, src 0.75–2.1s @0.9 (45f) then freeze (147f).
// src_in 0.75 skips the skeleton loading state (loaded home per
// tutorial_segments.json key_events). Slow zoom 1.0→1.2 toward the message
// input box + synthetic Thai typing inside it (starts ~1.2s in, types
// cluster-by-cluster over ~2.5s so combining marks stay attached). Typing
// lands mostly on the frozen frame — desirable.
// ---------------------------------------------------------------------------
const S12_PLAY = 45; // (2.1 - 0.75)s src / 0.9 speed
const S12_TOTAL = 192;
const TYPE_TEXT = 'ช่วยเขียนรายงานประจำเดือนให้หน่อย';
const TYPE_START = 36; // ~1.2s into the segment
const TYPE_FRAMES = 75; // ~2.5s of typing

// Message-text row inside the input box: source x367–815, y140–170 → stage.
const TYPE_ROW = (() => {
  const tl = sourceToStage(367, 140);
  return {left: tl.x, top: tl.y, width: 448 * APP_SCALE, height: 26};
})();

const TypingOverlay: React.FC<{frame: number}> = ({frame}) => {
  const clusters = thaiClusters(TYPE_TEXT);
  const typed = Math.round(
    interpolate(
      frame,
      [TYPE_START, TYPE_START + TYPE_FRAMES],
      [0, clusters.length],
      CLAMP,
    ),
  );
  const caretOn = Math.floor(frame / 15) % 2 === 0; // ~1s blink cycle
  return (
    <div
      style={{
        position: 'absolute',
        left: TYPE_ROW.left,
        top: TYPE_ROW.top,
        width: TYPE_ROW.width,
        height: TYPE_ROW.height,
        display: 'flex',
        alignItems: 'center',
        overflow: 'hidden',
      }}
    >
      <span
        style={{
          fontFamily: THEME.fonts.body,
          fontWeight: 500,
          fontSize: 17,
          lineHeight: '26px',
          color: 'rgba(235,236,238,0.95)',
          whiteSpace: 'pre',
        }}
      >
        {clusters.slice(0, typed).join('')}
      </span>
      <div
        style={{
          flex: 'none',
          width: 2,
          height: 17,
          marginLeft: 1,
          backgroundColor: 'rgba(235,236,238,0.9)',
          opacity: caretOn ? 1 : 0,
        }}
      />
    </div>
  );
};

export const TypePromptSeg: React.FC = () => {
  const frame = useCurrentFrame();
  const zoom = interpolate(frame, [0, S12_TOTAL - 1], [1.0, 1.2], CLAMP);
  return (
    <>
      <Sequence from={0} durationInFrames={S12_PLAY}>
        <AppWindow
          videoSrc={`${STEPS}/step07_project_home_loaded.mp4`}
          startFrom={(0.75 * 30) / 0.9}
          endAt={(2.1 * 30) / 0.9}
          playbackRate={0.9}
          scale={zoom}
          originX={INPUT_BOX.x}
          originY={INPUT_BOX.y}
        >
          <TypingOverlay frame={frame} />
        </AppWindow>
      </Sequence>
      <Sequence from={S12_PLAY} durationInFrames={S12_TOTAL - S12_PLAY}>
        <AppWindow
          imgSrc={STEP07_FREEZE}
          scale={zoom}
          originX={INPUT_BOX.x}
          originY={INPUT_BOX.y}
        >
          <TypingOverlay frame={frame} />
        </AppWindow>
      </Sequence>
    </>
  );
};
