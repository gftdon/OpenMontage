import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';
import {evaluateAvatarBackingSweep} from '../qc_layout_eval.mjs';
const source=fs.readFileSync(new URL('../../../../../remotion-composer/src/YtNewsStyle01V4.tsx',import.meta.url),'utf8');
test('missing avatar is expected only after exact endcard boundary, with explicit not-applicable data',()=>{
 assert.ok(source.includes("if(!avatar&&frame/fps<VO_END_SEC)throw Error('missing avatar measurement');"));
 assert.ok(source.includes("let avatarBacking:unknown={applicable:false,reason:'endcard',avatar:null,candidates:[]};"));
 assert.ok(source.includes('if(avatar){\n        try{'));
 const condition=source.match(/if\((!avatar&&frame\/fps<VO_END_SEC)\)throw Error\('missing avatar measurement'\)/)[1];
 const missingActive=Function('avatar','frame','fps','VO_END_SEC','return '+condition);
 assert.equal(missingActive(null,8412,25,336.5),true);
 assert.equal(missingActive(null,8413,25,336.5),false);
 assert.equal(missingActive(null,8524,25,336.5),false);
 assert.equal(missingActive({},8412,25,336.5),false);
});
test('not-applicable endcard cannot bypass required avatar measurements within sweep window',()=>{
 const result=evaluateAvatarBackingSweep([{id:'unexpected-endcard',beatT:336.52,startFrame:8413,endFrame:8413}],[{frame:8413,fontsOk:true,avatarBacking:{applicable:false,reason:'endcard',avatar:null,candidates:[]}}],25,{visibleOpacity:.05,avatarEmptyMinArea:1500,avatarEmptyMinDimension:24,avatarEmptyMaxSeconds:.3});
 assert.equal(result.complete,false);assert.ok(result.issues.some(i=>i.code==='sweep-incomplete'));
});
