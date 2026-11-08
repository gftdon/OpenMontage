#!/usr/bin/env python3
"""V3 images-only adapter. Dry-run default; never loads .env or discovers tools.
Direct registry.get + tool.execute avoids registry retry wrappers. Imagen.execute
performs one requests.post (retry_policy is metadata, not an execution loop).
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from broll_costs import Budget,StopPaid
from broll_plan import file_sha256,probe_duration
from media_manifest import save_json

def registry_tool(root):
 # No discover(): discovery implicitly loads .env. Register exact existing adapter.
 sys.path.insert(0,str(Path(root).resolve()))
 from tools.tool_registry import registry
 from tools.graphics.google_imagen import GoogleImagen
 if registry.get('google_imagen') is None:registry.register(GoogleImagen())
 return registry.get('google_imagen')

def still_to_mp4(image,output,duration):
 subprocess.run(['ffmpeg','-v','error','-y','-loop','1','-i',str(image),'-t',str(duration),'-vf','scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=25','-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p','-an',str(output)],check=True)

def classify_image_error(error):
 """Allowlisted facts only: never retain raw provider strings, URLs or credentials."""
 text=str(error).lower();match=re.search(r'(?<!\d)(401|403|404|410|429|5\d\d)(?!\d)',text);status=int(match[1]) if match else None
 if status in (401,403) or any(x in text for x in ('unauthorized','credentials','authentication','permission denied')):category='auth'
 elif status in (404,410) or any(x in text for x in ('model not found','retired','model unavailable')):category='model_unavailable'
 elif status==429 or 'rate limit' in text:category='rate_limit'
 elif isinstance(error,TimeoutError) or 'timeout' in text or 'timed out' in text:category='timeout'
 elif 'no images' in text or 'output file missing' in text:category='no_image'
 elif status is not None and status>=500:category='provider_unavailable'
 else:category='unknown'
 messages={'auth':'Provider authentication/permission unavailable; do not change credentials automatically.','model_unavailable':'Approved model unavailable; no paid model substitution.','rate_limit':'Provider rate limited the attempt.','timeout':'Provider attempt timed out; billing/response uncertain.','no_image':'Provider returned no usable image output.','provider_unavailable':'Provider server unavailable.','unknown':'Image attempt cause unknown; raw error excluded from report.'}
 return {'error_category':category,'http_status':status,'sanitized_error':messages[category]}

def image_failure(budget,attempt,meta,error):
 facts=classify_image_error(error);report={'status':'unverified','fallback':'stock','severity':'warning','reason':'image attempt failed; reservation retained','attempt_id':attempt['id'],'budget_status':'STOP_PAID',**facts}
 # Record safe evidence before accounting writes; never retry the paid call.
 failure_path=meta.with_suffix('.failure.json');save_json(failure_path,report)
 try:budget.receipt(attempt['id'],'image_failed_'+facts['error_category'])
 except (StopPaid,OSError):report['journal_warning']='receipt persistence failed; do not retry'
 try:budget.stop('image '+facts['error_category']+'; Main review required before further calls')
 except (StopPaid,OSError):report['journal_warning']='stop persistence failed; do not retry'
 save_json(failure_path,report);return report

def generate(budget,name,prompt,style,gen_dir,public_dir,duration,tool=None,transcode=still_to_mp4,probe=probe_duration):
 if not re.fullmatch(r'ai_[A-Za-z0-9_-]+',name) or not 0<duration<=10:raise ValueError('ai_ safe name and duration <=10 required')
 if not prompt.strip() or len(prompt+style)>4000:raise ValueError('bounded nonempty prompt required')
 gen=Path(gen_dir);pub=Path(public_dir);gen.mkdir(parents=True,exist_ok=True);pub.mkdir(parents=True,exist_ok=True)
 image=gen/(name+'.png');movie=pub/(name+'.mp4');meta=gen/(name+'.json')
 params={'prompt':(prompt+' '+style).strip(),'style':style,'model':budget.config['image']['model'],'aspect_ratio':'16:9','number_of_images':1}
 key=hashlib.sha256(json.dumps(params,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 old=json.loads(meta.read_text()) if meta.exists() else {}
 cached=old.get('cache_key')==key and image.is_file() and old.get('image_sha256')==file_sha256(image)
 if not cached:
  if budget.config['image']['provider']!='google_imagen':return {'status':'STOP_PAID','fallback':'stock','severity':'warning','reason':'replacement model requires exact pre-counted native generate_native; shared registry forbidden'}
  if tool is None:return {'status':'STOP_PAID','fallback':'stock','severity':'warning','reason':'registry unavailable; no implicit discovery/auth'}
  if params['model'] not in tool.input_schema.get('properties',{}).get('model',{}).get('enum',[]):return {'status':'STOP_PAID','fallback':'stock','severity':'warning','reason':'approved model missing/retired; no model substitution'}
  try:attempt=budget.reserve('image')
  except StopPaid as e:return e.warning
  try:
   # Exactly one execute invocation per reservation, no retry wrapper.
   result=tool.execute({k:v for k,v in params.items() if k!='style'}|{'output_path':str(image)})
  except Exception as error:
   return image_failure(budget,attempt,meta,error)
  if not result.success:return image_failure(budget,attempt,meta,getattr(result,'error',None) or 'unknown tool failure')
  if not image.is_file():return image_failure(budget,attempt,meta,'image output file missing')
  budget.receipt(attempt['id'],'ok')
  old={'cache_key':key,'image_sha256':file_sha256(image),'cost_attempts':old.get('cost_attempts',[])+[attempt['id']],'parameters':params};save_json(meta,old)
 # Re-render locally if duration/bytes changed; no paid call for render changes.
 if not movie.is_file() or old.get('mp4_sha256')!=file_sha256(movie) or old.get('duration')!=duration:
  transcode(image,movie,duration)
 measured=probe(movie)
 if measured<=0 or measured>10+1/25:raise ValueError('actual AI clip exceeds hold ceiling')
 record={'schema':'a44-public-media-1','origin':'ai','image_sha256':file_sha256(image),'sha256':file_sha256(movie),'duration':measured,'path':str(movie.resolve()),'provider':params.get('provider','google_imagen'),'model':params['model'],'cost_attempts':old.get('cost_attempts',[]),'actual_usd':None,'provenance':{'image':str(image.resolve()),'cache_key':key}}
 old.update(mp4_sha256=record['sha256'],duration=duration);save_json(meta,old)
 path=pub/'_manifest.json';manifest=json.loads(path.read_text()) if path.exists() else {};manifest[name]=record;save_json(path,manifest)
 return {'status':'cache_hit' if cached else 'generated','manifest':record}

def generate_native(budget,name,request_path,count_binding,key_identity,gen_dir,public_dir,duration,runner=None,transcode=still_to_mp4,probe=probe_duration):
 """One exact native image call, then local still->MP4. Never registry/discover."""
 from native_paid import execute_exact
 if not re.fullmatch(r'ai_[A-Za-z0-9_-]+',name) or not 0<duration<=10:raise ValueError('safe ai_ name/duration required')
 gen=Path(gen_dir);pub=Path(public_dir);gen.mkdir(parents=True,exist_ok=True);pub.mkdir(parents=True,exist_ok=True)
 raw=Path(request_path).read_bytes();key=hashlib.sha256(raw).hexdigest();image=gen/(name+'.png');movie=pub/(name+'.mp4');meta=gen/(name+'.native.json');old=json.loads(meta.read_text()) if meta.exists() else {}
 cached=old.get('payload_sha256')==key and image.is_file() and old.get('image_sha256')==file_sha256(image)
 if not cached:
  result=execute_exact(budget,'image',request_path,count_binding,key_identity,runner)
  data=result.pop('image_bytes',None);save_json(gen/(name+'.native-result.json'),result)
  if not data:return {**result,'fallback':'stock','severity':'warning'}
  image.write_bytes(data);old={'payload_sha256':key,'image_sha256':file_sha256(image),'cost_attempts':old.get('cost_attempts',[])+[result['attempt_id']],'budget_status':result['budget_status']};save_json(meta,old)
 if not movie.is_file() or old.get('mp4_sha256')!=file_sha256(movie) or old.get('duration')!=duration:transcode(image,movie,duration)
 measured=probe(movie)
 if measured<=0 or measured>10+1/25:raise ValueError('AI duration exceeds hold bound')
 record={'origin':'ai','image_sha256':file_sha256(image),'sha256':file_sha256(movie),'duration':measured,'provider':budget.config['image']['provider'],'model':budget.config['image']['model'],'cost_attempts':old['cost_attempts'],'actual_usd':None,'provenance':{'payload_sha256':key,'image':str(image.resolve())}}
 path=pub/'_manifest.json';manifest=json.loads(path.read_text()) if path.exists() else {};manifest[name]=record;save_json(path,manifest);old.update(mp4_sha256=record['sha256'],duration=duration);save_json(meta,old)
 return {'status':'cache_hit' if cached else 'generated','budget_status':old.get('budget_status'),'manifest':record}

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--project',required=True);ap.add_argument('--shots',required=True);ap.add_argument('--approval');ap.add_argument('--public',required=True);ap.add_argument('--root');ap.add_argument('--execute',action='store_true');ap.add_argument('--out',required=True);a=ap.parse_args()
 shots=json.loads(Path(a.shots).read_text());approval=json.loads(Path(a.approval).read_text()) if a.approval else None;b=Budget(a.project,approval)
 if not a.execute:save_json(a.out,{'status':'offline_dry_run','provider':'google_imagen','model':b.config['image']['model'],'shots':list(shots['shots']),'network_calls':0});return
 if b.config['image']['provider']!='google_imagen':save_json(a.out,{'status':'STOP_PAID','reason':'use generate_native with exact counted request; legacy registry CLI disabled'});return
 tool=registry_tool(a.root) if a.root else None
 result={n:generate(b,n,s['image'],shots.get('style',''),Path(a.project)/'assets/generated',a.public,s.get('duration',8),tool=tool) for n,s in shots['shots'].items()};save_json(a.out,result)
 for name,row in result.items():
  print(json.dumps({'name':name,'status':row.get('status'),'error_category':row.get('error_category'),'http_status':row.get('http_status'),'attempt_id':row.get('attempt_id'),'sanitized_error':row.get('sanitized_error')},ensure_ascii=False))
if __name__=='__main__':main()
