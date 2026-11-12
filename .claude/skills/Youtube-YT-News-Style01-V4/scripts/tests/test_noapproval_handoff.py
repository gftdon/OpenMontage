"""Offline characterization: no approval is not a fabricated relevance pass."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import batch_relevance as batch
import broll_costs as costs
import gen_stills as images
import score_relevance as relevance

JPEG = b'\xff\xd8\xff\xc0\x00\x0b\x08\x02\x40\x04\x00\x01\x01\x11\x00\xff\xd9'

class NoApprovalHandoffTests(unittest.TestCase):
 def setUp(self):
  self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
  self.project = Path(self.tmp.name).resolve()
  self.budget = costs.Budget(self.project, None, today='2026-11-08')
 def identity(self, origin='stock'):
  return {'origin':origin, 'identity':'pixabay:1' if origin=='stock' else 'image-sha256:'+'a'*64, 'cue_ids':['c1'], 'context_sha256':'b'*64}
 def test_native_image_execute_cli_is_disabled_without_approval(self):
  shots=self.project/'shots.json'; shots.write_text('{"shots":{"ai_one":{"image":"abstract"}}}')
  out=self.project/'images.json'
  args=['gen_stills.py','--project',str(self.project),'--shots',str(shots),'--public',str(self.project/'public'),'--out',str(out),'--execute']
  with patch.object(sys,'argv',args), patch.object(images,'registry_tool',side_effect=AssertionError('no registry')), patch.object(images,'generate_native',side_effect=AssertionError('no native call')):
   self.assertIsNone(images.main())
  self.assertEqual(json.loads(out.read_text())['status'],'STOP_PAID')
  self.assertFalse(self.budget.path.exists())
 def test_image_api_returns_stock_warning_without_reservation(self):
  result=images.generate(self.budget,'ai_one','abstract','',self.project/'generated',self.project/'public',8)
  self.assertEqual((result['status'],result['fallback'],result['severity']),('STOP_PAID','stock','warning'))
  self.assertFalse(self.budget.path.exists())
 def test_relevance_api_no_runner_is_unverified_not_hard_failure(self):
  result=relevance.score_asset(self.budget,JPEG,'spoken',self.identity())
  self.assertIsNone(result['score']); self.assertEqual(result['status'],'unverified_budget')
  self.assertEqual(result['warning']['severity'],'warning'); self.assertFalse(relevance.hard_failure([result]))
  self.assertFalse(self.budget.path.exists())
 def test_batch_no_transports_is_not_verified_and_has_no_hard_failure(self):
  rows=[{'id':'b1','frame':JPEG,'spoken':'spoken','identity':self.identity()}]
  report=batch.run_rows(self.budget,rows,self.project/'batch',complete=True)
  self.assertFalse(report['paid_enabled']); self.assertFalse(report['pass'])
  self.assertEqual(report['coverage'],{'total':1,'valid':0,'unverified':1,'failures':0})
  self.assertFalse(relevance.hard_failure(report['results'])); self.assertFalse(self.budget.path.exists())
 def test_known_zero_and_text_reject_survive_noapproval_no_transports(self):
  config=costs.load_config(); approval={'approved':True,'project':str(self.project),'config_sha256':costs.config_sha256(config),'caps':config['caps'],**{kind:{k:config[kind][k] for k in ('provider','model')} for kind in ('image','relevance')}}
  approved=costs.Budget(self.project,approval,today='2026-11-08')
  for origin,score,text in [('stock',0,None),('ai',2,True)]:
   verdict={'score':score,'reason':'known rejection'}
   if text is not None: verdict['readable_text']=text
   def stub(*_): return {'outputs':[{'type':'text','text':json.dumps(verdict)}],'usage':{'total_input_tokens':10,'total_output_tokens':10,'total_thought_tokens':0,'total_tokens':20}}
   relevance.score_asset(approved,JPEG,'spoken',self.identity(origin),runner=stub,exposure_verified=True)
  before=self.budget.path.read_bytes()
  rows=[{'id':origin,'frame':JPEG,'spoken':'new frame context','identity':self.identity(origin)} for origin in ('stock','ai')]
  report=batch.run_rows(self.budget,rows,self.project/'known')
  self.assertFalse(report['pass']); self.assertEqual(report['coverage']['failures'],2)
  self.assertTrue(relevance.hard_failure(report['results'])); self.assertEqual(self.budget.path.read_bytes(),before)
 def test_score_cli_unverified_exit_zero_does_not_establish_verification(self):
  inputs={'plan':{'beats':[{'id':'b1','t':0,'end':2,'spoken':'spoken','cue_ids':['c1'],'selected':{'identity':'pixabay:1'}}]},'context':{'timing_inputs':{},'narration_cues':[]},'manifest':{'stock':{'sha256':relevance.digest(b'media'),'pixabay_id':'1'}},'cuts':{'clips':{}}}
  args=['score_relevance.py','--project',str(self.project)]
  for name,value in inputs.items():
   p=self.project/(name+'.json'); p.write_text(json.dumps(value)); args += ['--'+name,str(p)]
  beats=self.project/'beats.tsx'; beats.write_text('const VO_END_SEC = 2;'); args += ['--beats',str(beats),'--public',str(self.project),'--out',str(self.project/'score.json')]
  (self.project/'stock.mp4').write_bytes(b'media')
  with patch.object(sys,'argv',args),patch('broll_ledger.parse_beats',return_value=[{'t':0,'src':'stock','origin':'stock','media':'broll','layout':'full'}]),patch.object(relevance,'validate_plan',return_value=[]),patch.object(relevance,'reconcile_plan',return_value=[]),patch.object(relevance,'parse_renderer_durations',return_value={'stock':3}),patch.object(relevance,'probe_duration',return_value=3),patch.object(relevance,'extract_frame',return_value=JPEG):
   self.assertEqual(relevance.main(),0)
  report=json.loads((self.project/'score.json').read_text())
  self.assertFalse(report['paid_calls_enabled']); self.assertTrue(report['pass'])
  self.assertEqual(report['acceptance'],'unverified'); self.assertEqual(report['coverage']['valid'],0)
  self.assertFalse(relevance.hard_failure(report['results'])); self.assertFalse(self.budget.path.exists())
