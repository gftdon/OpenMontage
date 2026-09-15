import React, { useEffect, useState } from "react";
import {
  OffthreadVideo,
  Img,
  Loop,
  Sequence,
  interpolate,
  spring,
  staticFile,
  continueRender,
  delayRender,
  useCurrentFrame,
  useVideoConfig,
  CalculateMetadataFunction,
} from "remotion";
import { CAPTION_PAGES, type CaptionPage } from "./fuguNewsCaptions";
import { WEB_CLIPS } from "./fuguNewsWeb";
import {
  EPISODE, SEG, BROLL_DUR, BEATS_TL as BEATS, AGENDA_TL, SUMMARY3_TL, FINAL4_TL, VS_TL, CTA_TL, CHAPTERS_TL,
  VO_END_TL, TOTAL_TL, R,
  type Beat, type CamKey, type Tone, type Explain, type Chart, type Terminal,
} from "./fuguNewsEpisodeV2";

// ===========================================================================
// FuguNewsYTV2 — 16:9 AI-news report ENGINE (1920x1080@25)
// V2 adds (all without a new avatar take):
//  STOP   pre-lap teaser cut from the presenter's own lines + ident sting,
//         hook typography, frame 0 == thumbnail, thumbnail variants
//  STAY   chapter pill, "ต่อไป" tease chips at pivots, punchline full-frame
//         cut, explain cards, chart scene, SFX/music events (audio scripts)
//  ONLY   VERIFIED capture badge + stamp, terminal demo, generated shots,
//         animated benchmark chart, "มุมไทย" card
//  EASY   Thai translation strips under English highlights, glossary chips
// Episode data (beats, copy, timeline) lives in fuguNewsEpisodeV2.ts.
// ===========================================================================

// ---- Design tokens --------------------------------------------------------
const NAVY = "#0B0E17";
const NAVY_2 = "#141A2B";
const CREAM = "#F5F1E8";
const CREAM_DIM = "rgba(245,241,232,0.62)";
const INK = "#1A1714";
const AMBER = "#F2B34C";
const AMBER_DEEP = "#D98E1F";
const CLAY = "#D97757";
const MINT = "#8FD6B4";
const GOLD = "#F59E0B"; // karaoke locked style
const GOLD_LIGHT = "#FDE68A";
const FONT = '"KanitX", "Kanit", system-ui, -apple-system, sans-serif';
const MONO = '"SF Mono", "JetBrains Mono", Menlo, monospace';

const VO_END_SEC = VO_END_TL;
const TOTAL_DURATION_SEC = TOTAL_TL;
const MODE_BLEND_SEC = 0.55;

// ---- Geometry (locked) -----------------------------------------------------
const W = 1920;
const H = 1080;
const STAGE = { x: 80, y: 100, w: 1210, h: 840, r: 22 };
const CHROME_H = 46;
const VW = STAGE.w;
const VH = STAGE.h - CHROME_H;
const AV = { x: 1362, y: 96, w: 478, h: 850, r: 26 };
const AV_CX = 940;
const AV_CY = 540;
const S0 = VW / 1100;

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
    ensureFonts().then(() => continueRender(handle)).catch(() => continueRender(handle));
  }, [handle]);
};

// ---- Helpers --------------------------------------------------------------
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const easeInOutCos = (p: number) => (1 - Math.cos(Math.PI * clamp01(p))) / 2;
const easeOutCubic = (p: number) => 1 - Math.pow(1 - clamp01(p), 3);
const springIn = (frame: number, fps: number, damping = 16, stiffness = 130) =>
  spring({ frame: Math.max(0, frame), fps, config: { damping, stiffness } });
const tone = (k?: Tone) => (k === "mint" ? MINT : k === "clay" ? CLAY : AMBER);

function pipProgress(t: number): number {
  let p = BEATS[0].mode === "pip" ? 1 : 0;
  for (let i = 1; i < BEATS.length; i++) {
    const b = BEATS[i];
    const target = b.mode === "pip" ? 1 : 0;
    if (t >= b.t) {
      const local = (t - b.t) / MODE_BLEND_SEC;
      p = local >= 1 ? target : p + (target - p) * easeInOutCos(local);
    } else break;
  }
  return p;
}

// ---- Captions in timeline space (teaser pages + main pages) ----------------
function buildCaptions(): CaptionPage[] {
  const out: CaptionPage[] = [];
  SEG.teaser.forEach((seg) => {
    CAPTION_PAGES.forEach((p) => {
      if (p.end <= seg.src || p.start >= seg.end) return;
      const words = p.words
        .filter((w) => w.s >= seg.src - 0.05 && w.s < seg.end)
        .map((w) => ({ w: w.w, s: Math.max(w.s, seg.src) - seg.src + seg.dst, e: Math.min(w.e, seg.end) - seg.src + seg.dst }));
      if (!words.length) return;
      out.push({ start: Math.max(p.start, seg.src) - seg.src + seg.dst, end: Math.min(p.end, seg.end) - seg.src + seg.dst, words });
    });
  });
  const m = SEG.main;
  CAPTION_PAGES.forEach((p) => {
    if (p.end <= m.src) return;
    const words = p.words.filter((w) => w.e > m.src).map((w) => ({ w: w.w, s: Math.max(w.s, m.src) - m.src + m.dst, e: w.e - m.src + m.dst }));
    if (!words.length) return;
    out.push({ start: Math.max(p.start, m.src) - m.src + m.dst, end: p.end - m.src + m.dst, words });
  });
  return out.sort((a, b) => a.start - b.start);
}
const PAGES_TL = buildCaptions();

// ===========================================================================
// Web browser stage
// ===========================================================================
const BrowserChrome: React.FC = () => (
  <div
    style={{
      position: "absolute", left: 0, top: 0, width: VW, height: CHROME_H,
      background: "linear-gradient(180deg, #F1EEE7, #E6E2D9)", borderBottom: "1px solid rgba(0,0,0,0.12)",
      display: "flex", alignItems: "center", padding: "0 18px", gap: 8,
    }}
  >
    {["#FF5F57", "#FEBC2E", "#28C840"].map((c) => (
      <div key={c} style={{ width: 12, height: 12, borderRadius: 6, background: c, marginRight: 2 }} />
    ))}
    <div
      style={{
        marginLeft: 16, flex: 1, height: 30, borderRadius: 9, background: "#FFFFFF",
        border: "1px solid rgba(0,0,0,0.10)", display: "flex", alignItems: "center", gap: 8,
        padding: "0 12px", fontFamily: FONT, fontSize: 16, color: "#3A3733", fontWeight: 700,
      }}
    >
      <span style={{ fontSize: 13 }}>🔒</span>
      <span style={{ color: "#6B665E" }}>{EPISODE.page.domain}</span>
      <span style={{ color: "#8A857C", fontWeight: 700 }}>{EPISODE.page.path}</span>
    </div>
    {/* VERIFIED capture badge — receipts are the format's brand */}
    <div style={{ display: "flex", alignItems: "center", gap: 7, height: 26, padding: "0 12px", borderRadius: 8, background: "rgba(20,26,43,0.92)", fontFamily: FONT, fontWeight: 700, fontSize: 13, color: CREAM, letterSpacing: 0.5 }}>
      <div style={{ width: 8, height: 8, borderRadius: 4, background: MINT, boxShadow: `0 0 8px ${MINT}` }} />
      {EPISODE.captureLabel}
    </div>
  </div>
);

const VerifiedStamp: React.FC<{ local: number; fps: number }> = ({ local, fps }) => {
  if (local < 0.25 || local > 3.2) return null;
  const a = springIn(Math.round((local - 0.25) * fps), fps, 12, 170);
  const out = clamp01((local - 2.6) / 0.5);
  return (
    <div
      style={{
        position: "absolute", right: 26, bottom: 22, zIndex: 20,
        opacity: a * (1 - out), transform: `scale(${interpolate(a, [0, 1], [1.8, 1])}) rotate(${interpolate(a, [0, 1], [-14, -6])}deg)`,
        transformOrigin: "center", fontFamily: FONT, fontWeight: 800, fontSize: 18, letterSpacing: 3, color: MINT,
        border: `3px solid ${MINT}`, borderRadius: 10, padding: "6px 14px", background: "rgba(11,14,23,0.55)",
        boxShadow: `0 0 18px rgba(143,214,180,0.35)`,
      }}
    >
      ✓ VERIFIED
    </div>
  );
};

