import copy
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
JPEG=b'\xff\xd8\xff\xe1\x00\x03a\xff\xc0\x00\x0b\x08\x02\x40\x04\x00\x01\x01\x11\x00\xff\xd9'
import broll_costs as bc
import score_relevance as sr
import broll_plan as bp
def historical_config():return json.loads((Path(__file__).parent/'fixtures/recovery1-config.json').read_text())
def legacy_setup(self):
 from unittest.mock import patch
 mock=patch('broll_costs.load_config',side_effect=historical_config);mock.start();self.addCleanup(mock.stop)

class ReviewTests(unittest.TestCase):
 def setUp(self):
  legacy_setup(self)
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name);self.c=bc.load_config()
  self.a={'approved':True,'project':str(self.p.resolve()),'caps':self.c['caps'],**{k:{x:self.c[k][x] for x in ('provider','model')} for k in ('image','relevance')},'config_sha256':bc.config_sha256(self.c)}
 def budget(self):return bc.Budget(self.p,self.a,today='2026-11-08')
 def reply(self,score,usage=None):return {'outputs':[{'type':'text','text':json.dumps({'score':score,'reason':'test reason'})}],'usage':usage}
 def identity(self,name='123'):return {'origin':'stock','identity':'pixabay:'+name,'sha256':'a'*64,'cue_ids':['c1'],'context_sha256':'b'*64}
 def test_exceeded_receipt_raises_reservation_and_stops_both_kinds_persistently(self):
  b=self.budget();r=b.reserve('relevance');b.receipt(r['id'],'ok',{'input_tokens':40000,'output_tokens':2000})
  row=json.loads(b.path.read_text())['attempts'][0];self.assertAlmostEqual(row['reserved_usd'],.0375);self.assertTrue(row['exposure_exceeded'])
  for kind in ('image','relevance'):
   with self.assertRaises(bc.StopPaid):self.budget().reserve(kind)
 def test_ambiguous_usage_flags_and_concurrent_next_reservations_stop(self):
  b=self.budget();r=b.reserve('relevance');b.receipt(r['id'],'ok',{'input_tokens':-1,'output_tokens':2});row=json.loads(b.path.read_text())['attempts'][0];self.assertTrue(row['usage_ambiguous']);self.assertEqual(row['reserved_usd'],r['reserved_usd'])
  admitted=[]
  def attempt():
   try:admitted.append(self.budget().reserve('image'))
   except bc.StopPaid:pass
  ts=[threading.Thread(target=attempt) for _ in range(8)]
  for t in ts:t.start()
  for t in ts:t.join()
  self.assertEqual(admitted,[])
 def test_approval_hash_covers_rate_changes_even_if_caps_unchanged(self):
  b=self.budget();self.a['config_sha256']='0'*64
  with self.assertRaises(bc.StopPaid):b.reserve('image')
  self.a['config_sha256']=bc.config_sha256(self.c);r=b.reserve('image');self.assertEqual(r['config_sha256'],self.a['config_sha256'])
 def test_usage_null_valid_zero_persisted_and_stops_without_retry(self):
  b=self.budget();calls=[]
  def run(*_):calls.append(1);return self.reply(0)
  result=sr.score_asset(b,JPEG,'spoken',self.identity(),runner=run,exposure_verified=True)
  self.assertEqual(result['score'],0);self.assertEqual(result['status'],'fail');self.assertTrue(result['stop_paid_reason']);self.assertEqual(len(calls),1)
  self.assertTrue(sr.hard_failure([sr.score_asset(self.budget(),JPEG.replace(b'a',b'b',1),'spoken',self.identity())]))
 def test_receipt_errors_never_retry_or_erase_valid_score(self):
  for index,error in enumerate((bc.StopPaid('journal refused'),OSError('disk failed'))):
   with self.subTest(error=type(error).__name__):
    (self.p/'artifacts/broll-costs.json').unlink(missing_ok=True)
    b=self.budget();calls=[]
    def receipt(*_,**__):raise error
    b.receipt=receipt
    def run(*_):calls.append(1);return self.reply(0)
    result=sr.score_asset(b,JPEG.replace(b'a',bytes([65+index]),1),'spoken',self.identity(),runner=run,exposure_verified=True)
    self.assertEqual(result['score'],0);self.assertTrue(result['stop_paid_reason']);self.assertEqual(len(calls),1)
 def test_usage_unknown_thinking_or_inconsistent_total_is_ambiguous(self):
  for usage in (None,[],{'total_input_tokens':1,'total_output_tokens':2}, {'total_input_tokens':1,'total_output_tokens':2,'total_thought_tokens':3,'total_tokens':99}):
   score,accounting=sr.parse_reply(self.reply(2,usage));self.assertEqual(score['score'],2);self.assertIsNone(accounting)
  for total in (3,6):
   score,u=sr.parse_reply(self.reply(2,{'total_input_tokens':1,'total_output_tokens':2,'total_thought_tokens':3,'total_tokens':total}));self.assertEqual(u['output_tokens'],5)
 def test_known_zero_survives_frame_from_changes_until_valid_rescore_or_replacement(self):
  b=self.budget();good={'total_input_tokens':100,'total_output_tokens':20,'total_thought_tokens':3,'total_tokens':123}
  zero=sr.score_asset(b,JPEG,'spoken',self.identity(),runner=lambda *_:self.reply(0,good),exposure_verified=True);self.assertEqual(zero['score'],0)
  changed=self.identity();changed['frame_spec']={'from':.04,'punch':1.2}
  pending=sr.score_asset(self.budget(),JPEG.replace(b'a',b'c',1),'changed words',changed);self.assertEqual(pending['score'],0);self.assertEqual(pending['status'],'fail')
  replacement=sr.score_asset(self.budget(),JPEG.replace(b'a',b'c',1),'spoken',self.identity('456'));self.assertIsNone(replacement['score']);self.assertTrue(replacement['replacement_log'])
  # Original zero can only be resolved with a new valid score for the same context/identity.
  resolved=sr.score_asset(self.budget(),JPEG.replace(b'a',b'd',1),'spoken',changed,runner=lambda *_:self.reply(2,good),exposure_verified=True);self.assertEqual(resolved['score'],2)
  self.assertIsNone(sr.score_asset(self.budget(),JPEG.replace(b'a',b'e',1),'spoken',changed)['score'])
 def test_decoded_fingerprint_never_replaces_stable_identity_or_origin(self):
  for origin in (None,'soucre','source','stock','ai'):
   u={'t':0,'end':1,'from':0,'duration':3,'media':'broll','origin':origin,'decoded_sha256':'a'*64}
   self.assertTrue(bp.check_usage([u])['violations'])
 def test_request_payload_bounds_all_text_and_high_image(self):
  body=sr.request_body(JPEG,'6 วินาที',self.c);self.assertEqual(body['input'][1]['resolution'],'high');self.assertEqual(self.c['relevance']['max_jpeg_bytes'],262144)
  with self.assertRaises(ValueError):sr.request_body(b'x'*262145,'hello',self.c)
  with self.assertRaises(ValueError):sr.request_body(JPEG,'ก'*4000,self.c)
 def test_jpeg_dimensions_invalid_or_exceed_cap_rejected(self):
  jpeg=lambda w,h:b'\xff\xd8\xff\xc0\x00\x0b\x08'+h.to_bytes(2,'big')+w.to_bytes(2,'big')+b'\x01\x01\x11\x00\xff\xd9'
  self.assertEqual(sr.jpeg_dimensions(jpeg(1024,576)),(1024,576))
  with self.assertRaises(ValueError):sr.request_body(jpeg(1025,576),'hello',self.c)
  with self.assertRaises(ValueError):sr.request_body(b'not jpeg','hello',self.c)
 def test_stop_survives_actual_process_restart(self):
  import subprocess
  b=self.budget();r=b.reserve('relevance');b.receipt(r['id'],'ok',None)
  args=json.dumps({'project':str(self.p),'approval':self.a})
  code="import sys,json;sys.path.insert(0,sys.argv[1]);import broll_costs as b;b.load_config=lambda:json.load(open(sys.argv[1]+'/tests/fixtures/recovery1-config.json'));x=json.loads(sys.argv[2]);b.Budget(x['project'],x['approval'],today='2026-11-08').reserve('image')"
  result=subprocess.run([sys.executable,'-I','-c',code,str(Path(bc.__file__).parent),args],capture_output=True,text=True)
  self.assertNotEqual(result.returncode,0);self.assertIn('usage ambiguous',result.stderr)
 def test_inflight_relevance_blocks_all_admission_until_receipt(self):
  b=self.budget();b.reserve('relevance')
  with self.assertRaises(bc.StopPaid):self.budget().reserve('image')
 def test_stale_zero_cache_does_not_undo_later_valid_resolution(self):
  b=self.budget();good={'total_input_tokens':100,'total_output_tokens':20,'total_thought_tokens':3,'total_tokens':123}
  sr.score_asset(b,JPEG,'spoken',self.identity(),runner=lambda *_:self.reply(0,good),exposure_verified=True)
  sr.score_asset(b,JPEG.replace(b'a',b'z',1),'spoken',self.identity(),runner=lambda *_:self.reply(2,good),exposure_verified=True)
  stale=sr.score_asset(b,JPEG,'spoken',self.identity());self.assertIsNone(stale['score'])
 def test_malformed_reply_never_retries_after_lead_no_retry_rule(self):
  b=self.budget();calls=[];good={'total_input_tokens':100,'total_output_tokens':20,'total_thought_tokens':3,'total_tokens':123}
  def run(*_):
   calls.append(1)
   if len(calls)==1:return {'outputs':[{'type':'text','text':'truncated{'}],'usage':good}
   return self.reply(2,good)
  result=sr.score_asset(b,JPEG,'spoken',self.identity(),runner=run,exposure_verified=True);self.assertIsNone(result['score']);self.assertEqual(len(calls),1)
 def test_score_two_ambiguous_usage_keeps_verdict_but_stops_paid(self):
  b=self.budget();r=sr.score_asset(b,JPEG,'spoken',self.identity(),runner=lambda *_:self.reply(2,None),exposure_verified=True)
  self.assertEqual(r['score'],2);self.assertEqual(r['status'],'pass');self.assertEqual(r['budget_status'],'STOP_PAID')
  with self.assertRaises(bc.StopPaid):self.budget().reserve('image')
 def test_rate_edit_same_caps_invalidates_preexisting_approval(self):
  from unittest.mock import patch
  changed=copy.deepcopy(self.c);changed['relevance']['input_usd_per_million']=.01
  with patch.object(bc,'load_config',return_value=changed):
   with self.assertRaises(bc.StopPaid):bc.Budget(self.p,self.a,changed,today='2026-11-08').reserve('image')
 def test_manifest_identity_derives_valid_origin_and_namespace_not_caller_override(self):
  beats=[{'t':0,'end':1,'media':'broll','mode':'pip','origin':'stock','src':'s','identity':'pixabay:999'}]
  records={'s':{'pixabay_id':'123','duration':3,'sha256':'a'*64}}
  self.assertEqual(bp.derive_usage(beats,records)[0]['identity'],'pixabay:123')
  self.assertEqual(bp.manifest_identity('source',{'source_sha256':'a'*64}),'source:'+'a'*64)
  self.assertEqual(bp.manifest_identity('ai',{'image_sha256':'b'*64}),'image-sha256:'+'b'*64)
  for origin,record in [('source',{'source_sha256':'abc'}),('ai',{'image_sha256':'xyz'}),('stock',{'pixabay_id':'abc'}),('soruce',{})]:
   with self.assertRaises(ValueError):bp.manifest_identity(origin,record)
 def test_sync_avatar_hash_cannot_be_optional_bypassed(self):
  c={'timing_authority':'existing-word-spine','timing_inputs':{'wordTimingSha256':'a'*64,'scriptSha256':'b'*64},'inputs':{'w':'a'*64,'s':'b'*64},'sync_verification':{'status':'accepted','reference':'x','wordTimingSha256':'a'*64,'scriptSha256':'b'*64,'avatarSha256':'c'*64}}
  self.assertTrue(bp.validate_sync(c))
