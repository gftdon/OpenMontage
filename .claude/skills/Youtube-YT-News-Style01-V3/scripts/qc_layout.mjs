#!/usr/bin/env node
import {randomUUID} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {beginReport,writeReport,makeReport,hashSources,createRunDirectory} from './qc_report.mjs';
import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs/promises';
import {evaluateLayout,validateSamples} from './qc_layout_eval.mjs';
const [id,outArg,composerArg,...args]=process.argv.slice(2);
if(!id||!outArg||!composerArg)throw Error('qc_layout.mjs <comp-id> <out-dir> <composer-dir> [--frames 225,2225]');
const out=path.resolve(outArg),composer=path.resolve(composerArg);
await fs.mkdir(out,{recursive:true});
const meta={compositionId:id,runId:randomUUID(),startedAt:new Date().toISOString()};
await beginReport(out,meta);let browser;let runOut;
try {
 runOut=await createRunDirectory(out,meta.runId);meta.artifactDirectory=runOut;
 const require=createRequire(path.join(composer,'package.json'));
 const {bundle}=require('@remotion/bundler');
 const {selectComposition,renderStill,openBrowser}=require('@remotion/renderer');
 const scriptDir=path.dirname(fileURLToPath(import.meta.url));
 const source=path.join(composer,'src',id+'.tsx');
 const text=await fs.readFile(source,'utf8');
 const helpers=[...text.matchAll(/from ["'](\.\/[^"']*Captions)["']/g)].map(m=>path.join(composer,'src',m[1]+'.ts'));
 meta.sourceHashes=await hashSources([source,...helpers,path.join(composer,'src/Root.tsx'),path.join(composer,'src/index.tsx'),path.join(scriptDir,'lint_beats.py'),...(await fs.readdir(scriptDir)).filter(f=>f.startsWith('qc_')&&(f.endsWith('.mjs')||f.endsWith('.json'))).map(f=>path.join(scriptDir,f))]);
 const thresholds=JSON.parse(await fs.readFile(path.join(scriptDir,'qc_thresholds.json')));
 const browserExecutable='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
 const serveUrl=await bundle({entryPoint:path.join(composer,'src/index.tsx'),publicDir:path.join(composer,'public'),outDir:path.join(runOut,'bundle')});
 browser=await openBrowser('chrome',{browserExecutable});
 const inputProps={qcPlan:true,qcMeasure:true};
 const common={serveUrl,inputProps,browserExecutable,puppeteerInstance:browser,timeoutInMilliseconds:90000,onBrowserLog:()=>{}};
 let plan;
 const composition=await selectComposition({...common,id});
 const capture=async(frame)=>{
  const logs=[];
  await renderStill({...common,composition,frame,output:path.join(runOut,`${frame}.png`),onBrowserLog:l=>{
   if(l.text.startsWith('__QC_PLAN__'))plan=JSON.parse(l.text.slice(11));
   if(l.text.startsWith('__QC__'))logs.push(JSON.parse(l.text.slice(6)));
  }});
  // renderStill may mount at frame zero then seek; only retain the requested frame.
  const matching=logs.filter(s=>s.frame===frame);
  if(matching.length!==1)throw Error(`frame ${frame}: expected one probe log, got ${matching.length}`);
  await fs.writeFile(path.join(runOut,`${frame}.json`),JSON.stringify(matching[0],null,2));
  return matching[0];
 };
 const first=await capture(0);
 if(!plan||!Array.isArray(plan.frames)||!plan.frames.length)throw Error('missing QC plan');
 const explicit=args.indexOf('--frames');
 const frames=explicit>=0?args[explicit+1].split(',').map(Number):plan.frames;
 if(frames.some(f=>!Number.isInteger(f)||f<0||f>=composition.durationInFrames)||new Set(frames).size!==frames.length)throw Error('invalid sample plan');
 const samples=[];
 for(const frame of frames){samples.push(frame===0?first:await capture(frame));console.log(`QC_FRAME ${frame}`);}
 const issues=validateSamples(frames,samples);
 for(const s of samples)for(const i of evaluateLayout(s,thresholds).issues)issues.push({frame:s.frame,...i});
 const report=makeReport({...meta,endedAt:new Date().toISOString(),fullPlanFrames:plan.frames,requestedFrames:frames,issues});
 await writeReport(runOut,report);await writeReport(out,report);
 console.log(JSON.stringify({acceptancePass:report.pass,diagnosticPass:report.diagnosticPass,complete:report.complete,samples:frames.length,issues:issues.length}));
 process.exitCode=report.diagnosticPass?0:1;
} catch(error){await writeReport(out,{schema:'yt-news-layout-report',version:2,...meta,endedAt:new Date().toISOString(),status:'failed',complete:false,pass:false,diagnosticPass:false,error:String(error)});throw error;} finally {if(browser)await browser.close({silent:true});}
