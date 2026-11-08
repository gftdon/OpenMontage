#!/usr/bin/env node
// Offline render helper. Caller supplies composer and output; no media/network fetch.
import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs/promises';
const [composerArg,id,outArg,...args]=process.argv.slice(2);
const rangeAt=args.indexOf('--frames');
const frameRange=rangeAt<0?undefined:args[rangeAt+1].split('-').map(Number);
if(frameRange&&(frameRange.length!==2||frameRange.some(x=>!Number.isInteger(x))))throw Error('invalid frame range');
if(!composerArg||!id||!outArg)throw Error('render_episode.mjs <composer-dir> <comp-id> <visual.mp4>');
const composer=path.resolve(composerArg),out=path.resolve(outArg);
await fs.mkdir(path.dirname(out),{recursive:true});
const require=createRequire(path.join(composer,'package.json'));
const {bundle}=require('@remotion/bundler');const {selectComposition,renderMedia}=require('@remotion/renderer');
const serveUrl=await bundle({entryPoint:path.join(composer,'src/index.tsx'),publicDir:path.join(composer,'public'),outDir:path.join(path.dirname(out),'render-bundle')});
const browserExecutable='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const composition=await selectComposition({serveUrl,id,inputProps:{},browserExecutable});
let last=-1;
await renderMedia({composition,serveUrl,inputProps:{},browserExecutable,codec:'h264',crf:20,muted:true,concurrency:1,frameRange,outputLocation:out,onProgress:p=>{const n=Math.floor(p.progress*20);if(n!==last){last=n;console.log(`RENDER ${n*5}%`);}}});
console.log(`RENDER_DONE ${out}`);
