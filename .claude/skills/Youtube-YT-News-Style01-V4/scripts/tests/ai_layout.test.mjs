import test from 'node:test';
import assert from 'node:assert/strict';
import {evaluateLayout} from '../qc_layout_eval.mjs';
const box={x:116,y:186,width:220,height:40};
const label={id:'ai-label',role:'label',text:'ภาพประกอบ AI',fontSize:24,opacity:1,rects:[box],inkRects:[box],box,backed:true,clipped:false};
const s={schemaVersion:2,frame:225,width:1920,height:1080,fontsOk:true,fields:[label],occluders:[],footage:{origin:'ai',src:'ai_concept',layout:'full',credit:false,chrome:false}};
const codes=s=>evaluateLayout(s,{safeFraction:.05,readFontPx:28,labelFontPx:22,visibleOpacity:.05}).issues.map(i=>i.code);
test('AI provenance requires label and full-footage backing without source attribution',()=>{
 assert.deepEqual(codes(s),[]);
 assert.ok(codes({...s,fields:[{...label,text:'official UI'}]}).includes('ai-label'));
 assert.ok(codes({...s,fields:[{...label,backed:false}]}).includes('backing'));
 assert.ok(codes({...s,footage:{...s.footage,credit:true}}).includes('ai-chrome'));
 assert.ok(codes({...s,footage:{...s.footage,src:'yt_fake'}}).includes('origin'));
});
