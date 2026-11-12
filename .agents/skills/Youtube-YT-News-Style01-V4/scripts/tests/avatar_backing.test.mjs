import test from 'node:test';import assert from 'node:assert/strict';
import {emptyBackingRegions,evaluateAvatarBackingSweep} from '../qc_layout_eval.mjs';
const t={visibleOpacity:.05,avatarEmptyMinArea:1500,avatarEmptyMinDimension:24,avatarEmptyMaxSeconds:.3};
const box={x:0,y:0,width:200,height:100};
const window={id:'beat-0',beatT:0,startFrame:0,endFrame:9};
const candidate=(extra={})=>({id:'div:1/div:2',box,opacity:1,background:{alpha:0,image:'linear-gradient(red,blue)'},protectedRects:[],emptyRegions:[{...box,paintOrderEvidence:{above:true,x:100,y:50,candidateIndex:0,avatarIndex:1}}],...extra});
const sample=(frame,dirty=true)=>({frame,fontsOk:true,avatarBacking:{avatar:{box,opacity:1},candidates:dirty?[candidate()]:[]}});
const sweep=(samples,windows=[window],extra={})=>evaluateAvatarBackingSweep(windows,samples,25,t,extra);
test('7 consecutive frames .28 pass, 8 .32 fail, clean frame breaks run',()=>{
 assert.equal(sweep(Array.from({length:10},(_,i)=>sample(i,i<7))).issues.length,0);
 const fail=sweep(Array.from({length:10},(_,i)=>sample(i,i<8))).issues.find(i=>i.code==='avatar-empty-backing');assert.equal(fail.nframes,8);assert.equal(fail.duration,.32);
 assert.equal(sweep(Array.from({length:10},(_,i)=>sample(i,i!==4&&i!==9))).issues.length,0);
});
test('dirty final frame is unbounded even for one frame; missing duplicate and outside fail',()=>{
 assert.ok(sweep(Array.from({length:10},(_,i)=>sample(i,i===9))).issues.some(i=>i.code==='avatar-empty-backing-unbounded'));
 for(const samples of [[sample(0)],[...Array.from({length:10},(_,i)=>sample(i,false)),sample(0,false)],[...Array.from({length:10},(_,i)=>sample(i,false)),sample(10,false)]])assert.ok(sweep(samples).issues.some(i=>i.code==='sweep-incomplete'));
});
test('gradient no-tag candidate captured but low opacity or paint-below does not count',()=>{
 for(const replacement of [candidate({opacity:.04}),candidate({emptyRegions:[{...box,paintOrderEvidence:{above:false,x:100,y:50,candidateIndex:1,avatarIndex:0}}]}),candidate({background:{alpha:0,image:'none'}})]){
  const samples=Array.from({length:10},(_,i)=>({...sample(i),avatarBacking:{avatar:{box,opacity:1},candidates:[replacement]}}));assert.equal(sweep(samples).issues.length,0);
 }
});
test('glyph-hull plus padding protects localized text, not wide blank bar; 12px strip retained',()=>{
 assert.equal(emptyBackingRegions(box,[{...box}]).length,0);
 const regions=emptyBackingRegions(box,[{x:0,y:0,width:60,height:100}]);assert.ok(regions.some(r=>r.width*r.height>=1500));
 const strip={x:0,y:0,width:12,height:200};const samples=Array.from({length:10},(_,i)=>({...sample(i),avatarBacking:{avatar:{box:strip,opacity:1},candidates:i===9?[]:[candidate({box:strip,emptyRegions:[{...strip,paintOrderEvidence:{above:true,x:6,y:100,candidateIndex:0,avatarIndex:1}}]})]}}));assert.ok(sweep(samples).issues.some(i=>i.code==='avatar-empty-backing'));
});
test('missing measurement or fonts fails closed, diagnostic incomplete cannot be complete',()=>{
 for(const s of [{frame:0},{...sample(0),fontsOk:false}])assert.ok(sweep([s]).issues.length);
 const result=sweep([sample(0,false)],[window],{requireComplete:false});assert.equal(result.complete,false);
});

