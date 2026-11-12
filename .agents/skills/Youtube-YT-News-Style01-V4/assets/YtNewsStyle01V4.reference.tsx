import React, { useEffect, useLayoutEffect, useState } from "react";
import {
  OffthreadVideo,
  Loop,
  Freeze,
  Sequence,
  spring,
  staticFile,
  continueRender,
  cancelRender,
  delayRender,
  useCurrentFrame,
  useVideoConfig,
  CalculateMetadataFunction,
} from "remotion";

// ===========================================================================
// YtNewsStyle01V4 — 16:9 AI-news report (1920x1080@25), data-driven by episode schema v1
// Format "Youtube-YT-News-Style01-V4":
//   P = presenter full-bleed          S = browser-window stage + museum-card picture + presenter card
//   T = browser-window stage + text card (card | summary3 | final4 | vs) + presenter card
//   W = wide 16:9 source window, presenter hidden        E = end card
// The engine holds NO episode data: `episode` and `captions` arrive as Remotion props.
// Scene changes are true cross-fades driven by the pure `layerPlan(frame, beats)`; the component renders FROM that plan.
// ===========================================================================

// ---- Design tokens --------------------------------------------------------
const NAVY = "#0B0E17";
const NAVY_2 = "#141A2B";
const NAVY_3 = "#0E1322";
const CREAM = "#F5F1E8";
const CREAM_DIM = "#CFC9BE";
const AMBER = "#F2B34C";
const CLAY = "#D97757";
const MINT = "#8FD6B4";
const GOLD = "#F59E0B"; // karaoke locked style
const GOLD_LIGHT = "#FDE68A";
const FONT = '"KanitX", "Kanit", system-ui, -apple-system, sans-serif';

// ---- Timing ---------------------------------------------------------------
const MODE_BLEND_SEC = 0.55;
export const IN_F = 14; // frames: presenter morph / incoming window fade (= ceil(MODE_BLEND_SEC * 25))
export const XF_F = 9; // frames: scene-to-scene cross-fade inside one frame (S/T->S/T, W->W)
export const OUT_F = 9; // frames: outgoing layer fades under the incoming one, then unmounts

// ---- Frame geometry (locked) ----------------------------------------------
const W = 1920;
const H = 1080;

// ===========================================================================
// Episode schema v1 (types) — one definition shared with assets/episode.schema.json
// ===========================================================================
export type NormRect = { x: number; y: number; w: number; h: number };
export type SrcCrop = { x: number; y: number; w: number; h: number }; // integer source px of the 1920x1080 frame
export type Rect = { w: number; h: number };
export type Tone = "amber" | "mint" | "clay";
export interface Stat { at: number; dur: number; big?: string; label: string; tone?: Tone }
export interface Punch { at: number; z: number; fx?: number; fy?: number }
export interface Card { at: number; lines: string[] }
export interface Item { at: number; text: string; icon?: string }
export interface VsSide { title: string; badge: string; lines: string[] }
export interface Vs { left: VsSide; right: VsSide; conclusion: string }
export interface Lower { at: number; dur: number; title: string; sub: string }

export interface Beat {
  t: number; // absolute seconds, beat start
  mode: "full" | "pip"; // full = presenter full-bleed
  media?: "broll" | "clip" | "typo"; // pip only
  layout?: "stage" | "wide"; // pip only; wide = source clip only
  src?: string;
  from?: number; // seconds into the public cut file (not into the original video)
  origin?: "source" | "stock" | "ai";
  srcCrop?: SrcCrop;
  kicker?: string;
  headline?: string;
  sub?: string;
  stats?: Stat[];
  punch?: Punch[]; // presenter-full beats only
  typo?: "card" | "summary3" | "final4" | "vs";
  cards?: Card[];
  items?: Item[];
  vs?: Vs;
  lower?: Lower; // full beats only
}

export interface EpisodeData {
  schema: "yt-news-v4-episode/1";
  assetDir: string; // public/<assetDir>/
  avatarFile: string; // public/<assetDir>/<avatarFile>
  avatarFaceBox: NormRect; // face + hair box, normalised to the 1920x1080 avatar frame
  fps: 25;
  voEndSec: number; // narration end; the end card starts here
  totalDurationSec: number; // voEndSec + 3..5
  ctaT: number; // closing question appears (absolute s)
  captionsInputSha256: string; // must equal captions.inputSha256
  brand: string;
  dateLabel: string;
  breakingLabel: string;
  officialTag: string;
  page: { domain: string; path: string };
  cta: string;
  endcard: { eyebrow: string; titleA: string; titleB: string; cta: string };
  brollDur: Record<string, number>; // src -> public mp4 duration in seconds (±1 frame)
  beats: Beat[];
}

export interface CaptionWord { w: string; s: number; e: number }
export interface CaptionChunk { text: string; displaySpaceBefore: string; displayStart: number; displayEnd: number; spaceBefore?: string; tokens?: CaptionWord[]; sourceTokens?: CaptionWord[]; merged_from?: number[]; scriptStart?: number; scriptEnd?: number; displayBoundReason?: string }
export interface CaptionPage { start: number; end: number; displayText: string; chunks: CaptionChunk[]; text?: string; leadingWhitespace?: string; boundReason?: string; words?: CaptionWord[] }
export interface CaptionData { schema: number; algorithm: string; inputSha256: string; pages: CaptionPage[]; trailingSpace?: string; diagnostics?: unknown }

export const V4_EPISODE_KEYS = ["schema", "assetDir", "avatarFile", "avatarFaceBox", "fps", "voEndSec", "totalDurationSec", "ctaT", "captionsInputSha256", "brand", "dateLabel", "breakingLabel", "officialTag", "page", "cta", "endcard", "brollDur", "beats"] as const;
export const V4_BEAT_KEYS = ["t", "mode", "media", "layout", "src", "from", "origin", "srcCrop", "kicker", "headline", "sub", "stats", "punch", "typo", "cards", "items", "vs", "lower"] as const;

// ===========================================================================
// Engine-side check (fail-closed). Covers exactly what the renderer dereferences;
// it is never stricter than scripts/episode_schema.mjs (agreement test proves it).
// ===========================================================================
const SRC_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/;
const DIR_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const MP4_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.mp4$/;
const ICONS = ["✍️", "📊", "💻", "💡", "📄", "📝", "🧾", "🗣️", "🔎", "🤖", "🌅", "⚠️", "🧪", "⏱️", "🗒️", "▶️", "🌍", "🔓", "🛡️", "🧬", "🎭", "🚫", "🧠", "🚀", "💸", "✨"];

