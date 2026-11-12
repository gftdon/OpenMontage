#!/usr/bin/env node
// episode_schema.mjs - validator library + CLI for the V4 episode data contract.
//
// One schema (assets/episode.schema.json), three consumers:
//   * Node gate scripts      -> import { validateEpisode, projectCaptions }
//   * Python lint            -> run the CLI and read the --json output (never re-implement the rules)
//   * the engine's browser   -> has its own small check; agreement is proven by a test elsewhere
//
// Dependency-free ESM, Node >= 22 (needs Intl.Segmenter with full ICU for Thai graphemes).
//
// CLI contract (see runCli below):
//   node episode_schema.mjs validate <episode.json> [--captions <captions.json>] [--public <dir>] [--json]
//   exit 0 = valid, 1 = invalid, 2 = usage / IO / JSON-parse / schema-file error
//   --json  -> stdout is exactly one JSON object {valid, errors, warnings, schemaSha256}
//   default -> one line per finding ("ERROR <path> [<rule>] <message>", "WARNING ...") and a final
//              "EPISODE_SCHEMA valid=<bool> errors=<n> warnings=<n>" line.

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const SCHEMA_PATH = path.resolve(HERE, '../assets/episode.schema.json');

const FPS = 25; // schema pins fps to 25
const EPS = 1e-9; // tolerance for comparing seconds that came from decimal JSON literals

// ---------------------------------------------------------------------------
// 1. Schema loading and the supported-subset interpreter
// ---------------------------------------------------------------------------

// Keywords the interpreter understands. Anything else in the schema file throws (fail closed),
// so a future schema edit can never silently lose a constraint.
const SUPPORTED_KEYWORDS = new Set([
  '$id', '$defs', '$ref',
  'type', 'enum', 'required', 'properties', 'additionalProperties', 'propertyNames',
  'items', 'minItems', 'maxItems', 'minimum', 'maximum', 'minLength', 'pattern',
]);
const SUPPORTED_TYPES = new Set(['string', 'number', 'integer', 'boolean', 'object', 'array']);

/** Loads and checks the schema file. Returns { schema, sha256 } (sha256 of the raw file bytes). */
export function loadSchema(schemaPath = SCHEMA_PATH) {
  const raw = fs.readFileSync(schemaPath);
  const schema = JSON.parse(raw.toString('utf8'));
  assertSupportedSchema(schema);
  return { schema, sha256: crypto.createHash('sha256').update(raw).digest('hex') };
}

/**
 * Walks a whole schema document and throws on any keyword (or keyword value) the interpreter
 * does not support. Property NAMES inside `properties` / `$defs` are not keywords and are skipped.
 */
export function assertSupportedSchema(schema, pointer = '#') {
  if (schema === null || typeof schema !== 'object' || Array.isArray(schema)) {
    throw new Error(`schema at ${pointer} must be an object`);
  }
  for (const [kw, val] of Object.entries(schema)) {
    if (!SUPPORTED_KEYWORDS.has(kw)) throw new Error(`unsupported schema keyword "${kw}" at ${pointer}`);
    const here = `${pointer}/${kw}`;
    switch (kw) {
      case '$id':
        if (typeof val !== 'string') throw new Error(`${here} must be a string`);
        break;
      case '$ref':
        if (typeof val !== 'string' || !/^#\/\$defs\/[^/]+$/.test(val)) {
          throw new Error(`${here}: only "#/$defs/<name>" references are supported`);
        }
        break;
      case 'type':
        if (typeof val !== 'string' || !SUPPORTED_TYPES.has(val)) throw new Error(`${here}: unsupported type ${JSON.stringify(val)}`);
        break;
      case 'enum':
        if (!Array.isArray(val) || val.length === 0) throw new Error(`${here} must be a non-empty array`);
        break;
      case 'required':
        if (!Array.isArray(val) || val.some((k) => typeof k !== 'string')) throw new Error(`${here} must be an array of strings`);
        break;
      case 'minItems': case 'maxItems': case 'minLength':
        if (!Number.isInteger(val) || val < 0) throw new Error(`${here} must be a non-negative integer`);
        break;
      case 'minimum': case 'maximum':
        if (typeof val !== 'number' || !Number.isFinite(val)) throw new Error(`${here} must be a finite number`);
        break;
      case 'pattern':
        if (typeof val !== 'string') throw new Error(`${here} must be a string`);
        compilePattern(val); // throws on a bad regex
        break;
      case 'properties': case '$defs':
        if (val === null || typeof val !== 'object' || Array.isArray(val)) throw new Error(`${here} must be an object`);
        for (const [name, sub] of Object.entries(val)) assertSupportedSchema(sub, `${here}/${name}`);
        break;
      case 'additionalProperties':
        if (typeof val === 'boolean') break;
        assertSupportedSchema(val, here);
        break;
      case 'items':
        assertSupportedSchema(val, here);
        break;
      case 'propertyNames':
        // Only `pattern` is supported for property names.
        if (val === null || typeof val !== 'object' || Array.isArray(val)) throw new Error(`${here} must be an object`);
        for (const k of Object.keys(val)) {
          if (k !== 'pattern') throw new Error(`unsupported keyword "${k}" in propertyNames at ${here}`);
        }
        assertSupportedSchema(val, here);
        break;
      default:
        break;
    }
  }
}

const patternCache = new Map();
function compilePattern(source) {
  let re = patternCache.get(source);
  if (!re) {
    re = new RegExp(source, 'u'); // ECMAScript, unicode mode
    patternCache.set(source, re);
  }
  return re;
}

