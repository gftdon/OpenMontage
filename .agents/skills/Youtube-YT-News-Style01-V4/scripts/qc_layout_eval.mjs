// qc_layout_eval.mjs — layout gate rules for the YtNewsStyle01V4 probe (schema v3).
//
// Every rule is a pure function  rule<Name>(snapshot, thresholds, ctx) -> issue[]
// so a test can call a single rule on a hand-built or augmented snapshot.
// evaluateLayout() runs all per-frame rules; production requires schemaVersion === 3.
//
//   ctx = { plan, fieldRules }
//     plan.lanes       { "<laneId>": {x,y,width,height} }   (from __QC_PLAN__)
//     fieldRules       contents of qc_field_rules.json       (id -> {tier, lanes, maxLines})
//
// Issue shape (all rules):
//   { id, code, frame, field?, message, detail, ...numbers used by the rule }
//   `code` mirrors `id` and `detail` keeps the old meaning (field id / short text) so that
//   code written against the earlier `{code, detail}` issues keeps working.
//
// Shared vocabulary
//   visible          field.opacity >= t.visibleOpacity
//   effAlpha(b)      b.alpha * b.opacity                     (0 when there is no backing)
//   backedEff(f)     the field's own backing is effectively opaque, shares the field's visibility
//                    ancestry and contains every ink rect of the field.

import fs from 'node:fs';

// ---------------------------------------------------------------------------------------------
// Loading helpers (the rules themselves never touch the file system)
// ---------------------------------------------------------------------------------------------

export function loadThresholds(url = new URL('./qc_thresholds.json', import.meta.url)) {
  return JSON.parse(fs.readFileSync(url, 'utf8'));
}

export function loadFieldRules(url = new URL('./qc_field_rules.json', import.meta.url)) {
  return JSON.parse(fs.readFileSync(url, 'utf8'));
}

/**
 * Looks a field id up in the field-rules table.
 * Exact id first; then prefix patterns written as "typo-*" / "stat-*" (longest prefix wins).
 * Keys starting with "_" (e.g. "_status") are metadata, never rules.
 */
export function resolveFieldRule(fieldRules, id) {
  if (!fieldRules || typeof id !== 'string') return null;
  if (!id.startsWith('_') && Object.hasOwn(fieldRules, id) && !id.endsWith('*')) return fieldRules[id];
  let best = null;
  for (const key of Object.keys(fieldRules)) {
    if (key.startsWith('_') || !key.endsWith('*')) continue;
    const prefix = key.slice(0, -1);
    if (id.startsWith(prefix) && (best === null || prefix.length > best.length)) best = prefix;
  }
  return best === null ? null : fieldRules[`${best}*`];
}

// ---------------------------------------------------------------------------------------------
// Geometry + issue helpers
// ---------------------------------------------------------------------------------------------

const EPS = 1e-9;
const RECT_KEYS = ['x', 'y', 'width', 'height'];

const finiteRect = r => !!r && RECT_KEYS.every(k => Number.isFinite(r[k])) && r.width > 0 && r.height > 0;

// Two rects overlap by more than half a pixel on both axes (same tolerance as the V2 rules).
const intersects = (a, b) =>
  Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x) > 0.5 &&
  Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y) > 0.5;

// Intersection rectangle of a and b, or null when it is empty.
function intersection(a, b) {
  const x = Math.max(a.x, b.x);
  const y = Math.max(a.y, b.y);
  const right = Math.min(a.x + a.width, b.x + b.width);
  const bottom = Math.min(a.y + a.height, b.y + b.height);
  return right > x && bottom > y ? { x, y, width: right - x, height: bottom - y } : null;
}

// Every ink rect lies inside `box` (tolerance `tol` px).
const inkInside = (inkRects, box, tol) =>
  Array.isArray(inkRects) && inkRects.length > 0 && finiteRect(box) &&
  inkRects.every(r =>
    r.x >= box.x - tol && r.y >= box.y - tol &&
    r.x + r.width <= box.x + box.width + tol && r.y + r.height <= box.y + box.height + tol);

const inkOf = f => f.inkRects ?? f.rects;
const tierOf = f => f.tier ?? f.role;           // `role` mirrors `tier` for the older rules
const hasInk = f => (inkOf(f) ?? []).some(finiteRect);

// opacityOf: the opacity the probe measured on the element (already multiplied through ancestors).
const opacityOf = f => f.opacity;
const isVisible = (f, t) => opacityOf(f) >= t.visibleOpacity;

/** Effective alpha of a backing: its own background alpha times its (ancestor-multiplied) opacity. */
export const effAlpha = b => (b ? b.alpha * b.opacity : 0);

/**
 * The field is backed by an effectively opaque backing that fades with the field and covers its ink.
 *   effAlpha(backing) >= t.minBackingEffAlpha
 *   && backing.sameVisibilityAncestry && every ink rect inside backing.box (0.5 px)
 */
export function backedEff(f, t) {
  const b = f.backing;
  return !!b &&
    effAlpha(b) >= t.minBackingEffAlpha - EPS &&
    b.sameVisibilityAncestry === true &&
    inkInside(f.inkRects, b.box, 0.5);
}

// Legacy export kept for callers that only have a backing object + ink rects.
// Now uses the effective alpha (the V2 shared-fade acceptance was inverted, see tests).
export function backingPresent(backing, inkRects, t = { minBackingEffAlpha: 0.9 }) {
  return backedEff({ backing, inkRects }, t);
}

function issue(s, id, message, extra = {}) {
  const { field, detail, ...numbers } = extra;
  const out = { id, code: id, frame: s?.frame, message, detail: detail ?? field ?? message };
  if (field !== undefined) out.field = field;
  return Object.assign(out, numbers);
}