export function checkEpisodeMinimal(ep: unknown, cap: unknown): string[] {
  const errs: string[] = [];
  const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
  const fin = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
  const str = (v: unknown): v is string => typeof v === "string" && v.length > 0;
  const keys = (o: Record<string, unknown>, allowed: readonly string[], where: string) => { for (const k of Object.keys(o)) if (!allowed.includes(k)) errs.push(`${where}.${k} is not a known key`); };
  const finAt = (o: unknown, k: string, where: string) => { if (!isObj(o) || !fin(o[k])) errs.push(`${where}.${k} must be a finite number`); };
  const strAt = (o: unknown, k: string, where: string) => { if (!isObj(o) || !str(o[k])) errs.push(`${where}.${k} must be a non-empty string`); };
  const lines = (v: unknown, where: string) => { if (!Array.isArray(v) || v.length < 1 || v.length > 3 || !v.every(str)) errs.push(`${where} must be 1..3 non-empty strings`); };
  if (!isObj(ep)) { errs.push("episode must be an object"); }
  else {
    keys(ep, V4_EPISODE_KEYS, "episode");
    if (ep.schema !== "yt-news-v4-episode/1") errs.push('episode.schema must be "yt-news-v4-episode/1"');
    if (typeof ep.assetDir !== "string" || !DIR_RE.test(ep.assetDir)) errs.push("episode.assetDir must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$");
    if (typeof ep.avatarFile !== "string" || !MP4_RE.test(ep.avatarFile)) errs.push("episode.avatarFile must be a plain .mp4 file name");
    const fb = ep.avatarFaceBox;
    if (!isObj(fb)) errs.push("episode.avatarFaceBox must be an object");
    else for (const k of ["x", "y", "w", "h"]) if (!fin(fb[k]) || (fb[k] as number) < 0 || (fb[k] as number) > 1) errs.push(`episode.avatarFaceBox.${k} must be a number in 0..1`);
    if (ep.fps !== 25) errs.push("episode.fps must be 25");
    for (const k of ["voEndSec", "totalDurationSec", "ctaT"]) finAt(ep, k, "episode");
    for (const k of ["brand", "dateLabel", "breakingLabel", "officialTag", "cta"]) strAt(ep, k, "episode");
    if (!isObj(ep.page)) errs.push("episode.page must be an object"); else { strAt(ep.page, "domain", "episode.page"); strAt(ep.page, "path", "episode.page"); }
    if (!isObj(ep.endcard)) errs.push("episode.endcard must be an object"); else for (const k of ["eyebrow", "titleA", "titleB", "cta"]) strAt(ep.endcard, k, "episode.endcard");
    const bd = ep.brollDur;
    if (!isObj(bd)) errs.push("episode.brollDur must be an object");
    else for (const [k, v] of Object.entries(bd)) { if (!SRC_RE.test(k)) errs.push(`episode.brollDur key "${k}" must match ^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$`); if (!fin(v) || v <= 0) errs.push(`episode.brollDur.${k} must be a positive finite number`); }
    if (!Array.isArray(ep.beats) || ep.beats.length === 0) errs.push("episode.beats must be a non-empty array");
    else {
      let prev = -Infinity;
      ep.beats.forEach((b: unknown, i: number) => {
        const w = `episode.beats[${i}]`;
        if (!isObj(b)) { errs.push(`${w} must be an object`); return; }
        keys(b, V4_BEAT_KEYS, w);
        if (!fin(b.t)) errs.push(`${w}.t must be a finite number`);
        else { if (b.t <= prev) errs.push(`${w}.t must be strictly greater than the previous beat`); prev = b.t; }
        if (b.mode !== "full" && b.mode !== "pip") errs.push(`${w}.mode must be "full" or "pip"`);
        if (b.kicker !== undefined && !str(b.kicker)) errs.push(`${w}.kicker must be a non-empty string`);
        if (b.sub !== undefined && !str(b.sub)) errs.push(`${w}.sub must be a non-empty string`);
        if (b.mode === "full") {
          if (b.punch !== undefined) { if (!Array.isArray(b.punch)) errs.push(`${w}.punch must be an array`); else b.punch.forEach((p: unknown, j: number) => { finAt(p, "at", `${w}.punch[${j}]`); finAt(p, "z", `${w}.punch[${j}]`); if (isObj(p)) for (const k of ["fx", "fy"]) if (p[k] !== undefined && !fin(p[k])) errs.push(`${w}.punch[${j}].${k} must be a finite number`); }); }
          if (b.lower !== undefined) { const lw = `${w}.lower`; if (!isObj(b.lower)) errs.push(`${lw} must be an object`); else { finAt(b.lower, "at", lw); finAt(b.lower, "dur", lw); strAt(b.lower, "title", lw); strAt(b.lower, "sub", lw); } }
        }
        if (b.stats !== undefined) {
          if (!Array.isArray(b.stats)) errs.push(`${w}.stats must be an array`);
          else b.stats.forEach((s: unknown, j: number) => { const sw = `${w}.stats[${j}]`; finAt(s, "at", sw); finAt(s, "dur", sw); strAt(s, "label", sw); if (isObj(s)) { if (s.big !== undefined && !str(s.big)) errs.push(`${sw}.big must be a non-empty string`); if (s.tone !== undefined && s.tone !== "amber" && s.tone !== "mint" && s.tone !== "clay") errs.push(`${sw}.tone must be amber, mint or clay`); } });
        }
        if (b.mode !== "pip") return;
        if (b.media !== "broll" && b.media !== "clip" && b.media !== "typo") errs.push(`${w}.media must be broll, clip or typo`);
        if (b.layout !== "stage" && b.layout !== "wide") errs.push(`${w}.layout must be stage or wide`);
        strAt(b, "headline", w);
        if (b.media === "broll" || b.media === "clip") {
          if (typeof b.src !== "string" || !SRC_RE.test(b.src)) errs.push(`${w}.src must match ^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$`);
          else if (!isObj(bd) || !Object.prototype.hasOwnProperty.call(bd, b.src)) errs.push(`${w}.src "${b.src}" is not a key of brollDur`);
          if (b.origin !== "source" && b.origin !== "stock" && b.origin !== "ai") errs.push(`${w}.origin must be source, stock or ai`);
          if (b.from !== undefined && (!fin(b.from) || b.from < 0)) errs.push(`${w}.from must be a finite number >= 0`);
          if (b.srcCrop !== undefined) {
            const c = b.srcCrop;
            if (!isObj(c) || !["x", "y", "w", "h"].every(k => Number.isInteger(c[k]))) errs.push(`${w}.srcCrop must have integer x, y, w, h`);
            else {
              const [x, y, cw, ch] = [c.x, c.y, c.w, c.h] as number[];
              if (x < 0 || x > 1280 || y < 0 || y > 720 || cw < 640 || cw > 1920 || ch < 360 || ch > 1080) errs.push(`${w}.srcCrop is outside the allowed ranges`);
              if (x + cw > 1920 || y + ch > 1080) errs.push(`${w}.srcCrop must stay inside the 1920x1080 frame`);
            }
          }
        }
        if (b.media === "typo") {
          const n = (v: unknown) => (Array.isArray(v) ? v.length : -1);
          const items = (cnt: number) => {
            if (n(b.items) !== cnt) errs.push(`${w}.items must have exactly ${cnt} entries`);
            else (b.items as unknown[]).forEach((it, j) => { finAt(it, "at", `${w}.items[${j}]`); strAt(it, "text", `${w}.items[${j}]`); if (isObj(it) && it.icon !== undefined && (typeof it.icon !== "string" || !ICONS.includes(it.icon))) errs.push(`${w}.items[${j}].icon is not in the allowed list`); });
          };
          if (b.typo === "card") {
            if (!Array.isArray(b.cards) || b.cards.length < 1 || b.cards.length > 4) errs.push(`${w}.cards must have 1..4 entries`);
            else b.cards.forEach((c: unknown, j: number) => { finAt(c, "at", `${w}.cards[${j}]`); lines(isObj(c) ? c.lines : undefined, `${w}.cards[${j}].lines`); });
          } else if (b.typo === "summary3") items(3);
          else if (b.typo === "final4") items(4);
          else if (b.typo === "vs") {
            const v = b.vs;
            if (!isObj(v)) errs.push(`${w}.vs must be an object`);
            else {
              strAt(v, "conclusion", `${w}.vs`);
              for (const side of ["left", "right"]) { const s = v[side]; if (!isObj(s)) errs.push(`${w}.vs.${side} must be an object`); else { strAt(s, "title", `${w}.vs.${side}`); strAt(s, "badge", `${w}.vs.${side}`); lines(s.lines, `${w}.vs.${side}.lines`); } }
            }
          } else errs.push(`${w}.typo must be card, summary3, final4 or vs`);
        }
      });
    }
  }
  if (!isObj(cap)) errs.push("captions must be an object");
  else {
    if (!Array.isArray(cap.pages)) errs.push("captions.pages must be an array");
    else cap.pages.forEach((p: unknown, i: number) => {
      const w = `captions.pages[${i}]`;
      if (!isObj(p)) { errs.push(`${w} must be an object`); return; }
      if (!fin(p.start) || !fin(p.end) || p.start >= p.end) errs.push(`${w}.start/end must be finite with start < end`);
      if (typeof p.displayText !== "string") errs.push(`${w}.displayText must be a string`);
      if (!Array.isArray(p.chunks)) errs.push(`${w}.chunks must be an array`);
      else p.chunks.forEach((c: unknown, j: number) => { const cw = `${w}.chunks[${j}]`; if (!isObj(c)) { errs.push(`${cw} must be an object`); return; } if (typeof c.text !== "string" || typeof c.displaySpaceBefore !== "string") errs.push(`${cw}.text and displaySpaceBefore must be strings`); if (!fin(c.displayStart) || !fin(c.displayEnd) || c.displayStart >= c.displayEnd) errs.push(`${cw}.displayStart/displayEnd must be finite with displayStart < displayEnd`); });
    });
    if (isObj(ep) && ep.captionsInputSha256 !== cap.inputSha256) errs.push("episode.captionsInputSha256 does not equal captions.inputSha256");
  }
  return errs;
}

// ===========================================================================
// LANES — single source of truth for every text lane, backing and layer rect.
// Every rect is {x,y,w,h} px on the 1920x1080 frame (r = corner radius).
// `scenes` lists the scene kinds a lane exists in (E = end card).
// ===========================================================================
export type SceneKind = "P" | "S" | "T" | "W";
export type LaneScene = SceneKind | "E";
export type LaneRole = "text" | "backing" | "layer";
export interface Lane { x: number; y: number; w: number; h: number; r: number; scenes: LaneScene[]; role: LaneRole }
const lane = (x: number, y: number, w: number, h: number, role: LaneRole, scenes: LaneScene[], r = 0): Lane => ({ x, y, w, h, r, scenes, role });
const ALL: LaneScene[] = ["P", "S", "T", "W"];
export const LANES = {
  "header.brand": lane(96, 54, 480, 44, "text", ALL, 12),
  "header.kicker": lane(1344, 54, 480, 44, "text", ALL, 12),
  "avatar": lane(1362, 100, 478, 850, "layer", ["S", "T", "W"], 26), // presenter card (hidden in W)
  "avatar.full": lane(0, 0, 1920, 1080, "layer", ["P"]),
  "stage": lane(80, 100, 1210, 840, "layer", ["S", "T"], 22),
  "split.chrome": lane(80, 100, 1210, 52, "backing", ["S", "T"]),
  "split.chrome.url": lane(164, 104, 700, 44, "text", ["S"], 10),
  "split.chrome.label": lane(872, 104, 400, 44, "text", ["S"]),
  "split.picture": lane(116, 172, 1138, 640, "layer", ["S"], 16),
  "split.lower": lane(80, 812, 1210, 128, "backing", ["S"]),
  "split.headline": lane(116, 820, 1138, 56, "text", ["S"]),
  "typo.backing": lane(80, 152, 1210, 716, "backing", ["T"]),
  "typo.content": lane(120, 172, 1130, 676, "text", ["T"]),
  "sub": lane(116, 878, 1138, 56, "text", ["P", "S", "T"]), // description, or the stat rail
  "full.lowerThird": lane(96, 520, 960, 196, "text", ["P"]),
  "full.cta": lane(260, 722, 1400, 150, "text", ["P"]),
  "wide.window": lane(320, 100, 1280, 844, "layer", ["W"], 22),
  "wide.chrome": lane(320, 100, 1280, 52, "backing", ["W"]),
  "wide.chrome.url": lane(404, 104, 640, 44, "text", ["W"], 10),
  "wide.chrome.label": lane(1182, 104, 400, 44, "text", ["W"]),
  "wide.picture": lane(320, 152, 1280, 720, "layer", ["W"]),
  "wide.bar": lane(320, 872, 1280, 72, "backing", ["W"]),
  "wide.headline": lane(344, 880, 1232, 56, "text", ["W"]),
  "caption": lane(96, 954, 1728, 72, "text", ALL),
  "end.eyebrow": lane(360, 300, 1200, 44, "text", ["E"]),
  "end.title": lane(160, 360, 1600, 94, "text", ["E"]),
  "end.sub": lane(260, 470, 1400, 60, "text", ["E"]),
  "end.cta": lane(260, 560, 1400, 144, "text", ["E"]),
};
export type LaneId = keyof typeof LANES;

export function sceneKind(b: Beat): SceneKind {
  if (b.mode === "full") return "P";
  if (b.media === "typo") return "T";
  return b.layout === "wide" ? "W" : "S";
}

