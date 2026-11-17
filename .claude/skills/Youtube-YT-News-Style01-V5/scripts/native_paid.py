#!/usr/bin/env python3
"""Exact pre-counted native GenerateContent admission. No HTTP, keys or recovery.
Main injects a one-call transport receiving original request bytes + exact model.
"""
import base64
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from broll_costs import StopPaid,config_sha256,bytes_sha256
from media_manifest import save_json

def validate_payload(body,config,kind):
 model='models/'+config[kind]['model']
 if body.get('model')!=model:raise StopPaid('exact approved native model required')
 contents=body.get('contents');generation=body.get('generationConfig',{})
 if not isinstance(contents,list) or len(contents)!=1 or contents[0].get('role')!='user':raise StopPaid('one native user contents required')
 if generation.get('maxOutputTokens')!=config[kind]['max_output_tokens']:raise StopPaid('native output cap mismatch')
 if set(body)-{'model','contents','systemInstruction','generationConfig'}:raise StopPaid('unsupported native request fields')
 if kind=='image':
  if generation!={'maxOutputTokens':config['image']['max_output_tokens'],'responseModalities':['IMAGE'],'imageConfig':{'aspectRatio':'16:9','imageSize':'1K'}}:raise StopPaid('image requires exact1K/16:9/'+str(config['image']['max_output_tokens'])+' IMAGE-only config')
  if any(set(p)!={'text'} or not isinstance(p['text'],str) for p in contents[0].get('parts',[])):raise StopPaid('image prompt must contain text only')
 else:
  import score_relevance as sr
  parts=contents[0].get('parts',[])
  if len(parts)!=2 or set(parts[0])!={'text'} or set(parts[1])!={'inlineData'}:raise StopPaid('one text + one typed image required')
  try:
   spoken=json.loads(parts[0]['text'])['spoken'];image=parts[1]['inlineData']
   if image.get('mimeType')!='image/jpeg':raise ValueError('jpeg required')
   system=body.get('systemInstruction',{}).get('parts',[{}])[0].get('text');variant='ai' if system==sr.SYSTEM+sr.AI_SYSTEM_SUFFIX else 'base'
   expected=sr.request_body(base64.b64decode(image['data'],validate=True),spoken,config,variant)
  except (ValueError,KeyError,TypeError):raise StopPaid('invalid bounded native relevance data')
  if body.get('systemInstruction')!={'parts':[{'text':expected['system_instruction']}]}:raise StopPaid('untrusted data system mismatch')
  if generation.get('responseJsonSchema')!=expected['response_format']['schema']:raise StopPaid('strict relevance schema mismatch')
  if generation.get('thinkingConfig')!={'thinkingLevel':'LOW'} or generation.get('responseMimeType')!='application/json' or not generation.get('responseJsonSchema'):raise StopPaid('native relevance bounded JSON/LOW required')
 return model

def bind_count_receipt(request_path,count_path,config,kind,key_identity):
 raw=Path(request_path).read_bytes();body=json.loads(raw);model=validate_payload(body,config,kind);count=json.loads(Path(count_path).read_text())
 if not key_identity or count.get('operation')!='countTokens' or count.get('http_status')!=200 or count.get('model')!=model or count.get('payload_sha256')!=bytes_sha256(raw) or count.get('generate_called') is not False:raise StopPaid('countTokens precheck failed or payload/model mismatch')
 if count.get('key_identity') and count['key_identity']!=key_identity:raise StopPaid('count key identity mismatch')
 tokens=count.get('totalTokens')
 if type(tokens) is not int or not 0<=tokens<=config[kind]['max_input_tokens_reserved']:raise StopPaid('counted input exceeds approved ceiling')
 return {'schema':'a44-count-binding-1','kind':kind,'model':model,'payload_sha256':bytes_sha256(raw),'count_receipt_sha256':bytes_sha256(Path(count_path).read_bytes()),'input_tokens':tokens,'config_sha256':config_sha256(config),'key_identity':key_identity,'http_status':200}