function camAt(cam: CamKey[] | undefined, local: number): { fx: number; fy: number; z: number } {
  if (!cam || cam.length === 0) return { fx: 550, fy: 300, z: 1 };
  if (local <= cam[0].t) return { fx: cam[0].fx ?? 550, fy: cam[0].fy, z: cam[0].z };
  for (let i = 0; i < cam.length - 1; i++) {
    const a = cam[i], b = cam[i + 1];
    if (local >= a.t && local < b.t) {
      const p = easeInOutCos((local - a.t) / Math.max(0.001, b.t - a.t));
      return {
        fx: interpolate(p, [0, 1], [a.fx ?? 550, b.fx ?? 550]),
        fy: interpolate(p, [0, 1], [a.fy, b.fy]),
        z: interpolate(p, [0, 1], [a.z, b.z]),
      };
    }
  }
  const l = cam[cam.length - 1];
  return { fx: l.fx ?? 550, fy: l.fy, z: l.z };
}

const WebStage: React.FC<{ beat: Beat; t: number; fps: number; stamp: boolean }> = ({ beat, t, fps, stamp }) => {
  const file = beat.file || "sec_hero";
  const clip = WEB_CLIPS[file] ?? WEB_CLIPS[file.replace(/^sec_/, "")] ?? WEB_CLIPS[file.replace(/_\d+$/, "")];
  const cssH = beat.cssH ?? clip?.h ?? 800;
  const local = t - beat.t;
  const cam = camAt(beat.cam, local);
  const s = S0 * cam.z;
  const pageW = 1100 * s;
  const pageH = cssH * s;
  let left = VW / 2 - cam.fx * s;
  let top = VH * 0.46 - cam.fy * s;
  left = Math.min(0, Math.max(VW - pageW, left));
  if (pageH <= VH) top = (VH - pageH) / 2; else top = Math.min(0, Math.max(VH - pageH, top));
  const enter = easeOutCubic(local / 0.5);
  const pageTop = top + (1 - enter) * 24;

  return (
    <div style={{ position: "absolute", left: 0, top: CHROME_H, width: VW, height: VH, overflow: "hidden", background: "#F5F4EE" }}>
      <div style={{ position: "absolute", left, top: pageTop, width: pageW, height: pageH }}>
        <Img src={staticFile(`${EPISODE.assetDir}/web/${file}.png`)} style={{ width: pageW, height: pageH, display: "block" }} />
        {(beat.hl || []).map((h, i) => {
          if (t < h.t) return null;
          const r = h.rect || (h.key ? R(h.key) : null);
          if (!r) return null;
          const pad = h.pad ?? 5;
          const wipe = springIn(Math.round((t - h.t) * fps), fps, 20, 120);
          return (
            <div
              key={i}
              style={{
                position: "absolute",
                left: (r.x - pad) * s, top: (r.y - pad) * s,
                width: (r.w + pad * 2) * s * wipe, height: (r.h + pad * 2) * s,
                background: "rgba(242,179,76,0.55)", borderRadius: 6 * s,
                mixBlendMode: "multiply",
                boxShadow: `0 0 0 ${1.5 * s}px rgba(217,142,31,${0.5 * wipe})`,
              }}
            />
          );
        })}
        {/* Thai translation strips — the "read it for me" layer (only the latest one stays up) */}
        {(beat.hl || []).map((h, i, arr) => {
          if (!h.th || t < h.t + 0.18) return null;
          const later = arr.some((o, j) => j !== i && !!o.th && o.t > h.t && t >= o.t + 0.18);
          if (later) return null;
          const r = h.rect || (h.key ? R(h.key) : null);
          if (!r) return null;
          const a = springIn(Math.round((t - h.t - 0.18) * fps), fps, 16, 150);
          const belowY = (r.y + r.h) * s + 10;
          const aboveY = r.y * s - 62;
          const roomAbove = pageTop + aboveY >= 6;
          const roomBelow = pageTop + belowY + 64 <= VH - 8;
          // prefer above (covers the line already read), else below, else clamp
          const y = roomAbove ? aboveY : roomBelow ? belowY : Math.max(6 - pageTop, Math.min(belowY, VH - 70 - pageTop));
          let x = r.x * s;
          x = Math.min(x, VW - left - 640);
          x = Math.max(x, -left + 10);
          return (
            <div
              key={`th${i}`}
              style={{
                position: "absolute", left: x, top: y, maxWidth: 620, zIndex: 5,
                display: "flex", alignItems: "center", gap: 10, padding: "7px 14px 7px 12px", borderRadius: 12,
                background: "rgba(11,14,23,0.92)", borderLeft: `4px solid ${AMBER}`,
                boxShadow: "0 10px 26px rgba(0,0,0,0.35)",
                opacity: a, transform: `translateY(${(1 - a) * 8}px)`,
              }}
            >
              <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 14, color: AMBER, letterSpacing: 1, flexShrink: 0 }}>แปล</span>
              <span style={{ fontFamily: FONT, fontWeight: 700, fontSize: 22, color: CREAM, lineHeight: 1.25 }}>{h.th}</span>
            </div>
          );
        })}
      </div>
      {stamp ? <VerifiedStamp local={local} fps={fps} /> : null}
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 40, background: "linear-gradient(180deg, rgba(0,0,0,0.10), transparent)", pointerEvents: "none" }} />
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 60, background: "linear-gradient(0deg, rgba(0,0,0,0.12), transparent)", pointerEvents: "none" }} />
    </div>
  );
};

// ===========================================================================
// Footage stage (full-bleed b-roll + kinetic headline) and clip cards
// ===========================================================================
const Footage: React.FC<{ src: string; from: number; beatStart: number; fps: number; style?: React.CSSProperties; zoom?: [number, number]; beatEnd: number; t: number }> = ({
  src, from, beatStart, fps, style, zoom = [1.04, 1.12], beatEnd, t,
}) => {
  const dur = BROLL_DUR[src] || 10;
  const p = clamp01((t - beatStart) / Math.max(0.1, beatEnd - beatStart));
  const scale = interpolate(p, [0, 1], [zoom[0], zoom[1]]);
  const loopFrames = Math.max(1, Math.floor((dur - from) * fps) - 2);
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", ...style }}>
      <div style={{ position: "absolute", inset: 0, transform: `scale(${scale})`, transformOrigin: "50% 50%" }}>
        <Loop durationInFrames={loopFrames} layout="none">
          <OffthreadVideo muted src={staticFile(`${EPISODE.assetDir}/broll/${src}.mp4`)} startFrom={Math.round(from * fps)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        </Loop>
      </div>
    </div>
  );
};

const HeadlineBlock: React.FC<{ beat: Beat; t: number; fps: number; light?: boolean }> = ({ beat, t, fps, light }) => {
  const local = Math.round((t - beat.t) * fps);
  const a = springIn(local - 4, fps, 18, 120);
  const subOn = beat.sub && t >= (beat.subT ?? beat.t + 1.2);
  const b = springIn(Math.round((t - (beat.subT ?? beat.t + 1.2)) * fps), fps, 18, 120);
  const ink = light ? INK : CREAM;
  const hook = !!beat.hook;
  return (
    <div style={{ position: "absolute", left: 64, top: hook ? 150 : 96, width: hook ? 1000 : 820, zIndex: 5 }}>
      {beat.idx ? (
        <div
          style={{
            display: "inline-block", fontFamily: FONT, fontWeight: 800, fontSize: 22, letterSpacing: 2,
            color: NAVY, background: AMBER, padding: "4px 14px", borderRadius: 8, marginBottom: 14,
            opacity: a, transform: `translateY(${(1 - a) * 12}px)`,
          }}
        >
          {beat.idx}
        </div>
      ) : null}
      <div
        style={{
          fontFamily: FONT, fontWeight: 800, fontSize: hook ? 112 : 74, lineHeight: 1.08, color: ink,
          textShadow: light ? "none" : "0 6px 30px rgba(0,0,0,0.55)",
          opacity: a, transform: `translateY(${(1 - a) * 26}px)`,
        }}
      >
        {beat.headline}
      </div>
      <div style={{ width: (hook ? 180 : 120) * a, height: hook ? 7 : 5, background: `linear-gradient(90deg, ${AMBER}, ${CLAY})`, borderRadius: 3, margin: "16px 0 14px" }} />
      {subOn ? (
        <div
          style={{
            fontFamily: FONT, fontWeight: 800, fontSize: hook ? 58 : 32, lineHeight: 1.25, color: light ? "#5A5248" : AMBER,
            textShadow: light ? "none" : "0 3px 16px rgba(0,0,0,0.55)",
            opacity: b, transform: `translateY(${(1 - b) * 14}px)`,
          }}
        >
          {beat.sub}
        </div>
      ) : null}
    </div>
  );
};

const FootageStage: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, beatEnd, t, fps }) => (
  <div style={{ position: "absolute", inset: 0 }}>
    <Footage src={beat.src || "abstract"} from={beat.from || 0} beatStart={beat.t} beatEnd={beatEnd} t={t} fps={fps} zoom={beat.hook ? [1.0, 1.14] : undefined} />
    <div style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg, rgba(11,14,23,0.90) 0%, rgba(11,14,23,0.62) 48%, rgba(11,14,23,0.28) 100%)" }} />
    <div style={{ position: "absolute", inset: 0, background: "linear-gradient(180deg, rgba(11,14,23,0.25), transparent 30%, transparent 70%, rgba(11,14,23,0.55))" }} />
    <HeadlineBlock beat={beat} t={t} fps={fps} />
  </div>
);

