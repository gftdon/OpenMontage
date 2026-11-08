"""Additive report contract; all provider interaction is local test stubs."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_b3_coverage as coverage_fixture
import test_noapproval_handoff as handoff_fixture
import score_relevance as s
import batch_relevance as b

class VerificationStatusTests(unittest.TestCase):
 setUp=coverage_fixture.CoverageTests.setUp
 prepared=coverage_fixture.CoverageTests.prepared
 live=coverage_fixture.CoverageTests.live
 def test_row_status_is_derived_not_trusted(self):
  cases=[({'score':1,'reason':'partial','status':'warning','verification_status':'failed'},'stock','verified'),({'score':0,'reason':'bad','verification_status':'verified'},'stock','failed'),({'score':2,'readable_text':True},'ai','failed'),({'score':2,'readable_text':False},'ai','verified'),({'score':2},'ai','unverified'),({'score':True},'stock','unverified'),({'score':None,'verification_status':'verified'},'stock','unverified'),({'score':2,'pending_zero':True},'stock','failed')]
  for result,origin,expected in cases:
   with self.subTest(result=result):self.assertEqual(s.verification_status(result,origin),expected)
 def test_warning_one_is_verified_and_cache_status_missing_or_stale_is_rederived(self):
  row=self.row;identity=row['identity']
  raw={'outputs':[{'type':'text','text':'{"score":1,"reason":"partial"}'}],'usage':{'total_input_tokens':10,'total_output_tokens':10,'total_thought_tokens':0,'total_tokens':20}}
  first=s.score_asset(self.budget,row['frame'],row['spoken'],identity,runner=lambda *_:raw,exposure_verified=True)
  self.assertEqual(first['status'],'warning');self.assertEqual(first['verification_status'],'verified')
  cache=self.p/'artifacts/relevance-cache'/(first['cache_key']+'.json');value=json.loads(cache.read_text())
  self.budget.stop('explicit STOP')
  for stale in (None,'failed','unverified'):
   value.pop('verification_status',None)
   if stale:value['verification_status']=stale
   cache.write_text(json.dumps(value))
   result=s.score_asset(self.budget,row['frame'],row['spoken'],identity)
   self.assertTrue(result['cached']);self.assertEqual(result['verification_status'],'verified')
 def test_full_batch_verified_but_plain_and_partial_unverified(self):
  full=self.prepared();report=self.live(full)
  self.assertEqual(report['verification_status'],'verified');self.assertEqual(report['results'][0]['verification_status'],'verified')
  self.budget.stop('STOP')
  cached=b.run_rows(self.budget,full,self.p/'cached')
  self.assertEqual(cached['verification_status'],'verified')
  plain=b.run_rows(self.budget,list(full),self.p/'plain',complete=True)
  self.assertEqual(plain['verification_status'],'unverified')
  full.pop();partial=b.run_rows(self.budget,full,self.p/'partial')
  self.assertEqual(partial['verification_status'],'unverified')
 def test_aggregate_failed_beats_unknown_and_structural_errors_fail(self):
  self.assertEqual(s.aggregate_verification_status([{'score':0},{'score':None}],False),'failed')
  self.assertEqual(s.aggregate_verification_status([],False,['invalid plan']),'failed')
  self.assertEqual(s.aggregate_verification_status([],True),'unverified')
  self.assertEqual(s.aggregate_verification_status([{'score':1,'media':{'origin':'stock'}}],True),'verified')
 def test_offline_preview_valid_unverified_invalid_failed_no_paid(self):
  args=['batch_relevance.py']
  for key in ('project','plan','context','beats','manifest','cuts','public','out'):
   path=self.p/key
   if key in ('plan','context','manifest','cuts'):path.write_text('{}')
   if key=='beats':path.write_text('const VO_END_SEC=1;')
   args += ['--'+key,str(path)]
  (self.p/'out').mkdir()  # Real prepare_rows creates the frames/output parent.
  with patch.object(sys,'argv',args),patch.object(b,'prepare_rows',return_value=[self.row]):self.assertEqual(b.main(),0)
  report=json.loads((self.p/'out/preview.json').read_text());self.assertEqual(report['verification_status'],'unverified');self.assertEqual(report['rows'][0]['verification_status'],'unverified');self.assertEqual(report['paid_calls'],0);self.assertFalse(report['pass'])
  with patch.object(sys,'argv',args),patch.object(b,'prepare_rows',side_effect=ValueError('invalid plan')):self.assertEqual(b.main(),1)
  report=json.loads((self.p/'out/preview.json').read_text());self.assertEqual(report['verification_status'],'failed');self.assertEqual(report['paid_calls'],0)

class LegacyVerificationTests(unittest.TestCase):
 setUp=handoff_fixture.NoApprovalHandoffTests.setUp
 identity=handoff_fixture.NoApprovalHandoffTests.identity
 def test_noapproval_legacy_pass_is_explicitly_unverified(self):
  handoff_fixture.NoApprovalHandoffTests.test_score_cli_unverified_exit_zero_does_not_establish_verification(self)
  report=json.loads((self.project/'score.json').read_text())
  self.assertTrue(report['pass']);self.assertEqual(report['verification_status'],'unverified');self.assertEqual(report['results'][0]['verification_status'],'unverified')
 def test_legacy_structural_errors_failed_keep_exit_one(self):
  args=['score_relevance.py','--project',str(self.project)]
  values={'plan':{'beats':[]},'context':{},'manifest':{},'cuts':{'clips':{}}}
  for key,value in values.items():
   path=self.project/(key+'.json');path.write_text(json.dumps(value));args += ['--'+key,str(path)]
  beats=self.project/'beats.tsx';beats.write_text('const VO_END_SEC = 2;');args += ['--beats',str(beats),'--public',str(self.project),'--out',str(self.project/'invalid.json')]
  with patch.object(sys,'argv',args),patch('broll_ledger.parse_beats',return_value=[]),patch.object(s,'validate_plan',return_value=['invalid structure']),patch.object(s,'reconcile_plan',return_value=[]),patch.object(s,'parse_renderer_durations',return_value={}):self.assertEqual(s.main(),1)
  report=json.loads((self.project/'invalid.json').read_text());self.assertEqual(report['verification_status'],'failed');self.assertFalse(report['pass'])
 def test_known_rejection_batch_status_failed(self):
  handoff_fixture.NoApprovalHandoffTests.test_known_zero_and_text_reject_survive_noapproval_no_transports(self)
  report=json.loads((self.project/'known/report.json').read_text())
  self.assertEqual(report['verification_status'],'failed');self.assertEqual([r['verification_status'] for r in report['results']],['failed','failed'])
