import importlib.util
from pathlib import Path
import tempfile
import unittest
S=Path(__file__).resolve().parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,S/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
bp=load('broll_plan');sc=load('source_context')
class RepairTests(unittest.TestCase):
 def context(self):return {'inputs':{'word':'a'*64,'script':'b'*64},'timing_inputs':{'wordTimingSha256':'a'*64,'scriptSha256':'b'*64},'timing_authority':'existing-word-spine','sync_verification':{'status':'accepted','reference':'qc/anchors.json','wordTimingSha256':'a'*64,'scriptSha256':'b'*64},'narration_cues':[{'id':'c1','start':9,'end':11,'text':'minor'},{'id':'c2','start':11,'end':20,'text':'dominant'}]}
 def plan(self):return {'schema':bp.PLAN_SCHEMA,'beats':[{'id':'a','t':10,'end':20,'cue_ids':['c1'],'spoken':'minor','query':'query','semantic_rationale':'reason','selected':{'tier':'stock','identity':'pixabay:1','path':'desk.mp4','from':0},'rejected_tiers':[{'tier':'source','reason':'none'},{'tier':'ai','reason':'real action'}]}]}
 def test_all_positive_overlap_cues_required_order_no_duplicates(self):
  p=self.plan();c=self.context()
  self.assertTrue(bp.validate_plan(p,c))
  p['beats'][0].update(cue_ids=['c1','c2'],spoken='minor\ndominant');self.assertEqual(bp.validate_plan(p,c),[])
  p['beats'][0]['cue_ids']=['c2','c1'];self.assertTrue(bp.validate_plan(p,c))
  p['beats'][0]['cue_ids']=['c1','c2','c2'];self.assertTrue(bp.validate_plan(p,c))
 def test_missing_word_spine_or_unaccepted_sync_fails(self):
  c=self.context();c['timing_authority']='none';self.assertTrue(bp.validate_plan(self.plan(),c))
  c=self.context();c['sync_verification']['status']='provisional';self.assertTrue(bp.validate_plan(self.plan(),c))
 def test_srt_is_reference_never_narration_authority(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);v=p/'v.srt';v.write_text('1\n00:00:01,000 --> 00:00:02,000\nreference')
   c=sc.build_context(p,narration_srt=v)
   self.assertEqual(c['narration_cues'],[]);self.assertEqual(c['timing_authority'],'none');self.assertEqual(len(c['reference_srt_cues']),1)
 def test_reconcile_actual_render_and_hash_derived_identity(self):
  p=self.plan();b=[{'t':10,'end':20,'src':'desk','origin':'stock','media':'broll','mode':'pip','from':0}];r={'desk':{'pixabay_id':1,'sha256':'a'*64,'duration':30}}
  self.assertEqual(bp.reconcile_plan(p,b,r,diagnostic_subset=True),[])
  for key,value in [('src','wrong'),('from',2),('origin','source'),('end',19)]:
   changed=[{**b[0],key:value}];self.assertTrue(bp.reconcile_plan(p,changed,r,diagnostic_subset=True))
  r['desk']['pixabay_id']=2;self.assertTrue(bp.reconcile_plan(p,b,r,diagnostic_subset=True))
 def test_full_plan_requires_every_rendered_cutaway(self):
  b=[{'t':10,'end':20,'src':'desk','origin':'stock','media':'broll','mode':'pip','from':0},{'t':30,'end':35,'src':'other','origin':'stock','media':'broll','mode':'pip'}]
  self.assertTrue(bp.reconcile_plan(self.plan(),b,{'desk':{'pixabay_id':1,'sha256':'a'*64,'duration':30}},diagnostic_subset=False))
 def test_actual_duration_and_renderer_table_are_authoritative_not_manifest(self):
  records={'desk':{'duration':45,'pixabay_id':1}}
  beats=[{'t':0,'end':8,'src':'desk','origin':'stock','media':'broll','mode':'pip','from':25}]
  uses=bp.derive_usage(beats,records,actual_durations={'desk':30},renderer_durations={'desk':30})
  self.assertTrue(bp.check_usage(uses)['violations'])
  with self.assertRaises(ValueError):bp.derive_usage(beats,records,actual_durations={'desk':30},renderer_durations={'desk':45})
  with self.assertRaises(ValueError):bp.derive_usage(beats,records,actual_durations={'desk':30},renderer_durations={})
