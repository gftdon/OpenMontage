// Test-side builders for schema-3 snapshots and the augmentation of the real V3 frames.
// Nothing here is shipped to production; see README.md in this folder for what each augmentation does.
import fs from 'node:fs';
import { loadThresholds, loadFieldRules } from '../../../qc_layout_eval.mjs';

export const thresholds = loadThresholds();
export const fieldRules = loadFieldRules();

// ---- plan used by the synthetic tests (inside the 5 % safe area: x 96..1824, y 54..1026) ----
// Lane ids are the engine's LANES ids (the text lanes of plan v2); the boxes are roomy synthetic ones.
// The engine plan has no single `header` lane (the header is two lanes, header.brand / header.kicker, whose backings
// are reserved), so PLAN has none either. PLAN_WITH_HEADER adds the synthetic header zone the evaluator also understands.
export const HEADER_ZONE = { x: 116, y: 58, width: 1688, height: 48 };
export const PLAN = {
  planVersion: 2, fps: 25, durationInFrames: 16296, voEndFrame: 16183,
  lanes: {
    'header.brand': { x: 116, y: 58, width: 600, height: 48 },
    'header.kicker': { x: 1204, y: 58, width: 600, height: 48 },
    'split.chrome.url': { x: 116, y: 112, width: 600, height: 52 },
    'wide.chrome.url': { x: 116, y: 112, width: 600, height: 52 },
    'split.chrome.label': { x: 116, y: 186, width: 600, height: 40 },
    'wide.chrome.label': { x: 116, y: 186, width: 600, height: 40 },
    'split.headline': { x: 116, y: 700, width: 1688, height: 72 },
    'wide.headline': { x: 116, y: 700, width: 1688, height: 72 },
    sub: { x: 116, y: 300, width: 400, height: 300 },
    'typo.content': { x: 300, y: 300, width: 1300, height: 300 },
    'full.lowerThird': { x: 116, y: 780, width: 1000, height: 120 },
    'full.cta': { x: 116, y: 805, width: 1688, height: 60 },
    caption: { x: 700, y: 940, width: 600, height: 80 },
    'end.eyebrow': { x: 300, y: 300, width: 1320, height: 60 },
    'end.title': { x: 300, y: 380, width: 1320, height: 100 },
    'end.sub': { x: 300, y: 500, width: 1320, height: 70 },
    'end.cta': { x: 300, y: 600, width: 1320, height: 160 },
  },
};
export const PLAN_WITH_HEADER = { ...PLAN, lanes: { header: HEADER_ZONE, ...Object.fromEntries(Object.entries(PLAN.lanes).filter(([k]) => !k.startsWith('header.'))) } };
export const CTX = { plan: PLAN, fieldRules };
export const CTX_HEADER = { plan: PLAN_WITH_HEADER, fieldRules };

const rect = (x, y, width, height) => ({ x, y, width, height });
export const FULL_FRAME = rect(0, 0, 1920, 1080);

// ---- schema-3 field / snapshot builders ----
export function v3Field(id, over = {}) {
  const tier = over.tier ?? over.role ?? 'read';
  const fontSize = over.fontSize ?? (tier === 'label' ? 28 : 36);
  const x = over.x ?? 100, y = over.y ?? 100, w = over.w ?? 200, h = over.h ?? 40;
  const { x: _x, y: _y, w: _w, h: _h, ...rest } = over;
  return {
    id, role: tier, tier, layer: 'current', text: id, fontSize, opacity: 1,
    rects: [rect(x, y, w, h)], inkRects: [rect(x, y, w, h)], box: rect(x, y, w, h), clipped: false,
    lane: 'any',
    // Thai reference-glyph ink at 0.56 em; /0.7 keeps the rubric a little above the 28/22 floors.
    rubric: { glyph: 'thai', thaiInkPx: fontSize * 0.56, latinInkPx: null, scaleY: 1, rubricPx: null },
    colorAlpha: 1, lineCount: 1, whiteSpace: 'normal', scrollWidth: w, clientWidth: w,
    backing: null,
    ...rest,
  };
}

