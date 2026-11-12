import React,{useLayoutEffect} from 'react';
import {Composition,registerRoot} from 'remotion';
import {YtNewsStyle01V4} from '../../../../../../remotion-composer/src/YtNewsStyle01V4';
// Negative fixture only. No test injection interface exists in the production composition.
const Fixture:React.FC<{scenario?:string}>=({scenario='opaque'})=>{
 useLayoutEffect(()=>{
  const root=document.querySelector('[data-qc-root]') as HTMLElement;if(!root)throw Error('fixture root missing');
  if(scenario==='missing-backing'){
   const css=document.createElement('style');css.textContent='[data-qc-backing]{background:transparent!important}';root.append(css);return()=>css.remove();
  }
  if(scenario==='hidden-credit'){
   const css=document.createElement('style');css.textContent='[data-qc-field="source-credit"]{opacity:0!important}';root.append(css);return()=>css.remove();
  }
  const el=document.createElement('div');el.style.position='absolute';el.style.zIndex='200';
  if(scenario==='opaque'){
   el.dataset.qcOccluder='negative-pointer-none-image';el.style.cssText+=';left:116px;top:712px;width:600px;height:54px;background:#fff;pointer-events:none';
   const image=document.createElement('img');image.src='data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="600" height="54"><rect width="600" height="54" fill="white"/></svg>';image.style.width='100%';el.append(image);
  }else if(scenario==='thai-clip'){
   el.style.cssText+=';left:300px;top:300px;width:400px;height:18px;overflow:hidden';
   const text=document.createElement('div');text.dataset.qcField='negative-thai';text.dataset.qcRole='read';text.textContent='น้ำพึ่งรู้ที่นี่';text.style.cssText='font-family:KanitX;font-size:40px;font-weight:800;line-height:1.5';el.append(text);
  }else if(scenario==='thai-ink-only'){
   el.style.cssText+=';left:300px;top:300px;width:1100px;height:60px;overflow:hidden';
   const text=document.createElement('div');text.dataset.qcField='thai-ink-only';text.dataset.qcRole='read';text.textContent='นิ้วปั้น น้ำพึ่งรู้ที่นี่ ปี่กุ้ง จิ๋ว พื้นที่ ตั้งขึ้น';text.style.cssText='font-family:KanitX;font-size:40px;font-weight:800;line-height:1.5';el.append(text);
  }else if(scenario==='thai-metrics'){
   el.style.cssText+=';left:300px;top:300px;width:1100px';
   const text=document.createElement('div');text.dataset.qcField='thai-metrics';text.dataset.qcRole='read';text.textContent='นิ้วปั้น น้ำพึ่งรู้ที่นี่ ปี่กุ้ง จิ๋ว พื้นที่ ตั้งขึ้น';text.style.cssText='font-family:KanitX;font-size:40px;font-weight:800;line-height:1.5';el.append(text);
  }else if(scenario==='stock-url'){
   el.dataset.qcField='source-url';el.dataset.qcRole='label';el.textContent='youtube.com/source';el.style.cssText+=';left:300px;top:300px;font:700 24px KanitX;color:white';
  }
  root.append(el);return()=>el.remove();
 },[scenario]);
 return <YtNewsStyle01V4 qcMeasure qcPlan/>;
};
registerRoot(()=> <Composition id="NegativeDom" component={Fixture} width={1920} height={1080} fps={25} durationInFrames={8525} defaultProps={{scenario:'opaque'}}/>);