// ===========================================================================
// Transitions (spec D9) — ONE pure function decides everything a frame shows.
// z-order: backdrop 0 · outgoing frame 10 · incoming frame 11 · presenter 20 (a wide window arriving over a
// leaving presenter takes 21) · header 30 · stat rail 40 · lower third 45 · CTA 46 · caption 60 · end card 90.
// Rules: the outgoing layer HOLDS at opacity 1 until the incoming layer reaches 1, then fades under it
// over OUT_F frames and unmounts; outgoing labels unmount at f = 0; incoming labels start at labelDelayFrames.
// ===========================================================================
export type FrameRect = { x: number; y: number; w: number; h: number; r: number };
export interface SceneLayerPlan { key: string; index: number; kind: "S" | "T" | "W"; frame: "stage" | "wide"; role: "current" | "outgoing"; opacity: number; startFrame: number; labels: boolean /* labels render only on the current layer */ }
export interface FramePlan { mounted: boolean; opacity: number; z: number }
export interface AvatarPlan {
  rect: FrameRect;
  opacity: number;
  cropProgress: number; // 0 = full-bleed, 1 = presenter card
  interpolated: boolean; // the rect is mid-morph (only when both states are fully visible)
  punch: { z: number; fx: number; fy: number };
}
export interface LayerPlan {
  frame: number;
  index: number; // current beat
  kind: SceneKind;
  startFrame: number; // ceil(beat.t * fps)
  localFrame: number; // f = frame - startFrame
  prevIndex: number | null;
  prevKind: SceneKind | null;
  boundary: string | null; // e.g. "P>S" — the boundary INTO the current beat
  transitionActive: boolean;
  outgoingIndex: number | null; // at most one outgoing layer (beats last >= 1.0 s)
  outgoingKind: SceneKind | null;
  outgoingCount: number;
  labelDelayFrames: number; // incoming labels start this many frames after startFrame
  labelStartFrame: number; // startFrame + labelDelayFrames
  stage: FramePlan;
  wide: FramePlan;
  layers: SceneLayerPlan[]; // scene layers in S/T/W frames (outgoing first)
  avatar: AvatarPlan;
  incomingOpacity: number; // effective opacity of the incoming picture (scene layer x frame, or the presenter on P)
  coverOpacity: number; // effective opacity of the outgoing layer, 0 when there is none
  coverageOk: boolean; // incomingOpacity >= 1 || coverOpacity >= 1 — no frame may be emptier than both scenes
}

const easeIO = (x: number) => 0.5 - 0.5 * Math.cos(Math.PI * Math.min(1, Math.max(0, x)));
const lerp = (a: number, b: number, p: number) => a + (b - a) * p;
const lerpRect = (a: FrameRect, b: FrameRect, p: number): FrameRect => ({ x: lerp(a.x, b.x, p), y: lerp(a.y, b.y, p), w: lerp(a.w, b.w, p), h: lerp(a.h, b.h, p), r: lerp(a.r, b.r, p) });
const isZ = (k: SceneKind | null) => k === "S" || k === "T";

export function beatStartFrame(b: Beat, fps = 25): number { return Math.ceil(b.t * fps); }

// Frames (after the new beat starts) during which incoming labels wait. Spec §5 table, last column.
export function labelDelayFor(prev: SceneKind | null, cur: SceneKind): number {
  if (prev === null) return 0;
  if ((isZ(prev) && isZ(cur)) || (prev === "W" && cur === "W") || (prev === "P" && cur === "P")) return 0;
  return IN_F;
}
// A typo row / chip / label never starts before the labels of its scene are allowed to enter.
export const entranceStartSec = (at: number, plan: Pick<LayerPlan, "labelStartFrame">, fps = 25): number => Math.max(at, plan.labelStartFrame / fps);

export function layerPlan(frame: number, beats: Beat[], fps = 25): LayerPlan {
  let index = 0;
  for (let i = 0; i < beats.length; i++) { if (frame >= Math.ceil(beats[i].t * fps)) index = i; else break; }
  const cur = beats[index], kind = sceneKind(cur), startFrame = Math.ceil(cur.t * fps), f = Math.max(0, frame - startFrame);
  const prevIndex = index > 0 ? index - 1 : null, prev = prevIndex === null ? null : beats[prevIndex], pk = prev ? sceneKind(prev) : null;
  const labelDelayFrames = labelDelayFor(pk, kind);
  const zp = isZ(pk), zc = isZ(kind);
  // Frames until every transition object of this boundary has settled.
  const settle = pk === null ? 0 : (zp && zc) || (pk === "W" && kind === "W") ? XF_F + OUT_F : (zp && kind === "W") || (pk === "W" && zc) ? IN_F + OUT_F : pk === "P" && kind === "P" ? 0 : IN_F;
  const active = pk !== null && f < settle;
  const hold = (hf: number) => (f < hf ? 1 : 1 - easeIO((f - hf) / OUT_F)); // outgoing: hold, then fade
  const eIn = easeIO(f / IN_F), eXf = easeIO(f / XF_F);

  const full = LANES["avatar.full"], card = LANES.avatar;
  const FULL: FrameRect = { x: full.x, y: full.y, w: full.w, h: full.h, r: full.r }, CARD: FrameRect = { x: card.x, y: card.y, w: card.w, h: card.h, r: card.r };
  const stage: FramePlan = { mounted: false, opacity: 0, z: 10 }, wide: FramePlan = { mounted: false, opacity: 0, z: 10 };
  const layers: SceneLayerPlan[] = [];
  const mk = (i: number, k: "S" | "T" | "W", role: "current" | "outgoing", opacity: number): SceneLayerPlan => ({ key: `scene-${i}`, index: i, kind: k, frame: k === "W" ? "wide" : "stage", role, opacity, startFrame: Math.ceil(beats[i].t * fps), labels: role === "current" });
  const curK = kind as "S" | "T" | "W", prevK = pk as "S" | "T" | "W";
  // Presenter (default = the current scene's settled state).
  let av: Omit<AvatarPlan, "punch"> = kind === "P" ? { rect: FULL, opacity: 1, cropProgress: 0, interpolated: false } : kind === "W" ? { rect: CARD, opacity: 0, cropProgress: 1, interpolated: false } : { rect: CARD, opacity: 1, cropProgress: 1, interpolated: false };
  // Settled frames.
  if (zc) { stage.mounted = true; stage.opacity = 1; stage.z = 11; }
  if (kind === "W") { wide.mounted = true; wide.opacity = 1; wide.z = 11; }
  let curOpacity = 1;
  if (active) {
    if (pk === "P" && zc) { av = { rect: lerpRect(FULL, CARD, eIn), opacity: 1, cropProgress: eIn, interpolated: true }; }
    else if (zp && kind === "P") { stage.mounted = true; stage.opacity = 1; stage.z = 10; layers.push(mk(prevIndex as number, prevK, "outgoing", 1)); av = { rect: lerpRect(CARD, FULL, eIn), opacity: 1, cropProgress: 1 - eIn, interpolated: true }; }
    else if (zp && zc) { curOpacity = eXf; layers.push(mk(prevIndex as number, prevK, "outgoing", hold(XF_F))); av = { rect: CARD, opacity: 1, cropProgress: 1, interpolated: false }; }
    else if (zp && kind === "W") { wide.opacity = eIn; wide.z = 21; stage.mounted = true; stage.opacity = hold(IN_F); stage.z = 10; layers.push(mk(prevIndex as number, prevK, "outgoing", 1)); av = { rect: CARD, opacity: hold(IN_F), cropProgress: 1, interpolated: false }; }
    else if (pk === "W" && zc) { stage.opacity = eIn; wide.mounted = true; wide.opacity = hold(IN_F); wide.z = 10; layers.push(mk(prevIndex as number, "W", "outgoing", 1)); av = { rect: CARD, opacity: eIn, cropProgress: 1, interpolated: false }; }
    else if (pk === "W" && kind === "W") { curOpacity = eXf; layers.push(mk(prevIndex as number, "W", "outgoing", hold(XF_F))); }
    else if (pk === "P" && kind === "W") { av = { rect: FULL, opacity: 1 - eIn, cropProgress: 0, interpolated: false }; }
    else if (pk === "W" && kind === "P") { wide.mounted = true; wide.opacity = 1; wide.z = 10; layers.push(mk(prevIndex as number, "W", "outgoing", 1)); av = { rect: FULL, opacity: eIn, cropProgress: 0, interpolated: false }; }
  }
  if (kind !== "P") layers.push(mk(index, curK, "current", curOpacity));
  layers.sort((a, b) => (a.role === b.role ? 0 : a.role === "outgoing" ? -1 : 1));

  // Punch zoom: the presenter-full state keeps its own zoom; across a presenter-state change it eases to / from 1.
  const t = frame / fps;
  const lastPunch = (b: Beat, upTo: number) => (b.punch ?? []).filter(p => upTo >= p.at).slice(-1)[0];
  const curP = kind === "P" ? lastPunch(cur, t) : undefined, prevP = pk === "P" && prev ? lastPunch(prev, Infinity) : undefined;
  const e = pk !== null && pk !== kind && active ? eIn : 1;
  const zFrom = prevP?.z ?? 1, zTo = curP?.z ?? 1, src = (e < 1 ? prevP ?? curP : curP) ?? prevP;
  const punch = { z: e < 1 ? lerp(zFrom, zTo, e) : zTo, fx: src?.fx ?? 0.5, fy: src?.fy ?? 0.5 };

  const eff = (l: SceneLayerPlan) => l.opacity * (l.frame === "stage" ? stage.opacity : wide.opacity);
  const curLayer = layers.find(l => l.role === "current"), outLayer = layers.find(l => l.role === "outgoing");
  const incomingOpacity = kind === "P" ? av.opacity : curLayer ? eff(curLayer) : 1;
  const coverOpacity = outLayer ? eff(outLayer) : 0;
  return {
    frame, index, kind, startFrame, localFrame: f, prevIndex, prevKind: pk, boundary: pk ? `${pk}>${kind}` : null,
    transitionActive: active, outgoingIndex: outLayer ? outLayer.index : null, outgoingKind: outLayer ? outLayer.kind : null, outgoingCount: layers.filter(l => l.role === "outgoing").length,
    labelDelayFrames, labelStartFrame: startFrame + labelDelayFrames, stage, wide, layers, avatar: { ...av, punch },
    incomingOpacity, coverOpacity, coverageOk: incomingOpacity >= 1 || coverOpacity >= 1,
  };
}

// ---- Source crop maths (spec §6): crop = region of the 1920x1080 source that is cover-fitted into the box ----
export function srcCropStyle(crop: SrcCrop | undefined, box: Rect): React.CSSProperties {
  if (!crop) {
    const s = Math.min(box.w / W, box.h / H);
    return { position: "absolute", width: W * s, height: H * s, left: (box.w - W * s) / 2, top: (box.h - H * s) / 2, objectFit: "contain" };
  }
  const s = Math.max(box.w / crop.w, box.h / crop.h);
  return { position: "absolute", width: W * s, height: H * s, left: -crop.x * s + (box.w - crop.w * s) / 2, top: -crop.y * s + (box.h - crop.h * s) / 2, objectFit: "fill" };
}