const roundN = (n, d = 4) => (Number.isFinite(n) ? Math.round(n * 10 ** d) / 10 ** d : n);

// ---------------------------------------------------------------------------------------------
// Snapshot helpers
// ---------------------------------------------------------------------------------------------

// A field the probe measured completely. Incomplete fields are reported by ruleGeometry and then
// skipped by every other rule (same behaviour as V2).
function fieldGeometryOk(f, s) {
  if (!f || !f.id || !f.text || !['read', 'label'].includes(f.role) ||
      !Number.isFinite(f.opacity) || !Number.isFinite(f.fontSize) ||
      !Array.isArray(f.rects) || !f.rects.length || !f.rects.every(finiteRect)) return false;
  if (s.schemaVersion >= 2 &&
      (!finiteRect(f.box) || !Array.isArray(f.inkRects) || !f.inkRects.length || !f.inkRects.every(finiteRect))) return false;
  return true;
}

const validFields = s => (Array.isArray(s.fields) ? s.fields : []).filter(f => fieldGeometryOk(f, s));
const visibleFields = (s, t) => validFields(s).filter(f => isVisible(f, t));

// Fields covered by an opaque-enough occluder painted in front of them (used by credit / ai-label).
function coveredFieldIds(s, t) {
  const covered = new Set();
  for (const o of s.occluders ?? []) {
    if (!finiteRect(o.box) || !Number.isFinite(o.opacity) || !Array.isArray(o.frontOf)) continue;
    if (o.opacity < t.visibleOpacity) continue;
    for (const f of visibleFields(s, t)) {
      if (o.frontOf.includes(f.id) && inkOf(f).some(r => intersects(r, o.box))) covered.add(f.id);
    }
  }
  return covered;
}

// Reports a missing ctx part once, so rules that need the plan / field rules fail closed.
function ctxProblem(s, ctx, needs) {
  const missing = [];
  if (needs.includes('plan') && !(ctx?.plan?.lanes && typeof ctx.plan.lanes === 'object')) missing.push('plan.lanes');
  if (needs.includes('fieldRules') && !(ctx?.fieldRules && typeof ctx.fieldRules === 'object')) missing.push('fieldRules');
  return missing.length ? [issue(s, 'ctx-missing', `rule context is missing ${missing.join(', ')}`)] : null;
}

// ---------------------------------------------------------------------------------------------
// Snapshot-level rules
// ---------------------------------------------------------------------------------------------

/** schemaVersion must be 3 and the v3 arrays must exist. Returns at most one issue. */
export function ruleSchema(s, t, ctx) {
  const missing = [];
  if (s.schemaVersion !== 3) missing.push(`schemaVersion=${s.schemaVersion} (need 3)`);
  else {
    for (const key of ['fields', 'occluders', 'backings', 'layers']) if (!Array.isArray(s[key])) missing.push(key);
    if (s.avatar === undefined) missing.push('avatar');
    if (!['vo', 'endcard'].includes(s.phase)) missing.push('phase');
  }
  return missing.length ? [issue(s, 'schema', `probe schema v3 required: ${missing.join(', ')}`)] : [];
}

/** fonts: the probe could not confirm that the fonts were loaded. */
export function ruleFonts(s) {
  return s.fontsOk === true ? [] : [issue(s, 'fonts', 'fonts not ready')];
}

/** fields: no text measurements at all. */
export function ruleFields(s) {
  return Array.isArray(s.fields) && s.fields.length ? [] : [issue(s, 'fields', 'missing text measurements')];
}

/**
 * probe-issues: problems the in-page probe itself detected (`untagged-text`, `unsupported-transform`, ...).
 * snapshot.probeIssues = [{id, field?, message}]; absent or empty means no issue. Each entry becomes a
 * gate issue with the same id, so the engine cannot hide what the probe saw.
 */
export function ruleProbeIssues(s) {
  if (s.probeIssues === undefined || s.probeIssues === null) return [];
  if (!Array.isArray(s.probeIssues)) return [issue(s, 'probe-issues', 'probeIssues must be an array')];
  return s.probeIssues.map(p => {
    const id = typeof p?.id === 'string' && p.id ? p.id : 'probe-issues';
    const message = typeof p?.message === 'string' && p.message ? p.message : `probe reported ${id}`;
    return issue(s, id, message, p?.field === undefined ? {} : { field: p.field });
  });
}

/** geometry: a field (or occluder) lacks complete, finite measurements. */
export function ruleGeometry(s) {
  const out = [];
  for (const f of s.fields ?? []) {
    if (!fieldGeometryOk(f, s)) out.push(issue(s, 'geometry', 'incomplete field measurement', { field: f?.id, detail: f?.id }));
  }
  for (const o of s.occluders ?? []) {
    if (!finiteRect(o.box) || !Number.isFinite(o.opacity) || !Array.isArray(o.frontOf)) {
      out.push(issue(s, 'geometry', 'incomplete occluder measurement', { detail: `occluder ${o.id}` }));
    }
  }
  return out;
}

// ---------------------------------------------------------------------------------------------
// Typography
// ---------------------------------------------------------------------------------------------

/** font: CSS font size under the tier floor (read 36 px / label 28 px). */
export function ruleFont(s, t) {
  const out = [];
  for (const f of visibleFields(s, t)) {
    const floor = tierOf(f) === 'label' ? t.labelFontPx : t.readFontPx;
    if (f.fontSize < floor - 0.01) {
      out.push(issue(s, 'font', `font ${f.fontSize}px < ${floor}px`, { field: f.id, fontSize: f.fontSize, floor }));
    }
  }
  return out;
}

