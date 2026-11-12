import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { loadEngine } from './_engine_bundle.mjs';

const { LANES } = await loadEngine();
const doc = JSON.parse(fs.readFileSync(new URL('../../assets/yt-news-v4-lanes.json', import.meta.url), 'utf8'));

test('lanes json header', () => {
  assert.equal(doc.schema, 'yt-news-v4-lanes');
  assert.equal(doc.version, 1);
  assert.equal(doc.width, 1920);
  assert.equal(doc.height, 1080);
  assert.equal(doc.fps, 25);
});

test('lanes json has exactly the engine LANES ids', () => {
  assert.deepEqual(Object.keys(doc.lanes).sort(), Object.keys(LANES).sort());
});

test('every lane number equals the engine LANES (r is omitted when 0)', () => {
  for (const [id, l] of Object.entries(LANES)) {
    const j = doc.lanes[id];
    assert.ok(j, `${id} missing`);
    for (const k of ['x', 'y', 'w', 'h']) assert.equal(j[k], l[k], `${id}.${k}`);
    assert.equal(j.r ?? 0, l.r, `${id}.r`);
    assert.deepEqual(Object.keys(j).filter((k) => !['x', 'y', 'w', 'h', 'r'].includes(k)), [], `${id} has unknown keys`);
    if ('r' in j) assert.ok(j.r > 0, `${id}.r must be omitted when 0`);
  }
});

test('the per-scene maps reference existing lanes valid for that scene', () => {
  const maps = { pictureLaneByScene: doc.pictureLaneByScene, cardLaneByScene: doc.cardLaneByScene, presenterLaneByScene: doc.presenterLaneByScene };
  for (const [name, map] of Object.entries(maps)) {
    assert.ok(map && typeof map === 'object', name);
    for (const [scene, id] of Object.entries(map)) {
      assert.ok(['P', 'S', 'T', 'W'].includes(scene), `${name}: unknown scene ${scene}`);
      if (id === null) continue;
      assert.ok(Object.hasOwn(doc.lanes, id), `${name}.${scene} -> ${id} is not a lane`);
      assert.ok(LANES[id].scenes.includes(scene), `${name}.${scene} -> ${id} does not exist in scene ${scene}`);
    }
  }
  assert.deepEqual(Object.keys(doc.pictureLaneByScene).sort(), ['P', 'S', 'T', 'W']);
  assert.deepEqual(Object.keys(doc.presenterLaneByScene).sort(), ['P', 'S', 'T', 'W']);
});
