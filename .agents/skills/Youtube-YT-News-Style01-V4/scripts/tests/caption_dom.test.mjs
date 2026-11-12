import test from 'node:test';import assert from 'node:assert/strict';import {evaluateLayout} from '../qc_layout_eval.mjs';
const box={x:116,y:248,width:500,height:120};
const s={schemaVersion:2,frame:625,width:1920,height:1080,fontsOk:true,captionLane:'top',occluders:[],footage:{origin:'stock',src:'desk'},fields:[{id:'caption',text:'คำจริง',role:'read',fontSize:32,opacity:1,box,rects:[{x:142,y:310,width:120,height:40}],inkRects:[{x:142,y:310,width:120,height:40}],clipped:false,captionBlankFirstLine:true,captionLineCount:1}]};
test('measured blank first caption line is rejected even if pill fits safe area',()=>assert.ok(evaluateLayout(s,{safeFraction:.05,readFontPx:28,labelFontPx:22,visibleOpacity:.05}).issues.some(i=>i.code==='caption-blank-line')));
