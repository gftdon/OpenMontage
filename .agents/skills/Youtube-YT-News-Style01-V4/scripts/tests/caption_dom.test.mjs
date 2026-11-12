import test from 'node:test';
import assert from 'node:assert/strict';
import { evaluateLayout } from '../qc_layout_eval.mjs';
import { thresholds, v3Field, v3Snap, permissiveCtx } from './fixtures/v3/builders.mjs';

const box = { x: 116, y: 248, width: 500, height: 120 };
const caption = v3Field('caption', {
  text: 'คำจริง', fontSize: 36, box,
  rects: [{ x: 142, y: 310, width: 120, height: 40 }], inkRects: [{ x: 142, y: 310, width: 120, height: 40 }],
  captionBlankFirstLine: true, captionLineCount: 1,
});
const s = v3Snap([caption], { frame: 625, captionLane: 'top' });

test('measured blank first caption line is rejected even if pill fits safe area', () => {
  assert.ok(evaluateLayout(s, thresholds, permissiveCtx(s)).issues.some(i => i.code === 'caption-blank-line'));
});
test('without the blank line the same caption passes', () => {
  const clean = v3Snap([{ ...caption, captionBlankFirstLine: false }], { frame: 625, captionLane: 'top' });
  assert.deepEqual(evaluateLayout(clean, thresholds, permissiveCtx(clean)).issues, []);
});