const ClipStage: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, t, fps }) => {
  const src = beat.src || "nipah";
  const dur = BROLL_DUR[src] || 5;
  const loopFrames = Math.max(1, Math.floor(dur * fps) - 1);
  const local = Math.round((t - beat.t) * fps);
  const a = springIn(local - 2, fps, 18, 120);
  const subOn = beat.sub && t >= (beat.subT ?? beat.t + 1.2);
  return (
    <div style={{ position: "absolute", inset: 0, background: "#EFECE4", overflow: "hidden" }}>
      <div style={{ position: "absolute", inset: 0 }}>
        <Loop durationInFrames={loopFrames} layout="none">
          <OffthreadVideo muted src={staticFile(`${EPISODE.assetDir}/broll/${src}.mp4`)} style={{ width: "100%", height: "100%", objectFit: beat.clipFit ?? "contain" }} />
        </Loop>
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 260, background: "linear-gradient(0deg, rgba(11,14,23,0.86), rgba(11,14,23,0.0))" }} />
      <div style={{ position: "absolute", left: 40, bottom: 34, width: 1120, zIndex: 5 }}>
        <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 46, color: CREAM, textShadow: "0 4px 22px rgba(0,0,0,0.6)", opacity: a, transform: `translateY(${(1 - a) * 18}px)` }}>
          {beat.headline}
        </div>
        {subOn ? (
          <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 22, color: CREAM_DIM, marginTop: 6 }}>{beat.sub}</div>
        ) : null}
      </div>
      <div style={{ position: "absolute", right: 22, top: 18, fontFamily: FONT, fontWeight: 700, fontSize: 16, color: NAVY, background: "rgba(245,241,232,0.85)", padding: "5px 12px", borderRadius: 8, letterSpacing: 1 }}>
        {EPISODE.officialTag}
      </div>
    </div>
  );
};

// ===========================================================================
// Typography scenes (agenda / summary3 / vs / final4)
// ===========================================================================
const ChipRow: React.FC<{ items: { t: number; text: string; icon: string }[]; t: number; fps: number; big?: boolean; col?: boolean; size?: number }> = ({ items, t, fps, big, col, size }) => (
  <div style={{ display: "flex", flexDirection: col ? "column" : "row", flexWrap: "wrap", gap: big ? 22 : 18, alignItems: col ? "stretch" : "center", justifyContent: "center" }}>
    {items.map((it, i) => {
      const a = t >= it.t ? springIn(Math.round((t - it.t) * fps), fps, 14, 140) : 0;
      const fs = size ?? (big ? 62 : 46);
      return (
        <div
          key={i}
          style={{
            display: "flex", alignItems: "center", gap: 18,
            padding: big ? "22px 38px" : "16px 28px", borderRadius: 24,
            background: "rgba(245,241,232,0.10)", border: "1.5px solid rgba(242,179,76,0.55)",
            backdropFilter: "blur(14px)", WebkitBackdropFilter: "blur(14px)",
            boxShadow: "0 14px 40px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.12)",
            opacity: a, transform: `translateY(${(1 - a) * 26}px) scale(${interpolate(a, [0, 1], [0.9, 1])})`,
          }}
        >
          <span style={{ fontSize: fs * 0.84 }}>{it.icon}</span>
          <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: fs, color: CREAM, textShadow: "0 3px 14px rgba(0,0,0,0.5)" }}>{it.text}</span>
        </div>
      );
    })}
  </div>
);

