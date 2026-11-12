import test from 'node:test';
import assert from 'node:assert/strict';
import { loadEngine } from './_engine_bundle.mjs';

const { srcCropStyle } = await loadEngine();
const close = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-6, `${msg}: ${a} vs ${b}`);
const BOXES = [{ w: 1138, h: 640 }, { w: 1280, h: 720 }];

test('with a crop: cover scale s = max(bw/C.w, bh/C.h), formulas of spec section 6', () => {
  for (const box of BOXES) for (const C of [{ x: 240, y: 135, w: 1440, h: 810 }, { x: 160, y: 90, w: 1600, h: 900 }, { x: 0, y: 0, w: 1920, h: 1080 }, { x: 100, y: 100, w: 1000, h: 700 }]) {
    const s = Math.max(box.w / C.w, box.h / C.h), st = srcCropStyle(C, box);
    assert.equal(st.position, 'absolute');
    assert.equal(st.objectFit, 'fill');
    close(st.width, 1920 * s, 'width'); close(st.height, 1080 * s, 'height');
    close(st.left, -C.x * s + (box.w - C.w * s) / 2, 'left'); close(st.top, -C.y * s + (box.h - C.h * s) / 2, 'top');
  }
});

test('with a crop the picture box is always fully covered by the source frame', () => {
  for (const box of BOXES) for (const C of [{ x: 240, y: 135, w: 1440, h: 810 }, { x: 160, y: 90, w: 1600, h: 900 }, { x: 0, y: 0, w: 1920, h: 1080 }, { x: 1280, y: 720, w: 640, h: 360 }]) {
    const st = srcCropStyle(C, box);
    assert.ok(st.left <= 1e-6 && st.top <= 1e-6 && st.left + st.width >= box.w - 1e-6 && st.top + st.height >= box.h - 1e-6, JSON.stringify(C));
  }
});

test('visible source region (no punch): R0 = {C.x+(C.w-bw/s)/2, C.y+(C.h-bh/s)/2, bw/s, bh/s}', () => {
  for (const box of BOXES) for (const C of [{ x: 240, y: 135, w: 1440, h: 810 }, { x: 160, y: 90, w: 1600, h: 900 }, { x: 100, y: 100, w: 1000, h: 700 }]) {
    const s = Math.max(box.w / C.w, box.h / C.h), st = srcCropStyle(C, box);
    const k = st.width / 1920; // px per source px actually drawn
    const region = { x: -st.left / k, y: -st.top / k, w: box.w / k, h: box.h / k };
    close(region.x, C.x + (C.w - box.w / s) / 2, 'x0'); close(region.y, C.y + (C.h - box.h / s) / 2, 'y0');
    close(region.w, box.w / s, 'w0'); close(region.h, box.h / s, 'h0');
  }
});

test('a crop with the box aspect shows exactly the crop rect', () => {
  const box = { w: 1280, h: 720 }, C = { x: 240, y: 135, w: 1440, h: 810 }, st = srcCropStyle(C, box), k = st.width / 1920;
  close(-st.left / k, 240, 'x'); close(-st.top / k, 135, 'y'); close(box.w / k, 1440, 'w'); close(box.h / k, 810, 'h');
});

test('without a crop the whole frame is cover-fitted and centred: the box is always completely filled (E3)', () => {
  for (const box of [...BOXES, { w: 1000, h: 800 }, { w: 1600, h: 600 }]) {
    const s = Math.max(box.w / 1920, box.h / 1080), st = srcCropStyle(undefined, box);
    assert.equal(st.objectFit, 'contain');
    close(st.width, 1920 * s, 'width'); close(st.height, 1080 * s, 'height');
    close(st.left, (box.w - 1920 * s) / 2, 'left'); close(st.top, (box.h - 1080 * s) / 2, 'top');
    assert.ok(st.left <= 1e-6 && st.top <= 1e-6 && st.left + st.width >= box.w - 1e-6 && st.top + st.height >= box.h - 1e-6, JSON.stringify(box));
  }
  const st = srcCropStyle(undefined, { w: 1280, h: 720 });
  close(st.left, 0, 'left'); close(st.top, 0, 'top'); close(st.width, 1280, 'width');
});

test('16:9 media in every picture lane (split.picture, wide.picture) covers the picture box exactly: no black sliver on any side', async () => {
  const { LANES } = await loadEngine();
  for (const id of ['split.picture', 'wide.picture']) {
    const box = { w: LANES[id].w, h: LANES[id].h }, st = srcCropStyle(undefined, box);
    assert.ok(st.left <= 1e-9, `${id} left edge ${st.left}`); assert.ok(st.top <= 1e-9, `${id} top edge ${st.top}`);
    assert.ok(st.left + st.width >= box.w - 1e-9, `${id} right edge ${st.left + st.width} < ${box.w}`);
    assert.ok(st.top + st.height >= box.h - 1e-9, `${id} bottom edge ${st.top + st.height} < ${box.h}`);
    assert.ok(st.width - box.w < 1 && st.height - box.h < 1, `${id} overflow ${st.width - box.w} x ${st.height - box.h}`);
  }
});
