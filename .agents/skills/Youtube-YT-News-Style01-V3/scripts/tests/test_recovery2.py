import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import broll_costs as bc
import native_paid as n
ROOT=Path(__file__).resolve().parents[5]
PROJECT=ROOT/'projects/v261107-001-yt-news-v3-broll-test'
class Recovery2Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name).resolve();self.c=bc.load_config();self.a={'approved':True,'project':str(self.p),'config_sha256':bc.config_sha256(),'caps':self.c['caps'],**{k:{x:self.c[k][x] for x in ('provider','model')} for k in ('image','relevance')}};self.b=bc.Budget(self.p,self.a,today='2026-11-08')
  self.j=json.loads((Path(__file__).parent/'fixtures/recovery2-journal-before.json').read_text());self.j['project']=str(self.p);self.original=copy.deepcopy(self.j);self.b.path.parent.mkdir(parents=True);self.b.path.write_text(json.dumps(self.j));self.raw=self.b.path.read_bytes();self.evidence=Path(__file__).parent/'fixtures/recovery2-image-summary.json'
  self.event={'id':'Lead-recovery-2','approved':True,'approver':'Lead','timestamp':'2026-11-08T14:00:00Z','reason':'explicit recovery2 maximum-rate settlement','old_stop_reason':self.j['stop_paid_reason'],'old_config_sha256':'ced183e9c209fe852ae4ab1743f53c51ed1e2bf06833bcccb2e1c978702cc7ec','new_config_sha256':bc.config_sha256(),'snapshot_sha256':bc.bytes_sha256(self.raw),'retained_attempt_ids':[e['id'] for e in self.j['attempts']],'evidence_sha256':bc.bytes_sha256(self.evidence.read_bytes())}
 def recover(self):return bc.apply_recovery2(self.b,self.event,self.evidence)
 def test_recovery_preserves_three_attempts_event1_and_settles_no_refund(self):
  result=self.recover();self.assertEqual(result['attempts'],self.original['attempts']);self.assertEqual(result['recovery_events'][0],self.original['recovery_events'][0]);self.assertEqual(len(result['recovery_events']),2)
  settlement=result['recovery_events'][1]['settlement'];self.assertAlmostEqual(settlement['estimated_usd'],.092909);self.assertEqual(settlement['output_cap_overrun'],11);self.assertEqual(settlement['unallocated_candidate_tokens'],427);self.assertAlmostEqual(sum(x['reserved_usd'] for x in result['attempts']),.18784)
  with self.assertRaises(bc.StopPaid):self.recover()
 def test_wrong_snapshot_chain_stop_ids_rejected_without_mutation(self):
  for field,value in [('snapshot_sha256','0'*64),('old_stop_reason','other'),('retained_attempt_ids',[]),('old_config_sha256','0'*64),('id','Lead-recovery-3'),('evidence_sha256','0'*64)]:
   with self.subTest(field=field):
    changed={**self.event,field:value}
    with self.assertRaises(bc.StopPaid):bc.apply_recovery2(self.b,changed,self.evidence)
    self.assertEqual(self.b.path.read_bytes(),self.raw)
  journal=copy.deepcopy(self.original);journal['recovery_events'][0]['new_config_sha256']='0'*64;self.b.path.write_text(json.dumps(journal));event={**self.event,'snapshot_sha256':bc.bytes_sha256(self.b.path.read_bytes())}
  with self.assertRaises(bc.StopPaid):bc.apply_recovery2(self.b,event,self.evidence)
 def test_recovery2_rejects_unapproved_historical_origin_config(self):
  journal=copy.deepcopy(self.original);journal['attempts'][2]['config_sha256']='0'*64;self.b.path.write_text(json.dumps(journal));event={**self.event,'snapshot_sha256':bc.bytes_sha256(self.b.path.read_bytes())}
  with self.assertRaises(bc.StopPaid):bc.apply_recovery2(self.b,event,self.evidence)
 def test_final_image_requires_actual_postevent2_relevance_then_only_one_image(self):
  self.recover()
  with self.assertRaises(bc.StopPaid):self.b.reserve('image',input_tokens=178)
  entry=self.b.reserve('relevance',input_tokens=1198);self.b.receipt(entry['id'],'ok',{'input_tokens':1198,'output_tokens':73})
  final=self.b.reserve('image',input_tokens=14000);self.assertEqual(final['reserved_usd'],.13);self.assertAlmostEqual(14000*.5/1e6+2048*60/1e6,.12988)
  with self.assertRaises(bc.StopPaid):self.b.reserve('image',input_tokens=1)
 def test_strict_stop_at_195(self):
  self.recover();rel=self.b.reserve('relevance',input_tokens=1);self.b.receipt(rel['id'],'ok',{'input_tokens':1,'output_tokens':1})
  with self.b.locked() as j:j['attempts'].append({'id':'budget-near','kind':'relevance','status':'ok','config_sha256':bc.config_sha256(),'reserved_usd':1.95-sum(e['reserved_usd'] for e in j['attempts'])-.13})
  with self.assertRaises(bc.StopPaid):self.b.reserve('image',input_tokens=178)
 def test_old_relevance_exact_payload_rebinds_new_hash(self):
  p=PROJECT/'qc/recovery-precheck';binding=n.bind_count_receipt(p/'relevance-generate-request.json',p/'relevance-count-result.json',self.c,'relevance','same-key')
  self.assertEqual(binding['input_tokens'],1198);self.assertEqual(binding['payload_sha256'],'0b135a4fe7f748b578af753fae6785009eb60e035e1a464866c9aa9054535220');self.assertEqual(binding['config_sha256'],bc.config_sha256())
 def test_image_all_output_maxrate_and_incomplete_breakdown_no_inference(self):
  self.recover();r=self.b.reserve('relevance',input_tokens=1);self.b.receipt(r['id'],'ok',{'input_tokens':1,'output_tokens':1});image=self.b.reserve('image',input_tokens=178)
  usage=n.image_accounting({'usageMetadata':{'promptTokenCount':178,'candidatesTokenCount':2059,'totalTokenCount':2237,'candidatesTokensDetails':[{'modality':'IMAGE','tokenCount':1120}]}})
  self.assertEqual(usage['output_tokens'],2059);self.assertTrue(usage['breakdown_unknown']);self.assertIsNone(self.b.receipt(image['id'],'native_image_ok',usage));row=json.loads(self.b.path.read_text())['attempts'][-1];self.assertTrue(row['output_cap_warning']);self.assertFalse(row['exposure_exceeded']);self.assertAlmostEqual(row['estimated_usd'],.123629)
 def test_native_relevance_first_actual_receipt_unlocks_image_missing_breakdown(self):
  import base64
  self.recover();pre=PROJECT/'qc/recovery-precheck';request=pre/'relevance-generate-request.json';bound=n.bind_count_receipt(request,pre/'relevance-count-result.json',self.c,'relevance','same-key')
  response={'candidates':[{'content':{'parts':[{'text':'{"score":2,"reason":"relevant"}'}]}}],'usageMetadata':{'promptTokenCount':1198,'candidatesTokenCount':73,'totalTokenCount':1271}}
  result=n.execute_exact(self.b,'relevance',request,bound,'same-key',lambda *_:response,identity={'origin':'stock','identity':'pixabay:1','cue_ids':['c1'],'context_sha256':'a'*64})
  self.assertEqual(result['score'],2);self.assertEqual(result['budget_status'],'reserved_with_usage')
  image=self.p/'image.json';body=json.loads((pre/'image-generate-request.json').read_text());body['generationConfig']['maxOutputTokens']=2048;image.write_text(json.dumps(body));count=self.p/'image-count.json';count.write_text(json.dumps({'operation':'countTokens','http_status':200,'generate_called':False,'model':body['model'],'payload_sha256':bc.bytes_sha256(image.read_bytes()),'totalTokens':178}));binding=n.bind_count_receipt(image,count,self.c,'image','same-key');calls=[]
  def run(*_):calls.append(1);return {'candidates':[{'content':{'parts':[{'inlineData':{'mimeType':'image/png','data':base64.b64encode(b'png').decode()}}]}}],'usageMetadata':{'promptTokenCount':178,'candidatesTokenCount':2059,'totalTokenCount':2237}}
  output=n.execute_exact(self.b,'image',image,binding,'same-key',run);self.assertEqual(len(calls),1);self.assertEqual(output['budget_status'],'reserved_with_usage');self.assertTrue(output['usage']['breakdown_unknown'])
 def test_image_invalid_details_totals_stop_and_above_reserve_raises_charge(self):
  for raw in ({'promptTokenCount':1,'candidatesTokenCount':2,'totalTokenCount':3,'candidatesTokensDetails':[{'modality':'IMAGE','tokenCount':3}]},{'promptTokenCount':1,'candidatesTokenCount':2,'totalTokenCount':3,'candidatesTokensDetails':[{'modality':'IMAGE','tokenCount':-1}]},{'promptTokenCount':1,'candidatesTokenCount':2,'totalTokenCount':4}):self.assertIsNone(n.image_accounting({'usageMetadata':raw}))
  self.recover();r=self.b.reserve('relevance',input_tokens=1);self.b.receipt(r['id'],'ok',{'input_tokens':1,'output_tokens':1});image=self.b.reserve('image',input_tokens=178)
  u=n.image_accounting({'usageMetadata':{'promptTokenCount':178,'candidatesTokenCount':3000,'totalTokenCount':3178}});self.assertTrue(self.b.receipt(image['id'],'native_image_ok',u));row=json.loads(self.b.path.read_text())['attempts'][-1];self.assertAlmostEqual(row['reserved_usd'],.180089)