/**
 * Rubric size of a field = min(applicable reference-glyph ink) * scaleY / t.rubricInkDivisor.
 * Thai text uses the Thai reference glyph, Latin/digits the Latin one, mixed the smaller of the two.
 * Returns null when the field has no measurable script (glyph "none").
 * `computed:false` means the ink numbers were missing and the probe's own rubricPx was used.
 */
export function rubricSize(rubric, t) {
  if (!rubric || typeof rubric !== 'object') return undefined;
  if (rubric.glyph === 'none') return null;
  const inks = [];
  if (rubric.glyph === 'thai' || rubric.glyph === 'mixed') inks.push(rubric.thaiInkPx);
  if (rubric.glyph === 'latin' || rubric.glyph === 'mixed') inks.push(rubric.latinInkPx);
  const usable = inks.filter(Number.isFinite);
  if (usable.length && usable.length === inks.length && Number.isFinite(rubric.scaleY) && t.rubricInkDivisor > 0) {
    return Math.min(...usable) * rubric.scaleY / t.rubricInkDivisor;
  }
  return Number.isFinite(rubric.rubricPx) ? rubric.rubricPx : undefined;
}

/** font-rubric: rubric size under the tier floor (read 28 / label 22). Fails closed when unmeasurable. */
export function ruleFontRubric(s, t) {
  const out = [];
  for (const f of visibleFields(s, t)) {
    const size = rubricSize(f.rubric, t);
    if (size === null) continue;                                    // no Thai/Latin glyph: only the CSS floor applies
    if (size === undefined) {
      out.push(issue(s, 'font-rubric', 'rubric measurement missing', { field: f.id }));
      continue;
    }
    const floor = tierOf(f) === 'label' ? t.labelRubricPx : t.readRubricPx;
    if (size < floor) {
      out.push(issue(s, 'font-rubric', `rubric ${roundN(size, 2)}px < ${floor}px`, { field: f.id, rubricPx: roundN(size, 3), floor }));
    }
  }
  return out;
}

/** tier-missing / tier-mismatch / unknown-field: every field must be in the table with the right tier. */
export function ruleTier(s, t, ctx) {
  const bad = ctxProblem(s, ctx, ['fieldRules']);
  if (bad) return bad;
  const out = [];
  for (const f of s.fields ?? []) {
    if (!f?.id) continue;
    const rule = resolveFieldRule(ctx.fieldRules, f.id);
    if (!rule) out.push(issue(s, 'unknown-field', `field "${f.id}" is not in qc_field_rules`, { field: f.id }));
    if (f.tier !== 'read' && f.tier !== 'label') {
      out.push(issue(s, 'tier-missing', `field "${f.id}" has no data-qc-tier`, { field: f.id, tier: f.tier ?? null }));
    } else if (rule && f.tier !== rule.tier) {
      out.push(issue(s, 'tier-mismatch', `tier ${f.tier} != ${rule.tier}`, { field: f.id, tier: f.tier, expected: rule.tier }));
    }
  }
  return out;
}

/**
 * text-alpha: read text drawn with a translucent colour (the colour's own alpha < t.minReadTextAlpha, e.g. V3's CREAM_DIM .62).
 * Element opacity is deliberately NOT part of this rule: it is also what an entrance / exit fade animates, and a fade inside an opaque
 * backing is not a legibility defect. Text over the presenter and its backing are covered by the opacity-aware backedEff rules
 * (backing, presenter-text-backing), which is where a half-transparent label really matters.
 */
export function ruleTextAlpha(s, t) {
  const out = [];
  for (const f of visibleFields(s, t)) {
    if (tierOf(f) !== 'read') continue;
    if (!Number.isFinite(f.colorAlpha)) {
      out.push(issue(s, 'text-alpha', 'colorAlpha missing', { field: f.id }));
      continue;
    }
    const alpha = f.colorAlpha;
    if (alpha < t.minReadTextAlpha - EPS) {
      out.push(issue(s, 'text-alpha', `text colour alpha ${roundN(alpha)} < ${t.minReadTextAlpha}`, { field: f.id, colorAlpha: f.colorAlpha, opacity: f.opacity, alpha: roundN(alpha) }));
    }
  }
  return out;
}

/** line-count: the text wrapped onto more lines than allowed (fieldRules[id].maxLines). */
export function ruleLineCount(s, t, ctx) {
  const bad = ctxProblem(s, ctx, ['fieldRules']);
  if (bad) return bad;
  const out = [];
  for (const f of visibleFields(s, t)) {
    const rule = resolveFieldRule(ctx.fieldRules, f.id);
    if (!rule) continue;                                            // unknown-field is reported by ruleTier
    if (!Number.isFinite(f.lineCount)) {
      out.push(issue(s, 'line-count', 'lineCount missing', { field: f.id }));
    } else if (f.lineCount > rule.maxLines) {
      out.push(issue(s, 'line-count', `${f.lineCount} lines > ${rule.maxLines}`, { field: f.id, lineCount: f.lineCount, maxLines: rule.maxLines }));
    }
  }
  return out;
}

/** nowrap-overflow: a nowrap/pre text is wider than its box (scrollWidth > clientWidth + 1). */
export function ruleNowrapOverflow(s, t) {
  const out = [];
  for (const f of visibleFields(s, t)) {
    if (!['nowrap', 'pre'].includes(f.whiteSpace)) continue;
    if (!Number.isFinite(f.scrollWidth) || !Number.isFinite(f.clientWidth)) {
      out.push(issue(s, 'nowrap-overflow', 'scrollWidth/clientWidth missing', { field: f.id }));
    } else if (f.scrollWidth > f.clientWidth + 1) {
      out.push(issue(s, 'nowrap-overflow', `scrollWidth ${f.scrollWidth} > clientWidth ${f.clientWidth}`, { field: f.id, scrollWidth: f.scrollWidth, clientWidth: f.clientWidth }));
    }
  }
  return out;
}