test('temporal incomplete prevents report completeness without changing legacy reports',async()=>{
 const {makeReport}=await import('../qc_report.mjs');
 assert.equal(makeReport({fullPlanFrames:[0],requestedFrames:[0],issues:[],temporalSweep:{complete:false}}).complete,false);
});
test('actual default plan sweeps geometry changes and all-root paint-order probe has no tag filter',async()=>{
 const fs=await import('node:fs/promises');const source=await fs.readFile(new URL('../../../../../remotion-composer/src/YtNewsStyle01V4.tsx',import.meta.url),'utf8');
 assert.ok(source.includes('sceneKind(BEATS[i-1])!==sceneKind(b)||JSON.stringify(rectFor(BEATS[i-1]))!==JSON.stringify(rectFor(b))'),'window on any scene-kind change or presenter-state change');
 assert.ok(source.includes('startFrame:Math.ceil(b.t*fps),endFrame:Math.min(Math.ceil(TOTAL_DURATION_SEC*fps)-1,Math.ceil(b.t*fps)+IN_F+OUT_F+3)'),'window = ceil(b.t*fps) .. +IN_F+OUT_F+3');
 assert.ok(!source.includes('Math.ceil((b.t+MODE_BLEND_SEC)*fps)+3'),'old .55 s window is gone');
 assert.ok(source.includes('\'[data-qc-scene-role="current"] [data-qc-footage]\''),'footage selector reads the current layer only');
 assert.ok(source.includes("root.querySelectorAll<HTMLElement>('*')"));
 assert.ok(source.includes('const candidateIndex=stack.indexOf(el)'));
 assert.ok(source.includes('avatarBacking,transition:'));
});

test('actual old 88.62 headline fixture fails continuous gate for12 frames .48s',async()=>{
 const fs=await import('node:fs/promises');const fixture=JSON.parse(await fs.readFile(new URL('./fixtures/avatar-empty-backing-actual-89.json',import.meta.url),'utf8'));
 const result=evaluateAvatarBackingSweep(fixture.windows,fixture.samples,fixture.fps,t);
 assert.equal(result.complete,true);const issue=result.issues.find(i=>i.code==='avatar-empty-backing');assert.ok(issue);assert.equal(issue.nframes,12);assert.equal(issue.duration,.48);assert.equal(issue.firstFrame,2216);assert.equal(issue.lastFrame,2227);
});

test('actual fadeout headline fixtures fail12frames each without exemption',async()=>{
 const fs=await import('node:fs/promises');const fixture=JSON.parse(await fs.readFile(new URL('./fixtures/avatar-empty-backing-fadeout.json',import.meta.url),'utf8'));
 const result=evaluateAvatarBackingSweep(fixture.windows,fixture.samples,fixture.fps,t);assert.equal(result.complete,true);
 const issues=result.issues.filter(i=>i.code==='avatar-empty-backing');assert.equal(issues.length,2);assert.deepEqual(issues.map(i=>[i.firstFrame,i.lastFrame,i.nframes,i.duration]),[[2716,2727,12,.48],[4295,4306,12,.48]]);
});

test('disjoint empty fragment area sums per candidate/frame; 7pass8fail and clean reset',()=>{
 const intersection={x:0,y:0,width:70,height:60};const regions=emptyBackingRegions(intersection,[{x:18,y:18,width:34,height:24}]);
 assert.deepEqual(regions.map(r=>r.width*r.height),[1260,1260,432,432]);
 const frame=(i,dirty=true,below=false)=>({...sample(i,false),avatarBacking:{avatar:{box:intersection,opacity:1},candidates:dirty?[candidate({box:intersection,emptyRegions:regions.map((r,j)=>({...r,paintOrderEvidence:{above:!below||j===0,x:r.x+r.width/2,y:r.y+r.height/2,candidateIndex:!below||j===0?0:1,avatarIndex:!below||j===0?1:0}}))})]:[]}});
 assert.equal(sweep(Array.from({length:10},(_,i)=>frame(i,i<7))).issues.length,0);
 const eight=sweep(Array.from({length:10},(_,i)=>frame(i,i<8)));const issue=eight.issues.find(i=>i.code==='avatar-empty-backing');assert.ok(issue);assert.equal(issue.maxEmptyPx,3384);assert.equal(issue.nframes,8);
 assert.equal(sweep(Array.from({length:10},(_,i)=>frame(i,i<8,true))).issues.length,0);
 assert.equal(sweep(Array.from({length:10},(_,i)=>frame(i,i!==4&&i!==9))).issues.length,0);
});