const TypoStage: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, beatEnd, t, fps }) => {
  const local = Math.round((t - beat.t) * fps);
  const a = springIn(local, fps, 18, 120);
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      <Footage src={beat.src || "abstract"} from={beat.from || 0} beatStart={beat.t} beatEnd={beatEnd} t={t} fps={fps} zoom={[1.06, 1.16]} />
      <div style={{ position: "absolute", inset: 0, background: "rgba(11,14,23,0.78)" }} />
      <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 50% 30%, rgba(242,179,76,0.16), transparent 60%)` }} />

      {beat.typo === "agenda" ? (
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 34, padding: "0 60px" }}>
          <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 30, letterSpacing: 4, color: AMBER, opacity: a }}>{EPISODE.agendaLabel}</div>
          <ChipRow items={AGENDA_TL.map((x, i) => ({ ...x, text: `${i + 1}. ${x.text}` }))} t={t} fps={fps} size={38} />
        </div>
      ) : null}

      {beat.typo === "summary3" ? (
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 46 }}>
          <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 30, letterSpacing: 4, color: AMBER, opacity: a }}>{EPISODE.summary3Label}</div>
          <ChipRow items={SUMMARY3_TL} t={t} fps={fps} big />
        </div>
      ) : null}

      {beat.typo === "final4" ? (
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 36 }}>
          <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 58, color: CREAM, opacity: a, transform: `translateY(${(1 - a) * 16}px)`, textAlign: "center", lineHeight: 1.15 }}>
            {EPISODE.final4.title}
            <div style={{ fontSize: 28, fontWeight: 700, color: AMBER, marginTop: 4 }}>{EPISODE.final4.sub}</div>
          </div>
          <div style={{ width: 900 }}>
            <ChipRow items={FINAL4_TL} t={t} fps={fps} />
          </div>
        </div>
      ) : null}

      {beat.typo === "vs" ? <VsCard t={t} fps={fps} /> : null}
    </div>
  );
};

const VsCard: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  const VS = VS_TL;
  const f = t >= VS.fableT ? springIn(Math.round((t - VS.fableT) * fps), fps, 16, 120) : 0;
  const m = t >= VS.mythosT ? springIn(Math.round((t - VS.mythosT) * fps), fps, 16, 120) : 0;
  const s = t >= VS.subT ? springIn(Math.round((t - VS.subT) * fps), fps, 16, 120) : 0;
  const eq = springIn(Math.round((t - (VS.fableT - 0.6)) * fps), fps, 16, 120);
  const card = (on: number, title: string, badge: string, lines: string[], accent: string, lineT: number[]): React.ReactNode => (
    <div
      style={{
        width: 520, padding: "32px 34px", borderRadius: 28,
        background: "rgba(245,241,232,0.08)", border: `2px solid ${accent}`,
        boxShadow: `0 20px 60px rgba(0,0,0,0.5), 0 0 40px ${accent}33`,
        backdropFilter: "blur(16px)", WebkitBackdropFilter: "blur(16px)",
        opacity: on, transform: `translateY(${(1 - on) * 30}px) scale(${interpolate(on, [0, 1], [0.94, 1])})`,
      }}
    >
      <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 18, letterSpacing: 3, color: accent, marginBottom: 6 }}>{badge}</div>
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 60, color: CREAM, lineHeight: 1.05 }}>{title}</div>
      <div style={{ width: 90, height: 4, background: accent, borderRadius: 2, margin: "16px 0 18px" }} />
      {lines.map((l, i) => {
        const lt = lineT[i] ?? VS.fableT;
        const la = t >= lt ? springIn(Math.round((t - lt) * fps), fps, 16, 140) : 0;
        return (
          <div key={i} style={{ fontFamily: FONT, fontWeight: 700, fontSize: 25, color: la > 0.9 ? CREAM : CREAM_DIM, lineHeight: 1.45, opacity: 0.25 + 0.75 * la, transform: `translateX(${(1 - la) * -14}px)` }}>
            {l}
          </div>
        );
      })}
    </div>
  );
  return (
    <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 30 }}>
      <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 30, color: AMBER, letterSpacing: 2, opacity: eq, transform: `translateY(${(1 - eq) * 10}px)` }}>
        {EPISODE.vs.eyebrow}
      </div>
      <div style={{ display: "flex", gap: 40, alignItems: "stretch" }}>
        {card(f, EPISODE.vs.left.title, EPISODE.vs.left.badge, EPISODE.vs.left.lines, AMBER, VS.leftLines)}
        <div style={{ alignSelf: "center", fontFamily: FONT, fontWeight: 800, fontSize: 46, color: CREAM_DIM, opacity: eq }}>vs</div>
        {card(m, EPISODE.vs.right.title, EPISODE.vs.right.badge, EPISODE.vs.right.lines, CLAY, VS.rightLines)}
      </div>
      <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 26, color: CREAM, background: "rgba(217,119,87,0.22)", border: "1.5px solid rgba(217,119,87,0.6)", padding: "12px 28px", borderRadius: 18, opacity: s, transform: `translateY(${(1 - s) * 14}px)` }}>
        {EPISODE.vs.conclusion}
      </div>
    </div>
  );
};

// ===========================================================================
// Explain cards — "ย่อยให้เห็นภาพ" (flow / list / compare)
// ===========================================================================
const ExplainStage: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, beatEnd, t, fps }) => {
  const ex = beat.explain as Explain;
  const local = Math.round((t - beat.t) * fps);
  const a = springIn(local - 2, fps, 18, 120);
  const glass: React.CSSProperties = {
    background: "rgba(245,241,232,0.08)", border: "1.5px solid rgba(242,179,76,0.45)",
    backdropFilter: "blur(14px)", WebkitBackdropFilter: "blur(14px)",
    boxShadow: "0 14px 40px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.10)",
  };
  const item = (it: Explain["items"][number], i: number, wide: boolean) => {
    const on = t >= it.t ? springIn(Math.round((t - it.t) * fps), fps, 14, 140) : 0;
    return (
      <div key={i} style={{ display: "flex", alignItems: "center", gap: 20, padding: "14px 24px", borderRadius: 20, ...glass, width: wide ? "100%" : undefined, opacity: on, transform: `translateX(${(1 - on) * -26}px)` }}>
        <span style={{ fontSize: 40, lineHeight: 1 }}>{it.icon}</span>
        <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 34, color: it.tone ? tone(it.tone) : CREAM, lineHeight: 1.2 }}>{it.text}</span>
      </div>
    );
  };
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      <Footage src={beat.src || "abstract"} from={beat.from || 0} beatStart={beat.t} beatEnd={beatEnd} t={t} fps={fps} zoom={[1.04, 1.12]} />
      <div style={{ position: "absolute", inset: 0, background: "rgba(11,14,23,0.84)" }} />
      <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 30% 20%, rgba(242,179,76,0.18), transparent 55%)` }} />
      <div style={{ position: "absolute", left: 64, top: 64, right: 64, bottom: 56, display: "flex", flexDirection: "column", gap: 26 }}>
        <div style={{ opacity: a, transform: `translateY(${(1 - a) * 16}px)` }}>
          <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 50, color: CREAM, lineHeight: 1.15, textShadow: "0 6px 30px rgba(0,0,0,0.5)" }}>{ex.title}</div>
          {ex.sub ? <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 26, color: AMBER, marginTop: 6 }}>{ex.sub}</div> : null}
          <div style={{ width: 120 * a, height: 5, background: `linear-gradient(90deg, ${AMBER}, ${CLAY})`, borderRadius: 3, marginTop: 14 }} />
        </div>

        {ex.layout === "compare" && ex.left && ex.right ? (
          <div style={{ display: "flex", gap: 28, alignItems: "stretch" }}>
            {[ex.left, ex.right].map((side, i) => {
              const on = springIn(local - 6 - i * 8, fps, 16, 120);
              const c = tone(side.tone);
              return (
                <div key={i} style={{ flex: 1, padding: "24px 26px", borderRadius: 24, ...glass, border: `2px solid ${c}`, boxShadow: `0 16px 44px rgba(0,0,0,0.45), 0 0 30px ${c}33`, opacity: on, transform: `translateY(${(1 - on) * 22}px)`, display: "flex", alignItems: "center", gap: 20 }}>
                  <span style={{ fontSize: 52, lineHeight: 1 }}>{side.icon}</span>
                  <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 32, color: c, lineHeight: 1.2 }}>{side.title}</span>
                </div>
              );
            })}
          </div>
        ) : null}

        {ex.layout === "flow" ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 16, position: "relative", paddingLeft: 34 }}>
            <div style={{ position: "absolute", left: 10, top: 20, bottom: 20, width: 4, borderRadius: 2, background: `linear-gradient(180deg, ${AMBER}, ${CLAY})`, opacity: 0.7 }} />
            {ex.items.map((it, i) => {
              const on = t >= it.t ? springIn(Math.round((t - it.t) * fps), fps, 14, 140) : 0;
              return (
                <div key={i} style={{ position: "relative", display: "flex", alignItems: "center", gap: 20 }}>
                  <div style={{ position: "absolute", left: -34, width: 24, height: 24, borderRadius: 12, background: NAVY, border: `4px solid ${AMBER}`, opacity: on, transform: `scale(${on})` }} />
                  <div style={{ display: "flex", alignItems: "center", gap: 20, padding: "14px 24px", borderRadius: 20, ...glass, opacity: on, transform: `translateX(${(1 - on) * -26}px)` }}>
                    <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 20, color: AMBER, letterSpacing: 2 }}>0{i + 1}</span>
                    <span style={{ fontSize: 40, lineHeight: 1 }}>{it.icon}</span>
                    <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 34, color: CREAM, lineHeight: 1.2 }}>{it.text}</span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}

        {ex.layout === "list" || ex.layout === "compare" ? (
          <div style={{ display: "flex", flexDirection: ex.layout === "list" ? "column" : "row", flexWrap: "wrap", gap: 16, alignItems: ex.layout === "list" ? "flex-start" : "center" }}>
            {ex.items.map((it, i) => item(it, i, false))}
          </div>
        ) : null}

        {ex.footnote ? (
          <div style={{ marginTop: "auto", fontFamily: FONT, fontWeight: 700, fontSize: 18, color: CREAM_DIM, opacity: a }}>{ex.footnote}</div>
        ) : null}
      </div>
    </div>
  );
};