// ---------------------------------------------------------------------------------------------
// Clipping, safe area, captions (behaviour unchanged from V2)
// ---------------------------------------------------------------------------------------------

/** clip: ink leaves its clip boxes (or the probe flagged the field clipped). */
export function ruleClip(s, t) {
  const out = [];
  for (const f of visibleFields(s, t)) {
    const clipBoxes = f.clipBoxes ?? [];
    const outside = (f.inkRects ?? []).some(r => clipBoxes.some(c =>
      r.x < c.x - 0.5 || r.y < c.y - 0.5 || r.x + r.width > c.x + c.width + 0.5 || r.y + r.height > c.y + c.height + 0.5));
    if (f.clipped || outside) out.push(issue(s, 'clip', 'text clipped', { field: f.id }));
  }
  return out;
}

/** safe: ink leaves the title-safe area (t.safeFraction on every side). */
export function ruleSafe(s, t) {
  const out = [];
  for (const f of visibleFields(s, t)) {
    for (const r of inkOf(f)) {
      if (r.x < s.width * t.safeFraction - 0.5 || r.y < s.height * t.safeFraction - 0.5 ||
          r.x + r.width > s.width * (1 - t.safeFraction) + 0.5 || r.y + r.height > s.height * (1 - t.safeFraction) + 0.5) {
        out.push(issue(s, 'safe', 'ink outside safe area', { field: f.id }));
      }
    }
  }
  return out;
}

/** caption-blank-line / caption-text / caption-lane (V2 behaviour). */
export function ruleCaption(s, t) {
  const out = [];
  for (const f of visibleFields(s, t)) {
    if (f.id !== 'caption') continue;
    if (f.captionBlankFirstLine === true) out.push(issue(s, 'caption-blank-line', 'blank first line enlarges caption pill', { field: f.id }));
    if (f.captionExpectedText !== undefined && f.text !== f.captionExpectedText.trim()) {
      out.push(issue(s, 'caption-text', 'rendered caption differs from display text', { field: f.id }));
    }
    const bottom = f.box.y + f.box.height;
    if (s.captionLane && ((s.captionLane === 'top' && bottom > 540) || (s.captionLane === 'bottom' && f.box.y < 540))) {
      out.push(issue(s, 'caption-lane', `caption lane ${s.captionLane} but box at y=${f.box.y}`, { field: f.id }));
    }
  }
  return out;
}

/** overlap: ink of two visible fields intersects (a real old/new crossfade of the same field is exempt). */
export function ruleOverlap(s, t) {
  const out = [];
  const visible = visibleFields(s, t);
  for (let i = 0; i < visible.length; i++) {
    for (let j = i + 1; j < visible.length; j++) {
      const a = visible[i];
      const b = visible[j];
      const crossfade = s.transition === true && a.id === b.id &&
        new Set([a.layer, b.layer]).size === 2 && [a.layer, b.layer].every(l => ['previous', 'current'].includes(l));
      if (crossfade) continue;
      if (inkOf(a).some(r => inkOf(b).some(q => intersects(r, q)))) {
        out.push(issue(s, 'overlap', `${a.id} overlaps ${b.id}`, { detail: `${a.id}/${b.id}`, field: a.id, other: b.id }));
      }
    }
  }
  return out;
}

/** occlusion: a visible occluder painted in front of a field intersects its ink. */
export function ruleOcclusion(s, t) {
  const out = [];
  for (const o of s.occluders ?? []) {
    if (!finiteRect(o.box) || !Number.isFinite(o.opacity) || !Array.isArray(o.frontOf)) continue;
    if (o.opacity < t.visibleOpacity) continue;
    for (const f of visibleFields(s, t)) {
      if (o.frontOf.includes(f.id) && inkOf(f).some(r => intersects(r, o.box))) {
        out.push(issue(s, 'occlusion', `${o.id} covers ${f.id}`, { detail: `${o.id}/${f.id}`, field: f.id, occluder: o.id }));
      }
    }
  }
  return out;
}

// ---------------------------------------------------------------------------------------------
// Backings
// ---------------------------------------------------------------------------------------------

/**
 * backing: on full-layout footage of origin source/stock/ai every visible field needs an effectively
 * opaque backing (backedEff). Replaces V2 `backed`/`backing.opacity > 0`.
 */
export function ruleBacking(s, t) {
  const out = [];
  const f0 = s.footage;
  if (!(f0?.layout === 'full' && ['source', 'stock', 'ai'].includes(f0.origin))) return out;
  for (const f of visibleFields(s, t)) {
    if (!backedEff(f, t)) {
      out.push(issue(s, 'backing', 'text not on an effectively opaque backing', {
        field: f.id,
        effAlpha: f.backing ? roundN(effAlpha(f.backing)) : 0,
        backingAlpha: f.backing?.alpha ?? null,
        backingOpacity: f.backing?.opacity ?? null,
        sameVisibilityAncestry: f.backing?.sameVisibilityAncestry ?? null,
        needed: t.minBackingEffAlpha,
      }));
    }
  }
  return out;
}

// P = presenter media area actually painted: mediaBox clipped by the avatar card.
function presenterRegion(s, t) {
  const a = s.avatar;
  if (!a || s.phase !== 'vo') return null;
  if (!(a.opacity >= t.presenterVisibleOpacity)) return null;
  if (!finiteRect(a.box) || !finiteRect(a.mediaBox)) return null;
  return intersection(a.mediaBox, a.box);
}

