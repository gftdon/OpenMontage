import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import broll_costs as bc
import native_paid as n
import score_relevance as s
JPEG=b'\xff\xd8\xff\xc0\x00\x0b\x08\x02\x40\x04\x00\x01\x01\x11\x00\xff\xd9'
ROOT=Path(__file__).resolve().parents[5]
class B3Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name).resolve();c=bc.load_config();a={'approved':True,'project':str(self.p),'config_sha256':bc.config_sha256(),'caps':c['caps'],**{k:{x:c[k][x] for x in ('provider','model')} for k in ('image','relevance')}};self.b=bc.Budget(self.p,a,today='2026-11-08')
 def identity(self,asset='a',origin='ai'):return {'origin':origin,'identity':'image-sha256:'+asset*64 if origin=='ai' else 'pixabay:1','cue_ids':['c1'],'context_sha256':'b'*64}
 def reply(self,score,readable):return {'outputs':[{'type':'text','text':json.dumps({'score':score,'reason':'tested','readable_text':readable})}],'usage':{'total_input_tokens':10,'total_output_tokens':10,'total_thought_tokens':0,'total_tokens':20}}
 def test_ai_true_fail_false_one_warning_zero_fail_single_call(self):
  for i,(score,readable,status) in enumerate(((2,True,'fail'),(1,False,'warning'),(0,False,'fail'))):
   calls=[]
   def run(*_):calls.append(1);return self.reply(score,readable)
   result=s.score_asset(self.b,JPEG,'spoken',self.identity(chr(97+i)),runner=run,exposure_verified=True)
   self.assertEqual(result['status'],status);self.assertEqual(result['readable_text'],readable);self.assertEqual(len(calls),1);self.assertEqual(result['prompt_version'],'a44-relevance-ai-1')
   self.assertEqual(s.hard_failure([result]),status=='fail')
 def test_ai_missing_or_nonbool_invalid(self):
  for value in (None,'false',0):
   raw=self.reply(2,value)
   with self.assertRaises(ValueError):s.parse_reply(raw,variant='ai')
  raw=self.reply(2,False);raw['outputs'][0]['text']='{"score":2,"reason":"ok"}'
  with self.assertRaises(ValueError):s.parse_reply(raw,variant='ai')
 def test_readable_reject_survives_new_crop_stop_and_newasset_not_inherited(self):
  ident=self.identity();s.score_asset(self.b,JPEG,'spoken',ident,runner=lambda *_:self.reply(2,True),exposure_verified=True);self.b.stop('budget stop')
  changed={**ident,'frame_spec':{'from':.04}}
  result=s.score_asset(self.b,JPEG,'changed',changed);self.assertEqual(result['status'],'fail');self.assertTrue(result['readable_text']);self.assertTrue(s.hard_failure([result]))
  self.assertIsNone(s.score_asset(self.b,JPEG,'spoken',self.identity('c'))['score'])
 def test_valid_new_ai_call_false_resolves_readable_rejection_with_history(self):
  ident=self.identity();s.score_asset(self.b,JPEG,'spoken',ident,runner=lambda *_:self.reply(2,True),exposure_verified=True)
  changed={**ident,'frame_spec':{'from':.04}};result=s.score_asset(self.b,JPEG,'new spoken',changed,runner=lambda *_:self.reply(1,False),exposure_verified=True)
  self.assertEqual(result['status'],'warning');pending=s.score_asset(self.b,JPEG,'uncached',ident);self.assertFalse(s.hard_failure([pending]));self.assertIsNone(pending['score'])
  ledger=json.loads((self.p/'artifacts/relevance-outcomes.json').read_text());self.assertTrue(ledger['resolutions'])
 def test_batch_ai_success_has_one_count_one_generate_and_strict_bool(self):
  import batch_relevance as b
  rows=[{'id':'ai1','frame':JPEG,'spoken':'spoken','identity':self.identity()}];calls=[]
  def count(raw,model):calls.append('count');return {'totalTokens':10}
  def generate(raw,model):
   calls.append('generate');self.assertIn('readable_text',json.loads(raw)['generationConfig']['responseJsonSchema']['required'])
   return {'candidates':[{'content':{'parts':[{'text':'{"score":1,"reason":"partial","readable_text":false}'}]}}],'usageMetadata':{'promptTokenCount':10,'candidatesTokenCount':10,'totalTokenCount':20}}
  report=b.run_rows(self.b,rows,self.p/'batch',count_runner=count,generate_runner=generate,key_identity='same-key',complete=True)
  self.assertEqual(calls,['count','generate']);self.assertEqual(report['results'][0]['status'],'warning');self.assertFalse(report['pass']);self.assertFalse(report['complete'])  # plain rows are diagnostic, not reconciled acceptance
 def test_native_base_canonical_bytes_match_observed_old_request(self):
  p=ROOT/'projects/v261107-001-yt-news-v3-broll-test/qc/recovery-precheck';raw=(p/'relevance-generate-request.json').read_bytes();body=json.loads(raw);frame=base64.b64decode(body['contents'][0]['parts'][1]['inlineData']['data']);spoken=json.loads(body['contents'][0]['parts'][0]['text'])['spoken']
  self.assertEqual(s.native_request_bytes(frame,spoken,self.b.config,'stock'),raw)
  base=s.request_body(JPEG,'spoken',self.b.config);self.assertEqual(base['system_instruction'],s.SYSTEM);self.assertEqual(set(base['response_format']['schema']['properties']),{'score','reason'})
 def test_ai_schema_count_mismatch_rejected(self):
  body=s.native_request_bytes(JPEG,'spoken',self.b.config,'ai');req=self.p/'ai.json';req.write_bytes(body);count=self.p/'count.json';count.write_text(json.dumps({'operation':'countTokens','model':'models/gemini-3.8-flash','payload_sha256':'0'*64,'http_status':200,'generate_called':False,'totalTokens':20}))
  with self.assertRaises(bc.StopPaid):n.bind_count_receipt(req,count,self.b.config,'relevance','same-key')
 def test_batch_free_count_failure_no_paid_reservation(self):
  import batch_relevance as b
  rows=[{'id':'ai1','frame':JPEG,'spoken':'spoken','identity':self.identity()}];calls=[]
  def count(*_):calls.append('count');raise s.WireError('precheck_failed')
  def generate(*_):self.fail('paid must not run')
  report=b.run_rows(self.b,rows,self.p/'batch',count_runner=count,generate_runner=generate,key_identity='same-key',complete=True)
  self.assertEqual(calls,['count']);self.assertEqual(report['results'][0]['status'],'unverified_budget');self.assertFalse(self.b.path.exists());self.assertFalse(report['pass'])
 def test_batch_one_call_for_ai_both_checks_and_remaining_known_zero_still_checked(self):
  import batch_relevance as b
  bad=self.identity('d');s.score_asset(self.b,JPEG,'spoken',bad,runner=lambda *_:self.reply(0,False),exposure_verified=True)
  rows=[{'id':'first','frame':JPEG,'spoken':'spoken','identity':self.identity()},{'id':'known','frame':JPEG,'spoken':'changed','identity':bad}];calls=[]
  def count(raw,model):return {'totalTokens':10}
  def generate(raw,model):calls.append(1);raise s.WireError('auth',auth=True)
  report=b.run_rows(self.b,rows,self.p/'batch',count_runner=count,generate_runner=generate,key_identity='same-key',complete=True)
  self.assertEqual(len(calls),1);self.assertEqual(report['results'][1]['score'],0);self.assertFalse(report['pass'])
 def test_prepare_rows_full_reconcile_actual_manifest_and_no_avatar_card(self):
  import batch_relevance as b
  from unittest.mock import patch
  media=self.p/'stock.mp4';media.write_bytes(b'media');context={'timing_inputs':{'wordTimingSha256':'a'*64,'scriptSha256':'b'*64},'narration_cues':[{'id':'c1','start':0,'end':2,'text':'spoken'}],'inputs':{'w':'a'*64,'s':'b'*64},'timing_authority':'existing-word-spine','sync_verification':{'status':'accepted','reference':'test','wordTimingSha256':'a'*64,'scriptSha256':'b'*64}}
  plan={'schema':'a44-broll-plan-1','beats':[{'id':'b1','t':0,'end':2,'cue_ids':['c1'],'spoken':'spoken','query':'specific scene','semantic_rationale':'shows scene','selected':{'tier':'stock','path':'stock.mp4','identity':'pixabay:1'},'rejected_tiers':[{'tier':'source','reason':'no matching source'},{'tier':'ai','reason':'real scene preferred'}]}]};beats=[{'t':0,'end':2,'src':'stock','origin':'stock','mode':'pip','media':'broll','layout':'full'},{'t':2,'mode':'full'},{'t':4,'mode':'pip','media':'typo','src':'card'}];records={'stock':{'pixabay_id':'1','sha256':s.file_sha256(media),'duration':3}}
  with patch('broll_ledger.parse_beats',return_value=beats),patch.object(b,'probe_duration',return_value=3),patch.object(b,'parse_renderer_durations',return_value={'stock':3}),patch.object(s,'extract_frame',return_value=JPEG):
   rows=b.prepare_rows(plan,context,'const VO_END_SEC = 6;',records,self.p,self.p/'frames',self.b.config)
   self.assertEqual(len(rows),1);self.assertEqual(rows[0]['identity']['identity'],'pixabay:1');self.assertEqual(rows[0]['identity']['cue_ids'],['c1']);self.assertEqual(rows[0]['identity']['sha256'],s.file_sha256(media))
   changed=json.loads(json.dumps(plan));changed['beats'][0]['selected']['identity']='pixabay:2'
   with self.assertRaises(ValueError):b.prepare_rows(changed,context,'const VO_END_SEC = 6;',records,self.p,self.p/'frames',self.b.config)
 def test_http_failed_count_response_zero_generate_and_ai_true_single_native_call(self):
  import batch_relevance as b
  row={'id':'ai','frame':JPEG,'spoken':'spoken','identity':self.identity()};calls=[]
  report=b.run_rows(self.b,[row],self.p/'failed-count',count_runner=lambda *_:{'http_status':400,'totalTokens':10},generate_runner=lambda *_:self.fail('paid'),key_identity='same-key',complete=True)
  self.assertEqual(report['coverage']['unverified'],1);self.assertFalse(self.b.path.exists())
  def generate(*_):calls.append(1);return {'candidates':[{'content':{'parts':[{'text':'{"score":2,"reason":"text visible","readable_text":true}'}]}}],'usageMetadata':{'promptTokenCount':10,'candidatesTokenCount':10,'totalTokenCount':20}}
  report=b.run_rows(self.b,[row],self.p/'true',count_runner=lambda *_:{'totalTokens':10},generate_runner=generate,key_identity='same-key',complete=True);self.assertEqual(len(calls),1);self.assertFalse(report['pass']);self.assertTrue(report['results'][0]['readable_text']);self.assertEqual(report['results'][0]['native_usage_metadata']['totalTokenCount'],20)
 def test_resolved_readable_rejection_with_different_cues_no_longer_pending(self):
  ident=self.identity();s.score_asset(self.b,JPEG,'spoken',ident,runner=lambda *_:self.reply(2,True),exposure_verified=True)
  expanded={**ident,'cue_ids':['c1','c2']};s.score_asset(self.b,JPEG,'expanded',expanded,runner=lambda *_:self.reply(2,False),exposure_verified=True)
  result=s.score_asset(self.b,JPEG,'uncached',ident);self.assertFalse(s.hard_failure([result]));self.assertIsNone(result['score'])
 def test_diagnostic_never_full_pass(self):
  import batch_relevance as b
  report=b.run_rows(self.b,[],self.p/'batch',complete=False);self.assertFalse(report['pass']);self.assertFalse(report['complete'])