// ===========================================================================
// Chart scene — the page's table numbers as animated bars
// ===========================================================================
const ChartStage: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, beatEnd, t, fps }) => {
  const ch = beat.chart as Chart;
  const local = t - beat.t;
  const a = springIn(Math.round(local * fps) - 2, fps, 18, 120);
  const max = ch.max ?? Math.max(...ch.bars.map((b) => b.value)) * 1.15;
  const trackW = 700;
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      <Footage src={beat.src || "abstract"} from={beat.from || 0} beatStart={beat.t} beatEnd={beatEnd} t={t} fps={fps} zoom={[1.04, 1.1]} />
      <div style={{ position: "absolute", inset: 0, background: "rgba(11,14,23,0.86)" }} />
      <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 70% 20%, rgba(242,179,76,0.16), transparent 55%)` }} />
      <div style={{ position: "absolute", left: 64, top: 60, right: 64 }}>
        <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 46, color: CREAM, opacity: a, transform: `translateY(${(1 - a) * 14}px)` }}>{ch.title}</div>
        {ch.sub ? <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 24, color: AMBER, marginTop: 4, opacity: a }}>{ch.sub}</div> : null}
        <div style={{ display: "flex", flexDirection: "column", gap: 30, marginTop: 44 }}>
          {ch.bars.map((b, i) => {
            const start = 0.35 + i * 0.32;
            const g = local >= start ? springIn(Math.round((local - start) * fps), fps, 20, 90) : 0;
            const c = b.tone ? tone(b.tone) : "rgba(245,241,232,0.55)";
            const lead = b.tone === "amber";
            const w = (b.value / max) * trackW * g;
            return (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 22, opacity: Math.min(1, g * 3) }}>
                <div style={{ width: 290, textAlign: "right", fontFamily: FONT, fontWeight: lead ? 800 : 700, fontSize: lead ? 30 : 26, color: lead ? CREAM : CREAM_DIM, lineHeight: 1.15 }}>{b.label}</div>
                <div style={{ position: "relative", width: trackW, height: lead ? 54 : 44, borderRadius: 14, background: "rgba(245,241,232,0.06)", border: "1px solid rgba(245,241,232,0.10)" }}>
                  <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: w, borderRadius: 14, background: lead ? `linear-gradient(90deg, ${AMBER_DEEP}, ${AMBER})` : c, boxShadow: lead ? `0 0 26px ${AMBER}66` : "none" }} />
                </div>
                <div style={{ width: 150, fontFamily: FONT, fontWeight: 800, fontSize: lead ? 44 : 34, color: lead ? AMBER : c, lineHeight: 1 }}>
                  {(b.value * g).toFixed(1)}{ch.unit ?? ""}
                  {b.note ? <div style={{ fontSize: 18, fontWeight: 700, color: CREAM_DIM, marginTop: 4 }}>{b.note}</div> : null}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

// ===========================================================================
// Terminal demo — synthetic screen recording of a real Claude Code session
// ===========================================================================
const TerminalStage: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, t, fps }) => {
  const term = beat.terminal as Terminal;
  const local = t - beat.t;
  const a = springIn(Math.round(local * fps) - 2, fps, 18, 120);
  const colorOf: Record<string, string> = { cmd: CREAM, out: CREAM_DIM, ok: MINT, warn: CLAY, claude: AMBER, add: MINT, del: CLAY, dim: "rgba(245,241,232,0.45)" };
  const prefixOf: Record<string, string> = { cmd: "❯ ", out: "", ok: "✔ ", warn: "✖ ", claude: "✦ ", add: "", del: "", dim: "" };
  const winTop = 178;
  const visible = term.lines.filter((l) => local >= l.t);
  const lineH = 42;
  const maxLines = 13;
  const scroll = Math.max(0, visible.length - maxLines) * lineH;
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", background: `linear-gradient(180deg, ${NAVY_2}, ${NAVY})` }}>
      <div style={{ position: "absolute", inset: 0, backgroundImage: "radial-gradient(rgba(245,241,232,0.06) 1.2px, transparent 1.2px)", backgroundSize: "28px 28px" }} />
      <div style={{ position: "absolute", left: 48, top: 44, display: "flex", alignItems: "center", gap: 18, opacity: a, transform: `translateY(${(1 - a) * 14}px)` }}>
        {beat.idx ? <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 22, letterSpacing: 2, color: NAVY, background: AMBER, padding: "4px 14px", borderRadius: 8 }}>{beat.idx}</div> : null}
        <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 54, color: CREAM, lineHeight: 1.1, textShadow: "0 6px 30px rgba(0,0,0,0.55)" }}>{beat.headline}</div>
      </div>
      <div style={{ position: "absolute", left: 40, top: winTop, width: VW - 80, height: STAGE.h - winTop - 60, borderRadius: 18, overflow: "hidden", background: "#0A0C14", border: "1px solid rgba(245,241,232,0.14)", boxShadow: "0 30px 80px rgba(0,0,0,0.6)", opacity: a, transform: `translateY(${(1 - a) * 24}px)` }}>
        <div style={{ height: 44, display: "flex", alignItems: "center", padding: "0 16px", gap: 8, background: "#151926", borderBottom: "1px solid rgba(245,241,232,0.08)" }}>
          {["#FF5F57", "#FEBC2E", "#28C840"].map((c) => <div key={c} style={{ width: 12, height: 12, borderRadius: 6, background: c }} />)}
          <div style={{ marginLeft: 14, fontFamily: MONO, fontSize: 15, color: CREAM_DIM }}>{term.title}</div>
          <div style={{ marginLeft: "auto", fontFamily: FONT, fontWeight: 800, fontSize: 14, letterSpacing: 2, color: NAVY, background: AMBER, padding: "3px 10px", borderRadius: 6 }}>{term.tag}</div>
        </div>
        <div style={{ position: "absolute", left: 22, right: 22, top: 44 + 18 - scroll, fontFamily: MONO, fontSize: 21, lineHeight: `${lineH}px` }}>
          {visible.map((l, i) => {
            const age = local - l.t;
            const typed = l.kind === "cmd" ? Math.min(l.text.length, Math.floor(age * 60)) : l.text.length;
            const on = clamp01(age / 0.18);
            const bg = l.kind === "add" ? "rgba(143,214,180,0.12)" : l.kind === "del" ? "rgba(217,119,87,0.12)" : "transparent";
            return (
              <div key={i} style={{ color: colorOf[l.kind], opacity: on, background: bg, borderRadius: 6, padding: "0 8px", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                <span style={{ color: l.kind === "cmd" ? AMBER : colorOf[l.kind] }}>{prefixOf[l.kind]}</span>
                {l.text.slice(0, typed)}
                {l.kind === "cmd" && typed < l.text.length ? <span style={{ color: AMBER }}>▌</span> : null}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

// ===========================================================================
// Ident sting (between teaser and main)
// ===========================================================================
const StingScreen: React.FC<{ beat: Beat; t: number; fps: number; beatEnd: number }> = ({ beat, t, fps, beatEnd }) => {
  const local = t - beat.t;
  const dur = beatEnd - beat.t;
  const a = clamp01(local / 0.12);
  const out = clamp01((local - (dur - 0.35)) / 0.35);
  const s1 = springIn(Math.round((local - 0.08) * fps), fps, 14, 150);
  const s2 = springIn(Math.round((local - 0.45) * fps), fps, 16, 130);
  const ring = clamp01(local / 1.4);
  return (
    <div style={{ position: "absolute", inset: 0, zIndex: 80, opacity: a * (1 - out), background: NAVY, overflow: "hidden" }}>
      <div style={{ position: "absolute", inset: 0, opacity: 0.55 }}>
        <Footage src="gen_ident" from={0} beatStart={beat.t} beatEnd={beatEnd} t={t} fps={fps} zoom={[1.1, 1.22]} />
      </div>
      <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 50% 45%, rgba(11,14,23,0.15), ${NAVY} 78%)` }} />
      {/* expanding ring burst (a real circle: spread-shadows on a 0-size box render square) */}
      <div style={{ position: "absolute", left: 960, top: 520, width: ring * 1800, height: ring * 1800, borderRadius: "50%", transform: "translate(-50%,-50%)", opacity: 1 - ring, background: `radial-gradient(circle, transparent 58%, rgba(242,179,76,0.35) 62%, rgba(242,179,76,0.12) 70%, transparent 76%)` }} />
      <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 18 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, opacity: s1 }}>
          <div style={{ width: 12, height: 12, borderRadius: 6, background: CLAY, boxShadow: `0 0 12px ${CLAY}` }} />
          <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 24, letterSpacing: 6, color: AMBER }}>{EPISODE.sting.eyebrow}</div>
        </div>
        <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 112, color: CREAM, lineHeight: 1.02, textAlign: "center", opacity: s1, transform: `scale(${interpolate(s1, [0, 1], [1.25, 1])})`, textShadow: "0 10px 40px rgba(0,0,0,0.6)" }}>
          {EPISODE.sting.titleA}
          <span style={{ color: AMBER, fontWeight: 700 }}> {EPISODE.sting.amp} </span>
          {EPISODE.sting.titleB}
        </div>
        <div style={{ width: 220 * s2, height: 6, background: `linear-gradient(90deg, ${CLAY}, ${AMBER})`, borderRadius: 3 }} />
        <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 34, color: CREAM_DIM, opacity: s2, transform: `translateY(${(1 - s2) * 14}px)` }}>{EPISODE.sting.sub}</div>
      </div>
    </div>
  );
};

// ===========================================================================
// Overlays
// ===========================================================================
const StatChips: React.FC<{ beat: Beat; t: number; fps: number }> = ({ beat, t, fps }) => {
  const items = (beat.stats || []).filter((s) => t >= s.t);
  if (!items.length) return null;
  return (
    <div style={{ position: "absolute", left: STAGE.x + 28, bottom: H - (STAGE.y + STAGE.h) + 26, display: "flex", gap: 14, flexWrap: "wrap", width: STAGE.w - 56, zIndex: 40, alignItems: "flex-end" }}>
      {items.map((s, i) => {
        const a = springIn(Math.round((t - s.t) * fps), fps, 14, 150);
        const c = tone(s.tone);
        return (
          <div
            key={i}
            style={{
              display: "flex", alignItems: "baseline", gap: 12,
              padding: s.big ? "12px 22px 12px 20px" : "11px 20px", borderRadius: 18,
              background: "rgba(11,14,23,0.88)", border: `1.5px solid ${c}88`,
              boxShadow: `0 12px 34px rgba(0,0,0,0.45), 0 0 22px ${c}33`,
              backdropFilter: "blur(12px)", WebkitBackdropFilter: "blur(12px)",
              opacity: a, transform: `translateY(${(1 - a) * 22}px) scale(${interpolate(a, [0, 1], [0.86, 1])})`,
              transformOrigin: "left bottom",
            }}
          >
            {s.big ? <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 48, color: c, lineHeight: 1, textShadow: `0 0 18px ${c}66` }}>{s.big}</span> : null}
            <span style={{ fontFamily: FONT, fontWeight: 700, fontSize: s.big ? 24 : 27, color: CREAM, lineHeight: 1.2 }}>{s.label}</span>
          </div>
        );
      })}
    </div>
  );
};

// glossary chip — English jargon gets a one-line Thai meaning on first mention
const GlossChip: React.FC<{ beat: Beat; t: number; fps: number }> = ({ beat, t, fps }) => {
  const g = (beat.gloss || []).filter((x) => t >= x.t && t < x.t + 5.0).slice(-1)[0];
  if (!g) return null;
  const a = springIn(Math.round((t - g.t) * fps), fps, 14, 150);
  const out = clamp01((t - (g.t + 4.4)) / 0.5);
  const top = STAGE.y + (beat.media === "web" ? CHROME_H : 0) + 16;
  return (
    <div style={{ position: "absolute", right: W - (STAGE.x + STAGE.w) + 18, top, zIndex: 42, maxWidth: 560, opacity: a * (1 - out), transform: `translateY(${(1 - a) * -10}px)` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "9px 16px 9px 14px", borderRadius: 14, background: "rgba(11,14,23,0.92)", border: `1.5px solid ${AMBER}88`, boxShadow: "0 10px 30px rgba(0,0,0,0.45)" }}>
        <span style={{ fontSize: 20 }}>📖</span>
        <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 21, color: AMBER, whiteSpace: "nowrap" }}>{g.term}</span>
        <span style={{ width: 1, height: 22, background: "rgba(245,241,232,0.25)" }} />
        <span style={{ fontFamily: FONT, fontWeight: 700, fontSize: 20, color: CREAM, lineHeight: 1.25 }}>{g.th}</span>
      </div>
    </div>
  );
};