/**
 * presenter-text-backing: text drawn over the visible presenter video must be backedEff.
 * Applies when avatar.opacity >= t.presenterVisibleOpacity during the voice-over phase.
 */
export function rulePresenterTextBacking(s, t) {
  const P = presenterRegion(s, t);
  if (!P) return [];
  const out = [];
  for (const f of visibleFields(s, t)) {
    if (!inkOf(f).some(r => intersects(r, P))) continue;
    if (!backedEff(f, t)) {
      out.push(issue(s, 'presenter-text-backing', 'text over presenter video without opaque backing', {
        field: f.id,
        effAlpha: f.backing ? roundN(effAlpha(f.backing)) : 0,
        fieldOpacity: f.opacity,
        avatarOpacity: s.avatar.opacity,
        needed: t.minBackingEffAlpha,
      }));
    }
  }
  return out;
}

/**
 * face-text / face-backing: nothing but the presenter may cover the presenter's face (F = faceBox ∩ P).
 *   face-text    a visible field's ink intersects F
 *   face-backing a visible backing (opacity >= visibleOpacity) intersects F AND is not painted below the presenter there
 *                (backing.aboveAvatarAtFace === false means the probe measured it under the presenter; absent / null / true
 *                 count: a snapshot that does not say is treated as covering the face).
 */
export function ruleFace(s, t) {
  const P = presenterRegion(s, t);
  if (!P) return [];
  const faceBox = s.avatar.faceBox;
  if (!finiteRect(faceBox)) return [issue(s, 'schema', 'avatar.faceBox missing while the presenter is visible')];
  if (!Array.isArray(s.backings)) return [issue(s, 'schema', 'backings array missing')];
  const F = intersection(faceBox, P);
  if (!F) return [];
  const out = [];
  for (const f of visibleFields(s, t)) {
    if (inkOf(f).some(r => intersects(r, F))) out.push(issue(s, 'face-text', 'text over the presenter face', { field: f.id }));
  }
  for (const b of s.backings) {
    if (finiteRect(b.box) && b.opacity >= t.visibleOpacity && intersects(b.box, F) && b.aboveAvatarAtFace !== false) {
      out.push(issue(s, 'face-backing', 'backing over the presenter face', { detail: b.id, backing: b.id }));
    }
  }
  return out;
}

// ---------------------------------------------------------------------------------------------
// Lanes + reserved areas
// ---------------------------------------------------------------------------------------------

/**
 * lane-missing / lane-forbidden / lane-overflow
 *   lane-missing    the field has no data-qc-lane
 *   lane-forbidden  the lane is not in fieldRules[id].lanes
 *   lane-overflow   an ink rect leaves plan.lanes[lane] (grown by t.lanePadPx)
 */
export function ruleLane(s, t, ctx) {
  const bad = ctxProblem(s, ctx, ['plan', 'fieldRules']);
  if (bad) return bad;
  const out = [];
  const pad = t.lanePadPx ?? 0;
  for (const f of visibleFields(s, t)) {
    if (!f.lane) {
      out.push(issue(s, 'lane-missing', `field "${f.id}" has no data-qc-lane`, { field: f.id }));
      continue;
    }
    const rule = resolveFieldRule(ctx.fieldRules, f.id);
    if (rule && !(rule.lanes ?? []).includes(f.lane)) {
      out.push(issue(s, 'lane-forbidden', `lane ${f.lane} not allowed for ${f.id}`, { field: f.id, lane: f.lane, allowed: rule.lanes }));
    }
    const lane = ctx.plan.lanes[f.lane];
    if (!finiteRect(lane)) {
      out.push(issue(s, 'lane-overflow', `lane ${f.lane} is not defined in plan.lanes`, { field: f.id, lane: f.lane }));
      continue;
    }
    const outside = inkOf(f).filter(r =>
      r.x < lane.x - pad || r.y < lane.y - pad ||
      r.x + r.width > lane.x + lane.width + pad || r.y + r.height > lane.y + lane.height + pad);
    if (outside.length) {
      out.push(issue(s, 'lane-overflow', `ink leaves lane ${f.lane}`, { field: f.id, lane: f.lane, laneBox: lane, outsideRects: outside.length }));
    }
  }
  return out;
}

// Two stablePath()s are related when one is the other or an ancestor/descendant of it.
const pathsRelated = (a, b) =>
  typeof a === 'string' && typeof b === 'string' &&
  (a === b || a.startsWith(`${b}/`) || b.startsWith(`${a}/`));

/**
 * reserved-intersect: a visible backing that is neither reserved nor part of a reserved backing's
 * subtree must not intersect the header lane or any visible reserved backing (header / chrome).
 */
export function ruleReservedIntersect(s, t, ctx) {
  const bad = ctxProblem(s, ctx, ['plan']);
  if (bad) return bad;
  if (!Array.isArray(s.backings)) return [issue(s, 'schema', 'backings array missing')];
  const out = [];
  const reserved = s.backings.filter(b => b.reserved);
  const zones = [];
  if (finiteRect(ctx.plan.lanes.header)) zones.push({ name: 'lane:header', box: ctx.plan.lanes.header });
  for (const b of reserved) if (b.opacity >= t.visibleOpacity && finiteRect(b.box)) zones.push({ name: `reserved:${b.id}`, box: b.box });
  for (const b of s.backings) {
    if (b.reserved || !(b.opacity >= t.visibleOpacity) || !finiteRect(b.box)) continue;
    if (reserved.some(r => pathsRelated(b.path, r.path))) continue;
    for (const z of zones) {
      if (intersects(b.box, z.box)) out.push(issue(s, 'reserved-intersect', `backing ${b.id} intersects ${z.name}`, { detail: b.id, backing: b.id, zone: z.name }));
    }
  }
  return out;
}

