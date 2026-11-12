#!/usr/bin/env python3
"""V4 native relevance preview/batch (reads episode.json). No default paid transport or credentials.
Main injects count(raw_generate_bytes,model) and generate(raw_generate_bytes,model).
"""
import argparse
import json
import http.client
import sys
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import score_relevance as sr
import native_paid as native
from broll_costs import Budget,StopPaid,config_sha256
from broll_plan import validate_plan,reconcile_plan,load_v4_episode,probe_duration,file_sha256,manifest_identity,check_usage,derive_usage
from media_manifest import save_json

def rows_digest(rows):
 values=[{**{k:v for k,v in row.items() if k!='frame'},'frame_sha256':sr.digest(row['frame'])} for row in rows]
 return sr.digest(json.dumps(values,sort_keys=True,ensure_ascii=False).encode())

class PreparedRows(list):
 """Coverage evidence created only after prepare_rows reconciles actual inputs."""
 def __init__(self,rows,coverage):
  super().__init__(rows);self._coverage=coverage;self._coverage_digest=sr.digest(json.dumps(coverage,sort_keys=True).encode());self._prepared_digest=rows_digest(rows)
 def coverage_status(self):
  errors=[]
  if sr.digest(json.dumps(self._coverage,sort_keys=True).encode())!=self._coverage_digest:errors.append('prepared coverage metadata changed')
  if rows_digest(self)!=self._prepared_digest:errors.append('prepared row content/coverage changed')
  if [r['id'] for r in self]!=self._coverage['full_plan_ids']:errors.append('prepared plan IDs missing/reordered')
  return not errors and self._coverage['complete'],errors

def prepare_rows(plan,context,episode,records,public_dir,out_dir,config,diagnostic_subset=False):
 """`episode` is the dict from broll_plan.load_v4_episode (beats, vo_end, broll_dur, sha256)."""
 beats=episode['beats'];vo=episode['vo_end'];errors=validate_plan(plan,context)+reconcile_plan(plan,beats,records,diagnostic_subset,vo)
 if errors:raise ValueError('; '.join(errors))
 table=episode['broll_dur'];public=Path(public_dir);out=Path(out_dir);out.mkdir(parents=True,exist_ok=True);actual={}
 for beat in beats:
  if beat.get('mode')=='full' or beat.get('media') not in ('clip','broll'):continue
  name=beat['src'];record=records[name];media=public/(name+'.mp4')
  if file_sha256(media)!=record.get('sha256'):raise ValueError(name+': stale media hash')
  actual[name]=probe_duration(media)
 usage=derive_usage(beats,records,vo,actual,table);violations=check_usage(usage)['violations']
 if violations:raise ValueError('; '.join(violations))
 context_hash=sr.digest(json.dumps({'timing_inputs':context['timing_inputs'],'narration_cues':context['narration_cues']},sort_keys=True,ensure_ascii=False).encode());rows=[]
 for item in plan['beats']:
  beat=next(b for b in beats if b['t']==item['t']);beat={**beat,'end':item['end']};src=beat['src'];record=records[src];spec=sr.frame_spec(beat,table[src]);frame_path=out/(sr.digest(item['id'].encode())+'.jpg');frame=sr.extract_frame(public/(src+'.mp4'),spec,frame_path,config)
  identity={'origin':beat['origin'],'identity':manifest_identity(beat['origin'],record),'sha256':record['sha256'],'cue_ids':item['cue_ids'],'context_sha256':context_hash,'frame_spec':spec}
  if beat['origin']=='source':identity['source_sha256']=record['source_sha256']
  if beat['origin']=='ai':identity['image_sha256']=record['image_sha256']
  rows.append({'id':item['id'],'t':item['t'],'end':item['end'],'spoken':item['spoken'],'frame':frame,'frame_path':str(frame_path.resolve()),'identity':identity})
 coverage={'complete':not diagnostic_subset,'full_plan_ids':[item['id'] for item in plan['beats']],'plan_sha256':sr.digest(json.dumps(plan,sort_keys=True,ensure_ascii=False).encode()),'context_sha256':context_hash,'episode_sha256':episode['sha256'],'manifest_sha256':sr.digest(json.dumps(records,sort_keys=True,ensure_ascii=False).encode())}
 return PreparedRows(rows,coverage)