// ---- Fonts ----------------------------------------------------------------
let fontReady: Promise<void> | null = null;
function ensureFonts(): Promise<void> {
  if (!fontReady) {
    const defs: [string, number][] = [
      ["fonts/Kanit-ExtraBold.ttf", 800],
      ["fonts/Kanit-Bold.ttf", 700],
    ];
    fontReady = Promise.all(
      defs.map(async ([path, weight]) => {
        const ff = new FontFace("KanitX", `url(${staticFile(path)})`, { weight: String(weight) });
        await ff.load();
        (document as any).fonts.add(ff);
      })
    ).then(() => undefined);
  }
  return fontReady;
}
const useThaiFonts = () => {
  const [handle] = useState(() => delayRender("thai-fonts"));
  useEffect(() => {
    ensureFonts().then(() => continueRender(handle)).catch(cancelRender);
  }, [handle]);
};

// ---- Helpers --------------------------------------------------------------
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const springIn = (frame: number, fps: number, damping = 16, stiffness = 130) =>
  spring({ frame: Math.max(0, frame), fps, config: { damping, stiffness } });

const boundedEntrance = (t: number, start: number, fps: number): React.CSSProperties => {
  const p = clamp01(springIn(Math.round((t - start) * fps), fps, 18, 130));
  return { opacity: p, transform: `translateY(${(1 - p) * 6}px)` };
};

const tone = (k?: string) => (k === "mint" ? MINT : k === "clay" ? CLAY : AMBER);

// Position a lane container from the LANES table (optionally relative to a parent lane).
const laneBox = (id: LaneId, origin?: LaneId): React.CSSProperties => {
  const l = LANES[id], o = origin ? LANES[origin] : { x: 0, y: 0 };
  return { position: "absolute", left: l.x - o.x, top: l.y - o.y, width: l.w, height: l.h, boxSizing: "border-box" };
};

// ---- Text -----------------------------------------------------------------
// Minimum sizes: label 30 px / read 38 px. Text never shrinks; overflow is a layout bug to fix.
const MIN_PX = { label: 30, read: 38 } as const;
const LH: Record<number, number> = { 30: 44, 34: 48, 38: 56, 40: 56, 42: 58, 44: 62, 46: 64, 48: 66, 52: 68, 54: 76, 56: 76, 60: 82, 64: 86, 68: 88, 72: 94 };
const lhFor = (px: number) => LH[px] ?? Math.round(px * 1.4);
type Tier = "read" | "label";
const TextField: React.FC<{ id: string; role?: Tier; lane: LaneId; size?: number; style?: React.CSSProperties; attrs?: Record<string, string>; children: React.ReactNode }> = ({ id, role = "read", lane: laneId, size, style, attrs, children }) => {
  const px = Math.max(size ?? MIN_PX[role], MIN_PX[role]);
  return <div {...attrs} data-qc-field={id} data-qc-role={role} data-qc-tier={role} data-qc-lane={laneId} style={{ fontFamily: FONT, fontSize: px, fontWeight: 700, lineHeight: `${lhFor(px)}px`, color: CREAM, ...style }}>{children}</div>;
};

// A box behind text: solid colour (alpha >= .9), registered with the gate.
const Backing: React.FC<{ id: string; reserved?: "header" | "chrome"; occluder?: string; style: React.CSSProperties; children?: React.ReactNode; attrs?: Record<string, string | boolean> }> = ({ id, reserved, occluder, style, children, attrs }) => (
  <div {...attrs} data-qc-backing="solid" data-qc-backing-id={id} data-qc-reserved={reserved} data-qc-occluder={occluder} style={style}>{children}</div>
);

// ===========================================================================
// Scene pieces
// ===========================================================================
const Backdrop: React.FC = () => (
  <div data-qc-backdrop style={{ position: "absolute", inset: 0, zIndex: 0, backgroundColor: NAVY, backgroundImage: `radial-gradient(rgba(245,241,232,0.075) 1.2px, transparent 1.2px), linear-gradient(180deg, ${NAVY_2} 0%, ${NAVY} 100%)`, backgroundSize: "28px 28px, auto" }}>
    <div style={{ position: "absolute", left: -200, top: -260, width: 900, height: 900, borderRadius: "50%", background: "radial-gradient(circle, rgba(242,179,76,0.16), transparent 62%)" }} />
    <div style={{ position: "absolute", right: -260, bottom: -380, width: 1000, height: 1000, borderRadius: "50%", background: "radial-gradient(circle, rgba(217,119,87,0.16), transparent 62%)" }} />
  </div>
);

const Header: React.FC<{ episode: EpisodeData; beat: Beat }> = ({ episode, beat }) => (
  <>
    <div style={{ ...laneBox("header.brand"), zIndex: 30, display: "flex", alignItems: "center", justifyContent: "flex-start" }}>
      <Backing id="header.brand" reserved="header" occluder="header-brand" style={{ backgroundColor: "rgba(11,14,23,.92)", borderRadius: LANES["header.brand"].r, padding: "0 14px", height: 44 }}>
        <TextField id="brand" role="label" lane="header.brand" style={{ color: AMBER, whiteSpace: "nowrap" }}>{episode.brand} · {episode.dateLabel}</TextField>
      </Backing>
    </div>
    <div style={{ ...laneBox("header.kicker"), zIndex: 30, display: "flex", alignItems: "center", justifyContent: "flex-end" }}>
      <Backing id="header.kicker" reserved="header" occluder="header-kicker" style={{ backgroundColor: AMBER, borderRadius: LANES["header.kicker"].r, padding: "0 14px", height: 44 }}>
        <TextField id="kicker" role="label" lane="header.kicker" style={{ color: NAVY, whiteSpace: "nowrap" }}>{beat.kicker ?? "AI NEWS"}</TextField>
      </Backing>
    </div>
  </>
);