/**
 * lane-table (static, checked once per plan, not per frame): every lane lies inside the safe area and
 * no non-header lane intersects the header lane.
 */
export function ruleLaneTable(s, t, ctx) {
  const bad = ctxProblem(s, ctx, ['plan']);
  if (bad) return bad;
  const W = ctx.plan.width ?? s?.width ?? 1920;
  const H = ctx.plan.height ?? s?.height ?? 1080;
  const safe = { x: W * t.safeFraction, y: H * t.safeFraction, right: W * (1 - t.safeFraction), bottom: H * (1 - t.safeFraction) };
  const lanes = ctx.plan.lanes;
  const out = [];
  for (const [name, r] of Object.entries(lanes)) {
    if (!finiteRect(r)) {
      out.push(issue(s, 'lane-table', `lane ${name} has an invalid rect`, { lane: name }));
      continue;
    }
    if (r.x < safe.x - 0.5 || r.y < safe.y - 0.5 || r.x + r.width > safe.right + 0.5 || r.y + r.height > safe.bottom + 0.5) {
      out.push(issue(s, 'lane-table', `lane ${name} outside the safe area`, { lane: name }));
    }
    if (name !== 'header' && finiteRect(lanes.header) && intersects(r, lanes.header)) {
      out.push(issue(s, 'lane-table', `lane ${name} intersects the header lane`, { lane: name }));
    }
  }
  return out;
}

/** Plan-level rules (run once per run, not per frame). */
export function evaluatePlanRules(plan, t) {
  return ruleLaneTable(undefined, t, { plan });
}

// ---------------------------------------------------------------------------------------------
// Content presence
// ---------------------------------------------------------------------------------------------

/**
 * content-presence (voice-over phase): the painted content layers must cover the frame.
 *   coverage = sum(layer.opacity * area(layer.box ∩ frame)) / (W*H)  >=  t.minContentCoverage
 */
export function ruleContentPresence(s, t) {
  if (s.phase !== 'vo') return [];
  if (!Array.isArray(s.layers)) return [issue(s, 'schema', 'layers array missing')];
  const frame = { x: 0, y: 0, width: s.width, height: s.height };
  let covered = 0;
  for (const l of s.layers) {
    if (!finiteRect(l.box) || !Number.isFinite(l.opacity)) return [issue(s, 'schema', `layer ${l.id} has an invalid measurement`)];
    const inside = intersection(l.box, frame);
    if (inside) covered += l.opacity * inside.width * inside.height;
  }
  const coverage = covered / (s.width * s.height);
  return coverage < t.minContentCoverage
    ? [issue(s, 'content-presence', `content coverage ${roundN(coverage)} < ${t.minContentCoverage}`, { coverage: roundN(coverage, 6), needed: t.minContentCoverage, layers: s.layers.length })]
    : [];
}

// ---------------------------------------------------------------------------------------------
// Footage provenance (behaviour unchanged from V2)
// ---------------------------------------------------------------------------------------------

/**
 * footage / credit / stock-chrome / origin / ai-chrome / ai-label.
 * credit and ai-label are required once the beat has settled (snapshot.transition !== true, i.e. not within MODE_BLEND_SEC of the beat
 * start): while the incoming picture is still dissolving in or the presenter is still leaving, its attribution is allowed to be
 * a few frames behind (the engine starts chrome labels 2 frames ahead of the other labels so they are there when the window ends).
 */
export function ruleFootage(s, t) {
  const out = [];
  const f = s.footage;
  if (!f || !['source', 'stock', 'ai', 'avatar', 'typo', 'endcard'].includes(f.origin)) {
    return [issue(s, 'footage', 'missing provenance measurement')];
  }
  const visible = visibleFields(s, t);
  const covered = coveredFieldIds(s, t);
  const chromeText = visible.some(x => ['source-credit', 'source-url'].includes(x.id));
  const transitioning = s.transition === true;
  if (f.origin === 'source') {
    const creditOk = visible.some(x => x.id === 'source-credit' && !x.clipped && !covered.has(x.id) && finiteRect(x.box));
    if ((!creditOk && !transitioning) || !f.src?.startsWith('yt_')) out.push(issue(s, 'credit', 'source missing visible credit/path'));
  }
  if (f.origin === 'stock') {
    if (f.chrome || f.credit || chromeText) out.push(issue(s, 'stock-chrome', 'stock misattribution'));
    if (f.src?.startsWith('yt_') || f.src?.startsWith('ai_')) out.push(issue(s, 'origin', 'stock path mismatch'));
  }
  if (f.origin === 'ai') {
    if (!f.src?.startsWith('ai_')) out.push(issue(s, 'origin', 'AI path mismatch'));
    if (f.chrome || f.credit || chromeText) out.push(issue(s, 'ai-chrome', 'AI misattribution'));
    if (!transitioning && !visible.some(x => x.id === 'ai-label' && x.text === 'ภาพประกอบ AI' && !x.clipped && !covered.has(x.id))) {
      out.push(issue(s, 'ai-label', 'missing visible AI label'));
    }
  }
  return out;
}

// ---------------------------------------------------------------------------------------------
// evaluateLayout
// ---------------------------------------------------------------------------------------------