/** RFC 6901 escaping for one JSON Pointer token. */
export function pointerToken(key) {
  return String(key).replace(/~/g, '~0').replace(/\//g, '~1');
}

function typeMatches(value, type) {
  switch (type) {
    case 'string': return typeof value === 'string';
    case 'number': return typeof value === 'number' && Number.isFinite(value);
    case 'integer': return typeof value === 'number' && Number.isInteger(value);
    case 'boolean': return typeof value === 'boolean';
    case 'object': return value !== null && typeof value === 'object' && !Array.isArray(value);
    case 'array': return Array.isArray(value);
    default: throw new Error(`unsupported type ${type}`);
  }
}

function describeType(value) {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'array';
  if (typeof value === 'number') return Number.isFinite(value) ? (Number.isInteger(value) ? 'integer' : 'number') : `non-finite number (${value})`;
  return typeof value;
}

/**
 * Validates `value` against `schema` (a sub-schema of `rootSchema`, which supplies $defs).
 * `at` is the JSON Pointer of `value` (use a prefix such as '/$captions' for captions).
 * Returns an array of { path, rule, message } where `rule` is the schema keyword that failed.
 * The schema must already have passed assertSupportedSchema.
 */
export function validateAgainstSchema(value, schema, rootSchema = schema, at = '') {
  const errors = [];
  walk(value, schema, rootSchema, at, errors);
  return errors;
}

function walk(value, schema, root, at, errors) {
  const fail = (p, rule, message) => errors.push({ path: p, rule, message });

  if (schema.$ref !== undefined) {
    const name = schema.$ref.slice('#/$defs/'.length);
    const target = root.$defs && root.$defs[name];
    if (!target) throw new Error(`unresolved $ref ${schema.$ref}`);
    walk(value, target, root, at, errors);
  }

  if (schema.type !== undefined && !typeMatches(value, schema.type)) {
    fail(at, 'type', `expected ${schema.type}, got ${describeType(value)}`);
    return; // other keywords make no sense on a wrong type
  }

  if (schema.enum !== undefined && !schema.enum.some((e) => e === value)) {
    fail(at, 'enum', `value ${JSON.stringify(value)} is not one of ${JSON.stringify(schema.enum)}`);
  }

  if (typeof value === 'number') {
    if (schema.minimum !== undefined && value < schema.minimum) fail(at, 'minimum', `${value} is below the minimum ${schema.minimum}`);
    if (schema.maximum !== undefined && value > schema.maximum) fail(at, 'maximum', `${value} is above the maximum ${schema.maximum}`);
  }

  if (typeof value === 'string') {
    if (schema.minLength !== undefined && [...value].length < schema.minLength) {
      fail(at, 'minLength', `string is shorter than ${schema.minLength} characters`);
    }
    if (schema.pattern !== undefined && !compilePattern(schema.pattern).test(value)) {
      fail(at, 'pattern', `${JSON.stringify(value)} does not match ${schema.pattern}`);
    }
  }

  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) fail(at, 'minItems', `array has ${value.length} items, minimum is ${schema.minItems}`);
    if (schema.maxItems !== undefined && value.length > schema.maxItems) fail(at, 'maxItems', `array has ${value.length} items, maximum is ${schema.maxItems}`);
    if (schema.items !== undefined) {
      value.forEach((item, i) => walk(item, schema.items, root, `${at}/${i}`, errors));
    }
  }

  if (typeMatches(value, 'object')) {
    const props = schema.properties || {};
    for (const key of schema.required || []) {
      if (!Object.prototype.hasOwnProperty.call(value, key)) fail(`${at}/${pointerToken(key)}`, 'required', `missing required property "${key}"`);
    }
    if (schema.propertyNames && schema.propertyNames.pattern !== undefined) {
      const re = compilePattern(schema.propertyNames.pattern);
      for (const key of Object.keys(value)) {
        if (!re.test(key)) fail(`${at}/${pointerToken(key)}`, 'pattern', `property name ${JSON.stringify(key)} does not match ${schema.propertyNames.pattern}`);
      }
    }
    for (const key of Object.keys(value)) {
      const childPath = `${at}/${pointerToken(key)}`;
      if (Object.prototype.hasOwnProperty.call(props, key)) {
        walk(value[key], props[key], root, childPath, errors);
      } else if (schema.additionalProperties === false) {
        fail(childPath, 'additionalProperties', `unknown property "${key}"`);
      } else if (schema.additionalProperties && typeof schema.additionalProperties === 'object') {
        walk(value[key], schema.additionalProperties, root, childPath, errors);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// 2. Captions projection
// ---------------------------------------------------------------------------

/**
 * Keeps only what the engine reads (spec 1b): top-level schema / algorithm / inputSha256 and,
 * per page, start / end / displayText and chunks[].{text, displaySpaceBefore, displayStart, displayEnd}.
 */
export function projectCaptions(captions) {
  return {
    schema: captions.schema,
    algorithm: captions.algorithm,
    inputSha256: captions.inputSha256,
    pages: captions.pages.map((p) => ({
      start: p.start,
      end: p.end,
      displayText: p.displayText,
      chunks: p.chunks.map((c) => ({
        text: c.text,
        displaySpaceBefore: c.displaySpaceBefore,
        displayStart: c.displayStart,
        displayEnd: c.displayEnd,
      })),
    })),
  };
}

// ---------------------------------------------------------------------------
// 3. Semantic rules (S01..S19). They run only when the schema pass found no errors.
// ---------------------------------------------------------------------------

const SEGMENTER = new Intl.Segmenter('th', { granularity: 'grapheme' });
/** Number of user-perceived characters (Thai-aware). */
export function graphemes(text) {
  let n = 0;
  for (const _ of SEGMENTER.segment(String(text))) n++; // eslint-disable-line no-unused-vars
  return n;
}

const FULL_ALLOWED_KEYS = new Set(['t', 'mode', 'kicker', 'punch', 'stats', 'lower']);
const TYPO_ONLY_KEYS = ['typo', 'cards', 'items', 'vs'];

const isStageMedia = (b) => b.mode === 'pip' && (b.media === 'broll' || b.media === 'clip');
const hasKey = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

function makeContext(ep, captions, opts) {
  const beats = ep.beats;
  const ctx = {
    ep, captions, opts, beats,
    errors: [], warnings: [],
    timelineOk: true, // set to false by S01; time-based rules are skipped then
    err(p, rule, message) { ctx.errors.push({ path: p, rule, message }); },
    warn(p, rule, message) { ctx.warnings.push({ path: p, rule, message }); },
    /** end(i) = next beat's t, or voEndSec for the last beat */
    end(i) { return i + 1 < beats.length ? beats[i + 1].t : ep.voEndSec; },
    /** end(i+1), used for "carries over at most one boundary"; the last beat has none, so voEndSec */
    end2(i) { return i + 1 < beats.length ? ctx.end(i + 1) : ep.voEndSec; },
    /** whole frames a beat is on screen (the renderer mounts at ceil(t*fps)) */
    shownFrames(i) { return Math.ceil(ctx.end(i) * FPS) - Math.ceil(beats[i].t * FPS); },
    /** Loop length L = floor((brollDur[src] - from) * fps) - 2 */
    loopLength(b) { return Math.floor((ep.brollDur[b.src] - (b.from || 0)) * FPS) - 2; },
  };
  return ctx;
}

// S01: beats[0].t == 0; t strictly increasing; last t < voEndSec.
function ruleS01(ctx) {
  const { beats, ep } = ctx;
  const bad = (p, msg) => { ctx.timelineOk = false; ctx.err(p, 'S01', msg); };
  if (beats[0].t !== 0) bad('/beats/0/t', `first beat must start at 0, got ${beats[0].t}`);
  for (let i = 1; i < beats.length; i++) {
    if (!(beats[i].t > beats[i - 1].t)) bad(`/beats/${i}/t`, `beat start ${beats[i].t} must be greater than the previous start ${beats[i - 1].t}`);
  }
  const last = beats.length - 1;
  if (!(beats[last].t < ep.voEndSec)) bad(`/beats/${last}/t`, `last beat start ${beats[last].t} must be before voEndSec ${ep.voEndSec}`);
}

// S02: every beat lasts at least 1.0 s.
function ruleS02(ctx) {
  ctx.beats.forEach((b, i) => {
    const len = ctx.end(i) - b.t;
    if (len < 1.0 - EPS) ctx.err(`/beats/${i}/t`, 'S02', `beat lasts ${len.toFixed(3)} s, minimum is 1.0 s`);
  });
}

// S03: ctaT < voEndSec; totalDurationSec - voEndSec lies in [3, 5].
function ruleS03(ctx) {
  const { ep } = ctx;
  if (!(ep.ctaT < ep.voEndSec)) ctx.err('/ctaT', 'S03', `ctaT ${ep.ctaT} must be before voEndSec ${ep.voEndSec}`);
  const tail = ep.totalDurationSec - ep.voEndSec;
  if (tail < 3 - EPS || tail > 5 + EPS) ctx.err('/totalDurationSec', 'S03', `totalDurationSec - voEndSec is ${tail.toFixed(3)} s, must be within [3, 5]`);
}

// S04: full beats may only have {t, mode, kicker, punch, stats, lower}; pip beats need media, layout, headline
// (and may not carry punch: that is reported by S12).
function ruleS04(ctx) {
  ctx.beats.forEach((b, i) => {
    if (b.mode === 'full') {
      for (const key of Object.keys(b)) {
        if (!FULL_ALLOWED_KEYS.has(key)) ctx.err(`/beats/${i}/${pointerToken(key)}`, 'S04', `a full beat may not have "${key}"`);
      }
    } else if (b.mode === 'pip') {
      for (const key of ['media', 'layout', 'headline']) {
        if (!hasKey(b, key)) ctx.err(`/beats/${i}/${key}`, 'S04', `a pip beat needs "${key}"`);
      }
    }
  });
}

// S05: broll/clip need src and origin; typo needs `typo`; typo forbids src/from/srcCrop/origin/punch.
function ruleS05(ctx) {
  ctx.beats.forEach((b, i) => {
    if (b.mode !== 'pip') return;
    if (b.media === 'broll' || b.media === 'clip') {
      for (const key of ['src', 'origin']) {
        if (!hasKey(b, key)) ctx.err(`/beats/${i}/${key}`, 'S05', `a ${b.media} beat needs "${key}"`);
      }
    } else if (b.media === 'typo') {
      if (!hasKey(b, 'typo')) ctx.err(`/beats/${i}/typo`, 'S05', 'a typo beat needs "typo" (card | summary3 | final4 | vs)');
      for (const key of ['src', 'from', 'srcCrop', 'origin', 'punch']) {
        if (hasKey(b, key)) ctx.err(`/beats/${i}/${key}`, 'S05', `a typo beat may not have "${key}"`);
      }
    }
  });
}

// S06: yt_ prefix <=> origin source; ai_ <=> ai; clip <=> source; broll => stock or ai.
function ruleS06(ctx) {
  ctx.beats.forEach((b, i) => {
    if (!isStageMedia(b) || typeof b.src !== 'string' || typeof b.origin !== 'string') return;
    const p = `/beats/${i}/origin`;
    if (b.src.startsWith('yt_') !== (b.origin === 'source')) ctx.err(p, 'S06', `src "${b.src}" and origin "${b.origin}" disagree: the yt_ prefix means origin "source" and only that`);
    if (b.src.startsWith('ai_') !== (b.origin === 'ai')) ctx.err(p, 'S06', `src "${b.src}" and origin "${b.origin}" disagree: the ai_ prefix means origin "ai" and only that`);
    if ((b.media === 'clip') !== (b.origin === 'source')) ctx.err(p, 'S06', `media "${b.media}" and origin "${b.origin}" disagree: a clip is a source clip and only that`);
    if (b.media === 'broll' && b.origin !== 'stock' && b.origin !== 'ai') ctx.err(p, 'S06', `a broll beat needs origin "stock" or "ai", got "${b.origin}"`);
  });
}

// S07: src is a key of brollDur (the file is public/<assetDir>/broll/<src>.mp4). With opts.publicDir the files must exist (S07-file).
function ruleS07(ctx) {
  const { ep, opts } = ctx;
  const seen = new Set();
  ctx.beats.forEach((b, i) => {
    if (!isStageMedia(b) || typeof b.src !== 'string') return;
    if (!hasKey(ep.brollDur, b.src)) {
      ctx.err(`/beats/${i}/src`, 'S07', `src "${b.src}" is not a key of brollDur`);
      return;
    }
    if (opts.publicDir && !seen.has(b.src)) {
      seen.add(b.src);
      const file = path.join(opts.publicDir, ep.assetDir, 'broll', `${b.src}.mp4`);
      if (!isFile(file)) ctx.err(`/beats/${i}/src`, 'S07-file', `missing file ${file}`);
    }
  });
  if (opts.publicDir) {
    const avatar = path.join(opts.publicDir, ep.assetDir, ep.avatarFile);
    if (!isFile(avatar)) ctx.err('/avatarFile', 'S07-file', `missing file ${avatar}`);
  }
}

function isFile(p) {
  try { return fs.statSync(p).isFile(); } catch { return false; }
}

// S08: wide => clip, and no sub / stats; typo => stage.
function ruleS08(ctx) {
  ctx.beats.forEach((b, i) => {
    if (b.mode !== 'pip') return;
    if (b.layout === 'wide') {
      if (b.media !== 'clip') ctx.err(`/beats/${i}/layout`, 'S08', `layout "wide" needs media "clip", got "${b.media}"`);
      for (const key of ['sub', 'stats']) {
        if (hasKey(b, key)) ctx.err(`/beats/${i}/${key}`, 'S08', `a wide beat may not have "${key}"`);
      }
    }
    if (b.media === 'typo' && b.layout !== 'stage') ctx.err(`/beats/${i}/layout`, 'S08', 'a typo beat must use layout "stage"');
  });
}

// S09: loop length L >= 25 frames; source beats must not loop (shown frames <= L, error); stock/ai looping is a warning.
function ruleS09(ctx) {
  ctx.beats.forEach((b, i) => {
    if (!isStageMedia(b) || typeof b.src !== 'string' || !hasKey(ctx.ep.brollDur, b.src)) return;
    const L = ctx.loopLength(b);
    const shown = ctx.shownFrames(i);
    const p = hasKey(b, 'from') ? `/beats/${i}/from` : `/beats/${i}/src`;
    if (L < FPS) {
      ctx.err(p, 'S09', `loop length is ${L} frames (brollDur ${ctx.ep.brollDur[b.src]} s, from ${b.from || 0} s), minimum is ${FPS}`);
      return;
    }
    if (shown > L) {
      if (b.origin === 'source') ctx.err(p, 'S09', `source beat shows ${shown} frames but the clip only lasts ${L}: a source clip must not loop`);
      else ctx.warn(p, 'S09', `beat shows ${shown} frames but the clip lasts ${L}: it will loop`);
    }
  });
}

// S10: a src may appear in several beats only if it is a source clip and the source ranges are disjoint.
// Ranges are compared in frames exactly as the renderer plays them: [round(from*25), round(from*25) + shown).
function ruleS10(ctx) {
  const bySrc = new Map();
  ctx.beats.forEach((b, i) => {
    if (!isStageMedia(b) || typeof b.src !== 'string') return;
    const start = Math.round((b.from || 0) * FPS);
    const entry = { i, start, stop: start + ctx.shownFrames(i), source: b.origin === 'source' };
    if (!bySrc.has(b.src)) bySrc.set(b.src, []);
    bySrc.get(b.src).push(entry);
  });
  for (const [src, uses] of bySrc) {
    for (let k = 1; k < uses.length; k++) {
      const cur = uses[k];
      if (!cur.source) {
        ctx.err(`/beats/${cur.i}/src`, 'S10', `src "${src}" is reused but is not a source clip (also in beat ${uses[0].i})`);
        continue;
      }
      for (let m = 0; m < k; m++) {
        const prev = uses[m];
        if (!prev.source) continue; // already reported on the non-source use
        if (cur.start < prev.stop && prev.start < cur.stop) {
          ctx.err(`/beats/${cur.i}/src`, 'S10', `source ranges of "${src}" overlap: beat ${prev.i} plays frames [${prev.start}, ${prev.stop}), beat ${cur.i} plays [${cur.start}, ${cur.stop})`);
        }
      }
    }
  }
}

// S11: srcCrop x+w <= 1920, y+h <= 1080; |(w/h)/(16/9) - 1| <= 0.25 (error), > 0.10 (warning); only on broll/clip.
function ruleS11(ctx) {
  ctx.beats.forEach((b, i) => {
    if (!hasKey(b, 'srcCrop')) return;
    if (!isStageMedia(b)) return; // wrong beat kind is reported by S04 (full) / S05 (typo)
    const c = b.srcCrop;
    const p = `/beats/${i}/srcCrop`;
    if (c.x + c.w > 1920) ctx.err(p, 'S11', `srcCrop x+w = ${c.x + c.w} exceeds 1920`);
    if (c.y + c.h > 1080) ctx.err(p, 'S11', `srcCrop y+h = ${c.y + c.h} exceeds 1080`);
    const dev = Math.abs((c.w / c.h) / (16 / 9) - 1);
    if (dev > 0.25) ctx.err(p, 'S11', `srcCrop aspect ${(c.w / c.h).toFixed(3)} deviates ${(dev * 100).toFixed(1)}% from 16:9 (limit 25%)`);
    else if (dev > 0.10) ctx.warn(p, 'S11', `srcCrop aspect ${(c.w / c.h).toFixed(3)} deviates ${(dev * 100).toFixed(1)}% from 16:9 (warning above 10%)`);
  });
}

// S12: punch only on presenter-full beats (mode "full"); never on any pip beat (source stage/wide, stock/ai b-roll, typo).
// at in [t, end) and strictly increasing; no punch with at >= ctaT.   (Rule change from the lead, overrides spec 1c.)
function ruleS12(ctx) {
  ctx.beats.forEach((b, i) => {
    if (!hasKey(b, 'punch')) return;
    if (b.mode !== 'full') {
      ctx.err(`/beats/${i}/punch`, 'S12', 'punch is only allowed on full (presenter) beats, not on pip beats');
    }
    let prevAt = -Infinity;
    b.punch.forEach((pu, j) => {
      const p = `/beats/${i}/punch/${j}/at`;
      if (pu.at < b.t - EPS || pu.at >= ctx.end(i) - EPS) ctx.err(p, 'S12', `punch at ${pu.at} is outside the beat [${b.t}, ${ctx.end(i)})`);
      if (!(pu.at > prevAt)) ctx.err(p, 'S12', `punch times must increase (${pu.at} after ${prevAt})`);
      if (pu.at >= ctx.ep.ctaT - EPS) ctx.err(p, 'S12', `punch at ${pu.at} is at or after ctaT ${ctx.ep.ctaT}`);
      prevAt = pu.at;
    });
  });
}

// S13: stat chips. See the sub-conditions in the body.
function ruleS13(ctx) {
  const { beats, ep } = ctx;
  const all = []; // every stat with its owner beat, for the cross-beat checks below
  beats.forEach((b, i) => {
    (b.stats || []).forEach((st, j) => {
      const p = `/beats/${i}/stats/${j}/at`;
      const stop = st.at + st.dur;
      all.push({ i, j, p, start: st.at, stop, big: st.big, label: st.label });
      // (a) at inside the owner beat
      if (st.at < b.t - EPS || st.at >= ctx.end(i) - EPS) ctx.err(p, 'S13', `stat at ${st.at} is outside its beat [${b.t}, ${ctx.end(i)})`);
      // (b) carries over at most one boundary
      if (stop > ctx.end2(i) + EPS) ctx.err(p, 'S13', `stat ends at ${stop.toFixed(3)} but may only carry over one boundary (limit ${ctx.end2(i)})`);
      // (c) gone before the closing question
      if (stop > ep.ctaT + EPS) ctx.err(p, 'S13', `stat ends at ${stop.toFixed(3)}, after ctaT ${ep.ctaT}`);
      // (d) never visible during a wide beat (a stat on the wide beat itself is S08)
      beats.forEach((w, k) => {
        if (k === i || w.layout !== 'wide') return;
        if (st.at < ctx.end(k) - EPS && stop > w.t + EPS) ctx.err(p, 'S13', `stat [${st.at}, ${stop.toFixed(3)}) is visible during the wide beat ${k} [${w.t}, ${ctx.end(k)})`);
      });
    });
  });
  // (e) at most 3 visible at any instant (the count only changes when a stat starts)
  for (const s of all) {
    const visible = all.filter((o) => o.start <= s.start + EPS && o.stop > s.start + EPS);
    if (visible.length > 3) ctx.err(s.p, 'S13', `${visible.length} stats are visible at ${s.start} (maximum 3)`);
  }
  // (f) all visible stats belong to one owner beat
  for (let a = 0; a < all.length; a++) {
    for (let b2 = a + 1; b2 < all.length; b2++) {
      const x = all[a], y = all[b2];
      if (x.i === y.i) continue;
      if (x.start < y.stop - EPS && y.start < x.stop - EPS) {
        const later = x.start >= y.start ? x : y;
        const other = later === x ? y : x;
        ctx.err(later.p, 'S13', `stat overlaps a stat of beat ${other.i}: visible stats must all belong to one beat`);
      }
    }
  }
}

// S14: typo variants. card => cards 1..4; summary3 => 3 items; final4 => 4 items + sub; vs => vs.
// Fields of other variants are forbidden; times lie inside the beat.
function ruleS14(ctx) {
  ctx.beats.forEach((b, i) => {
    if (b.media !== 'typo') {
      // typo-only fields on any other beat are meaningless
      for (const key of TYPO_ONLY_KEYS) {
        if (hasKey(b, key)) ctx.err(`/beats/${i}/${key}`, 'S14', `"${key}" is only allowed on a typo beat`);
      }
      return;
    }
    const v = b.typo;
    const need = { card: ['cards'], summary3: ['items'], final4: ['items', 'sub'], vs: ['vs'] }[v];
    if (!need) return; // missing `typo` is S05
    const own = new Set(need);
    for (const key of ['cards', 'items', 'vs', 'sub']) {
      if (own.has(key) && !hasKey(b, key)) ctx.err(`/beats/${i}/${key}`, 'S14', `typo "${v}" needs "${key}"`);
      if (!own.has(key) && hasKey(b, key)) ctx.err(`/beats/${i}/${key}`, 'S14', `typo "${v}" may not have "${key}"`);
    }
    if (v === 'summary3' && hasKey(b, 'items') && b.items.length !== 3) ctx.err(`/beats/${i}/items`, 'S14', `summary3 needs exactly 3 items, got ${b.items.length}`);
    if (v === 'final4' && hasKey(b, 'items') && b.items.length !== 4) ctx.err(`/beats/${i}/items`, 'S14', `final4 needs exactly 4 items, got ${b.items.length}`);
    if (!ctx.timelineOk) return;
    const end = ctx.end(i);
    if (v === 'card' && hasKey(b, 'cards')) {
      if (Math.abs(b.cards[0].at - b.t) > EPS) ctx.err(`/beats/${i}/cards/0/at`, 'S14', `cards[0].at ${b.cards[0].at} must equal the beat start ${b.t}`);
      b.cards.forEach((c, j) => {
        if (j > 0 && !(c.at > b.cards[j - 1].at)) ctx.err(`/beats/${i}/cards/${j}/at`, 'S14', `card times must increase (${c.at} after ${b.cards[j - 1].at})`);
        if (c.at >= end - EPS) ctx.err(`/beats/${i}/cards/${j}/at`, 'S14', `card at ${c.at} is not before the beat end ${end}`);
      });
    }
    if ((v === 'summary3' || v === 'final4') && hasKey(b, 'items')) {
      b.items.forEach((it, j) => {
        if (it.at < b.t - EPS || it.at >= end - EPS) ctx.err(`/beats/${i}/items/${j}/at`, 'S14', `item at ${it.at} is outside the beat [${b.t}, ${end})`);
        if (j > 0 && it.at < b.items[j - 1].at - EPS) ctx.err(`/beats/${i}/items/${j}/at`, 'S14', `item times must not decrease (${it.at} after ${b.items[j - 1].at})`);
      });
    }
  });
}

// S15: lower only on full beats; [at, at+dur) lies inside [t, end).
function ruleS15(ctx) {
  ctx.beats.forEach((b, i) => {
    if (!hasKey(b, 'lower')) return;
    if (b.mode !== 'full') ctx.err(`/beats/${i}/lower`, 'S15', 'a lower third is only allowed on full beats');
    if (!ctx.timelineOk) return; // end(i) is meaningless when S01 failed
    const { at, dur } = b.lower;
    const end = ctx.end(i);
    if (at < b.t - EPS) ctx.err(`/beats/${i}/lower/at`, 'S15', `lower third starts at ${at}, before its beat ${b.t}`);
    if (at + dur > end + EPS) ctx.err(`/beats/${i}/lower/dur`, 'S15', `lower third ends at ${(at + dur).toFixed(3)}, after its beat end ${end}`);
  });
}

// S16 (face box vs lanes): NOT implemented in this step.
// TODO(CF-A66): S16 needs the engine LANES table (header lanes, lowerThird, cta, rail) to test
// the punch-zoomed face rectangle against; emit nothing for it until then.

// S17 (warning): text budgets in graphemes (spec section 4, "Budget" column). The DOM gate is authoritative.
function ruleS17(ctx) {
  const { ep } = ctx;
  const check = (p, text, budget, what) => {
    if (typeof text !== 'string' || budget === undefined) return;
    const g = graphemes(text);
    if (g > budget) ctx.warn(p, 'S17', `${what} is ${g} graphemes, budget is ${budget}`);
  };
  check('/brand', ep.brand, 26, 'brand');
  check('/officialTag', ep.officialTag, 22, 'officialTag (source credit)');
  check('/breakingLabel', ep.breakingLabel, 20, 'breakingLabel (lower-third label)');
  check('/page/path', ep.page.domain + ep.page.path, 40, 'page.domain + page.path (source URL)');
  check('/cta', ep.cta, 60, 'cta');
  check('/endcard/eyebrow', ep.endcard.eyebrow, 40, 'endcard.eyebrow');
  check('/endcard/titleA', ep.endcard.titleA, 24, 'endcard.titleA');
  check('/endcard/titleB', ep.endcard.titleB, 36, 'endcard.titleB');
  check('/endcard/cta', ep.endcard.cta, 60, 'endcard.cta');
  ctx.beats.forEach((b, i) => {
    const at = (k) => `/beats/${i}/${k}`;
    check(at('kicker'), b.kicker, 24, 'kicker');
    if (b.mode === 'pip') {
      // The headline lane and budget depend on the scene kind.
      let budget;
      let what = 'headline';
      if (b.media === 'typo') {
        if (b.typo === 'card') { budget = 36; what = 'typo-title (card)'; }
        else if (b.typo === 'final4') { budget = 30; what = 'typo-title (final4)'; }
        else { budget = 40; what = `typo-eyebrow (${b.typo})`; }
      } else {
        budget = b.layout === 'wide' ? 48 : 44;
      }
      check(at('headline'), b.headline, budget, what);
      if (b.media === 'typo') check(at('sub'), b.sub, 44, 'typo-sub (final4)');
      else check(at('sub'), b.sub, 48, 'description');
    }
    (b.stats || []).forEach((s, j) => {
      check(`${at('stats')}/${j}/big`, s.big, 10, 'stat big');
      check(`${at('stats')}/${j}/label`, s.label, 18, 'stat label');
    });
    (b.cards || []).forEach((c, j) => c.lines.forEach((l, k) => check(`${at('cards')}/${j}/lines/${k}`, l, 38, 'typo-line')));
    (b.items || []).forEach((it, j) => check(`${at('items')}/${j}/text`, it.text, b.typo === 'final4' ? 18 : 14, `typo-item (${b.typo})`));
    if (b.vs) {
      for (const side of ['left', 'right']) {
        const s = b.vs[side];
        check(`${at('vs')}/${side}/badge`, s.badge, 18, `vs-${side}-badge`);
        check(`${at('vs')}/${side}/title`, s.title, 14, `vs-${side}-title`);
        s.lines.forEach((l, k) => check(`${at('vs')}/${side}/lines/${k}`, l, 20, `vs-${side}-line`));
      }
      check(`${at('vs')}/conclusion`, b.vs.conclusion, 48, 'vs-conclusion');
    }
    if (b.lower) {
      check(`${at('lower')}/title`, b.lower.title, 30, 'lower-title');
      check(`${at('lower')}/sub`, b.lower.sub, 44, 'lower-sub');
    }
  });
}

// S18 (warning): estimated chip-row width <= 1138 for the chips visible together.
// width = sum(0.62*38*g(big) + 0.6*30*g(label) + 44) + 14*(n-1)   (38 px big, 30 px label: the engine's chip sizes)
function ruleS18(ctx) {
  const stats = [];
  ctx.beats.forEach((b, i) => (b.stats || []).forEach((s, j) => stats.push({ p: `/beats/${i}/stats/${j}`, start: s.at, stop: s.at + s.dur, big: s.big, label: s.label })));
  const reported = new Set();
  for (const s of stats) {
    const row = stats.filter((o) => o.start <= s.start + EPS && o.stop > s.start + EPS);
    const width = row.reduce((sum, o) => sum + 0.62 * 38 * graphemes(o.big || '') + 0.6 * 30 * graphemes(o.label) + 44, 0) + 14 * (row.length - 1);
    if (width > 1138 && !reported.has(s.p)) {
      reported.add(s.p);
      ctx.warn(s.p, 'S18', `estimated chip-row width ${Math.round(width)} px at ${s.start} s exceeds 1138 px (${row.length} chip(s))`);
    }
  }
}

// S19: captions agree with the episode. Hash equal; pages sorted, start < end; chunks displayStart < displayEnd;
// last page ends by voEndSec + 0.25 (ASR-aligned captions may end slightly after the measured VO end; the end card covers the caption lane); every page displayText <= 40 graphemes. Without captions: a warning only.
function ruleS19(ctx) {
  const { captions, ep } = ctx;
  if (!captions) {
    ctx.warn('/captionsInputSha256', 'S19', 'captions not checked (no captions given)');
    return;
  }
  const P = '/$captions';
  if (captions.inputSha256 !== ep.captionsInputSha256) {
    ctx.err(`${P}/inputSha256`, 'S19', `captions.inputSha256 ${captions.inputSha256} does not equal episode.captionsInputSha256 ${ep.captionsInputSha256}`);
  }
  const pages = captions.pages;
  pages.forEach((pg, k) => {
    const pp = `${P}/pages/${k}`;
    if (!(pg.start < pg.end)) ctx.err(`${pp}/end`, 'S19', `page end ${pg.end} must be after its start ${pg.start}`);
    if (k > 0 && pg.start < pages[k - 1].end - 1e-6) ctx.err(`${pp}/start`, 'S19', `pages must be sorted and not overlap: start ${pg.start} is before the previous end ${pages[k - 1].end}`);
    const g = graphemes(pg.displayText);
    if (g > 40) ctx.err(`${pp}/displayText`, 'S19', `displayText is ${g} graphemes, maximum is 40 (one line at 36 px)`);
    pg.chunks.forEach((c, m) => {
      if (!(c.displayStart < c.displayEnd)) ctx.err(`${pp}/chunks/${m}/displayEnd`, 'S19', `chunk displayEnd ${c.displayEnd} must be after displayStart ${c.displayStart}`);
    });
  });
  const last = pages[pages.length - 1];
  if (last.end > ep.voEndSec + 0.25 + EPS) ctx.err(`${P}/pages/${pages.length - 1}/end`, 'S19', `last page ends at ${last.end}, after voEndSec ${ep.voEndSec} + 0.25`);
}

// ---------------------------------------------------------------------------
// 4. Public entry point
// ---------------------------------------------------------------------------

/**
 * Validates an episode (and, optionally, its captions).
 * Returns { valid, errors, warnings, schemaSha256 }; every finding is { path, rule, message }.
 * `path` is a JSON Pointer ('' = document root; captions findings start with '/$captions').
 * Semantic rules run only when the schema pass has no errors.
 */
export function validateEpisode(episode, captions, opts = {}) {
  const { schema, sha256 } = loadSchema();
  const hasCaptions = captions !== undefined && captions !== null;

  const errors = validateAgainstSchema(episode, schema, schema, '');
  if (hasCaptions) {
    errors.push(...validateAgainstSchema(captions, { $ref: '#/$defs/captions' }, schema, '/$captions'));
  }
  const warnings = [];

  if (errors.length === 0) {
    const ctx = makeContext(episode, hasCaptions ? captions : null, opts);
    ruleS01(ctx);
    ruleS03(ctx);
    ruleS04(ctx);
    ruleS05(ctx);
    ruleS06(ctx);
    ruleS07(ctx);
    ruleS08(ctx);
    ruleS11(ctx);
    ruleS14(ctx); // runs its time checks only when S01 held
    ruleS15(ctx); // runs its time checks only when S01 held
    if (ctx.timelineOk) {
      ruleS02(ctx);
      ruleS09(ctx);
      ruleS10(ctx);
      ruleS12(ctx);
      ruleS13(ctx);
    }
    ruleS17(ctx);
    if (ctx.timelineOk) ruleS18(ctx);
    ruleS19(ctx);
    errors.push(...ctx.errors);
    warnings.push(...ctx.warnings);
  }
  return { valid: errors.length === 0, errors, warnings, schemaSha256: sha256 };
}

// ---------------------------------------------------------------------------
// 5. CLI
// ---------------------------------------------------------------------------

const USAGE = 'usage: node episode_schema.mjs validate <episode.json> [--captions <captions.json>] [--public <dir>] [--json]';

class UsageError extends Error {}

function parseArgs(argv) {
  const [command, ...rest] = argv;
  if (command !== 'validate') throw new UsageError(command ? `unknown command "${command}"` : 'missing command');
  const out = { file: null, captions: null, publicDir: null, json: false };
  for (let i = 0; i < rest.length; i++) {
    const a = rest[i];
    if (a === '--json') out.json = true;
    else if (a === '--captions' || a === '--public') {
      if (i + 1 >= rest.length) throw new UsageError(`${a} needs a value`);
      out[a === '--captions' ? 'captions' : 'publicDir'] = rest[++i];
    } else if (a.startsWith('--')) throw new UsageError(`unknown option ${a}`);
    else if (out.file === null) out.file = a;
    else throw new UsageError(`unexpected argument ${a}`);
  }
  if (out.file === null) throw new UsageError('missing <episode.json>');
  return out;
}

function readJson(file, what) {
  let text;
  try { text = fs.readFileSync(file, 'utf8'); } catch (e) { throw new Error(`cannot read ${what} ${file}: ${e.message}`); }
  try { return JSON.parse(text); } catch (e) { throw new Error(`${what} ${file} is not valid JSON: ${e.message}`); }
}

const oneLine = (s) => String(s).replace(/\s*[\r\n]+\s*/g, ' ');

/** Runs the CLI without touching process state. Returns { exitCode, stdout, stderr }. */
export function runCli(argv) {
  try {
    const args = parseArgs(argv);
    const episode = readJson(args.file, 'episode');
    const captions = args.captions ? readJson(args.captions, 'captions') : undefined;
    if (args.publicDir && !fs.existsSync(args.publicDir)) throw new Error(`--public directory ${args.publicDir} does not exist`);
    loadSchema(); // a broken schema file is a usage/IO-class failure (exit 2), not a validation result
    const result = validateEpisode(episode, captions, { publicDir: args.publicDir || undefined });
    const exitCode = result.valid ? 0 : 1;
    if (args.json) {
      const { valid, errors, warnings, schemaSha256 } = result;
      return { exitCode, stdout: `${JSON.stringify({ valid, errors, warnings, schemaSha256 })}\n`, stderr: '' };
    }
    const line = (kind, f) => `${kind} ${f.path === '' ? '/' : f.path} [${f.rule}] ${oneLine(f.message)}`;
    const lines = [
      ...result.errors.map((f) => line('ERROR', f)),
      ...result.warnings.map((f) => line('WARNING', f)),
      `EPISODE_SCHEMA valid=${result.valid} errors=${result.errors.length} warnings=${result.warnings.length}`,
    ];
    return { exitCode, stdout: `${lines.join('\n')}\n`, stderr: '' };
  } catch (e) {
    const usage = e instanceof UsageError ? `\n${USAGE}` : '';
    return { exitCode: 2, stdout: '', stderr: `episode_schema: ${oneLine(e.message)}${usage}\n` };
  }
}

// Run the CLI only when this file is executed directly (importing it has no side effects).
function isDirectRun() {
  if (!process.argv[1]) return false;
  try { return import.meta.url === pathToFileURL(fs.realpathSync(process.argv[1])).href; } catch { return false; }
}

if (isDirectRun()) {
  const { exitCode, stdout, stderr } = runCli(process.argv.slice(2));
  if (stdout) process.stdout.write(stdout);
  if (stderr) process.stderr.write(stderr);
  process.exitCode = exitCode;
}
