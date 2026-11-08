import test from 'node:test';
import assert from 'node:assert/strict';
import {buildCaptionPages as build, activeChunk, CAPTION_ALGORITHM_VERSION} from '../caption_join.mjs';
const buildCaptionPages=(tokens,script,options={})=>build(tokens,script,{endTime:tokens.at(-1)?.e,...options});
const timed = parts => parts.map((w,i)=>({w,s:i*.2,e:(i+1)*.2}));
const join = r => r.pages.map(p=>p.text).join('');
for (const [script,parts] of [
  ['เป็นการนำไปใช้ลงขายของ',['เป็นการ','นำไปใช้','ลง','ขายของ']],
  ['ความเร็วจุดนี้',['ความ','เร็ว','จุด','นี้']],
  ['บอกว่า',['บอ','กว่า']],
  ['บอกว่า',['บอก','ว่า']],
  ['GPT-Image-2.6 API 50% ราคา ๒๖ บาท!',['GPT-Image-2.6','API','50%','ราคา','๒๖','บาท!']],
  ['ใช้จริง  แล้วค่อยทำ\nภาพสวย ๆ',['ใช้','จริง','แล้ว','ค่อย','ทำ','ภาพ','สวย','ๆ']],
]) test(`lossless exact spacing: ${script}`,()=>{
  const r=buildCaptionPages(timed(parts),script,{maxUnits:20});
  assert.equal(join(r),script); assert.equal(r.diagnostics.unmatchedCharacters,0);
  const chunks=r.pages.flatMap(p=>p.chunks);
  assert.equal(chunks.map(c=>c.spaceBefore+c.text).join('')+r.trailingSpace,script);
  for(const p of r.pages) for(const c of p.chunks){
    assert.ok(c.tokens.every(t=>t.s>=p.start&&Number.isFinite(t.e)));assert.ok(c.displayEnd<=p.end);
    assert.equal(c.text,c.tokens.map(t=>t.w).join(''));
  }
});
test('ICU words and combining marks never split across chunks/pages',()=>{
  const r=buildCaptionPages(timed(['ควา','มเร็ว','จุด','นี้','น้ำ','ดี']), 'ความเร็วจุดนี้น้ำดี',{maxUnits:8});
  const boundaries=new Set([...new Intl.Segmenter('th',{granularity:'word'}).segment('ความเร็วจุดนี้น้ำดี')].map(x=>x.index));
  let pos=0;for(const c of r.pages.flatMap(p=>p.chunks)){assert.ok(boundaries.has(pos));pos+=c.text.length;}
  assert.ok(r.pages.flatMap(p=>p.chunks).some(c=>c.merged_from.length>1));
});
test('mismatch fails with exact diagnostics instead of skipping or inventing',()=>{
  assert.throws(()=>buildCaptionPages(timed(['บอก','วา']),'บอกว่า'),e=>e.code==='CAPTION_ALIGNMENT_MISMATCH'&&e.diagnostics.scriptOffset===4);
  assert.throws(()=>buildCaptionPages(timed(['หนึ่ง']),'หนึ่งสอง'),/unmatched script/);
  assert.throws(()=>buildCaptionPages([{w:'คำ',s:2,e:1}],'คำ'),/timestamp/);
});
test('phrase pages coalesce short legacy pages and active glow follows merged timing',()=>{
  const r=buildCaptionPages(timed(['บอ','กว่า','อยาก','ได้','รูป']), 'บอกว่าอยากได้รูป');
  assert.equal(r.pages.length,1); const c=r.pages[0].chunks[0];
  assert.equal(c.text,'บอกว่า');assert.equal(c.tokens[0].s,0);assert.equal(c.tokens[0].e,.4);
  assert.equal(activeChunk(c,.1),true);assert.equal(activeChunk(c,.4),false);
  assert.match(CAPTION_ALGORITHM_VERSION,/a44/);
});

test('display switches at latest start, ignores overlapping long tails and uses explicit phrase bound',()=>{
 const r=buildCaptionPages([{w:'กิน',s:0,e:5},{w:'ดื่ม',s:1,e:1},{w:'นอน',s:2,e:8}], 'กิน ดื่ม นอน',{phraseBounds:[{scriptEnd:'กิน ดื่ม นอน'.length,end:3,reason:'approved phrase boundary'}]});
 const chunks=r.pages.flatMap(p=>p.chunks);
 assert.equal(activeChunk(chunks[0],1.1),false);
 assert.equal(activeChunk(chunks[1],1.1),true);
 assert.equal(activeChunk(chunks[2],2.5),true);
 assert.equal(r.pages.at(-1).end,3);
 assert.equal(chunks[0].tokens[0].e,5);
 assert.equal(activeChunk(chunks[2],3),false);
});
