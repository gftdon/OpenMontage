import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
const root=path.resolve(new URL('../../../../..',import.meta.url).pathname);
const source=fs.readFileSync(path.join(root,'remotion-composer/src/YtNewsStyle01V4.tsx'),'utf8');
const sampleBeats=JSON.parse(fs.readFileSync(path.join(root,'remotion-composer/src/ytNewsStyle01V4Sample.json'),'utf8')).beats;
test('primary typography waits for full-avatar morph, then keeps bounded entrance',()=>{
 assert.match(source.split("\n").find(line=>line.includes("const typoEntranceStart"))??"",/const typoEntranceStart=Math\.max\(typoCard\?\.t\?\?beat\.t,beat\.t\+\(previous\.mode==="full"\?MODE_BLEND_SEC:0\)\)/);
 assert.match(source.split("\n").find(line=>line.includes("beat.media===\"typo\"&&<div"))??"",/beat\.media==="typo"[^\n]+boundedEntrance\(t,typoEntranceStart,fps\)/);
 assert.match(source,/const MODE_BLEND_SEC = 0\.55;/);
 assert.match(source,/const stageMotion=\{opacity:clamp01\(\(t-beat\.t\)\/\.35\)/);
});
test('actual failing frames precede morph completion, later cards do not replay initial delay',()=>{
 const duration=Number(source.match(/const MODE_BLEND_SEC = ([\d.]+);/)[1]);
 const beats=sampleBeats;
 for(const frame of [1870,2870,3594]){
  const index=beats.findLastIndex(b=>frame/25>=b.t);const beat=beats[index];
  assert.equal(beat.media,'typo');assert.equal(beats[index-1].mode,'full');
  assert.ok(frame/25<beat.t+duration);
 }
 for(const beat of beats.filter(b=>b.media==='typo')){
  for(const card of beat.cards??[]){
   const entrance=Math.max(card.t,beat.t+duration);
   if(card.t>=beat.t+duration)assert.equal(entrance,card.t);
  }
 }
});
