import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import broll_costs as bc
def historical_config():return json.loads((Path(__file__).parent/'fixtures/recovery1-config.json').read_text())
def legacy_setup(self):
 from unittest.mock import patch
 mock=patch('broll_costs.load_config',side_effect=historical_config);mock.start();self.addCleanup(mock.stop)

class TransitionTests(unittest.TestCase):
 def setUp(self):
  legacy_setup(self)
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name).resolve();self.c=bc.load_config();self.newhash=bc.config_sha256(self.c)
  self.a={'approved':True,'project':str(self.p),'config_sha256':self.newhash,'caps':self.c['caps'],**{k:{x:self.c[k][x] for x in ('provider','model')} for k in ('image','relevance')}}
  self.old='5dbcfcc7f2ab2e9e04ce5df93cdb4888c5f321a15715697e8a165d0d1bca5131';self.j={'schema':'a44-cost-journal-1','project':str(self.p),'attempts':[{'id':'old-image','config_sha256':self.old,'kind':'image','reserved_usd':.06,'status':'failed_or_ambiguous'},{'id':'old-rel','config_sha256':self.old,'kind':'relevance','reserved_usd':.02784,'status':'failed_or_ambiguous','usage_ambiguous':True}],'stop_paid_reason':'usage ambiguous'}
  self.b=bc.Budget(self.p,self.a,today='2026-11-08');self.b.path.parent.mkdir(parents=True);self.b.path.write_text(json.dumps(self.j));self.bytes=self.b.path.read_bytes();self.approval={'id':'Lead-recovery-1','approved':True,'approver':'Lead','timestamp':'2026-11-08T12:00:00Z','reason':'explicit one-time retain ambiguous attempts','old_stop_reason':'usage ambiguous','old_config_sha256':self.old,'new_config_sha256':self.newhash,'snapshot_sha256':bc.bytes_sha256(self.bytes),'retained_attempt_ids':['old-image','old-rel']}
 def test_recovery_is_explicit_single_append_preserves_attempts_and_no_refund(self):
  old=copy.deepcopy(self.j['attempts']);result=bc.apply_recovery(self.b,self.approval)
  self.assertEqual(result['attempts'],old);self.assertEqual(sum(x['reserved_usd'] for x in result['attempts']),.08784);self.assertEqual(len(result['recovery_events']),1)
  self.assertEqual(result['recovery_events'][0]['snapshot_sha256'],bc.bytes_sha256(self.bytes))
  with self.assertRaises(bc.StopPaid):bc.apply_recovery(self.b,self.approval)
  entry=self.b.reserve('image');self.assertEqual(entry['reserved_usd'],.10)
 def test_wrong_snapshot_no_recovery_and_future_stop_not_waived(self):
  wrong={**self.approval,'snapshot_sha256':'0'*64}
  with self.assertRaises(bc.StopPaid):bc.apply_recovery(self.b,wrong)
  self.assertEqual(self.b.path.read_bytes(),self.bytes)
  bc.apply_recovery(self.b,self.approval);e=self.b.reserve('relevance',input_tokens=1200);self.b.receipt(e['id'],'failed',None)
  with self.assertRaises(bc.StopPaid):self.b.reserve('image')
 def test_actual_count_reservation_and_strict_less_than_two(self):
  bc.apply_recovery(self.b,self.approval);r=self.b.reserve('relevance',input_tokens=1200);self.assertAlmostEqual(r['reserved_usd'],.00474);self.b.receipt(r['id'],'ok',{'input_tokens':1200,'output_tokens':10})
  with self.b.locked() as j:j['attempts'].append({'id':'near-cap','config_sha256':self.newhash,'kind':'image','reserved_usd':2-.08784-.00474-.10,'status':'ok'})
  with self.assertRaises(bc.StopPaid):self.b.reserve('image')
 def test_recovery_timestamp_requires_iso8601_timezone(self):
  for value in ('MAIN_MUST_SET_AT_APPLY','2026-11-08','2026-11-08T12:00:00','2026-99-08T12:00:00Z','nonsense'):
   with self.subTest(value=value):
    with self.assertRaises(bc.StopPaid):bc.apply_recovery(self.b,{**self.approval,'timestamp':value})
    self.assertEqual(self.b.path.read_bytes(),self.bytes)
 def test_approved_new_caps_include_old_attempts(self):
  self.assertEqual(self.c['caps']['relevance_calls'],45);self.assertEqual(self.c['caps']['image_attempts'],4);self.assertEqual(self.c['image']['model'],'gemini-3.1-flash-image')
