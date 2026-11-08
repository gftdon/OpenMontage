import test from 'node:test';
import assert from 'node:assert/strict';
import {evaluateLayout,validateSamples,backingPresent} from '../qc_layout_eval.mjs';
import fs from 'node:fs';
test('actual legacy Q1 snapshot fails overlap',()=>{
 const snapshot=JSON.parse(fs.readFileSync(new URL('./fixtures/q1-legacy-225.json',import.meta.url)));
 assert.ok(evaluateLayout(snapshot,{safeFraction:.05,readFontPx:28,labelFontPx:22,visibleOpacity:.05}).issues.some(i=>i.code==='overlap'));
});
const thresholds={safeFraction:.05,readFontPx:28,labelFontPx:22,visibleOpacity:.05};
const field=(id,x=100,y=100,extra={})=>({id,role:'read',layer:'current',text:id,fontSize:28,opacity:1,rects:[{x,y,width:200,height:40}],inkRects:[{x,y,width:200,height:40}],box:{x,y,width:200,height:40},clipped:false,...extra});
const snap=(fields=[field('headline'),field('chip',100,170)])=>({schemaVersion:2,frame:225,width:1920,height:1080,fontsOk:true,fields,occluders:[],footage:{origin:'stock',src:'desk',credit:false,chrome:false}});
const codes=s=>evaluateLayout(s,thresholds).issues.map(i=>i.code);
test('separated rows pass',()=>assert.deepEqual(codes(snap()),[]));
test('old Q1 chip overlapping headline fails',()=>assert.ok(codes(snap([field('headline'),field('chip',110,110)])).includes('overlap')));
test('outside safe area fails',()=>assert.ok(codes(snap([field('edge',90)])).includes('safe')));
test('read font below minimum fails',()=>assert.ok(codes(snap([field('small',100,100,{fontSize:27})])).includes('font')));
test('label font 22 passes',()=>assert.deepEqual(codes(snap([field('label',100,100,{fontSize:22,role:'label'})])),[]));
test('clipping fails',()=>assert.ok(codes(snap([field('clip',100,100,{clipped:true})])).includes('clip')));
test('missing fonts/log and invalid geometry fail closed',()=>{
 for(const s of [null,{...snap(),fontsOk:false},{...snap(),fields:[]},snap([field('bad',NaN)])]) assert.ok(codes(s).length);
});
test('source needs credit and stock rejects chrome or credit',()=>{
 let s=snap();s.footage={origin:'source',src:'yt_demo',credit:false,chrome:true};assert.ok(codes(s).includes('credit'));
 s=snap();s.footage.chrome=true;assert.ok(codes(s).includes('stock-chrome'));
});
test('nested logical field fragments are not compared against themselves',()=>assert.deepEqual(codes(snap([field('caption',100,100,{rects:[{x:100,y:100,width:200,height:40},{x:120,y:100,width:50,height:40}]})])),[]));
test('transition exemptions are limited to old/new versions of the same field',()=>{
 const a=field('headline',100,100,{layer:'previous'}),b=field('headline');
 assert.deepEqual(codes({...snap([a,b]),transition:true}),[]);
 assert.ok(codes({...snap([a,field('chip')]),transition:true}).includes('overlap'));
});
test('opaque container hides headline without text intersection including pointer-events none image',()=>{
 for(const kind of ['pill','image']){const s=snap([field('headline')]);s.occluders=[{id:'cover',kind,box:{x:110,y:100,width:200,height:40},opacity:1,frontOf:['headline'],pointerEvents:'none'}];assert.ok(codes(s).includes('occlusion'));}
});
test('Thai ink outside Range is clipped and missing ink fails closed',()=>{
 const s=snap([field('thai',100,100,{inkRects:[{x:100,y:90,width:200,height:55}],clipBoxes:[{x:100,y:100,width:200,height:40}]})]);assert.ok(codes(s).includes('clip'));
 const f=field('missing');delete f.inkRects;assert.ok(codes(snap([f])).includes('geometry'));
});
test('hidden or occluded source credit fails and stock URL detected without chrome attribute',()=>{
 for(const opacity of [0,.01]){const s=snap([field('source-credit',100,100,{opacity})]);s.footage={origin:'source',src:'yt_demo',credit:true,chrome:false};assert.ok(codes(s).includes('credit'));}
 const s=snap([field('source-credit')]);s.footage={origin:'source',src:'yt_demo',credit:true};s.occluders=[{id:'cover',box:{x:100,y:100,width:200,height:40},opacity:1,frontOf:['source-credit']}];assert.ok(codes(s).includes('credit'));
 assert.ok(codes(snap([field('source-url')])).includes('stock-chrome'));
});
test('full footage text requires backing and top caption lane is enforced',()=>{
 const s=snap([field('caption',100,950)]);s.footage.layout='full';s.captionLane='top';s.fields[0].backed=false;
 assert.ok(codes(s).includes('backing'));assert.ok(codes(s).includes('caption-lane'));
 s.fields=[field('caption',100,250,{backed:true})];assert.deepEqual(codes(s),[]);
 s.captionLane='bottom';assert.ok(codes(s).includes('caption-lane'));
});
test('missing duplicate wrong frame samples fail closed',()=>{
 assert.ok(validateSamples([225,226],[snap()]).length);
 assert.ok(validateSamples([225],[snap(),snap()]).length);
 assert.ok(validateSamples([226],[snap()]).length);
 assert.deepEqual(validateSamples([225],[snap()]),[]);
});

test('backing presence accepts shared fade, rejects missing/invisible/uncovered backing',()=>{const ink=[{x:100,y:100,width:100,height:40}];const good={alpha:.92,opacity:.45,sameVisibilityAncestry:true,box:{x:90,y:90,width:130,height:70}};assert.equal(backingPresent(good,ink),true);for(const bad of [{...good,alpha:0},{...good,opacity:0},{...good,sameVisibilityAncestry:false},{...good,box:{x:100,y:110,width:100,height:20}}])assert.equal(backingPresent(bad,ink),false);});

test('actual headline ink overhang is rejected until layout padding contains it',()=>{const field=JSON.parse(fs.readFileSync(new URL('./fixtures/headline-overhang.json',import.meta.url)));assert.equal(backingPresent(field.backing,field.inkRects),false);});

test('actual padded headline backing contains measured ink',()=>{const field=JSON.parse(fs.readFileSync(new URL('./fixtures/headline-padded.json',import.meta.url)));assert.equal(backingPresent(field.backing,field.inkRects),true);});