const TopBar: React.FC<{ beat: Beat; t: number; fps: number; p: number }> = ({ beat, t, fps, p }) => {
  const local = Math.round((t - beat.t) * fps);
  const k = springIn(local - 6, fps, 18, 120);
  const inTeaser = t < SEG.stingStart;
  let chIdx = -1;
  for (let i = 0; i < CHAPTERS_TL.length; i++) if (t >= CHAPTERS_TL[i].t) chIdx = i;
  const ch = chIdx >= 0 ? CHAPTERS_TL[chIdx] : null;
  const chA = ch ? springIn(Math.round((t - ch.t) * fps) - 4, fps, 18, 120) : 0;
  return (
    <div style={{ position: "absolute", left: 0, top: 0, width: W, height: 92, zIndex: 45, display: "flex", alignItems: "center", padding: "0 80px", gap: 22 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ width: 12, height: 12, borderRadius: 6, background: CLAY, boxShadow: `0 0 12px ${CLAY}` }} />
        <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 24, letterSpacing: 4, color: CREAM }}>{EPISODE.brand}</div>
        <div style={{ width: 1, height: 26, background: "rgba(245,241,232,0.25)" }} />
        <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 20, color: CREAM_DIM, letterSpacing: 1 }}>{EPISODE.dateLabel}</div>
      </div>
      {beat.kicker && p > 0.5 ? (
        <div
          style={{
            marginLeft: 26, fontFamily: FONT, fontWeight: 700, fontSize: 24, color: NAVY,
            background: AMBER, padding: "6px 20px", borderRadius: 12,
            boxShadow: `0 6px 20px rgba(242,179,76,0.35)`,
            opacity: k * p, transform: `translateX(${(1 - k) * -18}px)`,
          }}
        >
          {beat.kicker}
        </div>
      ) : null}
      {/* chapter pill (right) — structure promise + progress */}
      {inTeaser ? (
        <div style={{ marginLeft: "auto", fontFamily: FONT, fontWeight: 800, fontSize: 18, letterSpacing: 4, color: CREAM, background: "rgba(217,119,87,0.85)", padding: "6px 16px", borderRadius: 10, display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 10, height: 10, borderRadius: 5, background: CREAM, opacity: 0.5 + 0.5 * Math.abs(Math.sin(t * 4)) }} />
          {EPISODE.previewTag}
        </div>
      ) : ch ? (
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12, opacity: chA, transform: `translateX(${(1 - chA) * 18}px)` }}>
          <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 18, letterSpacing: 2, color: NAVY, background: CREAM, padding: "4px 12px", borderRadius: 8 }}>{chIdx + 1}/{CHAPTERS_TL.length}</div>
          <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 22, color: CREAM }}>{ch.title}</div>
        </div>
      ) : null}
    </div>
  );
};

const LowerThird: React.FC<{ beat: Beat; t: number; fps: number }> = ({ beat, t, fps }) => {
  if (!beat.lower) return null;
  const start = beat.lower.t ?? beat.t + 0.8;
  const dur = beat.lower.dur ?? 5;
  if (t < start || t > start + dur + 0.5) return null;
  const a = springIn(Math.round((t - start) * fps), fps, 18, 110);
  const out = clamp01((t - (start + dur)) / 0.45);
  const o = a * (1 - out);
  return (
    <div style={{ position: "absolute", left: 80, bottom: 150, zIndex: 46, opacity: o, transform: `translateX(${(1 - a) * -40 + out * -30}px)` }}>
      <div style={{ display: "inline-block", fontFamily: FONT, fontWeight: 800, fontSize: 20, letterSpacing: 4, color: NAVY, background: AMBER, padding: "5px 16px", borderRadius: 8 }}>{beat.lower.tag ?? "BREAKING"}</div>
      <div style={{ marginTop: 10, fontFamily: FONT, fontWeight: 800, fontSize: 62, color: CREAM, lineHeight: 1.1, textShadow: "0 6px 30px rgba(0,0,0,0.6)" }}>{beat.lower.title}</div>
      <div style={{ marginTop: 8, display: "inline-block", fontFamily: FONT, fontWeight: 700, fontSize: 28, color: CREAM, background: "rgba(11,14,23,0.78)", padding: "8px 18px", borderRadius: 12, borderLeft: `5px solid ${CLAY}` }}>
        {beat.lower.sub}
      </div>
    </div>
  );
};

// "ต่อไป ▶" tease chips on full-frame pivots — the open loop that keeps people watching
const NextChips: React.FC<{ beat: Beat; beatEnd: number; t: number; fps: number }> = ({ beat, beatEnd, t, fps }) => {
  if (!beat.next) return null;
  const start = beat.next.t ?? beat.t + 0.6;
  if (t < start) return null;
  const out = clamp01((t - (beatEnd - 0.4)) / 0.4);
  const a = springIn(Math.round((t - start) * fps), fps, 18, 120);
  const ctaUp = t >= CTA_TL && t < VO_END_SEC; // stack above the CTA chip when both are on screen
  return (
    <div style={{ position: "absolute", left: 80, bottom: ctaUp ? 300 : 150, zIndex: 46, opacity: a * (1 - out), transform: `translateY(${(1 - a) * 20}px)` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 20, letterSpacing: 4, color: NAVY, background: AMBER, padding: "5px 16px", borderRadius: 8 }}>{beat.next.pill ?? "ต่อไป ▶"}</div>
        {beat.next.label ? <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 34, color: CREAM, textShadow: "0 4px 20px rgba(0,0,0,0.6)" }}>{beat.next.label}</div> : null}
      </div>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", maxWidth: 1100 }}>
        {beat.next.items.map((it, i) => {
          const s = springIn(Math.round((t - start - 0.22 - i * 0.22) * fps), fps, 14, 150);
          return (
            <div key={i} style={{ fontFamily: FONT, fontWeight: 700, fontSize: 27, color: CREAM, background: "rgba(11,14,23,0.82)", border: "1.5px solid rgba(242,179,76,0.55)", padding: "9px 20px", borderRadius: 16, opacity: s, transform: `translateY(${(1 - s) * 16}px) scale(${interpolate(s, [0, 1], [0.9, 1])})`, backdropFilter: "blur(10px)", WebkitBackdropFilter: "blur(10px)" }}>
              {it}
            </div>
          );
        })}
      </div>
      {beat.next.tease ? (
        <div style={{ marginTop: 12, display: "inline-block", fontFamily: FONT, fontWeight: 700, fontSize: 24, color: CREAM, background: "rgba(217,119,87,0.28)", border: "1.5px solid rgba(217,119,87,0.7)", padding: "7px 18px", borderRadius: 12, opacity: springIn(Math.round((t - start - 0.22 - beat.next.items.length * 0.22 - 0.2) * fps), fps, 14, 150) }}>
          ⏭ {beat.next.tease}
        </div>
      ) : null}
    </div>
  );
};

const CtaChip: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  if (t < CTA_TL || t >= VO_END_SEC) return null;
  const a = springIn(Math.round((t - CTA_TL) * fps), fps, 14, 130);
  return (
    <div style={{ position: "absolute", left: 80, bottom: 170, zIndex: 46, opacity: a, transform: `translateY(${(1 - a) * 24}px) scale(${interpolate(a, [0, 1], [0.9, 1])})`, transformOrigin: "left bottom" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 18, padding: "16px 30px", borderRadius: 22, background: "rgba(11,14,23,0.86)", border: `2px solid ${AMBER}`, boxShadow: `0 16px 40px rgba(0,0,0,0.5), 0 0 30px ${AMBER}44` }}>
        <span style={{ fontFamily: FONT, fontWeight: 700, fontSize: 26, color: CREAM_DIM }}>{EPISODE.cta.lead}</span>
        <span style={{ fontFamily: FONT, fontWeight: 800, fontSize: 44, color: AMBER, letterSpacing: 1 }}>{EPISODE.cta.text}</span>
      </div>
    </div>
  );
};

