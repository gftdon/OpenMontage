#!/usr/bin/env node
// Export timeline data from the episode module (pure TS) without Remotion:
//   node events.mjs <remotion-composer dir> <episode module basename> <out.json>
// Emits: segments, beats (timeline seconds), chapters, sfx events, music dips,
// lint findings (visual-event gaps > 5 s, same-media runs, beat length).
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

const [rcDir, modName, outPath] = process.argv.slice(2);
if (!rcDir || !modName || !outPath) {
  console.error("usage: events.mjs <remotion-composer dir> <episodeModuleBasename> <out.json>");
  process.exit(2);
}
// esbuild is resolved from the remotion-composer install (this script has no node_modules of its own)
const { build } = createRequire(path.join(path.resolve(rcDir), "package.json"))("esbuild");
const entry = path.join(rcDir, "src", `${modName}.ts`);
const tmp = path.join(os.tmpdir(), `episode_${Date.now()}.cjs`);
await build({ entryPoints: [entry], bundle: true, platform: "node", format: "cjs", outfile: tmp, logLevel: "silent" });
const mod = createRequire(import.meta.url)(tmp);
fs.unlinkSync(tmp);

const { SEG, BEATS_TL, CHAPTERS_TL, MUSIC_DIPS, mapMain, VO_END_TL, TOTAL_TL, TIMELINE, CTA_TL } = mod;
const beats = BEATS_TL;
const endOf = (i) => (i + 1 < beats.length ? beats[i + 1].t : VO_END_TL);

// ---- SFX events ------------------------------------------------------------
const sfx = [];
const add = (t, name, gain, note) => sfx.push({ t: +t.toFixed(3), name, gain, note });
add(0, "impact", -11, "cold open hit");
add(0.05, "whoosh", -15, "cold open");
add(Math.max(0, SEG.stingStart - 2.45), "riser", -11, "riser into sting");
add(SEG.stingStart, "impact", -8, "sting hit");
add(SEG.stingStart + 0.05, "sting", -9, "ident");
add(SEG.mainDst, "whoosh", -14, "into main");
let prevMode = beats[0].mode;
beats.forEach((b, i) => {
  if (i > 0 && b.mode !== prevMode) add(b.t, "morph", -13, `morph -> ${b.mode}`);
  prevMode = b.mode;
  const prev = i > 0 ? beats[i - 1] : null;
  if (b.mode === "pip" && b.media && b.media !== "none" && prev && prev.media !== b.media && ["broll", "explain", "chart", "typo", "clip", "terminal"].includes(b.media)) add(b.t, "whoosh", -18, `media ${b.media}`);
  (b.stats || []).forEach((s) => add(s.t, "pop", -15, "stat chip"));
  (b.hl || []).forEach((h) => add(h.t, "swoosh", -19, "highlight"));
  (b.gloss || []).forEach((g) => add(g.t, "tick", -16, "gloss"));
  if (b.explain) b.explain.items.forEach((it) => add(it.t, "pop", -15, "explain item"));
  if (b.chart) b.chart.bars.forEach((_, k) => add(b.t + 0.35 + k * 0.32, "tick", -17, "chart bar"));
  if (b.next) {
    const st = b.next.t ?? b.t + 0.6;
    b.next.items.forEach((_, k) => add(st + 0.22 + k * 0.22, "tick", -16, "next chip"));
  }
  if (b.lower) add(b.lower.t ?? b.t + 0.8, "whoosh", -16, "lower third");
  if (b.media === "terminal") {
    const dur = endOf(i) - b.t;
    for (let k = 0; k * 3.0 < dur - 0.5; k++) add(b.t + k * 3.0, "typing", -24, "terminal typing");
  }
});
// typo chips
const typo = { agenda: mod.AGENDA_TL, summary3: mod.SUMMARY3_TL, final4: mod.FINAL4_TL };
Object.values(typo).forEach((arr) => arr.forEach((x) => add(x.t, "pop", -15, "typo chip")));
add(mod.VS_TL.fableT, "pop", -14, "vs card");
add(mod.VS_TL.mythosT, "pop", -14, "vs card");
add(mod.VS_TL.subT, "pop", -15, "vs conclusion");
CHAPTERS_TL.forEach((c, i) => { if (i > 0) add(c.t, "chapter", -12, `chapter ${i + 1}`); });
add(CTA_TL, "pop", -12, "cta");
add(VO_END_TL, "sting", -10, "endcard");
sfx.sort((a, b) => a.t - b.t);

