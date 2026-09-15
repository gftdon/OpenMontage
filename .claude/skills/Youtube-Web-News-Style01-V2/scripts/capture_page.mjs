// Config-driven Playwright capture of a real web page for the Web-News format.
//
//   node capture_page.mjs config.json
//
// Produces, in config.outDir:
//   sec_<name>.png        one PNG per section (CSS px clip @ DPR 2)
//   <carousel>_NN.png     one PNG per carousel item (optional)
//   <tabs.name>_N.png     one PNG per tab state (optional)
//   web_data.json         clips + rects (rects RELATIVE to their section clip)
//   videos.json           <video> sources on the page (optional download)
// and writes config.tsOut = a TS module exporting WEB_CLIPS / WEB_RECTS for the
// Remotion composition. Everything (clips + rects) is measured in ONE page load
// because the page height varies slightly between loads.
//
// Config schema (see ../assets/capture-config.example.json):
// {
//   "url": "...", "viewport": 1100, "dpr": 2, "outDir": "...", "tsOut": "...",
//   "hideSelectors": ["[class*=\"Consent\"]"],
//   "sections": [ { "name": "hero", "y": 0, "h": 840 },
//                 { "name": "intro", "anchor": "We're introducing", "offset": -40, "h": 1080, "anchorSelector": "h1,h2,p,strong",
//                   "phrases": { "intro_price": "cost an estimated 25% less", "efs": ["Enterprise Frontier Safeguards", 1] } } ],
//   "tables": [ { "name": "table", "section": "table", "selector": "table" } ],
//   "tabs": [ { "name": "chart", "buttonSelector": "button[class*=\"ViewSwitcher\"]",
//               "labels": ["Agentic coding", "..."], "minHeight": 500 } ],
//   "carousel": { "name": "quotes", "nextSelector": "button[class*=\"pagination-button\"]", "nextText": "Next",
//                 "h": 340, "items": [ { "index": 2, "phrases": { "q_million": "about one in a million runs" } } ] },
//   "downloadVideosTo": "projects/<slug>/assets/broll"   (optional)
// }
import fs from 'fs';
import path from 'path';
import { execSync } from 'child_process';
import { loadPlaywright } from './_pw.mjs';

const cfgPath = process.argv[2];
if (!cfgPath) { console.error('usage: node capture_page.mjs config.json'); process.exit(1); }
const cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
const VW = cfg.viewport || 1100;
const OUT = cfg.outDir;
fs.mkdirSync(OUT, { recursive: true });

const { chromium } = await loadPlaywright();
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: VW, height: 900 }, deviceScaleFactor: cfg.dpr || 2 });
const page = await ctx.newPage();
await page.goto(cfg.url, { waitUntil: cfg.waitUntil || 'networkidle', timeout: 120000 });
await page.waitForTimeout(1500);
for (const sel of cfg.hideSelectors || []) await page.addStyleTag({ content: `${sel}{display:none!important}` });
// scroll the whole page once: lazy charts / reveal animations only render in view
const H = await page.evaluate(() => document.documentElement.scrollHeight);
for (let y = 0; y < H; y += 600) { await page.evaluate((yy) => window.scrollTo(0, yy), y); await page.waitForTimeout(100); }
await page.evaluate(() => window.scrollTo(0, 0)); await page.waitForTimeout(1000);