// Presenter: uniform-scale crop around the face centre; the rect, opacity and zoom come from layerPlan (morphs between full and card).
const Avatar: React.FC<{ episode: EpisodeData; av: AvatarPlan }> = ({ episode: EPISODE, av }) => {
  const rect = av.rect, p = av.cropProgress;
  const s = rect.h / H, mw = W * s, mh = H * s;
  const cx = (EPISODE.avatarFaceBox.x + EPISODE.avatarFaceBox.w / 2) * mw;
  const left = -Math.min(Math.max(cx - rect.w / 2, 0), Math.max(0, mw - rect.w));
  return (
    <div data-qc-layer="avatar" data-qc-occluder="avatar" style={{ position: "absolute", left: rect.x, top: rect.y, width: rect.w, height: rect.h, borderRadius: rect.r, overflow: "hidden", zIndex: 20, opacity: av.opacity, backgroundColor: NAVY, boxShadow: p > 0 ? `0 30px 80px rgba(0,0,0,${0.6 * p}), 0 0 40px rgba(242,179,76,${0.18 * p}), 0 0 0 2px rgba(245,241,232,${0.16 * p})` : "none" }}>
      <div data-qc-avatar-media style={{ position: "absolute", left, top: (rect.h - mh) / 2, width: mw, height: mh, transform: `scale(${av.punch.z})`, transformOrigin: `${av.punch.fx * 100}% ${av.punch.fy * 100}%` }}>
        <OffthreadVideo muted src={staticFile(`${EPISODE.assetDir}/${EPISODE.avatarFile}`)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </div>
    </div>
  );
};

// Source clips never loop (schema S09/S10), but an outgoing layer outlives its beat by up to IN_F + OUT_F frames:
// after the clip's last usable frame it holds that frame instead of restarting.
const HoldLast: React.FC<{ L: number; children: React.ReactNode }> = ({ L, children }) => {
  const local = useCurrentFrame();
  return local >= L ? <Freeze frame={L - 1}>{children}</Freeze> : <>{children}</>;
};

// Footage: starts at the first selected frame of its own beat; loops from `from`, never past the file end.
const Footage: React.FC<{ beat: Beat; episode: EpisodeData; box: Rect }> = ({ beat, episode: EPISODE, box }) => {
  const { fps } = useVideoConfig();
  const src = beat.src as string;
  const layerStartFrame = Math.ceil(beat.t * fps);
  const from = beat.from ?? 0;
  const L = Math.max(1, Math.floor((EPISODE.brollDur[src] - from) * fps) - 2);
  if (beat.origin === "source") return <Sequence from={layerStartFrame} layout="none"><HoldLast L={L}><OffthreadVideo muted src={staticFile(`${EPISODE.assetDir}/broll/${src}.mp4`)} trimBefore={Math.round(from * fps)} style={srcCropStyle(beat.srcCrop, box)} /></HoldLast></Sequence>;
  return <Sequence from={layerStartFrame} layout="none"><Loop durationInFrames={L} layout="none"><OffthreadVideo muted src={staticFile(`${EPISODE.assetDir}/broll/${src}.mp4`)} trimBefore={Math.round(from * fps)} style={srcCropStyle(beat.srcCrop, box)} /></Loop></Sequence>;
};

// What a label does on entering: wait for labelStartSec, then the bounded entrance. Outgoing layers render no labels at all.
type Labels = { on: boolean; startSec: number; t: number; fps: number };
const enter = (l: Labels, at = 0) => boundedEntrance(l.t, Math.max(at, l.startSec), l.fps);

// Browser chrome: 52 px bar (persistent in its frame); URL pill + right-hand label only for the CURRENT beat's source / AI image.
const BrowserChrome: React.FC<{ prefix: "split" | "wide"; origin: LaneId; beat: Beat | null; episode: EpisodeData; labels: Labels }> = ({ prefix, origin, beat, episode, labels }) => {
  const chromeId = `${prefix}.chrome` as LaneId, urlId = `${prefix}.chrome.url` as LaneId, labelId = `${prefix}.chrome.label` as LaneId;
  const source = !!beat && beat.media !== "typo" && beat.origin === "source", ai = !!beat && beat.media !== "typo" && beat.origin === "ai";
  return (
    <Backing id={chromeId} reserved="chrome" occluder="chrome" attrs={{ "data-qc-chrome": true }} style={{ ...laneBox(chromeId, origin), zIndex: 5, backgroundColor: "#232B45", borderBottom: "1px solid rgba(245,241,232,0.10)" }}>
      {[0, 1, 2].map(i => <div key={i} style={{ position: "absolute", left: 18 + i * 22, top: 19, width: 14, height: 14, borderRadius: 7, background: ["#FF5F56", "#FFBD2E", "#27C93F"][i] }} />)}
      {source && <Backing id={urlId} style={{ ...laneBox(urlId, chromeId), backgroundColor: NAVY_3, borderRadius: LANES[urlId].r, padding: "0 14px", ...enter(labels) }}>
        <TextField id="source-url" role="label" lane={urlId} style={{ whiteSpace: "nowrap" }}>{episode.page.domain}{episode.page.path}</TextField>
      </Backing>}
      {(source || ai) && <div data-qc-credit={source ? true : undefined} style={{ ...laneBox(labelId, chromeId), textAlign: "right", ...enter(labels) }}>
        <TextField id={source ? "source-credit" : "ai-label"} role="label" lane={labelId} style={{ color: AMBER, whiteSpace: "nowrap" }}>{source ? episode.officialTag : "ภาพประกอบ AI"}</TextField>
      </div>}
    </Backing>
  );
};

const FRAME_SHADOW = "0 30px 80px rgba(0,0,0,0.55), 0 0 0 1px rgba(245,241,232,0.14)";

// Persistent stage window (S and T): frame + chrome bar; scene layers (children) are positioned relative to the stage lane.
const StageFrame: React.FC<{ plan: FramePlan; kind: SceneKind; chromeBeat: Beat | null; episode: EpisodeData; labels: Labels; children: React.ReactNode }> = ({ plan, kind, chromeBeat, episode, labels, children }) => (
  <div data-qc-layer="stage" data-qc-scene={kind} style={{ ...laneBox("stage"), zIndex: plan.z, opacity: plan.opacity, borderRadius: LANES.stage.r, overflow: "hidden", backgroundColor: NAVY_2, boxShadow: FRAME_SHADOW }}>
    {children}
    <BrowserChrome prefix="split" origin="stage" beat={chromeBeat} episode={episode} labels={labels} />
  </div>
);

// Persistent wide window (W): frame + chrome bar; picture layers are children.
const WideFrame: React.FC<{ plan: FramePlan; chromeBeat: Beat | null; episode: EpisodeData; labels: Labels; children: React.ReactNode }> = ({ plan, chromeBeat, episode, labels, children }) => (
  <div data-qc-layer="stage" data-qc-scene="wide" style={{ ...laneBox("wide.window"), zIndex: plan.z, opacity: plan.opacity, borderRadius: LANES["wide.window"].r, overflow: "hidden", backgroundColor: NAVY_2, boxShadow: FRAME_SHADOW }}>
    {children}
    <BrowserChrome prefix="wide" origin="wide.window" beat={chromeBeat} episode={episode} labels={labels} />
  </div>
);

// One scene layer inside a frame. The same keyed instance moves from "current" to "outgoing" and keeps its footage playing.
const SceneLayer: React.FC<{ layer: SceneLayerPlan; children: React.ReactNode }> = ({ layer, children }) => (
  <div data-qc-scene-role={layer.role} data-qc-scene-index={layer.index} style={{ position: "absolute", inset: 0, opacity: layer.opacity, zIndex: layer.role === "current" ? 2 : 1 }}>{children}</div>
);

// Museum card (S): picture + headline + description (the description yields to the stat rail).
const MuseumScene: React.FC<{ beat: Beat; episode: EpisodeData; statVisible: boolean; labels: Labels; current: boolean }> = ({ beat, episode, statVisible, labels, current }) => {
  const pic = LANES["split.picture"];
  return (
    <>
      <div data-qc-layer="picture" data-qc-footage={current ? beat.src : undefined} style={{ ...laneBox("split.picture", "stage"), borderRadius: pic.r, overflow: "hidden", backgroundColor: "#000", boxShadow: "0 14px 40px rgba(0,0,0,0.65), 0 0 0 1px rgba(245,241,232,0.1)" }}>
        <Footage beat={beat} episode={episode} box={{ w: pic.w, h: pic.h }} />
      </div>
      <Backing id="stage.lower" style={{ ...laneBox("split.lower", "stage"), backgroundColor: NAVY_2 }}>
        {current && <div style={{ ...laneBox("split.headline", "split.lower"), ...enter(labels) }}>
          <TextField id="headline" lane="split.headline" size={40} style={{ fontWeight: 800, whiteSpace: "nowrap" }}>{beat.headline}</TextField>
        </div>}
        {current && beat.sub && !statVisible && <div style={{ ...laneBox("sub", "split.lower"), ...enter(labels) }}>
          <TextField id="description" lane="sub" style={{ color: CREAM_DIM, whiteSpace: "nowrap" }}>{beat.sub}</TextField>
        </div>}
      </Backing>
    </>
  );
};

// Wide scene (W): 1280x720 picture + bottom bar with the headline. Presenter hidden.
const WideScene: React.FC<{ beat: Beat; episode: EpisodeData; labels: Labels; current: boolean }> = ({ beat, episode, labels, current }) => {
  const pic = LANES["wide.picture"];
  return (
    <>
      <div data-qc-layer="picture" data-qc-footage={current ? beat.src : undefined} style={{ ...laneBox("wide.picture", "wide.window"), overflow: "hidden", backgroundColor: "#000" }}>
        <Footage beat={beat} episode={episode} box={{ w: pic.w, h: pic.h }} />
      </div>
      <Backing id="wide.bar" style={{ ...laneBox("wide.bar", "wide.window"), backgroundColor: NAVY_2 }}>
        {current && <div style={{ ...laneBox("wide.headline", "wide.bar"), ...enter(labels) }}>
          <TextField id="headline" lane="wide.headline" size={40} style={{ fontWeight: 800, whiteSpace: "nowrap" }}>{beat.headline}</TextField>
        </div>}
      </Backing>
    </>
  );
};

// ---- Text cards (T) -----------------------------------------------------------
// Sizes are final (CSS px): the card must FILL its 1130x676 content box, never shrink.
const graphemeCount = (s: string) => {
  const Seg = (Intl as unknown as { Segmenter?: new (l: string, o: { granularity: string }) => { segment(t: string): Iterable<unknown> } }).Segmenter;
  return Seg ? Array.from(new Seg("th", { granularity: "grapheme" }).segment(s)).length : Array.from(s).length;
};
const chipEntrance = (t: number, at: number, fps: number): React.CSSProperties => {
  const a = t >= at ? clamp01(springIn(Math.round((t - at) * fps), fps, 14, 140)) : 0;
  return { opacity: a, transform: `translateY(${(1 - a) * 18}px)` };
};
const Chip: React.FC<{ id: string; item: Item; size: number; iconSize: number; labels: Labels; padding: string; width?: number | string; i: number }> = ({ id, item, size, iconSize, labels, padding, width, i }) => (
  <Backing id={id} style={{ display: "flex", alignItems: "center", width, boxSizing: "border-box", padding, borderRadius: 24, backgroundColor: NAVY, boxShadow: "inset 0 0 0 2px rgba(242,179,76,0.55), 0 14px 40px rgba(0,0,0,0.45)", ...chipEntrance(labels.t, Math.max(item.at, labels.startSec), labels.fps) }}>
    <TextField id={`typo-item-${i}`} lane="typo.content" size={size} style={{ fontWeight: 800, whiteSpace: "nowrap" }}>{item.icon && <span style={{ fontSize: iconSize, marginRight: 16 }}>{item.icon}</span>}{item.text}</TextField>
  </Backing>
);

const VsCard: React.FC<{ side: VsSide; accent: string; k: "left" | "right" }> = ({ side, accent, k }) => (
  <Backing id={`vs-${k}`} style={{ width: 520, flexShrink: 0, boxSizing: "border-box", padding: 28, borderRadius: 28, backgroundColor: NAVY_3, boxShadow: `inset 0 0 0 2px ${accent}, 0 20px 60px rgba(0,0,0,0.5)` }}>
    <TextField id={`vs-${k}-badge`} role="label" lane="typo.content" style={{ color: accent, whiteSpace: "nowrap" }}>{side.badge}</TextField>
    <TextField id={`vs-${k}-title`} lane="typo.content" size={60} style={{ fontWeight: 800, whiteSpace: "nowrap" }}>{side.title}</TextField>
    <div style={{ width: 90, height: 4, background: accent, borderRadius: 2, margin: "10px 0 12px" }} />
    {side.lines.map((l, i) => <TextField key={i} id={`vs-${k}-line-${i}`} lane="typo.content" size={44} style={{ color: CREAM_DIM, whiteSpace: "nowrap" }}>{l}</TextField>)}
  </Backing>
);

const CARD_ROW_H = 76 + 40; // 54 px text (line-height 76) + 20 px padding top and bottom
const TypoScene: React.FC<{ beat: Beat; labels: Labels; current: boolean }> = ({ beat, labels, current }) => {
  const { t, fps } = labels;
  const variant = beat.typo;
  const items = beat.items ?? [];
  const cardList = (beat.cards ?? []).filter(c => t >= c.at);
  const cardIdx = Math.max(0, cardList.length - 1);
  const card = cardList[cardIdx] ?? beat.cards?.[0];
  const maxRows = Math.max(1, ...(beat.cards ?? []).map(c => c.lines.length)); // reserve the tallest card so nothing jumps
  const chipW = (it: Item) => 0.62 * 56 * graphemeCount(it.text) + (it.icon ? 52 + 16 : 0) + 72;
  const rowOk = items.length > 0 && items.every(it => graphemeCount(it.text) <= 8) && items.reduce((n, it) => n + chipW(it), 0) + 22 * (items.length - 1) <= 1130;
  return (
    <Backing id="typo.backing" style={{ ...laneBox("typo.backing", "stage"), backgroundColor: NAVY_2, backgroundImage: "radial-gradient(ellipse at 50% 28%, rgba(242,179,76,0.20), transparent 60%), radial-gradient(rgba(245,241,232,0.13) 1.5px, transparent 1.5px), linear-gradient(160deg, #1B2440, #0E1220)", backgroundSize: "auto, 28px 28px, auto" }}>
      <div style={{ position: "absolute", inset: 20, borderRadius: 18, border: "1.5px solid rgba(242,179,76,0.35)", pointerEvents: "none" }} />
      {current && <div style={{ ...laneBox("typo.content", "typo.backing"), display: "flex", flexDirection: "column", justifyContent: "center" }}>
        {variant === "card" && <div style={{ display: "flex", flexDirection: "column" }}>
          <TextField id="typo-title" lane="typo.content" size={68} style={{ fontWeight: 800, whiteSpace: "nowrap", ...enter(labels) }}>{beat.headline}</TextField>
          <div style={{ width: 140, height: 6, borderRadius: 3, background: AMBER, margin: "16px 0 34px" }} />
          <div key={cardIdx} style={{ display: "flex", flexDirection: "column", gap: 18, minHeight: maxRows * CARD_ROW_H + (maxRows - 1) * 18, ...enter(labels, card?.at ?? beat.t) }}>
            {(card?.lines ?? []).map((line, i) => (
              <Backing key={i} id={`typo-row-${i}`} style={{ backgroundColor: NAVY, borderLeft: `6px solid ${i % 2 ? MINT : AMBER}`, borderRadius: 12, padding: "20px 32px" }}>
                <TextField id={`typo-line-${i}`} lane="typo.content" size={54} style={{ whiteSpace: "nowrap" }}>{line}</TextField>
              </Backing>
            ))}
          </div>
        </div>}
        {variant === "summary3" && <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 36 }}>
          <TextField id="typo-eyebrow" role="label" lane="typo.content" size={34} style={{ color: AMBER, whiteSpace: "nowrap", ...enter(labels) }}>{beat.headline}</TextField>
          <div style={{ display: "flex", flexDirection: rowOk ? "row" : "column", gap: 22, alignItems: rowOk ? "center" : "stretch", justifyContent: "center", width: rowOk ? undefined : 900 }}>
            {items.map((it, i) => <Chip key={i} id={`typo-chip-${i}`} i={i} item={it} size={56} iconSize={52} labels={labels} padding="22px 36px" />)}
          </div>
        </div>}
        {variant === "final4" && <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 30 }}>
          <div style={{ textAlign: "center", ...enter(labels) }}>
            <TextField id="typo-title" lane="typo.content" size={64} style={{ fontWeight: 800, whiteSpace: "nowrap", textAlign: "center" }}>{beat.headline}</TextField>
            {beat.sub && <TextField id="typo-sub" lane="typo.content" size={42} style={{ color: AMBER, whiteSpace: "nowrap", textAlign: "center" }}>{beat.sub}</TextField>}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "545px 545px", gap: 20 }}>
            {items.map((it, i) => <Chip key={i} id={`typo-chip-${i}`} i={i} item={it} size={46} iconSize={44} labels={labels} padding="22px 28px" width={545} />)}
          </div>
        </div>}
        {variant === "vs" && beat.vs && <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 24, ...enter(labels) }}>
          <TextField id="typo-eyebrow" role="label" lane="typo.content" size={34} style={{ color: AMBER, whiteSpace: "nowrap" }}>{beat.headline}</TextField>
          <div style={{ display: "flex", gap: 14, alignItems: "stretch" }}>
            <VsCard side={beat.vs.left} accent={AMBER} k="left" />
            <TextField id="vs-sep" lane="typo.content" size={48} style={{ alignSelf: "center", fontWeight: 800, color: CREAM_DIM }}>vs</TextField>
            <VsCard side={beat.vs.right} accent={CLAY} k="right" />
          </div>
          <Backing id="vs-conclusion" style={{ backgroundColor: NAVY, boxShadow: `inset 0 0 0 1.5px ${CLAY}`, borderRadius: 18, padding: "6px 36px" }}>
            <TextField id="vs-conclusion" lane="typo.content" size={44} style={{ whiteSpace: "nowrap" }}>{beat.vs.conclusion}</TextField>
          </Backing>
        </div>}
      </div>}
    </Backing>
  );
};