def transport_for_key(key,timeout_seconds=90):
 """Main passes in-memory key; never load/store credentials or retry requests."""
 import urllib.request
 import urllib.error
 import socket
 import http.client
 import score_relevance as sr
 def call(raw,model):
  if not model.startswith('models/') or '/' in model[len('models/'):]:raise StopPaid('unsafe native model path')
  request=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/'+model+':generateContent',data=raw,headers={'Content-Type':'application/json','x-goog-api-key':key},method='POST')
  try:
   with urllib.request.urlopen(request,timeout=timeout_seconds) as response:data=response.read(16*1024*1024+1)
  except urllib.error.HTTPError as e:
   status=e.code;category='auth' if status in (401,403) else 'model_unavailable' if status in (404,410) else 'rate_limit' if status==429 else 'provider_unavailable'
   raise sr.WireError(category,auth=category=='auth',diagnostic={'stage':'network','error_category':category,'http_status':status,'exit_code':None})
  except (urllib.error.URLError,OSError,http.client.HTTPException,TimeoutError,socket.timeout):raise sr.WireError('transport_unknown',diagnostic={'stage':'transport','error_category':'transport_unknown','http_status':None,'exit_code':None})
  if len(data)>16*1024*1024:raise sr.WireError('response_too_large')
  try:return json.loads(data)
  except (ValueError,UnicodeError):raise sr.WireError('unparseable_native_response',diagnostic={'stage':'parse','error_category':'unparseable_native_response','http_status':200,'exit_code':None})
 return call

def validate_binding(budget,kind,request_path,binding,key_identity):
 raw=Path(request_path).read_bytes();model=validate_payload(json.loads(raw),budget.config,kind)
 if binding.get('kind')!=kind or binding.get('model')!=model or binding.get('payload_sha256')!=bytes_sha256(raw) or binding.get('config_sha256')!=config_sha256(budget.config) or binding.get('key_identity')!=key_identity or binding.get('http_status')!=200:raise StopPaid('stale count receipt; recount exact payload/model/key/config')
 tokens=binding.get('input_tokens')
 if type(tokens) is not int or not 0<=tokens<=budget.config[kind]['max_input_tokens_reserved']:raise StopPaid('invalid counted input')
 return raw,model,tokens

def native_usage(raw):
 usage=raw.get('usageMetadata') if isinstance(raw,dict) else None
 if not isinstance(usage,dict):return None
 names=('promptTokenCount','candidatesTokenCount','totalTokenCount')
 if not all(type(usage.get(n)) is int and usage[n]>=0 for n in names):return None
 i,o,total=(usage[n] for n in names)
 if 'thoughtsTokenCount' not in usage:
  if total!=i+o:return None
  t=0  # Inferred ONLY from exact complete total equality, not field omission alone.
 else:
  t=usage['thoughtsTokenCount']
  if type(t) is not int or t<0:return None
 if total not in (i+o,i+o+t):return None
 return {'input_tokens':i,'output_tokens':o+t,'thought_tokens':t}

def image_accounting(raw):
 usage=native_usage(raw)
 if usage is None:return None
 metadata=raw['usageMetadata'];details=metadata.get('candidatesTokensDetails');candidate=metadata['candidatesTokenCount'];declared=0
 if details is not None:
  if not isinstance(details,list):return None
  for item in details:
   if not isinstance(item,dict) or item.get('modality') not in ('IMAGE','TEXT') or type(item.get('tokenCount')) is not int or item['tokenCount']<0:return None
   declared+=item['tokenCount']
  if declared>candidate:return None
 return {**usage,'breakdown_unknown':details is None or declared<candidate,'declared_candidate_tokens':declared,'unallocated_candidate_tokens':candidate-declared,'pricing_assumption':'ALL candidate+thought output at maximum output rate; no residual modality inference'}