await page.evaluate(() => {
  const clean = (c) => c.replace(/[‘’]/g, "'").replace(/[“”]/g, '"').replace(/[–—‑‐−]/g, '-');
  // Bounding box of the nth occurrence of a phrase, searched over the page's text
  // nodes (footer excluded). Whitespace is collapsed and typographic quotes /
  // dashes (incl. U+2011 non-breaking hyphen) normalised on both sides.
  window.__findRect = (phrase, nth = 0) => {
    const target = clean(phrase.replace(/\s+/g, ' ').replace(/ /g, ' '));
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, { acceptNode: (n) => (n.parentElement && !['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(n.parentElement.tagName) && n.parentElement.closest('footer') == null) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT });
    const nodes = []; let n; while ((n = walker.nextNode())) nodes.push(n);
    let raw = ''; const map = [];
    for (const nd of nodes) { for (let i = 0; i < nd.nodeValue.length; i++) map.push([nd, i]); raw += nd.nodeValue; }
    const nmap = []; let out = ''; let prevSpace = false;
    for (let i = 0; i < raw.length; i++) {
      let c = raw[i];
      if (/\s/.test(c) || c === ' ') { if (prevSpace) continue; c = ' '; prevSpace = true; } else prevSpace = false;
      out += clean(c); nmap.push(i);
    }
    let idx = -1, from = 0, hit = 0;
    while (true) { idx = out.indexOf(target, from); if (idx < 0) break; if (hit === nth) break; hit++; from = idx + 1; }
    if (idx < 0) return null;
    const [sn, so] = map[nmap[idx]]; const [en, eo] = map[nmap[idx + target.length - 1]];
    const r = document.createRange(); r.setStart(sn, so); r.setEnd(en, eo + 1);
    const rects = [...r.getClientRects()].filter((q) => q.width > 0);
    if (!rects.length) return null;
    const x0 = Math.min(...rects.map((q) => q.left)), x1 = Math.max(...rects.map((q) => q.right));
    const y0 = Math.min(...rects.map((q) => q.top)), y1 = Math.max(...rects.map((q) => q.bottom));
    return { x: +x0.toFixed(1), y: +(y0 + window.scrollY).toFixed(1), w: +(x1 - x0).toFixed(1), h: +(y1 - y0).toFixed(1) };
  };
  // Anchor = first element (default: headings / paragraphs / bold leads) whose text
  // starts with the given words. Quotes/dashes normalised (pages use curly ’).
  // Keep the selector narrow: adding `li`/`a` matches table-of-contents entries.
  window.__anchor = (t, selector = 'h1,h2,p,strong') => { const T = clean(t.replace(/\s+/g, ' ')); const el = [...document.querySelectorAll(selector)].find((e) => e.innerText && clean(e.innerText.trim().replace(/\s+/g, ' ')).startsWith(T)); return el ? el.getBoundingClientRect().top + window.scrollY : null; };
});

const clips = {}; const rel = {};
const shot = async (file, y, h) => {
  await page.evaluate((yy) => window.scrollTo(0, Math.max(0, yy - 200)), y);
  await page.waitForTimeout(450);
  await page.screenshot({ path: path.join(OUT, file), fullPage: true, clip: { x: 0, y, width: VW, height: h } });
};
const addRects = async (section, phrases) => {
  for (const [key, spec] of Object.entries(phrases || {})) {
    const [text, nth] = Array.isArray(spec) ? spec : [spec, 0];
    const r = await page.evaluate(([p, n]) => window.__findRect(p, n), [text, nth]);
    if (!r) { console.log('MISS', key, JSON.stringify(text)); continue; }
    rel[key] = { x: r.x, y: +(r.y - clips[section].y).toFixed(1), w: r.w, h: r.h };
  }
};

// ---- sections ------------------------------------------------------------
for (const s of cfg.sections || []) {
  let y = s.y ?? 0;
  if (s.anchor) { const a = await page.evaluate(([t, sel]) => window.__anchor(t, sel), [s.anchor, s.anchorSelector || 'h1,h2,p,strong']); if (a == null) { console.log('ANCHOR MISS', s.name, s.anchor); continue; } y = Math.round(a + (s.offset ?? -40)); }
  clips[s.name] = { y, h: s.h };
  await addRects(s.name, s.phrases);
  await shot(`sec_${s.name}.png`, y, s.h);
  console.log('section', s.name, JSON.stringify(clips[s.name]), Object.keys(s.phrases || {}).length, 'phrases');
}

// ---- tables: row / column rects (relative to their section) ---------------
for (const t of cfg.tables || []) {
  const info = await page.evaluate((sel) => { const tb = document.querySelector(sel); if (!tb) return null; const rows = [...tb.querySelectorAll('tr')].map((tr) => { const r = tr.getBoundingClientRect(); return { text: tr.innerText.replace(/\s+/g, ' ').trim().slice(0, 60), x: r.x, y: r.y + window.scrollY, w: r.width, h: r.height }; }).filter((r) => r.w > 0); const cols = [...tb.querySelectorAll('tr:first-child th, tr:first-child td')].map((c) => { const r = c.getBoundingClientRect(); return { text: c.innerText.trim(), x: r.x, w: r.width }; }); const tr = tb.getBoundingClientRect(); return { rows, cols, box: { x: tr.x, y: tr.y + window.scrollY, w: tr.width, h: tr.height } }; }, t.selector || 'table');
  if (!info || !clips[t.section]) { console.log('TABLE MISS', t.name); continue; }
  const cy = clips[t.section].y;
  rel[`${t.name}_box`] = { x: info.box.x, y: +(info.box.y - cy).toFixed(1), w: info.box.w, h: info.box.h };
  info.rows.forEach((r, i) => { rel[`${t.name}_row${i}`] = { x: r.x, y: +(r.y - cy).toFixed(1), w: r.w, h: r.h, text: r.text }; });
  info.cols.forEach((c, i) => { rel[`${t.name}_col${i}`] = { x: c.x, y: 0, w: c.w, h: 0, text: c.text }; });
  console.log('table', t.name, info.rows.length, 'rows', info.cols.length, 'cols');
}

// ---- tabbed widgets (charts) ---------------------------------------------
for (const tb of cfg.tabs || []) {
  for (let i = 0; i < tb.labels.length; i++) {
    const btn = page.locator(tb.buttonSelector, { hasText: tb.labels[i] }).first();
    try { await btn.scrollIntoViewIfNeeded(); await btn.click({ force: true }); } catch (e) { console.log('TAB MISS', tb.labels[i]); continue; }
    await page.waitForTimeout(tb.waitMs || 2000);
    const box = await btn.evaluate((b, minH) => { let el = b.parentElement; while (el && el.getBoundingClientRect().height < minH) el = el.parentElement; const r = el.getBoundingClientRect(); return { y: r.y + window.scrollY, h: r.height }; }, tb.minHeight || 500);
    const y = Math.round(box.y - 10), h = Math.min(Math.round(box.h + 20), 1400);
    clips[`${tb.name}_${i}`] = { y, h };
    await page.screenshot({ path: path.join(OUT, `${tb.name}_${i}.png`), fullPage: true, clip: { x: 0, y, width: VW, height: h } });
    console.log('tab', tb.name, i, tb.labels[i], JSON.stringify(clips[`${tb.name}_${i}`]));
  }
}

// ---- carousel (e.g. customer quotes) --------------------------------------
if (cfg.carousel) {
  const c = cfg.carousel;
  const nextBtn = page.locator(c.nextSelector, c.nextText ? { hasText: c.nextText } : {}).first();
  await nextBtn.scrollIntoViewIfNeeded();
  const box = await nextBtn.evaluate((n, minH) => { let el = n; while (el && el.getBoundingClientRect().height < minH) el = el.parentElement; const r = el.getBoundingClientRect(); return { y: r.y + window.scrollY, h: r.height }; }, c.minHeight || 250);
  clips[c.name] = { y: Math.round(box.y), h: c.h || Math.round(box.h) };
  let cur = 0;
  const items = [...(c.items || [])].sort((a, b) => a.index - b.index);
  for (const it of items) {
    while (cur < it.index) { await nextBtn.click({ force: true }); await page.waitForTimeout(c.waitMs || 700); cur++; }
    await page.evaluate((yy) => window.scrollTo(0, yy - 150), clips[c.name].y); await page.waitForTimeout(450);
    await addRects(c.name, it.phrases);
    await page.screenshot({ path: path.join(OUT, `${c.name}_${String(it.index).padStart(2, '0')}.png`), fullPage: true, clip: { x: 0, y: clips[c.name].y, width: VW, height: clips[c.name].h } });
    const txt = await page.evaluate(() => (document.body.innerText.match(/(\d+) of \d+/) || [''])[0]);
    console.log('carousel item', it.index, txt);
  }
}

// ---- videos on the page ----------------------------------------------------
const vids = await page.evaluate(() => [...document.querySelectorAll('video')].map((v) => ({ src: v.currentSrc || v.src, poster: v.poster, w: v.videoWidth, h: v.videoHeight, y: v.getBoundingClientRect().top + window.scrollY })));
fs.writeFileSync(path.join(OUT, 'videos.json'), JSON.stringify(vids, null, 1));
if (cfg.downloadVideosTo) {
  fs.mkdirSync(cfg.downloadVideosTo, { recursive: true });
  vids.forEach((v, i) => { if (!v.src) return; const ext = (v.src.split('?')[0].split('.').pop() || 'mp4').slice(0, 4); const f = path.join(cfg.downloadVideosTo, `page_video_${i}.${ext}`); try { execSync(`curl -sL -o "${f}" "${v.src}"`); console.log('downloaded', f); } catch (e) { console.log('download failed', v.src); } });
}

fs.writeFileSync(path.join(OUT, 'web_data.json'), JSON.stringify({ clips, rel }, null, 1));
if (cfg.tsOut) {
  let ts = `// AUTO-GENERATED by capture_page.mjs — captures (CSS px @ viewport ${VW}, DPR ${cfg.dpr || 2}) + phrase rects relative to each clip\n`;
  ts += 'export interface WebRect { x: number; y: number; w: number; h: number; text?: string }\n';
  ts += 'export const WEB_CLIPS: Record<string, { y: number; h: number }> = ' + JSON.stringify(clips) + ';\n';
  ts += 'export const WEB_RECTS: Record<string, WebRect> = ' + JSON.stringify(rel) + ';\n';
  fs.mkdirSync(path.dirname(cfg.tsOut), { recursive: true });
  fs.writeFileSync(cfg.tsOut, ts);
  console.log('wrote', cfg.tsOut, Object.keys(clips).length, 'clips', Object.keys(rel).length, 'rects');
}
await browser.close();