// ---- Overlays -----------------------------------------------------------------
// A chip is visible on [at, at+dur) regardless of beat boundaries (it may outlive its beat). Max 3.
type LiveStat = { stat: Stat; b: number; i: number };
const liveStats = (beats: Beat[], t: number): LiveStat[] =>
  beats.flatMap((beat, b) => (beat.stats ?? []).map((stat, i) => ({ stat, b, i }))).filter(({ stat }) => t >= stat.at && t < stat.at + stat.dur).sort((a, b) => a.stat.at - b.stat.at).slice(0, 3);

const StatRail: React.FC<{ live: LiveStat[]; t: number; fps: number }> = ({ live, t, fps }) => (
  <div style={{ ...laneBox("sub"), zIndex: 40, display: "flex", alignItems: "center", gap: 14 }}>
    {live.map(({ stat, b, i }) => {
      const exit = clamp01((stat.at + stat.dur - t) * fps / 6), enter = boundedEntrance(t, stat.at, fps), c = tone(stat.tone);
      return (
        <Backing key={`${b}-${i}`} id={`stat-${b}-${i}`} occluder={`chip-${b}-${i}`} style={{ display: "flex", alignItems: "center", gap: 12, height: 56, padding: "0 16px", borderRadius: 14, backgroundColor: NAVY_3, boxShadow: `inset 0 0 0 2px ${c}`, ...enter, opacity: Number(enter.opacity) * exit }}>
          {stat.big && <TextField id={`stat-${b}-${i}-big`} lane="sub" style={{ fontWeight: 800, color: c, whiteSpace: "nowrap" }}>{stat.big}</TextField>}
          <TextField id={`stat-${b}-${i}-label`} role="label" lane="sub" style={{ whiteSpace: "nowrap" }}>{stat.label}</TextField>
        </Backing>
      );
    })}
  </div>
);

// Lower third: three left-aligned boxes, each hugging its own line (no empty backing over the presenter).
const LowerThird: React.FC<{ episode: EpisodeData; lower: Lower; t: number; fps: number; startSec: number }> = ({ episode, lower, t, fps, startSec }) => (
  <div data-qc-occluder="lower-third" style={{ ...laneBox("full.lowerThird"), zIndex: 45, display: "flex", flexDirection: "column", alignItems: "flex-start", justifyContent: "flex-end", gap: 6, ...boundedEntrance(t, startSec, fps) }}>
    <Backing id="lower-label" style={{ backgroundColor: AMBER, borderRadius: 10, padding: "0 16px" }}>
      <TextField id="lower-label" role="label" lane="full.lowerThird" style={{ color: NAVY, fontWeight: 800, whiteSpace: "nowrap" }}>{episode.breakingLabel}</TextField>
    </Backing>
    <Backing id="lower-title" style={{ backgroundColor: "rgba(11,14,23,.94)", borderLeft: `6px solid ${AMBER}`, borderRadius: 16, padding: "0 24px" }}>
      <TextField id="lower-title" lane="full.lowerThird" size={52} style={{ fontWeight: 800, whiteSpace: "nowrap" }}>{lower.title}</TextField>
    </Backing>
    <Backing id="lower-sub" style={{ backgroundColor: "rgba(11,14,23,.94)", borderLeft: `6px solid ${AMBER}`, borderRadius: 16, padding: "0 24px" }}>
      <TextField id="lower-sub" lane="full.lowerThird" style={{ whiteSpace: "nowrap" }}>{lower.sub}</TextField>
    </Backing>
  </div>
);

const CtaChip: React.FC<{ text: string; t: number; ctaT: number; fps: number }> = ({ text, t, ctaT, fps }) => (
  <div style={{ ...laneBox("full.cta"), zIndex: 46, display: "flex", alignItems: "center", justifyContent: "center", ...boundedEntrance(t, ctaT, fps) }}>
    <Backing id="cta" occluder="cta" style={{ backgroundColor: NAVY, boxShadow: `inset 0 0 0 2px ${AMBER}`, borderRadius: 24, padding: "16px 36px", maxWidth: 1400, boxSizing: "border-box" }}>
      <TextField id="cta" lane="full.cta" size={40} style={{ fontWeight: 800, textAlign: "center" }}>{text}</TextField>
    </Backing>
  </div>
);

