import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
const root=path.resolve(new URL('../../../../..',import.meta.url).pathname);
const source=fs.readFileSync(path.join(root,'remotion-composer/src/YtNewsStyle01V4.tsx'),'utf8');
const lines=source.split('\n');
const beats=JSON.parse(fs.readFileSync(path.join(root,'remotion-composer/src/ytNewsStyle01V4Sample.json'),'utf8')).beats;
test('headline backing and text share bounded entrance only for full-to-pip morph',{skip:"rewritten in CF-A66 step 3 (transitions)"},()=>{
 assert.match(lines.find(l=>l.includes('const panelEntranceStart'))??'',/const panelEntranceStart=beat\.t\+\(delayPanelEntrance\?MODE_BLEND_SEC:0\)/);
 const panel=lines.find(l=>l.includes('gap:6,background:full?'))??'';
 assert.ok(panel.includes('...(delayPanelEntrance?boundedEntrance(t,panelEntranceStart,fps):{})'),'whole backing wrapper waits; existing nontransition style unchanged');
 assert.ok((lines.find(l=>l.includes('activeStats.map'))??'').includes('boundedEntrance(t,Math.max(st.t,panelEntranceStart),fps)'));
});
test('all full-to-pip transitions wait .55s, later stats and nontransitions unchanged',{skip:"rewritten in CF-A66 step 3 (transitions)"},()=>{
 const delay=Number(source.match(/const MODE_BLEND_SEC = ([\d.]+);/)[1]);
 let count=0;
 for(let i=1;i<beats.length;i++){
  const beat=beats[i],previous=beats[i-1],affected=previous.mode==='full'&&beat.mode!=='full';
  const start=beat.t+(affected?delay:0);
  if(affected){count++;assert.ok(start>beat.t+.3);}
  else assert.equal(start,beat.t);
  for(const st of beat.stats??[])assert.equal(Math.max(st.t,start),affected?Math.max(st.t,beat.t+delay):st.t);
 }
 assert.ok(count>=12);
 const beat=beats.find(b=>b.t===88.62);
 for(const frame of [2220,2225])assert.ok(frame/25<beat.t+delay);
});
test('provenance credit chrome and AI label keep original timing',{skip:"rewritten in CF-A66 step 3 (transitions)"},()=>{
 for(const marker of ['data-qc-credit','data-qc-chrome','beat.origin==="ai"&&<div']){
  const line=lines.find(l=>l.includes(marker))??'';assert.ok(line);assert.ok(!line.includes('panelEntranceStart'));
 }
});

test('source chrome background fits measured URL instead of full-width bar',{skip:"rewritten in CF-A66 step 3 (transitions)"},()=>{
 const chrome=lines.find(l=>l.includes('source&&beat.chrome&&<div'))??'';
 assert.ok(chrome.includes('width:"max-content"'));assert.ok(chrome.includes('maxWidth:full?1688:1190'));
 assert.ok(!chrome.includes('right:full?116:614'));
});

test('shared panel guard includes fadeout, excludes reverse and unchanged pip',{skip:"rewritten in CF-A66 step 3 (transitions)"},()=>{
 assert.ok(source.includes('const delayPanelEntrance=(previous.mode==="full"&&beat.mode!=="full")||from.opacity>to.opacity;'));
 const delay=(previous,beat,from,to)=>(previous.mode==="full"&&beat.mode!=="full")||from.opacity>to.opacity;
 assert.equal(delay({mode:"pip"},{mode:"pip"},{opacity:1},{opacity:0}),true);
 assert.equal(delay({mode:"pip"},{mode:"pip"},{opacity:0},{opacity:1}),false);
 assert.equal(delay({mode:"pip"},{mode:"pip"},{opacity:1},{opacity:1}),false);
 assert.equal(delay({mode:"full"},{mode:"pip"},{opacity:1},{opacity:1}),true);
});
