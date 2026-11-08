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
  if(s.footage?.layout==='full'&&['source','stock'].includes(s.footage.origin)&&f.backed!==true)add('backing',f.id);
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
 if(!f || !['source','stock','avatar','typo','endcard'].includes(f.origin))add('footage','missing provenance measurement');
 else {
  if(f.origin==='source'&&(!visible.some(x=>x.id==='source-credit'&&!x.clipped&&!covered.has(x.id)&&finiteRect(x.box)) || !f.src?.startsWith('yt_')))add('credit','source missing visible credit/path');
  if(f.origin==='stock'&&(f.chrome||f.credit||visible.some(x=>['source-credit','source-url'].includes(x.id))))add('stock-chrome','stock misattribution');
  if(f.origin==='stock'&&f.src?.startsWith('yt_'))add('origin','yt_ stock mismatch');
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