// Per-frame rules in reporting order (ruleLaneTable is plan-level: see evaluatePlanRules).
export const FRAME_RULES = [
  ruleFonts, ruleProbeIssues, ruleGeometry, ruleTier, ruleFont, ruleFontRubric, ruleTextAlpha, ruleClip, ruleSafe,
  ruleBacking, ruleCaption, ruleLane, ruleLineCount, ruleNowrapOverflow, ruleOverlap, ruleOcclusion,
  ruleReservedIntersect, rulePresenterTextBacking, ruleFace, ruleContentPresence, ruleFootage,
];

export function evaluateLayout(s, t, ctx = {}) {
  if (!s || !Number.isInteger(s.frame) || !Number.isFinite(s.width) || !Number.isFinite(s.height) || s.width <= 0 || s.height <= 0) {
    return { issues: [issue(s, 'snapshot', 'missing/invalid probe')] };
  }
  const schema = ruleSchema(s, t, ctx);
  if (schema.length) return { issues: schema };                     // fail closed: one issue, nothing else is trusted
  const missingCtx = ctxProblem(s, ctx, ['plan', 'fieldRules']);
  if (missingCtx) return { issues: missingCtx };
  const fields = ruleFields(s);
  if (fields.length) return { issues: [...ruleFonts(s), ...fields, ...ruleProbeIssues(s)] };
  const issues = [];
  for (const rule of FRAME_RULES) issues.push(...rule(s, t, ctx));
  return { issues };
}

// ---------------------------------------------------------------------------------------------
// Frame plan
// ---------------------------------------------------------------------------------------------

/**
 * buildFramePlan(enginePlan, t) -> sorted, de-duplicated frame numbers, every frame clamped to
 * [0, durationInFrames-1]. Union of
 *   - enginePlan.frames and every frame inside enginePlan.sweepWindows,
 *   - a grid: every multiple of t.gridStrideFrames below durationInFrames,
 *   - for each beat i >= 1: [startFrame - t.beatWindowPreFrames,
 *                            ceil((beat.t + t.beatWindowPostSec) * fps) + t.beatWindowPostExtraFrames],
 *   - the voice-over end: [voEndFrame - t.beatWindowPreFrames, voEndFrame + t.beatWindowPostExtraFrames].
 * Pure and deterministic. Throws on a malformed plan (fail closed).
 */
export function buildFramePlan(enginePlan, t) {
  const p = enginePlan;
  const bad = msg => { throw new TypeError(`buildFramePlan: ${msg}`); };
  if (!p || typeof p !== 'object') bad('plan missing');
  if (!Number.isInteger(p.durationInFrames) || p.durationInFrames < 1) bad('durationInFrames must be a positive integer');
  if (!Number.isFinite(p.fps) || p.fps <= 0) bad('fps must be positive');
  if (!Number.isInteger(p.voEndFrame)) bad('voEndFrame must be an integer');
  if (!Array.isArray(p.frames) || !p.frames.every(Number.isInteger)) bad('frames must be an array of integers');
  const beats = p.beats ?? [];
  const sweepWindows = p.sweepWindows ?? [];
  if (!Array.isArray(beats) || !Array.isArray(sweepWindows)) bad('beats/sweepWindows must be arrays');
  for (const k of ['gridStrideFrames', 'beatWindowPreFrames', 'beatWindowPostSec', 'beatWindowPostExtraFrames']) {
    if (!Number.isFinite(t?.[k])) bad(`threshold ${k} missing`);
  }
  if (!(t.gridStrideFrames >= 1)) bad('gridStrideFrames must be >= 1');

  const last = p.durationInFrames - 1;
  const clamp = n => Math.min(last, Math.max(0, n));
  const frames = new Set();
  const addRange = (from, to) => { for (let f = clamp(from); f <= clamp(to); f++) frames.add(f); };

  for (const f of p.frames) frames.add(clamp(f));
  for (const w of sweepWindows) {
    if (!Number.isInteger(w?.startFrame) || !Number.isInteger(w?.endFrame)) bad('sweep window needs integer startFrame/endFrame');
    addRange(w.startFrame, w.endFrame);
  }
  for (let f = 0; f < p.durationInFrames; f += t.gridStrideFrames) frames.add(f);
  for (const b of beats) {
    if (!Number.isInteger(b?.index) || b.index < 1) continue;       // beat 0 starts the video: no boundary
    if (!Number.isInteger(b.startFrame) || !Number.isFinite(b.t)) bad(`beat ${b.index} needs integer startFrame and numeric t`);
    // Rounded to 1e-6 before ceil so that 1.45 + 0.55 does not become 2.0000000000000004 -> +1 frame.
    const postEnd = Math.ceil(Math.round((b.t + t.beatWindowPostSec) * p.fps * 1e6) / 1e6) + t.beatWindowPostExtraFrames;
    addRange(b.startFrame - t.beatWindowPreFrames, postEnd);
  }
  addRange(p.voEndFrame - t.beatWindowPreFrames, p.voEndFrame + t.beatWindowPostExtraFrames);
  return [...frames].sort((a, b) => a - b);
}

// ---------------------------------------------------------------------------------------------
// Legacy helpers kept byte-for-byte from V2/V3 (unchanged behaviour, still covered by avatar_backing.test.mjs)
// ---------------------------------------------------------------------------------------------

export function validateSamples(expected,samples){
 const issues=[];const counts=new Map();
 for(const s of samples){if(!s||!expected.includes(s.frame))issues.push({code:'wrong-frame',frame:s?.frame});else counts.set(s.frame,(counts.get(s.frame)||0)+1);}
 for(const f of expected)if(counts.get(f)!==1)issues.push({code:'sample-count',frame:f,count:counts.get(f)||0});
 return issues;
}