const ProgressBar: React.FC<{ totalFrames: number }> = ({ totalFrames }) => {
  const frame = useCurrentFrame();
  const progress = Math.min(1, frame / totalFrames);
  return (
    <div style={{ position: "absolute", top: 0, left: 0, width: "100%", height: 5, backgroundColor: "rgba(245,241,232,0.10)", zIndex: 60 }}>
      <div style={{ width: `${progress * 100}%`, height: "100%", background: `linear-gradient(90deg, ${CLAY}, ${AMBER})`, boxShadow: `0 0 10px ${AMBER}` }} />
      {CHAPTERS_TL.map((c, i) => (
        <div key={i} style={{ position: "absolute", left: `${(c.t / (totalFrames / 25)) * 100}%`, top: 0, width: 2, height: "100%", background: "rgba(245,241,232,0.35)" }} />
      ))}
    </div>
  );
};

// karaoke caption lane (locked gold-glow look, 16:9 placement)
const isLatin = (s: string) => /^[A-Za-z0-9]/.test(s) || /[A-Za-z0-9]$/.test(s);
const CaptionLane: React.FC<{ t: number; fps: number; hidden: boolean }> = ({ t, fps, hidden }) => {
  if (t >= VO_END_SEC || hidden) return null;
  let pageIdx = -1;
  for (let i = 0; i < PAGES_TL.length; i++) if (t >= PAGES_TL[i].start) pageIdx = i;
  const page = pageIdx >= 0 ? PAGES_TL[pageIdx] : null;
  if (!page || t > page.end + 0.6) return null;
  const enter = spring({ frame: Math.max(0, Math.round((t - page.start) * fps)), fps, config: { damping: 18, stiffness: 160 } });
  return (
    <div style={{ position: "absolute", left: 0, right: 0, bottom: 26, display: "flex", justifyContent: "center", pointerEvents: "none", zIndex: 50 }}>
      <div
        style={{
          display: "flex", flexWrap: "wrap", justifyContent: "center", alignItems: "center", maxWidth: 1500,
          background: "rgba(11, 14, 23, 0.80)", backdropFilter: "blur(16px)", WebkitBackdropFilter: "blur(16px)",
          border: "1.5px solid rgba(242,179,76,0.30)", borderRadius: 20, padding: "10px 28px",
          boxShadow: "0 8px 32px rgba(0,0,0,0.6), 0 0 20px rgba(242,179,76,0.15)",
          transform: `scale(${interpolate(enter, [0, 1], [0.94, 1])})`, opacity: enter,
        }}
      >
        {page.words.map((w, i) => {
          const active = t >= w.s && t < w.e;
          const spoken = t >= w.e;
          const prev = i > 0 ? page.words[i - 1].w : "";
          const sep = i > 0 && (isLatin(prev) || isLatin(w.w)) ? " " : "";
          let color = "rgba(245,241,232,0.45)";
          let shadow = "none";
          let transform = "scale(1)";
          if (active) { color = GOLD_LIGHT; shadow = `0 0 16px ${GOLD}, 0 0 30px rgba(245,158,11,0.7)`; transform = "scale(1.1)"; }
          else if (spoken) { color = CREAM; shadow = "0 2px 4px rgba(0,0,0,0.4)"; }
          return (
            <span key={i} style={{ fontFamily: FONT, fontSize: 36, fontWeight: active ? 800 : 700, color, textShadow: shadow, transform, margin: "0 2px", display: "inline-block", lineHeight: 1.35 }}>
              {sep + w.w}
            </span>
          );
        })}
      </div>
    </div>
  );
};

