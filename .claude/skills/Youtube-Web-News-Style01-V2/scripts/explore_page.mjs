import { loadPlaywright } from './_pw.mjs';
const { chromium } = await loadPlaywright();
// usage: node explore_page.mjs <url>
const URL_ARG = process.argv[2];
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1100, height: 900 } });
await page.goto(URL_ARG, { waitUntil: 'networkidle', timeout: 90000 });
const info = await page.evaluate(() => {
  const vids = [...document.querySelectorAll('video')].map(v => ({ src: v.currentSrc || v.src, poster: v.poster, sources: [...v.querySelectorAll('source')].map(s => s.src), w: v.videoWidth, h: v.videoHeight, rect: v.getBoundingClientRect().toJSON() }));
  const btns = [...document.querySelectorAll('button')].map(b => ({ text: b.innerText.trim().slice(0, 40), aria: b.getAttribute('aria-label'), cls: b.className.slice(0, 80) })).filter(b => b.text || b.aria);
  const h2 = [...document.querySelectorAll('h1,h2,h3')].map(h => ({ tag: h.tagName, text: h.innerText.trim().slice(0, 80), y: h.getBoundingClientRect().top + window.scrollY }));
  const imgs = [...document.querySelectorAll('img')].map(i => ({ src: (i.currentSrc || i.src).slice(0, 160), alt: i.alt.slice(0, 60), w: i.naturalWidth, h: i.naturalHeight, y: i.getBoundingClientRect().top + window.scrollY })).filter(i => i.w > 300);
  const tabs = [...document.querySelectorAll('[role=tab]')].map(t => t.innerText.trim());
  return { vids, btns, h2, imgs, tabs, height: document.documentElement.scrollHeight };
});
console.log(JSON.stringify(info, null, 1));
await browser.close();
