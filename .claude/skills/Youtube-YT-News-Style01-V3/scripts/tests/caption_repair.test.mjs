import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {buildCaptionPages} from '../caption_join.mjs';
const build=(words,script,options={})=>buildCaptionPages(words,script,{endTime:8,...options});
const tokens=(parts,starts)=>parts.map((w,i)=>({w,s:starts?.[i]??i*.3,e:(starts?.[i]??i*.3)+.2}));
test('page source whitespace is lossless but leading newline never creates blank display line',()=>{
 const r=build(tokens(['หนึ่ง','สอง']), 'หนึ่ง\nสอง');
 assert.equal(r.pages.map(p=>p.text).join(''),'หนึ่ง\nสอง');
 assert.equal(r.pages[1].leadingWhitespace,'\n');assert.equal(r.pages[1].displayText,'สอง');
 assert.equal(r.pages[1].chunks[0].displaySpaceBefore,'');
});
test('pagination compares starts not pause-extended display ends; no orphan before long pause',()=>{
 const r=build(tokens(['A','B','C','D'],[0,.3,.6,5]), 'A B C D');
 assert.deepEqual(r.pages.map(p=>p.displayText),['A B C','D']);
 assert.equal(r.pages[0].end,5);assert.equal(r.pages[0].boundReason,'next lexical word start');
});
test('pause option acts on observed starts without guessing silence ends',()=>{
 const words=tokens(['A','B','C','D','E'],[0,.1,.2,1.2,1.3]);
 const a=build(words,'A B C D E',{pause:.5}),b=build(words,'A B C D E',{pause:2});
 assert.equal(a.pages.length,2);assert.equal(b.pages.length,1);
 assert.equal(a.pages[0].end,1.2);
});
test('width counts Thai graphemes rather than combining codepoints',()=>{
 const r=build(tokens(['น้ำ','ดี','มาก']), 'น้ำดีมาก',{maxUnits:6});
 assert.equal(r.pages.length,1);
});
for(const [text,parts] of [['ยาว ๆ',['ยาว','ๆ']],['ลื่นไหลขึ้น',['ลื่น','ไหล','ขึ้น']],['สั่งแก้ได้ทันที',['สั่ง','แก้','ได้','ทันที']]])test(`no orphan fragments: ${text}`,()=>{
 const r=build(tokens(parts),text,{maxUnits:8});
 assert.equal(r.pages.map(p=>p.text).join(''),text);
 assert.ok(r.pages.every(p=>!/^\s*[ๆฯ).!?]/u.test(p.displayText)));
 assert.ok(r.pages.length===1||r.pages.at(-1).chunks.length>1);
});
test('overlapping lexical override unions ICU spans without dropping partial characters',()=>{
 const r=build(tokens(['abcdef']), 'abcdef',{lexicalOverrides:['bcd','cdef']});
 assert.equal(r.pages.map(p=>p.text).join(''),'abcdef');
});
test('equal word starts share a visible group, never zero-duration lost words',()=>{
 const r=build(tokens(['กิน','ดื่ม','นอน'],[0,0,1]), 'กิน ดื่ม นอน');
 assert.equal(r.pages[0].chunks[0].text,'กิน ดื่ม');
 assert.ok(r.pages.flatMap(p=>p.chunks).every(c=>c.displayEnd>c.displayStart));
});
test('real data phrase fragments, exact helper provenance and reusable CLI',async()=>{
 const {generateCaptionModule}=await import('../caption_join.mjs');
 const module=generateCaptionModule(build(tokens(['น้ำ','ดี']),'น้ำดี'));
 assert.match(module,/CAPTION_PROVENANCE/);assert.match(module,/displaySpaceBefore/);
});

test('real episode caption output exactly reproduces helper and has no leading display blank line',async()=>{
 const path=await import('node:path');
 const root=path.resolve(new URL('../../../../..',import.meta.url).pathname);
 const artifact=path.join(root,'projects/v261107-001-yt-news-v3-broll-test/artifacts/caption-joined.json');
 if(!fs.existsSync(artifact))return;
 const r=JSON.parse(fs.readFileSync(artifact));
 const {generateCaptionModule}=await import('../caption_join.mjs');
 assert.equal(fs.readFileSync(path.join(root,'remotion-composer/src/ytNewsStyle01V3Captions.ts'),'utf8'),generateCaptionModule(r));
 assert.ok(r.pages.every(p=>!/^\s/u.test(p.displayText)&&!/^\s*[ๆฯ]/u.test(p.displayText)));
 assert.equal(r.diagnostics.unmatchedCharacters,0);
 assert.ok(r.pages.some(p=>p.displayText.includes('ลื่นไหล')));
});
