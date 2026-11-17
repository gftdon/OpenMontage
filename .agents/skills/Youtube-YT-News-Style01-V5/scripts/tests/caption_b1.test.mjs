import {test} from 'node:test';
import assert from 'node:assert/strict';
import {buildCaptionPages} from '../caption_join.mjs';
test('equal-start newline fails explicitly rather than losing a zero-duration word',()=>{
 assert.throws(()=>buildCaptionPages([{w:'หนึ่ง',s:0,e:1},{w:'สอง',s:0,e:1}],'หนึ่ง\nสอง',{endTime:2}),/simultaneous.*newline/);
});
for(const [text,pair] of [['ใช้เวลาสิบวินาทีต่อภาพ','สิบวินาที'],['ใช้เวลา10วินาทีต่อภาพ','10วินาที'],['รอ6 วินาทีต่อภาพ','6 วินาที'],['รอ6 วินาทีต่อภาพ','6 วินาที'],['ลด50เปอร์เซ็นต์ทันที','50เปอร์เซ็นต์'],['จ่ายหนึ่งร้อยบาททันที','หนึ่งร้อยบาท']])test('quantity-unit stays indivisible: '+pair,()=>{
 const ts=[...new Intl.Segmenter('th',{granularity:'word'}).segment(text)].map((x,i)=>({w:x.segment,s:i*.1,e:i*.1+.1}));
 const r=buildCaptionPages(ts,text,{endTime:4,maxUnits:8});
 assert.equal(r.pages.map(p=>p.text).join(''),text);assert.ok(r.pages.some(p=>p.chunks.some(c=>c.text.includes(pair))));
 assert.ok(r.pages.every(p=>p.end>p.start));
});
test('newline prevents quantity-unit pairing',()=>{
 const r=buildCaptionPages([{w:'6',s:0,e:.1},{w:'วินาที',s:1,e:2}],'6\nวินาที',{endTime:3,maxUnits:2});
 assert.equal(r.pages.map(p=>p.text).join(''),'6\nวินาที');assert.ok(!r.pages.some(p=>p.chunks.some(c=>c.text.includes('\n'))));
});
test('punctuation prevents quantity-unit pairing',()=>{
 const r=buildCaptionPages([{w:'สิบ',s:0,e:1},{w:',',s:1,e:1.1},{w:'วินาที',s:2,e:3}],'สิบ,วินาที',{endTime:4});
 assert.ok(!r.pages.some(p=>p.chunks.some(c=>c.text==='สิบ,วินาที')));
});
