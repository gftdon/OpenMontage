const finiteRect=r=>r && ['x','y','width','height'].every(k=>Number.isFinite(r[k])) && r.width>0 && r.height>0;
const intersects=(a,b)=>Math.min(a.x+a.width,b.x+b.width)-Math.max(a.x,b.x)>.5&&Math.min(a.y+a.height,b.y+b.height)-Math.max(a.y,b.y)>.5;
export function evaluateLayout(s,t) {
 const issues=[];const add=(code,detail)=>issues.push({code,detail});
 if(!s || !Number.isInteger(s.frame) || !Number.isFinite(s.width) || !Number.isFinite(s.height) || s.width<=0 || s.height<=0){add('snapshot','missing/invalid probe');return {issues};}
 if(s.schemaVersion!==2||!Array.isArray(s.occluders))add('schema','missing ink/occluder schema');
 if(s.fontsOk!==true)add('fonts','fonts not ready');
 if(!Array.isArray(s.fields)||!s.fields.length){add('fields','missing text measurements');return {issues};}
 const visible=[];
 for(const f of s.fields){
  if(!f.id || !f.text || !['read','label'].includes(f.role)||!Number.isFinite(f.opacity)||!Number.isFinite(f.fontSize)||!Array.isArray(f.rects)||!f.rects.length||!f.rects.every(finiteRect)){add('geometry',f.id);continue;}
  if(s.schemaVersion===2&&(!finiteRect(f.box)||!Array.isArray(f.inkRects)||!f.inkRects.length||!f.inkRects.every(finiteRect))){add('geometry',f.id);continue;}
  if(f.opacity<t.visibleOpacity)continue;
  if(f.fontSize<(f.role==='label'?t.labelFontPx:t.readFontPx)-.01)add('font',f.id);
  if(f.clipped||(f.inkRects??[]).some(r=>(f.clipBoxes??[]).some(c=>r.x<c.x-.5||r.y<c.y-.5||r.x+r.width>c.x+c.width+.5||r.y+r.height>c.y+c.height+.5)))add('clip',f.id);
  for(const r of (f.inkRects??f.rects))if(r.x<s.width*t.safeFraction-.5 || r.y<s.height*t.safeFraction-.5 || r.x+r.width>s.width*(1-t.safeFraction)+.5 || r.y+r.height>s.height*(1-t.safeFraction)+.5)add('safe',f.id);
  if(s.footage?.layout==='full'&&['source','stock','ai'].includes(s.footage.origin)&&f.backed!==true)add('backing',f.id);
  if(f.id==='caption'&&f.captionBlankFirstLine===true)add('caption-blank-line','blank first line enlarges caption pill');
  if(f.id==='caption'&&f.captionExpectedText!==undefined&&f.text!==f.captionExpectedText.trim())add('caption-text','rendered caption differs from display text');
  if(f.id==='caption'&&s.captionLane&&((s.captionLane==='top'&&f.box.y+f.box.height>540)||(s.captionLane==='bottom'&&f.box.y<540)))add('caption-lane',f.id);
  visible.push(f);
 }
 for(let i=0;i<visible.length;i++)for(let j=i+1;j<visible.length;j++){
  const a=visible[i],b=visible[j];
  // Only a genuine crossfade of the same logical field is exempt, never chip/headline.
  if(s.transition===true&&a.id===b.id&&new Set([a.layer,b.layer]).size===2&&[a.layer,b.layer].every(l=>['previous','current'].includes(l)))continue;
  if((a.inkRects??a.rects).some(r=>(b.inkRects??b.rects).some(q=>intersects(r,q))))add('overlap',`${a.id}/${b.id}`);
 }
 const covered=new Set();
 for(const o of s.occluders??[]){
  if(!finiteRect(o.box)||!Number.isFinite(o.opacity)||!Array.isArray(o.frontOf)){add('geometry','occluder '+o.id);continue;}
  if(o.opacity<t.visibleOpacity)continue;
  for(const field of visible)if(o.frontOf.includes(field.id)&&(field.inkRects??field.rects).some(r=>intersects(r,o.box))){add('occlusion',`${o.id}/${field.id}`);covered.add(field.id);}
 }
 const f=s.footage;
 if(!f || !['source','stock','ai','avatar','typo','endcard'].includes(f.origin))add('footage','missing provenance measurement');
 else {
  if(f.origin==='source'&&(!visible.some(x=>x.id==='source-credit'&&!x.clipped&&!covered.has(x.id)&&finiteRect(x.box)) || !f.src?.startsWith('yt_')))add('credit','source missing visible credit/path');
  if(f.origin==='stock'&&(f.chrome||f.credit||visible.some(x=>['source-credit','source-url'].includes(x.id))))add('stock-chrome','stock misattribution');
  if(f.origin==='stock'&&(f.src?.startsWith('yt_')||f.src?.startsWith('ai_')))add('origin','stock path mismatch');
  if(f.origin==='ai'){
   if(!f.src?.startsWith('ai_'))add('origin','AI path mismatch');
   if(f.chrome||f.credit||visible.some(x=>['source-credit','source-url'].includes(x.id)))add('ai-chrome','AI misattribution');
   if(!visible.some(x=>x.id==='ai-label'&&x.text==='ภาพประกอบ AI'&&!x.clipped&&!covered.has(x.id)))add('ai-label','missing visible AI label');
  }
 }
 return {issues};
}
export function validateSamples(expected,samples){
 const issues=[];const counts=new Map();
 for(const s of samples){if(!s||!expected.includes(s.frame))issues.push({code:'wrong-frame',frame:s?.frame});else counts.set(s.frame,(counts.get(s.frame)||0)+1);}
 for(const f of expected)if(counts.get(f)!==1)issues.push({code:'sample-count',frame:f,count:counts.get(f)||0});
 return issues;
}