const Endcard: React.FC<{ t: number; fps: number }> = ({ t, fps }) => {
  const local = t - VO_END_SEC;
  const a = clamp01(local / 0.6);
  const s1 = springIn(Math.round((local - 0.3) * fps), fps, 18, 110);
  const s2 = springIn(Math.round((local - 0.9) * fps), fps, 18, 110);
  const s3 = springIn(Math.round((local - 1.6) * fps), fps, 18, 110);
  return (
    <div style={{ position: "absolute", inset: 0, zIndex: 100, opacity: a, background: NAVY, overflow: "hidden", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 22 }}>
      <div style={{ position: "absolute", inset: 0, opacity: 0.4 }}>
        <Footage src="gen_ident" from={1} beatStart={VO_END_SEC} beatEnd={TOTAL_DURATION_SEC} t={t} fps={fps} zoom={[1.08, 1.2]} />
      </div>
      <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 50% 40%, rgba(20,26,43,0.2), ${NAVY} 75%)` }} />
      <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "center", gap: 22 }}>
        <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 22, letterSpacing: 6, color: AMBER, opacity: s1 }}>{EPISODE.endcard.eyebrow}</div>
        <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 84, color: CREAM, lineHeight: 1.05, textAlign: "center", opacity: s1, transform: `translateY(${(1 - s1) * 20}px)` }}>
          {EPISODE.endcard.titleA}
          <span style={{ color: CREAM_DIM, fontWeight: 700 }}> & </span>
          {EPISODE.endcard.titleB}
        </div>
        <div style={{ width: 160 * s1, height: 5, background: `linear-gradient(90deg, ${CLAY}, ${AMBER})`, borderRadius: 3 }} />
        <div style={{ fontFamily: FONT, fontWeight: 700, fontSize: 28, color: CREAM_DIM, opacity: s2, transform: `translateY(${(1 - s2) * 14}px)` }}>
          {EPISODE.endcard.sub}
        </div>
        <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 40, color: NAVY, background: AMBER, padding: "10px 34px", borderRadius: 18, opacity: s2, transform: `translateY(${(1 - s2) * 14}px)`, boxShadow: `0 16px 40px rgba(242,179,76,0.35)` }}>
          {EPISODE.endcard.cta}
        </div>
        <div style={{ marginTop: 26, fontFamily: FONT, fontWeight: 700, fontSize: 26, color: CREAM, background: "rgba(245,241,232,0.08)", border: "1.5px solid rgba(245,241,232,0.2)", padding: "10px 26px", borderRadius: 16, opacity: s3, transform: `translateY(${(1 - s3) * 14}px)` }}>
          {EPISODE.endcard.next}
        </div>
      </div>
    </div>
  );
};

// ===========================================================================
// Avatar layer — the same take, re-sequenced per timeline segment
// ===========================================================================
const AvatarLayer: React.FC<{ p: number; fps: number }> = ({ p, fps }) => {
  const cardX = interpolate(p, [0, 1], [0, AV.x]);
  const cardY = interpolate(p, [0, 1], [0, AV.y]);
  const cardW = interpolate(p, [0, 1], [W, AV.w]);
  const cardH = interpolate(p, [0, 1], [H, AV.h]);
  const radius = interpolate(p, [0, 1], [0, AV.r]);
  const scale = interpolate(p, [0, 1], [1, AV.h / 1080]);
  const cx = interpolate(p, [0, 1], [960, AV_CX]);
  const cy = interpolate(p, [0, 1], [540, AV_CY]);
  const innerLeft = -(cx - cardW / scale / 2) * scale;
  const innerTop = -(cy - cardH / scale / 2) * scale;
  const segs = [...SEG.teaser, SEG.main];
  return (
    <div
      style={{
        position: "absolute", left: cardX, top: cardY, width: cardW, height: cardH,
        borderRadius: radius, overflow: "hidden", zIndex: 30, backgroundColor: NAVY,
        border: p > 0.2 ? `2px solid rgba(245,241,232,${0.16 * p})` : "none",
        boxShadow: p > 0.2 ? `0 30px 80px rgba(0,0,0,${0.6 * p}), 0 0 40px rgba(242,179,76,${0.18 * p})` : "none",
      }}
    >
      <div style={{ position: "absolute", left: innerLeft, top: innerTop, width: 1920 * scale, height: 1080 * scale }}>
        {segs.map((seg, i) => (
          <Sequence key={i} from={Math.round(seg.dst * fps)} durationInFrames={Math.round(seg.dur * fps) + (i === segs.length - 1 ? 10 : 0)} layout="none">
            <OffthreadVideo muted src={staticFile(`${EPISODE.assetDir}/avatar_source.mp4`)} startFrom={Math.round(seg.src * fps)} style={{ width: "100%", height: "100%" }} />
          </Sequence>
        ))}
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 300, background: "linear-gradient(180deg, transparent, rgba(11,14,23,0.55))", opacity: 1 - p, pointerEvents: "none" }} />
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 120, background: "linear-gradient(180deg, transparent, rgba(11,14,23,0.35))", opacity: p, pointerEvents: "none" }} />
    </div>
  );
};

// ===========================================================================
// Root composition
// ===========================================================================
export type FuguNewsYTV2Props = { durationSec?: number };

export const calculateFuguNewsYTV2Metadata: CalculateMetadataFunction<FuguNewsYTV2Props> = ({ props }) => {
  const fps = 25;
  const durationSec = props.durationSec || TOTAL_DURATION_SEC;
  return { durationInFrames: Math.ceil(durationSec * fps), fps, width: W, height: H };
};

export const FuguNewsYTV2: React.FC<FuguNewsYTV2Props> = ({ durationSec = TOTAL_DURATION_SEC }) => {
  useThaiFonts();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const totalFrames = Math.ceil(durationSec * fps);

  let beatIdx = 0;
  for (let i = 0; i < BEATS.length; i++) if (t >= BEATS[i].t) beatIdx = i;
  const beat = BEATS[beatIdx];
  const beatEndOf = (i: number) => (i + 1 < BEATS.length ? BEATS[i + 1].t : VO_END_SEC);
  const isSting = beat.typo === "sting";

  const p = pipProgress(t);
  const stageOpacity = interpolate(p, [0, 0.6, 1], [0, 0.9, 1]);
  const stageSlide = interpolate(p, [0, 1], [-40, 0]);
  const showEndcard = t >= VO_END_SEC;
  const bgDrift = Math.sin(t * 0.25) * 30;

  return (
    <div style={{ width: W, height: H, position: "relative", overflow: "hidden", backgroundColor: NAVY, fontFamily: FONT }}>
      {/* ===== backdrop ===== */}
      <div style={{ position: "absolute", inset: 0, background: `linear-gradient(180deg, ${NAVY_2} 0%, ${NAVY} 100%)` }} />
      <div style={{ position: "absolute", inset: 0, backgroundImage: "radial-gradient(rgba(245,241,232,0.075) 1.2px, transparent 1.2px)", backgroundSize: "28px 28px", opacity: stageOpacity }} />
      <div style={{ position: "absolute", left: -200 + bgDrift, top: -260, width: 900, height: 900, borderRadius: "50%", background: `radial-gradient(circle, rgba(242,179,76,0.16), transparent 62%)`, opacity: stageOpacity }} />
      <div style={{ position: "absolute", right: -260 - bgDrift, bottom: -380, width: 1000, height: 1000, borderRadius: "50%", background: `radial-gradient(circle, rgba(217,119,87,0.16), transparent 62%)`, opacity: stageOpacity }} />

      {/* ===== LEFT STAGE ===== */}
      <div
        style={{
          position: "absolute", left: STAGE.x + stageSlide, top: STAGE.y, width: STAGE.w, height: STAGE.h,
          borderRadius: STAGE.r, overflow: "hidden", opacity: stageOpacity, zIndex: 10,
          background: NAVY_2, border: "1px solid rgba(245,241,232,0.14)",
          boxShadow: "0 30px 80px rgba(0,0,0,0.55), 0 0 0 1px rgba(0,0,0,0.4)",
        }}
      >
        {BEATS.map((b, i) => {
          if (b.mode !== "pip" || !b.media || b.media === "none") return null;
          const bStart = b.t;
          const bEnd = beatEndOf(i);
          if (t < bStart || t >= bEnd + 0.45) return null;
          const fadeIn = clamp01((t - bStart) / 0.35);
          const prev = i > 0 ? BEATS[i - 1] : null;
          const stamp = b.media === "web" && (!prev || prev.media !== "web");
          return (
            <div key={`m${i}`} style={{ position: "absolute", inset: 0, opacity: fadeIn, zIndex: i }}>
              {b.media === "web" ? (
                <>
                  <BrowserChrome />
                  <WebStage beat={b} t={t} fps={fps} stamp={stamp} />
                </>
              ) : null}
              {b.media === "broll" ? <FootageStage beat={b} beatEnd={bEnd} t={t} fps={fps} /> : null}
              {b.media === "clip" ? <ClipStage beat={b} beatEnd={bEnd} t={t} fps={fps} /> : null}
              {b.media === "typo" ? <TypoStage beat={b} beatEnd={bEnd} t={t} fps={fps} /> : null}
              {b.media === "explain" ? <ExplainStage beat={b} beatEnd={bEnd} t={t} fps={fps} /> : null}
              {b.media === "chart" ? <ChartStage beat={b} beatEnd={bEnd} t={t} fps={fps} /> : null}
              {b.media === "terminal" ? <TerminalStage beat={b} beatEnd={bEnd} t={t} fps={fps} /> : null}
            </div>
          );
        })}
      </div>

      {!showEndcard && beat.mode === "pip" ? <StatChips beat={beat} t={t} fps={fps} /> : null}
      {!showEndcard && beat.mode === "pip" ? <GlossChip beat={beat} t={t} fps={fps} /> : null}

      {/* ===== AVATAR ===== */}
      <AvatarLayer p={p} fps={fps} />

      {/* ===== Overlays ===== */}
      {!showEndcard && !isSting ? <TopBar beat={beat} t={t} fps={fps} p={p} /> : null}
      {!showEndcard ? <LowerThird beat={beat} t={t} fps={fps} /> : null}
      {!showEndcard && beat.mode === "full" ? <NextChips beat={beat} beatEnd={beatEndOf(beatIdx)} t={t} fps={fps} /> : null}
      <CtaChip t={t} fps={fps} />
      {isSting ? <StingScreen beat={beat} t={t} fps={fps} beatEnd={beatEndOf(beatIdx)} /> : null}
      <ProgressBar totalFrames={totalFrames} />
      <CaptionLane t={t} fps={fps} hidden={isSting} />
      {showEndcard ? <Endcard t={t} fps={fps} /> : null}
    </div>
  );
};

// ===========================================================================
// Thumbnail composition (1 frame) — variants A/B/C for YouTube "Test & compare"
// ===========================================================================
export type FuguNewsThumbProps = { variant?: string; avatarSec?: number };
export const FuguNewsThumb: React.FC<FuguNewsThumbProps> = ({ variant = "A", avatarSec = 3.0 }) => {
  useThaiFonts();
  const { fps } = useVideoConfig();
  const th = EPISODE.thumbs.find((x) => x.id === variant) ?? EPISODE.thumbs[0];
  const card = { x: 1290, y: 40, w: 590, h: 1000, r: 30 };
  const scale = card.h / 1080;
  const innerLeft = -(AV_CX - card.w / scale / 2) * scale;
  const innerTop = -(540 - card.h / scale / 2) * scale;
  const accent = tone(th.accentTone);
  return (
    <div style={{ width: W, height: H, position: "relative", overflow: "hidden", backgroundColor: NAVY, fontFamily: FONT }}>
      <div style={{ position: "absolute", inset: 0, background: `linear-gradient(180deg, ${NAVY_2} 0%, ${NAVY} 100%)` }} />
      <div style={{ position: "absolute", inset: 0, backgroundImage: "radial-gradient(rgba(245,241,232,0.075) 1.2px, transparent 1.2px)", backgroundSize: "28px 28px" }} />
      <div style={{ position: "absolute", left: -260, top: -300, width: 1100, height: 1100, borderRadius: "50%", background: `radial-gradient(circle, rgba(242,179,76,0.22), transparent 62%)` }} />
      <div style={{ position: "absolute", right: -300, bottom: -420, width: 1100, height: 1100, borderRadius: "50%", background: `radial-gradient(circle, rgba(217,119,87,0.22), transparent 62%)` }} />
      <div style={{ position: "absolute", left: 80, top: 64, display: "flex", alignItems: "center", gap: 14 }}>
        <div style={{ width: 16, height: 16, borderRadius: 8, background: CLAY, boxShadow: `0 0 14px ${CLAY}` }} />
        <div style={{ fontFamily: FONT, fontWeight: 800, fontSize: 34, letterSpacing: 6, color: CREAM }}>{EPISODE.brand}</div>
      </div>
      <div style={{ position: "absolute", left: 80, top: 250, width: 1160 }}>
        {th.lines.map((l, i) => (
          <div key={i} style={{ fontFamily: FONT, fontWeight: 800, fontSize: 132, lineHeight: 1.06, color: i === 1 ? AMBER : CREAM, textShadow: "0 10px 40px rgba(0,0,0,0.6)" }}>{l}</div>
        ))}
        <div style={{ display: "inline-block", marginTop: 34, fontFamily: FONT, fontWeight: 800, fontSize: 56, color: NAVY, background: accent, padding: "10px 34px", borderRadius: 22, boxShadow: `0 20px 50px ${accent}55` }}>{th.accent}</div>
      </div>
      <div style={{ position: "absolute", left: card.x, top: card.y, width: card.w, height: card.h, borderRadius: card.r, overflow: "hidden", border: "3px solid rgba(245,241,232,0.22)", boxShadow: `0 40px 100px rgba(0,0,0,0.65), 0 0 60px rgba(242,179,76,0.25)`, background: NAVY }}>
        <div style={{ position: "absolute", left: innerLeft, top: innerTop, width: 1920 * scale, height: 1080 * scale }}>
          <Sequence from={0} durationInFrames={2} layout="none">
            <OffthreadVideo muted src={staticFile(`${EPISODE.assetDir}/avatar_source.mp4`)} startFrom={Math.round(avatarSec * fps)} style={{ width: "100%", height: "100%" }} />
          </Sequence>
        </div>
      </div>
    </div>
  );
};
