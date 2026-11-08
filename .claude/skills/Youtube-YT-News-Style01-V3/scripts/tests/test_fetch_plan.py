import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fetch_broll as f
class FetchPlanTests(unittest.TestCase):
 def test_semantic_plan_queries_not_global_first_keyword(self):
  import broll_plan as bp
  context={'timing_authority':'existing-word-spine','timing_inputs':{'wordTimingSha256':'a'*64,'scriptSha256':'b'*64},'inputs':{'w':'a'*64,'s':'b'*64},'sync_verification':{'status':'accepted','reference':'anchors','wordTimingSha256':'a'*64,'scriptSha256':'b'*64},'narration_cues':[{'id':'c','start':0,'end':5,'text':'poster use'}]}
  plan={'schema':bp.PLAN_SCHEMA,'beats':[{'id':'one','t':0,'end':5,'cue_ids':['c'],'spoken':'poster use','query':'poster creation workflow','semantic_rationale':'specific scene','selected':{'tier':'stock','identity':'pixabay:1','path':'poster.mp4'},'rejected_tiers':[{'tier':'source','reason':'no poster demo in source'},{'tier':'ai','reason':'real creator preferred'}]}]}
  self.assertEqual(f.queries_from_plan(plan,context),{'poster':['poster creation workflow','']})
  plan['beats'][0]['rejected_tiers']=[]
  with self.assertRaises(ValueError):f.queries_from_plan(plan,context)