def run_rows(budget,rows,out_dir,count_runner=None,generate_runner=None,key_identity=None,complete=False):
 coverage_complete,coverage_errors=rows.coverage_status() if isinstance(rows,PreparedRows) else (False,['unbound rows: prepare_rows full reconciliation required'])
 out=Path(out_dir);out.mkdir(parents=True,exist_ok=True);report={'coverage_errors':coverage_errors,'schema':'a44-native-batch-1','runId':uuid.uuid4().hex,'complete':coverage_complete,'paid_enabled':count_runner is not None and generate_runner is not None,'results':[],'config_sha256':config_sha256(budget.config)};stop_reason=sr.durable_stop_reason(budget)
 for row in rows:
  frame=row['frame'];identity=row['identity'];origin=identity['origin'];request=sr.native_request_bytes(frame,row['spoken'],budget.config,origin);identity={**identity,'native_payload_sha256':sr.digest(request)};name=sr.digest(row['id'].encode());request_path=out/(name+'.request.json');request_path.write_bytes(request)
  # Always inspect judgement/history, even after stop; known failure never auto-resends.
  result=sr.score_asset(budget,frame,row['spoken'],identity)
  if result.get('score') is None and result.get('readable_text') is not True and not stop_reason and count_runner is not None and generate_runner is not None:
   try:
    model='models/'+budget.config['relevance']['model'];raw_count=count_runner(request,model)
    if not isinstance(raw_count,dict) or type(raw_count.get('totalTokens')) is not int or raw_count.get('http_status',200)!=200:raise StopPaid('countTokens failed/invalid')
    count={'operation':'countTokens','model':model,'payload_sha256':sr.digest(request),'generate_called':False,'http_status':200,'totalTokens':raw_count['totalTokens'],'response':{'totalTokens':raw_count['totalTokens']},'key_identity':key_identity}
    count_path=out/(name+'.count.json');save_json(count_path,count);binding=native.bind_count_receipt(request_path,count_path,budget.config,'relevance',key_identity)
    save_json(out/(name+'.binding.json'),binding)
    result=native.execute_exact(budget,'relevance',request_path,binding,key_identity,generate_runner,identity=identity)
    stop_reason=sr.durable_stop_reason(budget)
   except (StopPaid,sr.WireError,OSError,http.client.HTTPException) as error:
    stop_reason='precheck/admission stopped: '+type(error).__name__
    result=sr.score_asset(budget,frame,row['spoken'],identity)
    result['reason']=stop_reason;result['status']='unverified_budget' if result.get('score') is None else result['status'];result['budget_status']='STOP_PAID'
  if stop_reason:result['budget_stop_reason']=stop_reason
  result['verification_status']=sr.verification_status(result,origin)
  report['results'].append({'beat':row['id'],'t':row.get('t'),'end':row.get('end'),'spoken_lines':row['spoken'].splitlines(),'cue_ids':identity['cue_ids'],'source_identity':identity['identity'],'request_sha256':sr.digest(request),'frame_path':row.get('frame_path'),**result})
 report['coverage']={'total':len(rows),'valid':sum(type(r.get('score')) is int for r in report['results']),'unverified':sum(r.get('score') is None for r in report['results']),'failures':sum(r.get('score')==0 or r.get('readable_text') is True for r in report['results'])}
 report['verification_status']=sr.aggregate_verification_status(report['results'],coverage_complete)
 report['pass']=coverage_complete and bool(rows) and report['coverage']['unverified']==0 and not sr.hard_failure(report['results']);report['budget_stop_reason']=stop_reason;save_json(out/'report.json',report);return report

def main():
 ap=argparse.ArgumentParser(description=__doc__)
 for key in ('project','plan','context','beats','manifest','cuts','public','out'):ap.add_argument('--'+key,required=True)
 ap.add_argument('--diagnostic-subset',action='store_true');a=ap.parse_args();config=Budget(a.project,None).config;records=json.loads(Path(a.manifest).read_text());cuts=json.loads(Path(a.cuts).read_text());records.update(cuts.get('clips',cuts));out=Path(a.out)
 try:
  rows=prepare_rows(json.loads(Path(a.plan).read_text()),json.loads(Path(a.context).read_text()),load_v4_episode(a.beats),records,a.public,out/'frames',config,a.diagnostic_subset)
  # Preview does NOT inspect or mutate real outcome/journal state; requests + rows only.
  summary=[]
  for row in rows:
   body=sr.native_request_bytes(row['frame'],row['spoken'],config,row['identity']['origin']);request_path=out/(sr.digest(row['id'].encode())+'.request.json');request_path.write_bytes(body);summary.append({k:v for k,v in row.items() if k!='frame'}|{'request_sha256':sr.digest(body),'verification_status':'unverified'})
  save_json(out/'preview.json',{'schema':'a44-native-batch-1','status':'offline_preview','verification_status':'unverified','complete':not a.diagnostic_subset,'pass':False,'paid_calls':0,'rows':summary})
 except (ValueError,OSError) as error:
  save_json(out/'preview.json',{'status':'invalid_plan_or_media','verification_status':'failed','complete':False,'pass':False,'paid_calls':0,'error':str(error)});return 1
 return 0
if __name__=='__main__':raise SystemExit(main())
