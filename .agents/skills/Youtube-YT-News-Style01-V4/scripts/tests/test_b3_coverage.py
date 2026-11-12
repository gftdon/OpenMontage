import copy
import http.client
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import batch_relevance as b
import native_paid as n
import score_relevance as s
import broll_costs as bc
import broll_plan as bp
FIXTURES=Path(__file__).resolve().parent/'fixtures/a67/broll'
JPEG=b'\xff\xd8\xff\xc0\x00\x0b\x08\x02\x40\x04\x00\x01\x01\x11\x00\xff\xd9'
class CoverageTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name).resolve();c=bc.load_config();a={'approved':True,'project':str(self.p),'config_sha256':bc.config_sha256(),'caps':c['caps'],**{k:{x:c[k][x] for x in ('provider','model')} for k in ('image','relevance')}};self.budget=bc.Budget(self.p,a,today='2026-11-08');self.identity={'origin':'stock','identity':'pixabay:1','cue_ids':['c1'],'context_sha256':'a'*64};self.row={'id':'one','frame':JPEG,'spoken':'spoken','identity':self.identity}
 def prepared(self,diagnostic=False):
  media=self.p/'stock.mp4';media.write_bytes(b'media');records={'stock':{'pixabay_id':'1','sha256':s.file_sha256(media),'duration':3}};plan={'beats':[{'id':'one','t':0,'end':2,'spoken':'spoken','cue_ids':['c1']}]};ctx={'timing_inputs':{},'narration_cues':[]}
  episode=bp.load_v4_episode(FIXTURES/'one-stock-beat.json')
  with patch.object(b,'validate_plan',return_value=[]),patch.object(b,'reconcile_plan',return_value=[]),patch.object(b,'probe_duration',return_value=3),patch.object(s,'extract_frame',return_value=JPEG):return b.prepare_rows(plan,ctx,episode,records,self.p,self.p/'frames',self.budget.config,diagnostic)
 def live(self,rows,complete=True):
  return b.run_rows(self.budget,rows,self.p/'run',count_runner=lambda *_:{'totalTokens':10},generate_runner=lambda *_:{'candidates':[{'content':{'parts':[{'text':'{"score":2,"reason":"matches"}'}]}}],'usageMetadata':{'promptTokenCount':10,'candidatesTokenCount':10,'totalTokenCount':20}},key_identity='same-key',complete=complete)
 def test_plain_or_diagnostic_cannot_be_promoted_by_complete_flag(self):
  plain=self.live([self.row]);self.assertFalse(plain['complete']);self.assertFalse(plain['pass'])
  prepared=self.prepared(True);result=self.live(prepared);self.assertFalse(result['complete']);self.assertFalse(result['pass'])
 def test_full_prepared_acceptance_and_deleted_row_rejected(self):
  prepared=self.prepared();result=self.live(prepared,False);self.assertTrue(result['complete']);self.assertTrue(result['pass'])
  prepared.pop();result=self.live(prepared);self.assertFalse(result['complete']);self.assertFalse(result['pass']);self.assertTrue(result['coverage_errors'])
 def test_positive_native_cache_survives_stop_without_recount(self):
  result=self.live([self.row]);self.assertEqual(result['results'][0]['score'],2);self.budget.stop('explicit STOP')
  result=b.run_rows(self.budget,[self.row],self.p/'stopped',count_runner=lambda *_:self.fail('count'),generate_runner=lambda *_:self.fail('generate'),key_identity='same-key')
  self.assertEqual(result['results'][0]['score'],2);self.assertTrue(result['results'][0]['cached'])
 def test_count_http_exception_is_precheck_stop_no_paid(self):
  def count(*_):raise http.client.IncompleteRead(b'PRIVATE_KEY')
  result=b.run_rows(self.budget,[self.row],self.p/'error',count_runner=count,generate_runner=lambda *_:self.fail('paid'),key_identity='same-key')
  self.assertFalse(self.budget.path.exists());self.assertEqual(result['results'][0]['status'],'unverified_budget');self.assertNotIn('PRIVATE_KEY',json.dumps(result))
 def test_opposite_origin_variant_rejected_before_reserve_or_call(self):
  for request_origin,identity in [('stock',{'origin':'ai','identity':'image-sha256:'+'a'*64,'cue_ids':['c1'],'context_sha256':'b'*64}),('ai',self.identity)]:
   request=self.p/(request_origin+'.json');raw=s.native_request_bytes(JPEG,'spoken',self.budget.config,request_origin);request.write_bytes(raw);count=self.p/(request_origin+'-count.json');count.write_text(json.dumps({'operation':'countTokens','model':'models/gemini-3.8-flash','payload_sha256':s.digest(raw),'http_status':200,'generate_called':False,'totalTokens':10}));binding=n.bind_count_receipt(request,count,self.budget.config,'relevance','same-key')
   with self.assertRaises(bc.StopPaid):n.execute_exact(self.budget,'relevance',request,binding,'same-key',lambda *_:self.fail('paid'),identity=identity)
   self.assertFalse(self.budget.path.exists())