// Subtract protected glyph hulls (already expanded by measured padding) from overlap.
export function emptyBackingRegions(box,protectedRects){
 let regions=[box];
 for(const p of protectedRects){const next=[];for(const r of regions){
  const x=Math.max(r.x,p.x),y=Math.max(r.y,p.y),right=Math.min(r.x+r.width,p.x+p.width),bottom=Math.min(r.y+r.height,p.y+p.height);
  if(right<=x||bottom<=y){next.push(r);continue;}
  for(const q of [{x:r.x,y:r.y,width:r.width,height:y-r.y},{x:r.x,y:bottom,width:r.width,height:r.y+r.height-bottom},{x:r.x,y,width:x-r.x,height:bottom-y},{x:right,y,width:r.x+r.width-right,height:bottom-y}])if(q.width>0&&q.height>0)next.push(q);
 }regions=next;}return regions;
}
export function evaluateAvatarBackingSweep(windows,samples,fps,t,{requireComplete=true}={}){
 const issues=[],runs=[],coverage=[];const add=(code,detail)=>issues.push({code,detail});
 if(!Array.isArray(windows)||!Number.isFinite(fps)||fps<=0||![t.avatarEmptyMinArea,t.avatarEmptyMinDimension,t.avatarEmptyMaxSeconds,t.visibleOpacity].every(Number.isFinite)){add('sweep-incomplete','missing sweep plan/fps/thresholds');return {complete:false,issues,runs,coverage};}
 const expected=new Set();for(const w of windows){if(!w.id||!Number.isInteger(w.startFrame)||!Number.isInteger(w.endFrame)||w.endFrame<w.startFrame){add('sweep-incomplete','invalid window');continue;}for(let f=w.startFrame;f<=w.endFrame;f++)expected.add(f);}
 const counts=new Map();for(const s of samples){if(!s||!expected.has(s.frame)){add('sweep-incomplete','frame outside sweep');continue;}counts.set(s.frame,(counts.get(s.frame)||0)+1);}
 let complete=true;
 for(const w of windows){
  const frames=Array.from({length:w.endFrame-w.startFrame+1},(_,i)=>w.startFrame+i),present=frames.filter(f=>counts.has(f));
  const covered=frames.every(f=>counts.get(f)===1);coverage.push({id:w.id,beatT:w.beatT,startFrame:w.startFrame,endFrame:w.endFrame,expected:frames.length,observed:present.length,complete:covered});
  if(!covered){complete=false;if(requireComplete||present.length)add('sweep-incomplete',w.id);}
  const active=new Map();
  const flush=(id,endDirty=false)=>{const run=active.get(id);if(!run)return;active.delete(id);const nframes=run.lastFrame-run.firstFrame+1;const record={...run,beatT:w.beatT,windowId:w.id,id,nframes,duration:nframes/fps,unbounded:endDirty};runs.push(record);if(endDirty||record.duration>t.avatarEmptyMaxSeconds)issues.push({code:endDirty?'avatar-empty-backing-unbounded':'avatar-empty-backing',...record});};
  for(const frame of frames){
   const s=samples.find(s=>s?.frame===frame),dirty=new Map();
   if(counts.get(frame)!==1||!s) {for(const id of active.keys())flush(id);continue;}
   const measure=s.avatarBacking;
   if(s.fontsOk!==true||!measure||!finiteRect(measure.avatar?.box)||!Number.isFinite(measure.avatar.opacity)||!Array.isArray(measure.candidates)){add('sweep-incomplete','missing measurement/font at '+frame);complete=false;for(const id of active.keys())flush(id);continue;}
   const ids=new Set();
   for(const c of measure.candidates){
    if(!c.id||ids.has(c.id)||!finiteRect(c.box)||!Number.isFinite(c.opacity)||!c.background||!Number.isFinite(c.background.alpha)||typeof c.background.image!=='string'||!Array.isArray(c.emptyRegions)||!Array.isArray(c.protectedRects)||!c.protectedRects.every(finiteRect)){add('sweep-incomplete','invalid candidate at '+frame);complete=false;continue;}ids.add(c.id);
    if(measure.avatar.opacity<t.visibleOpacity||c.opacity<t.visibleOpacity||!(c.background.alpha>t.visibleOpacity||c.background.image!=='none'))continue;
    const aboveRegions=[];
    for(const r of c.emptyRegions){
     const e=r.paintOrderEvidence;
     if(!finiteRect(r)||!e||typeof e.above!=='boolean'||![e.x,e.y,e.candidateIndex,e.avatarIndex].every(Number.isFinite)){add('sweep-incomplete','missing paint order at '+frame);complete=false;continue;}
     if(e.above&&e.candidateIndex>=0&&e.avatarIndex>=0&&e.candidateIndex<e.avatarIndex)aboveRegions.push(r);
    }
    if(aboveRegions.length){
     const area=aboveRegions.reduce((sum,r)=>sum+r.width*r.height,0);
     const width=Math.max(...aboveRegions.map(r=>r.x+r.width))-Math.min(...aboveRegions.map(r=>r.x));
     const height=Math.max(...aboveRegions.map(r=>r.y+r.height))-Math.min(...aboveRegions.map(r=>r.y));
     if(area>=t.avatarEmptyMinArea&&Math.max(width,height)>=t.avatarEmptyMinDimension)dirty.set(c.id,area);
    }
   }
   for(const id of [...active.keys()])if(!dirty.has(id))flush(id);
   for(const [id,area] of dirty){const old=active.get(id);active.set(id,{firstFrame:old?.firstFrame??frame,lastFrame:frame,maxEmptyPx:Math.max(old?.maxEmptyPx??0,area)});}
  }
  for(const id of [...active.keys()])flush(id,true);
 }
 return {complete:complete&&!issues.some(i=>i.code==='sweep-incomplete'),issues,runs,coverage,fps};
}