/** A backing object (field.backing shape) that contains the field's ink with `pad` px of room. */
export function backingFor(f, over = {}, pad = 6) {
  const b = f.box;
  return {
    id: `${f.id}-backing`, path: `div:${f.id}`, alpha: 1, opacity: 1, sameVisibilityAncestry: true,
    box: rect(b.x - pad, b.y - pad, b.width + 2 * pad, b.height + 2 * pad), ...over,
  };
}

export function v3Snap(fields = [v3Field('headline'), v3Field('description', { y: 170 })], over = {}) {
  return {
    schemaVersion: 3, frame: 225, t: 9, phase: 'vo', beatIndex: 3, width: 1920, height: 1080, fontsOk: true,
    transition: false, fields, occluders: [], backings: [],
    layers: [{ kind: 'stage', id: 'stage-3', opacity: 1, box: FULL_FRAME }],
    avatar: null, avatarBacking: { avatar: { box: rect(1340, 128, 464, 690), opacity: 0 }, candidates: [] },
    footage: { origin: 'stock', src: 'desk', credit: false, chrome: false },
    ...over,
  };
}

/**
 * Context for the generic tests (layout / caption / ai): every field in the snapshot is allowed in one
 * big lane "any" with its own tier, so only the rule under test can fire. Lane/tier rules have their
 * own tests in eval_rules.test.mjs with the real qc_field_rules.json.
 */
export function permissiveCtx(snapshot) {
  const rules = {};
  for (const f of snapshot?.fields ?? []) if (f?.id) rules[f.id] = { tier: f.tier ?? f.role, lanes: ['any'], maxLines: 99 };
  return { plan: { lanes: { header: HEADER_ZONE, any: rect(0, 0, 1920, 1080) } }, fieldRules: rules };
}

// ---- real V3 frames (byte-identical copies of the V2-shaped probe output) ----
export const loadRaw = name => JSON.parse(fs.readFileSync(new URL(`./${name}`, import.meta.url), 'utf8'));
export const RAW = {
  6940: 'v3-dark-6940.json', 6941: 'v3-dark-6941.json', 6942: 'v3-dark-6942.json',
  1875: 'v3-headline-semi-1875.json', 1860: 'v3-morph-url-1860.json', 16035: 'v3-cta-16035.json',
};

/** 6940-6942: only the faded-out avatar layer exists (the stage is unmounted in mode "full"). */
export function augmentDark(raw) {
  const a = raw.avatarBacking.avatar;
  return { ...raw, phase: 'vo', layers: [{ kind: 'avatar', id: 'avatar', box: a.box, opacity: a.opacity }] };
}

/** Passing counterpart: the outgoing stage layer is held, fully opaque, over the whole frame. */
export function withHeldStage(s) {
  return { ...s, layers: [...s.layers, { kind: 'stage', id: 'stage-held', box: FULL_FRAME, opacity: 1 }] };
}

/** 1860 / 16035: add `avatar` the way the V4 probe would report the V3 geometry (punch = 1). */
export function augmentPresenter(raw) {
  const a = raw.avatarBacking.avatar;
  const B = a.box;
  const mw = 1920 * B.height / 1080;                                // 16:9 media at card height
  return {
    ...raw, phase: 'vo',
    avatar: { opacity: a.opacity, box: B, mediaBox: rect(B.x + (B.width - mw) / 2, B.y, mw, B.height) },
  };
}

/** Reference-only: the face-box mapping of spec §1c (the probe does this in V4; tests need the numbers). */
export function mapFaceBox(fb, m, aspect) {
  let cw, ch;
  if (m.width / m.height > aspect) { cw = m.width; ch = m.width / aspect; } else { ch = m.height; cw = m.height * aspect; }
  const cx = m.x + (m.width - cw) / 2, cy = m.y + (m.height - ch) / 2;
  return rect(cx + fb.x * cw, cy + fb.y * ch, fb.w * cw, fb.h * ch);
}

/** Bounding box of a field's ink rects. */
export function inkBox(f) {
  const x = Math.min(...f.inkRects.map(r => r.x)), y = Math.min(...f.inkRects.map(r => r.y));
  const r = Math.max(...f.inkRects.map(r => r.x + r.width)), b = Math.max(...f.inkRects.map(r => r.y + r.height));
  return rect(x, y, r - x, b - y);
}

export const clone = o => JSON.parse(JSON.stringify(o));
