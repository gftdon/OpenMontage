import test from 'node:test';
import assert from 'node:assert/strict';
import { evaluateLayout } from '../qc_layout_eval.mjs';
import { thresholds, v3Field, v3Snap, backingFor, permissiveCtx } from './fixtures/v3/builders.mjs';

const box = { x: 116, y: 186, width: 400, height: 40 };
const label = v3Field('ai-label', { tier: 'label', text: 'ภาพประกอบ AI', fontSize: 28, x: box.x, y: box.y, w: box.width, h: box.height });
label.backing = backingFor(label);
const s = v3Snap([label], { footage: { origin: 'ai', src: 'ai_concept', layout: 'full', credit: false, chrome: false } });
const codes = s => evaluateLayout(s, thresholds, permissiveCtx(s)).issues.map(i => i.code);

test('AI provenance requires label and full-footage backing without source attribution', () => {
  assert.deepEqual(codes(s), []);
  assert.ok(codes({ ...s, fields: [{ ...label, text: 'official UI' }] }).includes('ai-label'));
  assert.ok(codes({ ...s, fields: [{ ...label, backing: null }] }).includes('backing'));
  assert.ok(codes({ ...s, footage: { ...s.footage, credit: true } }).includes('ai-chrome'));
  assert.ok(codes({ ...s, footage: { ...s.footage, src: 'yt_fake' } }).includes('origin'));
});
test('a half-faded AI label backing no longer counts as a backing (alpha 1 * opacity .5)', () => {
  assert.ok(codes({ ...s, fields: [{ ...label, backing: { ...label.backing, opacity: 0.5 } }] }).includes('backing'));
});
