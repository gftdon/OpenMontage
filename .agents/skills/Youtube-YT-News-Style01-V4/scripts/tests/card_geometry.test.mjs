// The enlarged "card" typo variant (2-4 rows): title 76 px, rows 60 px, numbered amber badge, inner padding 26, row gap 22.
// It must fill >= 60 % of the typo.content lane (a 2-row card) and still fit inside it for 3 and 4 rows, with no text below
// the minimum sizes (read 38 px, label 30 px). The numbers are computed from the engine's own constants.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { enginePath, loadEngine } from './_engine_bundle.mjs';

const src = fs.readFileSync(enginePath, 'utf8');
const { LANES } = await loadEngine();
const num = name => Number(src.match(new RegExp(`${name} = (\\d+)`))?.[1]);

const CARD_TITLE_H = num('CARD_TITLE_H'), CARD_RULE_H = num('CARD_RULE_H'), CARD_PAD = num('CARD_PAD'), CARD_GAP = num('CARD_GAP'), CARD_ROW_PX = num('CARD_ROW_PX');
const margin = src.match(/CARD_RULE_MARGIN = "(\d+)px 0 (\d+)px"/);
const MARGIN = Number(margin[1]) + Number(margin[2]);
const LH = Object.fromEntries([...src.match(/const LH: Record<number, number> = \{([^}]*)\}/)[1].matchAll(/(\d+): (\d+)/g)].map(m => [m[1], Number(m[2])]));
const lane = LANES['typo.content'];

const ROW_LH = LH[CARD_ROW_PX];
const ROW_H = ROW_LH + 2 * CARD_PAD;                       // one line of row text + padding
const HEAD = LH[76] + MARGIN + CARD_RULE_H;                // title line + rule with its margins
const block = (rows, lines = 1) => HEAD + (rows <= 3 ? rows * ROW_H + (rows - 1) * CARD_GAP : 2 * (lines * ROW_LH + 2 * CARD_PAD) + CARD_GAP);

test('the final card sizes are in the source', () => {
  assert.equal(CARD_ROW_PX, 60); assert.equal(CARD_PAD, 26); assert.equal(CARD_GAP, 22);
  assert.match(src, /<TextField id="typo-title" lane="typo.content" size=\{76\}/);
  assert.match(src, /size=\{CARD_ROW_PX\}/);
  assert.match(src, /id=\{`typo-badge-\$\{i\}`\}[^>]*backgroundColor: AMBER/, 'numbered amber badge');
  assert.match(src, /id=\{`typo-num-\$\{i\}`\}[^>]*>\{i \+ 1\}</, 'badge shows the row number');
  assert.equal(LH[76], 98); assert.equal(ROW_LH, 82);
  assert.deepEqual([lane.w, lane.h], [1130, 676]);
});

test('a 2-row card fills >= 60 % of the content lane height (measured on the gate frames: 444 px = 65.7 %)', () => {
  assert.equal(block(2), 444);
  assert.ok(block(2) / lane.h >= 0.6, `${block(2) / lane.h}`);
});

test('3 rows (one column) and 4 rows (two columns, every row up to 2 lines) fit inside the lane', () => {
  assert.equal(block(3), 600); assert.ok(block(3) <= lane.h);
  assert.equal(block(4, 2), 608); assert.ok(block(4, 2) <= lane.h);
  assert.ok(block(4, 1) < block(4, 2));
  // what must not be possible: 4 rows stacked in one column (that is why 4 rows switch to two columns)
  assert.ok(HEAD + 4 * ROW_H + 3 * CARD_GAP > lane.h);
});

test('4 rows switch to two columns with wrapping; 1-3 rows stay on one line each', () => {
  assert.match(src, /const twoCols = \(card\?\.lines\.length \?\? 0\) > 3;/);
  assert.match(src, /gridTemplateColumns: twoCols \? "1fr 1fr" : "1fr"/);
  assert.match(src, /whiteSpace: twoCols \? "normal" : "nowrap"/);
});

test('no text in the card below the tier minimum (read 38 / label 30)', () => {
  const scene = src.slice(src.indexOf('const TypoScene'), src.indexOf('// ---- Overlays'));
  const card = scene.slice(scene.indexOf('variant === "card"'), scene.indexOf('variant === "summary3"'));
  for (const m of card.matchAll(/size=\{(\w+)\}/g)) assert.ok(Number(m[1] === 'CARD_ROW_PX' ? CARD_ROW_PX : m[1]) >= 38, `card text size ${m[1]}`);
  for (const m of scene.matchAll(/(role="label"[^>]*?size=\{(\d+)\})/g)) assert.ok(Number(m[2]) >= 30, `label size ${m[2]}`);
  assert.match(src, /const MIN_PX = \{ label: 30, read: 38 \} as const;/);
});