def execute_exact(budget,kind,request_path,binding,key_identity,runner,identity=None):
 raw,model,tokens=validate_binding(budget,kind,request_path,binding,key_identity)
 if runner is None:raise StopPaid('no approved one-call native transport')
 if kind=='relevance':
  import score_relevance as sr
  body=json.loads(raw);parts=body['contents'][0]['parts'];text=next(p['text'] for p in parts if 'text' in p);image=next(p['inlineData'] for p in parts if 'inlineData' in p);spoken=json.loads(text)['spoken'];frame=base64.b64decode(image['data'],validate=True)
  expected_system=sr.SYSTEM+sr.AI_SYSTEM_SUFFIX if (identity or {}).get('origin')=='ai' else sr.SYSTEM
  if body.get('systemInstruction')!={'parts':[{'text':expected_system}]}:raise StopPaid('origin/schema variant mismatch')
  called=False;safe_usage=None
  def once(*_):
   nonlocal called,safe_usage
   if called:raise sr.WireError('one_call_batch_complete')
   called=True;reply=runner(raw,model)
   if not isinstance(reply,dict):raise sr.WireError('unparseable_native_response')
   # Keep original native response only in memory; never print inline image data.
   texts=[p['text'] for c in reply.get('candidates',[]) for p in c.get('content',{}).get('parts',[]) if 'text' in p]
   u=native_usage(reply);metadata=reply.get('usageMetadata')
   safe_usage={k:metadata[k] for k in ('promptTokenCount','candidatesTokenCount','thoughtsTokenCount','totalTokenCount') if k in metadata and type(metadata[k]) is int} if isinstance(metadata,dict) else None
   return {'outputs':[{'type':'text','text':t} for t in texts],'usage':None if u is None else {'total_input_tokens':u['input_tokens'],'total_output_tokens':u['output_tokens'],'total_thought_tokens':0,'total_tokens':u['input_tokens']+u['output_tokens']}}
  result=sr.score_asset(budget,frame,spoken,{**(identity or {}),'native_payload_sha256':binding['payload_sha256']},runner=once,exposure_verified=True,counted_input_tokens=tokens)
  if safe_usage is not None:result['native_usage_metadata']=safe_usage
  if result.get('attempt_id'):save_json(budget.project/'artifacts/count-bindings'/(result['attempt_id']+'.json'),binding)
  return result
 attempt=budget.reserve('image',input_tokens=tokens)
 save_json(budget.project/'artifacts/count-bindings'/(attempt['id']+'.json'),binding)
 try:reply=runner(raw,model)
 except Exception as error:
  import score_relevance as sr
  budget.receipt(attempt['id'],'failed_or_ambiguous');budget.stop('native image transport ambiguous; no automatic recovery2')
  diagnostic=getattr(error,'diagnostic',{'stage':'transport','error_category':'unknown','http_status':None,'exit_code':None})
  result={'status':'unverified','budget_status':'STOP_PAID','attempt_id':attempt['id'],'wire_diagnostic':diagnostic,'image_bytes':None,'actual_usd':None}
  save_json(budget.project/'artifacts/native-errors'/(attempt['id']+'.json'),result);return result
 images=[p['inlineData'] for c in reply.get('candidates',[]) for p in c.get('content',{}).get('parts',[]) if isinstance(p,dict) and 'inlineData' in p] if isinstance(reply,dict) else []
 usage=image_accounting(reply);details=reply.get('usageMetadata',{}).get('candidatesTokensDetails') if isinstance(reply,dict) and isinstance(reply.get('usageMetadata'),dict) else None
 valid_details=usage is not None and details is not None
 ambiguous=usage is None or not images
 stop=budget.receipt(attempt['id'],'native_image_ok' if images else 'native_no_image',usage)
 if stop:ambiguous=True
 if ambiguous:budget.stop('native image usage/modalities ambiguous; retained full reservation')
 data=None
 if len(images)==1 and images[0].get('mimeType') in ('image/png','image/jpeg'):
  try:data=base64.b64decode(images[0]['data'],validate=True)
  except (ValueError,KeyError):pass
 if not data:budget.stop('native image output missing/invalid')
 return {'status':'generated' if data else 'unverified','budget_status':'STOP_PAID' if ambiguous or not data else 'reserved_with_usage','attempt_id':attempt['id'],'image_bytes':data,'usage':usage,'usage_modalities':details if valid_details else None,'actual_usd':None}
