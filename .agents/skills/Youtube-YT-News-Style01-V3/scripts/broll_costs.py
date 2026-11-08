#!/usr/bin/env python3
"""Durable conservative reservation journal. No credentials, HTTP, or refunds."""
import contextlib
import datetime
import fcntl
import hashlib
import json
import math
import sys
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from media_manifest import save_json

class StopPaid(ValueError):
 def __init__(self,reason):
  super().__init__(reason);self.warning={'status':'STOP_PAID','fallback':'stock','severity':'warning','reason':reason}

def load_config():return json.loads((Path(__file__).with_name('broll_config.json')).read_text())
OLD_CONFIG_HASH='5dbcfcc7f2ab2e9e04ce5df93cdb4888c5f321a15715697e8a165d0d1bca5131'
RECOVERY1_CONFIG_HASH='ced183e9c209fe852ae4ab1743f53c51ed1e2bf06833bcccb2e1c978702cc7ec'
def bytes_sha256(data):return hashlib.sha256(data).hexdigest()
def config_sha256(config=None):
 """Canonical JSON UTF-8 bytes, stable under formatting but not value changes."""
 return hashlib.sha256(json.dumps(load_config() if config is None else config,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')).hexdigest()
def valid_number(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>=0

def recovery_chain(journal,current_hash):
 events=journal.get('recovery_events',[]);allowed={};waived=set()
 if len(events)>2:raise StopPaid('recovery3 forbidden')
 previous=OLD_CONFIG_HASH
 for index,event in enumerate(events,1):
  if event.get('id')!='Lead-recovery-'+str(index) or event.get('approved') is not True or event.get('approver')!='Lead' or event.get('old_config_sha256')!=previous:raise StopPaid('invalid recovery chain')
  if index==1 and event.get('new_config_sha256')!=RECOVERY1_CONFIG_HASH:raise StopPaid('recovery1 chain hash mismatch')
  for aid in event.get('retained_attempt_ids',[]):
   entry=next((e for e in journal['attempts'] if e['id']==aid),None)
   if entry is None or entry.get('config_sha256') not in (set(allowed.get(aid,[]))|{event['old_config_sha256']}):raise StopPaid('retained ID/origin config mismatch')
   allowed.setdefault(aid,set()).add(entry['config_sha256']);waived.add(aid)
  previous=event.get('new_config_sha256')
 if events and previous!=current_hash:raise StopPaid('latest recovery config mismatch')
 return allowed,waived

def validate(config,approval,project,today):
 canonical=load_config()
 # Pin every admission/rate/limit field; callers cannot enlarge exposure via env/config.
 if config!=canonical:raise StopPaid('unknown or modified rate/limits; Lead approval required')
 if not approval or approval.get('config_sha256')!=config_sha256(canonical):raise StopPaid('approval canonical config hash mismatch')
 r=config['relevance']
 if today>r['valid_until']:raise StopPaid('expired relevance rate')
 if not approval or approval.get('approved') is not True or approval.get('project')!=str(project.resolve()) or approval.get('caps')!=config['caps']:raise StopPaid('missing project/caps-bound approval')
 for kind in ('image','relevance'):
  if approval.get(kind)!={k:config[kind][k] for k in ('provider','model')}:raise StopPaid('approval provider/model mismatch')

class Budget:
 def __init__(self,project,approval,config=None,today=None):
  self.project=Path(project).resolve();self.approval=approval;self.config=config or load_config();self.today=today or datetime.date.today().isoformat();self.path=self.project/'artifacts/broll-costs.json'
 @contextlib.contextmanager
 def locked(self):
  self.path.parent.mkdir(parents=True,exist_ok=True)
  with self.path.with_suffix('.lock').open('a') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX)
   try:
    j=json.loads(self.path.read_text()) if self.path.exists() else {'schema':'a44-cost-journal-1','project':str(self.project),'attempts':[]}
    if j.get('project')!=str(self.project) or not isinstance(j.get('attempts'),list):raise StopPaid('invalid journal')
    yield j
    save_json(self.path,j)
   finally:fcntl.flock(lock,fcntl.LOCK_UN)
 def reserve(self,kind,input_tokens=None):
  validate(self.config,self.approval,self.project,self.today)
  if kind not in ('image','relevance'):raise StopPaid('unknown paid operation')
  r=self.config['relevance'];count=self.config[kind]['max_input_tokens_reserved'] if input_tokens is None else input_tokens
  if type(count) is not int or not 0<=count<=self.config[kind]['max_input_tokens_reserved']:raise StopPaid('invalid/excessive counted input tokens')
  if kind=='image':
   image=self.config['image'];worst=(count*image['input_usd_per_million']+image['max_output_tokens']*image['image_usd_per_million'])/1e6;amount=max(image['reservation_usd'],worst)
   if amount>image['reservation_usd']+1e-12:raise StopPaid('image worst-case exceeds approved reservation')
  else:amount=(count*r['input_usd_per_million']+r['max_output_tokens']*r['output_including_thinking_usd_per_million'])/1e6
  with self.locked() as j:
   if j.get('stop_paid_reason'):raise StopPaid(j['stop_paid_reason'])
   if any(x.get('kind')=='relevance' and x.get('status')=='reserved_ambiguous_until_receipt' for x in j['attempts']):raise StopPaid('in-flight relevance usage unresolved')
   allowed,retained=recovery_chain(j,config_sha256(self.config))
   if any(x.get('config_sha256')!=config_sha256(self.config) and x.get('config_sha256') not in allowed.get(x['id'],set()) for x in j['attempts']):raise StopPaid('journal config hash mismatch')
   if any((x.get('exposure_exceeded') or x.get('usage_ambiguous')) and x['id'] not in retained for x in j['attempts']):raise StopPaid('previous exposure/usage uncertainty requires review')
   if kind=='image' and self.config['caps']['image_attempts']==3:
    events=j.get('recovery_events',[])
    if len(events)!=2:raise StopPaid('final image requires explicit recovery2 and fresh relevance receipt')
    retained2=set(events[1]['retained_attempt_ids'])
    valid_rel=any(x['id'] not in retained2 and x.get('kind')=='relevance' and x.get('config_sha256')==config_sha256(self.config) and x.get('status')=='ok' and isinstance(x.get('usage'),dict) and all(type(x['usage'].get(k)) is int and x['usage'][k]>=0 for k in ('input_tokens','output_tokens')) and not x.get('usage_ambiguous') and not x.get('exposure_exceeded') for x in j['attempts'])
    if not valid_rel:raise StopPaid('real post-recovery2 relevance receipt required before final image')
   if any(not valid_number(x.get('reserved_usd')) for x in j['attempts']):raise StopPaid('invalid journal reservation')
   cap=self.config['caps']['image_attempts' if kind=='image' else 'relevance_calls']
   if sum(x['kind']==kind for x in j['attempts'])>=cap:raise StopPaid(kind+' attempt ceiling exhausted')
   if sum(x['reserved_usd'] for x in j['attempts'])+amount>=min(self.config['caps']['total_estimated_usd'],self.config['caps'].get('stop_reserve_usd',2))-1e-12:raise StopPaid('estimated budget exhausted')
   entry={'counted_input_tokens':input_tokens,'config_sha256':config_sha256(self.config),'id':uuid.uuid4().hex,'kind':kind,'provider':self.config[kind]['provider'],'model':self.config[kind]['model'],'status':'reserved_ambiguous_until_receipt','reserved_usd':amount,'estimated_usd':amount,'actual_usd':None,'rate':self.config[kind].copy()}
   j['attempts'].append(entry)
  return entry
 def stop(self,reason):
  with self.locked() as j:j['stop_paid_reason']=reason
 def receipt(self,attempt_id,status,usage=None):
  stop_reason=None
  with self.locked() as j:
   e=next(x for x in j['attempts'] if x['id']==attempt_id);e['status']=status
   r=self.config['relevance'];valid=isinstance(usage,dict) and all(type(usage.get(k)) is int and usage[k]>=0 for k in ('input_tokens','output_tokens'))
   e['usage_invalid']=usage is not None and not valid;e['usage']=usage if valid else None
   image_valid=e['kind']=='image' and valid
   e['usage_ambiguous']=(e['kind']=='relevance' and not valid) or (e['kind']=='image' and usage is not None and not image_valid)
   e['exposure_exceeded']=False
   if e['kind']=='relevance' and valid:
    estimate=(usage['input_tokens']*r['input_usd_per_million']+usage['output_tokens']*r['output_including_thinking_usd_per_million'])/1e6
    old=e['reserved_usd'];e['estimated_usd']=estimate;e['reserved_usd']=max(old,estimate)
    e['exposure_exceeded']=usage['input_tokens']>r['max_input_tokens_reserved'] or usage['output_tokens']>r['max_output_tokens'] or estimate>old+1e-12
   if image_valid:
    rate=self.config['image'];estimate=(usage['input_tokens']*rate['input_usd_per_million']+usage['output_tokens']*max(rate['image_usd_per_million'],rate['text_thinking_usd_per_million']))/1e6
    old=e['reserved_usd'];e['estimated_usd']=estimate;e['reserved_usd']=max(old,estimate)
    e['output_cap_warning']=usage['output_tokens']>rate['max_output_tokens']
    e['exposure_exceeded']=estimate>old+1e-12 or usage['input_tokens']>rate['max_input_tokens_reserved']
    e['pricing_assumption']='ALL candidate+thought output at maximum output rate; not billing'
   if e['usage_ambiguous'] or e['exposure_exceeded']:
    stop_reason='usage ambiguous' if e['usage_ambiguous'] else 'observed usage exceeded reservation'
    j['stop_paid_reason']=stop_reason
   e['actual_usd']=None
  return stop_reason


def apply_recovery(budget,approval):
 """Explicit one-time transition; never called by generation or admission."""
 validate(budget.config,budget.approval,budget.project,budget.today)
 with budget.locked() as journal:
  snapshot=bytes_sha256(budget.path.read_bytes())
  if journal.get('recovery_events'):raise StopPaid('recovery already used; no automatic recovery2')
  required={'id','approved','approver','timestamp','reason','old_stop_reason','old_config_sha256','new_config_sha256','snapshot_sha256','retained_attempt_ids'}
  if not isinstance(approval,dict) or not required<=set(approval) or approval['approved'] is not True or approval['id']!='Lead-recovery-1' or approval['approver']!='Lead' or not approval['timestamp'] or not approval['reason']:raise StopPaid('explicit Lead recovery1 approval required')
  import re
  timestamp=approval['timestamp']
  try:
   if not isinstance(timestamp,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})',timestamp):raise ValueError('timezone ISO8601 required')
   parsed=datetime.datetime.fromisoformat(timestamp.replace('Z','+00:00'))
   if parsed.utcoffset() is None:raise ValueError('timezone required')
  except ValueError:raise StopPaid('recovery timestamp must be ISO8601 with timezone')
  if approval['old_config_sha256']!=OLD_CONFIG_HASH or approval['new_config_sha256']!=config_sha256(budget.config) or approval['snapshot_sha256']!=snapshot or approval['old_stop_reason']!=journal.get('stop_paid_reason'):raise StopPaid('recovery snapshot/config/stop mismatch')
  attempts=journal['attempts'];ids=[e['id'] for e in attempts]
  if len(attempts)!=2 or sorted(e['kind'] for e in attempts)!=['image','relevance'] or set(ids)!=set(approval['retained_attempt_ids']) or any(e['config_sha256']!=OLD_CONFIG_HASH for e in attempts) or abs(sum(e['reserved_usd'] for e in attempts)-.08784)>1e-9:raise StopPaid('recovery only admits exact first two retained charged attempts')
  journal['recovery_events']=[dict(approval)];journal['stop_paid_reason']=None
  return journal


def apply_recovery2(budget,approval,evidence_path):
 """Lead-only exact recovery2; preserves attempts/event1 and forbids recovery3."""
 validate(budget.config,budget.approval,budget.project,budget.today)
 with budget.locked() as journal:
  raw=budget.path.read_bytes();events=journal.get('recovery_events',[]);attempts=journal['attempts']
  if len(events)!=1 or len(attempts)!=3:raise StopPaid('recovery2 requires exact3 attempts and recovery1 only')
  recovery_chain(journal,RECOVERY1_CONFIG_HASH)
  if not isinstance(approval,dict) or approval.get('id')!='Lead-recovery-2' or approval.get('approved') is not True or approval.get('approver')!='Lead' or not approval.get('reason'):raise StopPaid('explicit Lead recovery2 approval required')
  import re
  timestamp=approval.get('timestamp')
  try:
   if not isinstance(timestamp,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})',timestamp):raise ValueError()
   if datetime.datetime.fromisoformat(timestamp.replace('Z','+00:00')).utcoffset() is None:raise ValueError()
  except ValueError:raise StopPaid('recovery2 timestamp requires ISO8601 timezone')
  expected_stop='native image usage/modalities ambiguous; retained full reservation'
  if journal.get('stop_paid_reason')!=expected_stop or approval.get('old_stop_reason')!=expected_stop or approval.get('old_config_sha256')!=RECOVERY1_CONFIG_HASH or approval.get('new_config_sha256')!=config_sha256(budget.config) or approval.get('snapshot_sha256')!=bytes_sha256(raw):raise StopPaid('recovery2 snapshot/config/stop mismatch')
  ids=[e['id'] for e in attempts]
  expected_origins={'f12facc833714ad484b2bd8af0798ad9':OLD_CONFIG_HASH,'4c1fbe35c72d45d7ae93fc9e82699e5e':OLD_CONFIG_HASH,'7b316a3bb2dc46c6bf1706bc793e9817':RECOVERY1_CONFIG_HASH}
  if any(e.get('config_sha256')!=expected_origins.get(e['id']) for e in attempts):raise StopPaid('recovery2 historical origin config mismatch')
  expected_ids={'f12facc833714ad484b2bd8af0798ad9','4c1fbe35c72d45d7ae93fc9e82699e5e','7b316a3bb2dc46c6bf1706bc793e9817'}
  if set(ids)!=expected_ids or set(approval.get('retained_attempt_ids',[]))!=expected_ids or abs(sum(e['reserved_usd'] for e in attempts)-.18784)>1e-9:raise StopPaid('recovery2 exact retained attempts/charges required')
  evidence=Path(evidence_path);evidence_bytes=evidence.read_bytes()
  if approval.get('evidence_sha256')!=bytes_sha256(evidence_bytes):raise StopPaid('settlement evidence hash mismatch')
  response=json.loads(evidence_bytes);usage=response.get('usageMetadata',{})
  if response.get('modelVersion')!='gemini-3.1-flash-image' or usage.get('promptTokenCount')!=178 or usage.get('candidatesTokenCount')!=1547 or usage.get('totalTokenCount')!=1725 or usage.get('candidatesTokensDetails')!=[{'modality':'IMAGE','tokenCount':1120}] or 'thoughtsTokenCount' in usage or response.get('candidates',[{}])[0].get('finishReason')!='MAX_TOKENS':raise StopPaid('settlement evidence does not match approved response')
  settlement={'attempt_id':'7b316a3bb2dc46c6bf1706bc793e9817','evidence_sha256':bytes_sha256(evidence_bytes),'raw_usage':usage,'estimated_usd':(178*.5+1547*60)/1e6,'retained_reserved_usd':.10,'output_cap_overrun':11,'finish_reason':'MAX_TOKENS','unallocated_candidate_tokens':427,'assumptions':['missing thoughts proven0 by total178+1547=1725','ALL1547candidate output atMAX60/M; residual427 NOT classified as text','no refund/no historic attempt rewrite'],'actual_usd':None}
  event=dict(approval);event['settlement']=settlement;journal['recovery_events'].append(event);journal['stop_paid_reason']=None
  return journal