export function backingPresent(backing,inkRects){return !!backing&&backing.alpha>=.9&&backing.opacity>0&&backing.sameVisibilityAncestry===true&&finiteRect(backing.box)&&inkRects.length>0&&inkRects.every(r=>r.x>=backing.box.x-.5&&r.y>=backing.box.y-.5&&r.x+r.width<=backing.box.x+backing.box.width+.5&&r.y+r.height<=backing.box.y+backing.box.height+.5);}

// Subtract protected glyph hulls (already expanded by measured padding) from overlap.
export function emptyBackingRegions(box,protectedRects){
 let regions=[box];
 for(const p of protectedRects){const next=[];for(const r of regions){
  const x=Math.max(r.x,p.x),y=Math.max(r.y,p.y),right=Math.min(r.x+r.width,p.x+p.width),bottom=Math.min(r.y+r.height,p.y+p.height);
  if(right<=x||bottom<=y){next.push(r);continue;}
  for(const q of [{x:r.x,y:r.y,width:r.width,height:y-r.y},{x:r.x,y:bottom,width:r.width,height:r.y+r.height-bottom},{x:r.x,y,width:x-r.x,height:bottom-y},{x:right,y,width:r.x+r.width-right,height:bottom-y}])if(q.width>0&&q.height>0)next.push(q);
 }regions=next;}return regions;
}
export function evaluateAvatarBackingSweep(windows,samples,fps,t,{requireComplete=true}={}){
 const issues=[],runs=[],coverage=[];const add=(code,detail)=>issues.push({code,detail});
 if(!Array.isArray(windows)||!Number.isFinite(fps)||fps<=0||![t.avatarEmptyMinArea,t.avatarEmptyMinDimension,t.avatarEmptyMaxSeconds,t.visibleOpacity].every(Number.isFinite)){add('sweep-incomplete','missing sweep plan/fps/thresholds');return {complete:false,issues,runs,coverage};}
 const expected=new Set();for(const w of windows){if(!w.id||!Number.isInteger(w.startFrame)||!Number.isInteger(w.endFrame)||w.endFrame<w.startFrame){add('sweep-incomplete','invalid window');continue;}for(let f=w.startFrame;f<=w.endFrame;f++)expected.add(f);}
 const counts=new Map();for(const s of samples){if(!s||!expected.has(s.frame)){add('sweep-incomplete','frame outside sweep');continue;}counts.set(s.frame,(counts.get(s.frame)||0)+1);}
 let complete=true;
 for(const w of windows){
  const frames=Array.from({length:w.endFrame-w.startFrame+1},(_,i)=>w.startFrame+i),present=frames.filter(f=>counts.has(f));
  const covered=frames.every(f=>counts.get(f)===1);coverage.push({id:w.id,beatT:w.beatT,startFrame:w.startFrame,endFrame:w.endFrame,expected:frames.length,observed:present.length,complete:covered});
  if(!covered){complete=false;if(requireComplete||present.length)add('sweep-incomplete',w.id);}
  const active=new Map();
  const flush=(id,endDirty=false)=>{const run=active.get(id);if(!run)return;active.delete(id);const nframes=run.lastFrame-run.firstFrame+1;const record={...run,beatT:w.beatT,windowId:w.id,id,nframes,duration:nframes/fps,unbounded:endDirty};runs.push(record);if(endDirty||record.duration>t.avatarEmptyMaxSeconds)issues.push({code:endDirty?'avatar-empty-backing-unbounded':'avatar-empty-backing',...record});};
  for(const frame of frames){
   const s=samples.find(s=>s?.frame===frame),dirty=new Map();
   if(counts.get(frame)!==1||!s) {for(const id of active.keys())flush(id);continue;}
   const measure=s.avatarBacking;
   if(s.fontsOk!==true||!measure||!finiteRect(measure.avatar?.box)||!Number.isFinite(measure.avatar.opacity)||!Array.isArray(measure.candidates)){add('sweep-incomplete','missing measurement/font at '+frame);complete=false;for(const id of active.keys())flush(id);continue;}
   const ids=new Set();
   for(const c of measure.candidates){
    if(!c.id||ids.has(c.id)||!finiteRect(c.box)||!Number.isFinite(c.opacity)||!c.background||!Number.isFinite(c.background.alpha)||typeof c.background.image!=='string'||!Array.isArray(c.emptyRegions)||!Array.isArray(c.protectedRects)||!c.protectedRects.every(finiteRect)){add('sweep-incomplete','invalid candidate at '+frame);complete=false;continue;}ids.add(c.id);
    if(measure.avatar.opacity<t.visibleOpacity||c.opacity<t.visibleOpacity||!(c.background.alpha>t.visibleOpacity||c.background.image!=='none'))continue;
    const aboveRegions=[];
    for(const r of c.emptyRegions){
     const e=r.paintOrderEvidence;
     if(!finiteRect(r)||!e||typeof e.above!=='boolean'||![e.x,e.y,e.candidateIndex,e.avatarIndex].every(Number.isFinite)){add('sweep-incomplete','missing paint order at '+frame);complete=false;continue;}
     if(e.above&&e.candidateIndex>=0&&e.avatarIndex>=0&&e.candidateIndex<e.avatarIndex)aboveRegions.push(r);
    }
    if(aboveRegions.length){
     const area=aboveRegions.reduce((sum,r)=>sum+r.width*r.height,0);
     const width=Math.max(...aboveRegions.map(r=>r.x+r.width))-Math.min(...aboveRegions.map(r=>r.x));
     const height=Math.max(...aboveRegions.map(r=>r.y+r.height))-Math.min(...aboveRegions.map(r=>r.y));
     if(area>=t.avatarEmptyMinArea&&Math.max(width,height)>=t.avatarEmptyMinDimension)dirty.set(c.id,area);
    }
   }
   for(const id of [...active.keys()])if(!dirty.has(id))flush(id);
   for(const [id,area] of dirty){const old=active.get(id);active.set(id,{firstFrame:old?.firstFrame??frame,lastFrame:frame,maxEmptyPx:Math.max(old?.maxEmptyPx??0,area)});}
  }
  for(const id of [...active.keys()])flush(id,true);
 }
 return {complete:complete&&!issues.some(i=>i.code==='sweep-incomplete'),issues,runs,coverage,fps};
}