const CaptionLane: React.FC<{ t: number; pages: CaptionPage[] }> = ({ t, pages }) => {
  const page = pages.find(p => t >= p.start && t < p.end);
  if (!page) return null;
  return (
    <div style={{ ...laneBox("caption"), zIndex: 60, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <Backing id="caption" occluder="caption-pill" style={{ backgroundColor: "rgba(11,14,23,.92)", boxShadow: "inset 0 0 0 1.5px rgba(242,179,76,.30)", borderRadius: 20, padding: "6px 26px", maxWidth: LANES.caption.w, boxSizing: "border-box" }}>
        <TextField id="caption" lane="caption" size={38} attrs={{ "data-qc-caption-display": page.displayText }} style={{ fontWeight: 800, whiteSpace: "pre" }}>
          {page.chunks.map((chunk, i) => {
            const on = t >= chunk.displayStart && t < chunk.displayEnd;
            return <React.Fragment key={i}>{chunk.displaySpaceBefore}<span style={{ display: "inline-block", whiteSpace: "pre", color: on ? GOLD_LIGHT : CREAM, textShadow: on ? `0 0 12px ${GOLD}` : "none" }}>{chunk.text}</span></React.Fragment>;
          })}
        </TextField>
      </Backing>
    </div>
  );
};

const EndCard: React.FC<{ episode: EpisodeData }> = ({ episode: EPISODE }) => (
  <Backing id="end.bg" style={{ position: "absolute", inset: 0, zIndex: 90, backgroundColor: NAVY, backgroundImage: "radial-gradient(ellipse at 50% 38%, rgba(242,179,76,0.14), transparent 60%), radial-gradient(rgba(245,241,232,0.06) 1.5px, transparent 1.5px)", backgroundSize: "auto, 28px 28px" }}>
    <div style={{ ...laneBox("end.eyebrow"), textAlign: "center" }}><TextField id="end-label" role="label" lane="end.eyebrow" style={{ color: AMBER, whiteSpace: "nowrap" }}>{EPISODE.endcard.eyebrow}</TextField></div>
    <div style={{ ...laneBox("end.title"), textAlign: "center" }}><TextField id="end-title" lane="end.title" size={72} style={{ fontWeight: 800, whiteSpace: "nowrap" }}>{EPISODE.endcard.titleA}</TextField></div>
    <div style={{ ...laneBox("end.sub"), textAlign: "center" }}><TextField id="end-sub" lane="end.sub" size={40} style={{ color: AMBER, whiteSpace: "nowrap" }}>{EPISODE.endcard.titleB}</TextField></div>
    <div style={{ ...laneBox("end.cta"), display: "flex", alignItems: "center", justifyContent: "center" }}>
      <Backing id="end.cta" style={{ backgroundColor: NAVY_3, boxShadow: `inset 0 0 0 2px ${AMBER}`, borderRadius: 24, padding: "16px 36px", maxWidth: 1400, boxSizing: "border-box" }}>
        <TextField id="end-cta" lane="end.cta" size={40} style={{ fontWeight: 800, textAlign: "center" }}>{EPISODE.endcard.cta}</TextField>
      </Backing>
    </div>
  </Backing>
);

// QC is observation-only: production has no layout injection or media substitution.
const QcProbe: React.FC<{enabled:boolean;plan:boolean;frame:number;beat:Beat;episode:EpisodeData;captions:CaptionData}> = ({enabled,plan,frame,beat,episode,captions}) => {
  const {fps}=useVideoConfig();
  const EPISODE=episode;const BEATS=EPISODE.beats;const VO_END_SEC=EPISODE.voEndSec;const TOTAL_DURATION_SEC=EPISODE.totalDurationSec;const CTA_T=EPISODE.ctaT;const CAPTION_PAGES=captions.pages;
  useLayoutEffect(() => {
    if (!enabled && !plan) return;
    const handle=delayRender("V3 DOM measurement");
    let live=true;
    ensureFonts().then(()=>document.fonts.ready).then(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())))).then(()=>{
      if(!live)return;
      if(plan){
        const times=new Set<number>([0,9,89,172,VO_END_SEC, TOTAL_DURATION_SEC-0.04]);
        BEATS.forEach((b,i)=>{const end=BEATS[i+1]?.t??VO_END_SEC; [b.t,b.t+0.12,b.t+0.36,b.t+0.56,(b.t+end)/2,end-0.04].forEach(t=>times.add(t)); b.stats?.forEach(st=>[st.at,st.at+0.12,st.at+0.32,st.at+0.64].forEach(t=>times.add(t))); b.cards?.forEach(c=>[c.at,c.at+0.12,c.at+0.36,c.at+0.64].forEach(t=>times.add(t))); b.punch?.forEach(p=>[p.at-0.04,p.at,p.at+0.04].forEach(t=>times.add(t)));if(b.lower)[b.lower.at,b.lower.at+0.32,b.lower.at+b.lower.dur-0.04].forEach(t=>times.add(t));});
        CAPTION_PAGES.forEach(p=>times.add((p.start+p.end)/2));
        [CTA_T,CTA_T+0.12,CTA_T+0.32,CTA_T+0.64].forEach(t=>times.add(t));
        const rectFor=(b:Beat)=>b.mode==="full"?[0,0,W,H,1]:b.layout==="wide"?[LANES.avatar.x,LANES.avatar.y,LANES.avatar.w,LANES.avatar.h,0]:[LANES.avatar.x,LANES.avatar.y,LANES.avatar.w,LANES.avatar.h,1];
        const sweepWindows=BEATS.flatMap((b,i)=>i&&(sceneKind(BEATS[i-1])!==sceneKind(b)||JSON.stringify(rectFor(BEATS[i-1]))!==JSON.stringify(rectFor(b)))?[{id:`avatar-${i}`,beatT:b.t,startFrame:Math.ceil(b.t*fps),endFrame:Math.min(Math.ceil(TOTAL_DURATION_SEC*fps)-1,Math.ceil(b.t*fps)+IN_F+OUT_F+3)}]:[]);
        const frames=new Set([...times].filter(t=>t>=0&&t<TOTAL_DURATION_SEC).map(t=>Math.round(t*fps)));
        sweepWindows.forEach(w=>{for(let f=w.startFrame;f<=w.endFrame;f++)frames.add(f);});
        console.log("__QC_PLAN__"+JSON.stringify({frames:[...frames].sort((a,b)=>a-b),fps,sweepWindows,sweepVersion:"avatar-empty-backing-1"}));
      }
      if(enabled){
        const root=document.querySelector('[data-qc-root]') as HTMLElement;
        if(!root)throw Error('missing QC root');
        const groups=new Map<HTMLElement,Text[]>();
        const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
        while(walker.nextNode()){
          const n=walker.currentNode as Text;if(!n.textContent?.trim())continue;
          const parent=n.parentElement!;
          const el=(parent.closest('[data-qc-field]')??parent) as HTMLElement;
          groups.set(el,[...(groups.get(el)??[]),n]);
        }
        const rect=(r:DOMRect)=>({x:r.x,y:r.y,width:r.width,height:r.height});
        const opacityOf=(el:HTMLElement)=>{let opacity=1;for(let a:HTMLElement|null=el;a&&a!==root.parentElement;a=a.parentElement){const cs=getComputedStyle(a);opacity*=Number(cs.opacity);if(cs.visibility==='hidden'||cs.display==='none')return 0;}return opacity;};
        const canvas=document.createElement('canvas');const ctx=canvas.getContext('2d');if(!ctx)throw Error('missing ink canvas');
        const entries=[...groups];
        const fields=entries.map(([el,nodes],i)=>{
          const rects:{x:number;y:number;width:number;height:number}[]=[];
          const inkRects:typeof rects=[];const clipBoxes:typeof rects=[];
          nodes.forEach(n=>{
            const parent=n.parentElement!;const cs=getComputedStyle(parent);ctx.font=`${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
            // Measure grapheme ink rather than UTF-16 units, preserving Thai combining marks.
            const Segmenter=(Intl as unknown as {Segmenter:new(locale:string,options:{granularity:string})=>{segment(text:string):Iterable<{index:number;segment:string}>}}).Segmenter;
            if(!Segmenter)throw Error('missing grapheme segmenter');
            const segments=Array.from(new Segmenter('th',{granularity:'grapheme'}).segment(n.textContent??''));
            for(const segment of segments){
              const range=document.createRange();range.setStart(n,segment.index);range.setEnd(n,segment.index+segment.segment.length);
              for(const r of Array.from(range.getClientRects())){
                if(r.width<=0||r.height<=0||!segment.segment.trim())continue;rects.push(rect(r));
                const metrics=ctx.measureText(segment.segment);const fontPx=parseFloat(cs.fontSize);
                const fa=metrics.fontBoundingBoxAscent,fd=metrics.fontBoundingBoxDescent;
                if(![fa,fd,metrics.actualBoundingBoxAscent,metrics.actualBoundingBoxDescent].every(Number.isFinite))throw Error('missing font ink metrics');
                const sy=r.height/(fa+fd);const baseline=r.y+fa*sy;
                const sx=metrics.width>0?r.width/metrics.width:1;
                inkRects.push({x:r.x-metrics.actualBoundingBoxLeft*sx,y:baseline-metrics.actualBoundingBoxAscent*sy,width:Math.max(.01,(metrics.actualBoundingBoxLeft+metrics.actualBoundingBoxRight)*sx),height:Math.max(.01,(metrics.actualBoundingBoxAscent+metrics.actualBoundingBoxDescent)*sy)});
              }
            }
          });
          for(let a:HTMLElement|null=el;a&&a!==root.parentElement;a=a.parentElement){const cs=getComputedStyle(a);if(['hidden','clip','scroll','auto'].some(v=>cs.overflowX===v||cs.overflowY===v))clipBoxes.push(rect(a.getBoundingClientRect()));}
          const cs=getComputedStyle(el);let scale=1;
          const backing=el.closest<HTMLElement>('[data-qc-backing]');const bg=backing?getComputedStyle(backing).backgroundColor:'';const rgba=bg.match(/[\d.]+/g)?.map(Number)??[];const alpha=rgba.length===4?rgba[3]:rgba.length===3?1:0;const backingBox=backing?rect(backing.getBoundingClientRect()):null;const backingOpacity=backing?opacityOf(backing):0;const backed=!!backing&&alpha>=.9&&backingOpacity>0&&backing.contains(el)&&!!backingBox&&inkRects.length>0&&inkRects.every(r=>r.x>=backingBox.x-.5&&r.y>=backingBox.y-.5&&r.x+r.width<=backingBox.x+backingBox.width+.5&&r.y+r.height<=backingBox.y+backingBox.height+.5);
          for(let a:HTMLElement|null=el;a&&a!==root.parentElement;a=a.parentElement){const tr=getComputedStyle(a).transform;if(tr!=='none'){const m=new DOMMatrixReadOnly(tr);scale*=Math.hypot(m.a,m.b);}}
          const lineYs=[...new Set(rects.map(r=>Math.round(r.y)))];
          const firstTextY=Math.min(...rects.map(r=>r.y));
          const blankFirstLine=el.dataset.qcField==='caption'&&firstTextY-el.getBoundingClientRect().y>parseFloat(cs.lineHeight)*.8;
          return {captionBlankFirstLine:blankFirstLine,captionLineCount:lineYs.length,captionExpectedText:el.dataset.qcCaptionDisplay,id:el.dataset.qcField??'auto-'+i,role:el.dataset.qcRole??'read',layer:'current',text:el.textContent?.trim(),fontSize:parseFloat(cs.fontSize)*scale,opacity:opacityOf(el),rects,inkRects,box:rect(el.getBoundingClientRect()),clipBoxes,clipped:false,backed,backing:backingBox?{alpha,opacity:backingOpacity,sameVisibilityAncestry:backing!.contains(el),box:backingBox}:null};
        });
        const tagged=Array.from(root.querySelectorAll<HTMLElement>('[data-qc-occluder]'));
        const saved=tagged.map(el=>[el,el.style.pointerEvents] as const);
        // Geometry identifies every potential cover. Temporarily enabling pointer hit testing
        // reveals browser paint order even for pointer-events:none image/container layers.
        tagged.forEach(el=>el.style.pointerEvents='auto');
        const occluders=tagged.map(el=>{
          const box=rect(el.getBoundingClientRect());const frontOf:string[]=[];
          fields.forEach((f,i)=>{
            const target=entries[i][0];if(el.contains(target)||target.contains(el)||opacityOf(el)<.05)return;
            for(const ink of f.inkRects){
              const x1=Math.max(box.x,ink.x),y1=Math.max(box.y,ink.y),x2=Math.min(box.x+box.width,ink.x+ink.width),y2=Math.min(box.y+box.height,ink.y+ink.height);
              if(x2<=x1||y2<=y1)continue;
              const stack=document.elementsFromPoint((x1+x2)/2,(y1+y2)/2);
              const coverIndex=stack.findIndex(x=>x===el||el.contains(x));const textIndex=stack.findIndex(x=>x===target||target.contains(x));
              if(coverIndex>=0&&textIndex>=0&&coverIndex<textIndex){frontOf.push(f.id);break;}
            }
          });
          return {id:el.dataset.qcOccluder,kind:el.tagName.toLowerCase(),box,opacity:opacityOf(el),frontOf,pointerEvents:getComputedStyle(el).pointerEvents};
        });
        saved.forEach(([el,value])=>el.style.pointerEvents=value);
        const avatar=root.querySelector<HTMLElement>('[data-qc-occluder="avatar"]');
        if(!avatar&&frame/fps<VO_END_SEC)throw Error('missing avatar measurement');
        type MeasuredRect={x:number;y:number;width:number;height:number};
        const intersectRect=(a:MeasuredRect,b:MeasuredRect):MeasuredRect|null=>{const x=Math.max(a.x,b.x),y=Math.max(a.y,b.y),right=Math.min(a.x+a.width,b.x+b.width),bottom=Math.min(a.y+a.height,b.y+b.height);return right>x&&bottom>y?{x,y,width:right-x,height:bottom-y}:null;};
        const subtractRects=(box:MeasuredRect,protect:MeasuredRect[])=>{let regions=[box];for(const p of protect){const next:MeasuredRect[]=[];for(const r of regions){const overlap=intersectRect(r,p);if(!overlap){next.push(r);continue;}const right=overlap.x+overlap.width,bottom=overlap.y+overlap.height;for(const q of [{x:r.x,y:r.y,width:r.width,height:overlap.y-r.y},{x:r.x,y:bottom,width:r.width,height:r.y+r.height-bottom},{x:r.x,y:overlap.y,width:overlap.x-r.x,height:overlap.height},{x:right,y:overlap.y,width:r.x+r.width-right,height:overlap.height}])if(q.width>0&&q.height>0)next.push(q);}regions=next;}return regions;};
        const stablePath=(el:HTMLElement)=>{const parts:string[]=[];for(let a:HTMLElement|null=el;a&&a!==root;a=a.parentElement){const parent=a.parentElement;if(!parent)throw Error('detached candidate');parts.unshift(a.tagName.toLowerCase()+':'+(Array.from(parent.children).indexOf(a)+1));}return parts.join('/');};
        const all=Array.from(root.querySelectorAll<HTMLElement>('*'));
        const hitSaved=all.map(el=>[el,el.style.pointerEvents] as const);
        let avatarBacking:unknown={applicable:false,reason:'endcard',avatar:null,candidates:[]};
        if(avatar){
        try{
          all.forEach(el=>el.style.pointerEvents='auto');
          const avatarBox=rect(avatar.getBoundingClientRect()),avatarOpacity=opacityOf(avatar);
          const candidates=all.flatMap(el=>{
            if(el===avatar||avatar.contains(el)||el.contains(avatar))return [];
            const cs=getComputedStyle(el),rgba=cs.backgroundColor.match(/[\d.]+/g)?.map(Number)??[];
            const alpha=rgba.length===4?rgba[3]:rgba.length===3?1:0,opacity=opacityOf(el),image=cs.backgroundImage;
            if(!(alpha>.05||image!=='none')||opacity<.05||avatarOpacity<.05)return [];
            const box=rect(el.getBoundingClientRect());
            if(![box.x,box.y,box.width,box.height,opacity,alpha].every(Number.isFinite)||box.width<=0||box.height<=0)throw Error('invalid background geometry');
            let intersection=intersectRect(box,avatarBox);
            for(let a=el.parentElement;a&&a!==root&&intersection;a=a.parentElement){const style=getComputedStyle(a);if(['hidden','clip','scroll','auto'].some(v=>style.overflowX===v||style.overflowY===v))intersection=intersectRect(intersection,rect(a.getBoundingClientRect()));}
            if(!intersection)return [];
            const padding={top:parseFloat(cs.paddingTop),right:parseFloat(cs.paddingRight),bottom:parseFloat(cs.paddingBottom),left:parseFloat(cs.paddingLeft)};
            if(!Object.values(padding).every(Number.isFinite))throw Error('missing background padding');
            const protectedRects=fields.flatMap((f,i)=>{
              if(!el.contains(entries[i][0])||f.opacity<.05)return [];
              if(!f.inkRects.length)throw Error('missing protected glyph ink');
              const x=Math.min(...f.inkRects.map(r=>r.x))-padding.left-4,y=Math.min(...f.inkRects.map(r=>r.y))-padding.top-4;
              const right=Math.max(...f.inkRects.map(r=>r.x+r.width))+padding.right+4,bottom=Math.max(...f.inkRects.map(r=>r.y+r.height))+padding.bottom+4;
              return [{x,y,width:right-x,height:bottom-y}];
            });
            const emptyRegions=subtractRects(intersection,protectedRects).map(region=>{
              const points=[[.5,.5],[.1,.1],[.9,.1],[.1,.9],[.9,.9]].map(([fx,fy])=>{
                const x=region.x+region.width*fx,y=region.y+region.height*fy,stack=document.elementsFromPoint(x,y);
                const candidateIndex=stack.indexOf(el),avatarIndex=stack.findIndex(x=>x===avatar||avatar.contains(x));
                return {x,y,candidateIndex,avatarIndex,above:candidateIndex>=0&&avatarIndex>=0&&candidateIndex<avatarIndex};
              });
              return {...region,paintOrderEvidence:{...(points.find(p=>p.above)??points[0]),samples:points}};
            });
            return [{id:stablePath(el),box,opacity,background:{color:cs.backgroundColor,alpha,image},padding,protectedRects,intersection,emptyRegions}];
          });
          avatarBacking={avatar:{box:avatarBox,opacity:avatarOpacity},candidates};
        }finally{hitSaved.forEach(([el,value])=>el.style.pointerEvents=value);}
        }
        const footageEl=root.querySelector<HTMLElement>('[data-qc-scene-role="current"] [data-qc-footage]');
        const actualSrc=footageEl?.dataset.qcFootage;
        console.log('__QC__'+JSON.stringify({schemaVersion:2,captionLane:'bottom',frame,width:1920,height:1080,fontsOk:document.fonts.check('800 28px KanitX')&&document.fonts.check('700 28px KanitX'),fields,occluders,avatarBacking,transition:frame/25-beat.t<MODE_BLEND_SEC,footage:{origin:frame/25>=VO_END_SEC?'endcard':beat.mode==='full'?'avatar':beat.media==='typo'?'typo':actualSrc?.startsWith('yt_')?'source':actualSrc?.startsWith('ai_')?'ai':'stock',layout:beat.layout,src:actualSrc,credit:false,chrome:false}}));
      }
      continueRender(handle);
    }).catch(cancelRender);
    return ()=>{live=false;continueRender(handle);};
  },[enabled,plan,frame,beat]);
  return null;
};

// ===========================================================================
// MAIN COMPOSITION
// ===========================================================================

export type YtNewsStyle01V4Props = {
  episode: EpisodeData;
  captions: CaptionData;
  qcPlan?: boolean;
  qcMeasure?: boolean;
};

export const calculateYtNewsStyle01V4Metadata: CalculateMetadataFunction<YtNewsStyle01V4Props> = async ({props}) => {
  const errs = checkEpisodeMinimal(props.episode, props.captions);
  if (errs.length) throw new Error("YtNewsStyle01V4 props invalid: " + errs.join("; "));
  return {
    durationInFrames: Math.ceil(props.episode.totalDurationSec * 25),
    fps: 25,
    width: W,
    height: H,
  };
};

export const YtNewsStyle01V4: React.FC<YtNewsStyle01V4Props> = (props) => {
  const errs = checkEpisodeMinimal(props.episode, props.captions);
  if (errs.length) throw new Error("YtNewsStyle01V4 props invalid: " + errs.join("; "));
  const {qcPlan=false,qcMeasure=false}=props;
  const EPISODE=props.episode;const BEATS=EPISODE.beats;const VO_END_SEC=EPISODE.voEndSec;const CTA_T=EPISODE.ctaT;const CAPTION_PAGES=props.captions.pages;
  useThaiFonts();
  const frame=useCurrentFrame();const {fps}=useVideoConfig();const t=frame/fps;
  const plan=layerPlan(frame,BEATS,fps);
  const beat=BEATS[plan.index];const isEnd=t>=VO_END_SEC;
  const live=liveStats(BEATS,t);
  const labelStartSec=plan.labelStartFrame/fps;const labels:Labels={on:true,startSec:labelStartSec,t,fps};
  const lowerStart=beat.lower?entranceStartSec(beat.lower.at,plan,fps):0;
  const showLower=!!beat.lower&&t>=lowerStart&&t<beat.lower.at+beat.lower.dur;
  const ctaStart=entranceStartSec(CTA_T,plan,fps);
  const layerOf=(l:SceneLayerPlan)=>{const b=BEATS[l.index],cur=l.labels;return <SceneLayer key={l.key} layer={l}>{l.kind==="S"?<MuseumScene beat={b} episode={EPISODE} statVisible={live.length>0} labels={labels} current={cur}/>:l.kind==="T"?<TypoScene beat={b} labels={labels} current={cur}/>:<WideScene beat={b} episode={EPISODE} labels={labels} current={cur}/>}</SceneLayer>;};
  return <div data-qc-root style={{width:W,height:H,position:"relative",overflow:"hidden",background:NAVY}}>
    <QcProbe enabled={qcMeasure} plan={qcPlan} frame={frame} beat={beat} episode={EPISODE} captions={props.captions}/>
    {!isEnd&&<>
      <Backdrop/>
      {plan.stage.mounted&&<StageFrame key="stage" plan={plan.stage} kind={isZ(plan.kind)?plan.kind:(plan.outgoingKind??"S")} chromeBeat={isZ(plan.kind)?beat:null} episode={EPISODE} labels={labels}>{plan.layers.filter(l=>l.frame==="stage").map(layerOf)}</StageFrame>}
      {plan.wide.mounted&&<WideFrame key="wide" plan={plan.wide} chromeBeat={plan.kind==="W"?beat:null} episode={EPISODE} labels={labels}>{plan.layers.filter(l=>l.frame==="wide").map(layerOf)}</WideFrame>}
      <Avatar key="avatar" episode={EPISODE} av={plan.avatar}/>
      <Header episode={EPISODE} beat={beat}/>
      {live.length>0&&<StatRail live={live} t={t} fps={fps}/>}
      {showLower&&beat.lower&&<LowerThird episode={EPISODE} lower={beat.lower} t={t} fps={fps} startSec={lowerStart}/>}
      {t>=ctaStart&&<CtaChip text={EPISODE.cta} t={t} ctaT={ctaStart} fps={fps}/>}
      <CaptionLane t={t} pages={CAPTION_PAGES}/>
    </>}
    {isEnd&&<EndCard episode={EPISODE}/>}
  </div>;
};