// ---- Music automation ------------------------------------------------------
const music = {
  base: 0.22,
  teaser: 0.3,
  sting: 0.38,
  endcard: 0.34,
  dips: MUSIC_DIPS.map((s) => ({ t: +mapMain(s).toFixed(3), pre: 0.5, hold: 1.2, level: 0.07 })),
};

// ---- Lint: visual-event density -------------------------------------------
const events = [];
beats.forEach((b, i) => {
  events.push(b.t);
  (b.cam || []).forEach((c) => { if (c.t > 0) events.push(b.t + c.t); });
  (b.hl || []).forEach((h) => events.push(h.t));
  (b.stats || []).forEach((s) => events.push(s.t));
  (b.gloss || []).forEach((g) => events.push(g.t));
  if (b.subT) events.push(b.subT);
  if (b.lower) events.push(b.lower.t ?? b.t + 0.8);
  if (b.next) events.push(b.next.t ?? b.t + 0.6);
  if (b.explain) b.explain.items.forEach((it) => events.push(it.t));
  if (b.chart) events.push(b.t + 0.35, b.t + 0.35 + (b.chart.bars.length - 1) * 0.32);
  if (b.terminal) b.terminal.lines.forEach((l) => events.push(b.t + l.t));
});
Object.values(typo).forEach((arr) => arr.forEach((x) => events.push(x.t)));
events.push(mod.VS_TL.fableT, mod.VS_TL.mythosT, mod.VS_TL.subT, ...(mod.VS_TL.leftLines || []), ...(mod.VS_TL.rightLines || []), CTA_TL, VO_END_TL);
events.sort((a, b) => a - b);
const gaps = [];
for (let i = 1; i < events.length; i++) {
  const g = events[i] - events[i - 1];
  if (g > 5.0) gaps.push({ from: +events[i - 1].toFixed(2), to: +events[i].toFixed(2), gap: +g.toFixed(2) });
}
// sameness: 3+ consecutive web beats showing captures of the same family (`<prefix>_NN`: quote cards, chart tabs…)
const family = (b) => (b.media === "web" && /^[a-z]+_\d+$/i.test(b.file || "") ? (b.file || "").replace(/_\d+$/, "") : null);
const runs = [];
let run = 1;
for (let i = 1; i < beats.length; i++) {
  const same = family(beats[i]) !== null && family(beats[i]) === family(beats[i - 1]);
  run = same ? run + 1 : 1;
  if (run >= 3) runs.push({ at: +beats[i].t.toFixed(2), run, family: family(beats[i]) });
}
const long = beats.map((b, i) => ({ t: +b.t.toFixed(2), media: b.media || b.mode, dur: +(endOf(i) - b.t).toFixed(2) })).filter((x) => x.dur > 16);
const counts = {};
beats.forEach((b) => { const k = b.mode === "full" ? "full" : b.media; counts[k] = (counts[k] || 0) + 1; });

const out = {
  segments: SEG, timeline: TIMELINE, voEnd: VO_END_TL, total: TOTAL_TL, ctaT: CTA_TL,
  chapters: CHAPTERS_TL, beats: beats.map((b, i) => ({ t: +b.t.toFixed(3), end: +endOf(i).toFixed(3), mode: b.mode, media: b.media || null, file: b.file || null, src: b.src || null, kicker: b.kicker || null })),
  sfx, music,
  lint: { beatCount: beats.length, counts, gapsOver5s: gaps, quoteRuns: runs, beatsOver16s: long, eventsPerMinute: +((events.length / (VO_END_TL / 60))).toFixed(1) },
};
fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, JSON.stringify(out, null, 2));
console.log(`events: ${sfx.length} sfx, ${beats.length} beats, voEnd ${VO_END_TL.toFixed(2)} total ${TOTAL_TL.toFixed(2)}`);
console.log("LINT counts", JSON.stringify(counts));
console.log("LINT gaps>5s", JSON.stringify(gaps));
console.log("LINT same-family capture runs>=3", JSON.stringify(runs));
console.log("LINT beats>16s", JSON.stringify(long));
console.log("LINT events/min", out.lint.eventsPerMinute);
