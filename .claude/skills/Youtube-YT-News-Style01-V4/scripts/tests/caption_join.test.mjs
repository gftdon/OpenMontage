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

// CLI (V4): the engine reads the --out JSON; there is no generated TSX module any more.
import {spawnSync} from 'node:child_process';
import fsCli from 'node:fs';
import osCli from 'node:os';
import pathCli from 'node:path';
import {fileURLToPath as toPathCli} from 'node:url';
const CLI=toPathCli(new URL('../caption_join.mjs',import.meta.url));
function cliFixture(){
 const dir=fsCli.mkdtempSync(pathCli.join(osCli.tmpdir(),'capjoin-'));
 fsCli.writeFileSync(pathCli.join(dir,'tokens.json'),JSON.stringify([{words:[{w:'น้ำ',s:0,e:.4},{w:'ดี',s:.4,e:.9}]}]));
 fsCli.writeFileSync(pathCli.join(dir,'script.txt'),'น้ำดี');
 fsCli.writeFileSync(pathCli.join(dir,'options.json'),JSON.stringify({endTime:.9}));
 return dir;
}
test('CLI writes the captions JSON with --out only (no --module needed)',()=>{
 const dir=cliFixture(),out=pathCli.join(dir,'captions.json');
 const r=spawnSync(process.execPath,[CLI,'--tokens',pathCli.join(dir,'tokens.json'),'--script',pathCli.join(dir,'script.txt'),'--options',pathCli.join(dir,'options.json'),'--out',out],{encoding:'utf8'});
 assert.equal(r.status,0,r.stderr);
 const result=JSON.parse(fsCli.readFileSync(out,'utf8'));
 assert.equal(result.pages.map(p=>p.text).join(''),'น้ำดี');assert.match(result.inputSha256,/^[0-9a-f]{64}$/);
 assert.deepEqual(fsCli.readdirSync(dir).sort(),['captions.json','options.json','script.txt','tokens.json']);
 fsCli.rmSync(dir,{recursive:true});
});
test('CLI refuses --module and a missing flag with exit 2 and writes nothing',()=>{
 const dir=cliFixture(),out=pathCli.join(dir,'captions.json');
 const base=['--tokens',pathCli.join(dir,'tokens.json'),'--script',pathCli.join(dir,'script.txt'),'--options',pathCli.join(dir,'options.json')];
 const a=spawnSync(process.execPath,[CLI,...base,'--out',out,'--module',pathCli.join(dir,'x.ts')],{encoding:'utf8'});
 assert.equal(a.status,2);assert.match(a.stderr,/--module is not supported/);
 const b=spawnSync(process.execPath,[CLI,...base],{encoding:'utf8'});
 assert.equal(b.status,2);assert.match(b.stderr,/missing --out/);
 assert.equal(fsCli.existsSync(out),false);assert.equal(fsCli.existsSync(pathCli.join(dir,'x.ts')),false);
 fsCli.rmSync(dir,{recursive:true});
});

// Real whisper alignment (V261111, tokens 719-722) collapses a word to zero length onto the start of the next line.
test('a zero-length last word of a line joins the display group of the word before it; the line break is kept',()=>{
 const tokens=[{w:'โปรแกรม',s:292.575,e:292.9},{w:'กราฟิก',s:292.9,e:292.9},{w:'ทำ',s:292.9,e:292.9},{w:'ให้การ',s:292.9,e:293.26},{w:'เปลี่ยน',s:293.26,e:293.58}];
 const script='โปรแกรมกราฟิก\nทำให้การเปลี่ยน';
 const r=build(tokens,script,{endTime:293.58});
 assert.equal(join(r),script);
 const chunks=r.pages.flatMap(p=>p.chunks);
 assert.deepEqual(chunks.map(c=>c.text),['โปรแกรมกราฟิก','ทำให้การ','เปลี่ยน']);
 assert.deepEqual(chunks.map(c=>[c.displayStart,c.displayEnd]),[[292.575,292.9],[292.9,293.26],[293.26,293.58]]);
 assert.ok(/\n/u.test(chunks[1].spaceBefore),'line break stays between the two groups');
 assert.deepEqual(chunks[0].sourceTokens.map(t=>t.w),['โปรแกรม','กราฟิก']);
 assert.equal(r.pages.length,2);
 for(const c of chunks)assert.ok(c.displayEnd>c.displayStart,'every group is visible for a non-zero time');
});
test('simultaneous starts across a newline still throw when the earlier word is alone on its line',()=>{
 assert.throws(()=>build([{w:'ก่อน',s:0,e:1},{w:'หนึ่ง',s:1,e:1},{w:'สอง',s:1,e:2}],'ก่อน\nหนึ่ง\nสอง',{endTime:2}),/simultaneous.*newline/);
});
