import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
S=Path(__file__).resolve().parents[1];sys.path.insert(0,str(S))
def module():
 spec=importlib.util.spec_from_file_location('broll_costs',S/'broll_costs.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def historical_config():return json.loads((Path(__file__).parent/'fixtures/recovery1-config.json').read_text())
def legacy_setup(self):
 from unittest.mock import patch
 mock=patch('broll_costs.load_config',side_effect=historical_config);mock.start();self.addCleanup(mock.stop)

class CostsTests(unittest.TestCase):
 def setUp(self):
  legacy_setup(self)
  self.m=module();self.m.load_config=historical_config;self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.project=Path(self.tmp.name)
  self.c=self.m.load_config();self.a={'config_sha256':self.m.config_sha256(self.c),'approved':True,'project':str(self.project.resolve()),'caps':self.c['caps'],'image':{'provider':self.c['image']['provider'],'model':self.c['image']['model']},'relevance':{'provider':'gemini-api','model':self.c['relevance']['model']}}
 def budget(self):return self.m.Budget(self.project,self.a,self.c,today='2026-11-08')
 def test_no_approval_no_rate_expired_and_wrong_binding_stop_paid(self):
  for change in [lambda:self.a.update(approved=False),lambda:self.c['relevance'].update(input_usd_per_million=None),lambda:self.c['relevance'].update(valid_until='2026-01-01'),lambda:self.a['image'].update(model='other')]:
   self.setUp();change()
   with self.assertRaises(self.m.StopPaid):self.budget().reserve('image')
 def test_failed_or_ambiguous_attempt_never_refunded_across_reruns(self):
  for _ in range(4):
   b=self.budget();r=b.reserve('image');b.receipt(r['id'],status='timeout',usage=None)
  with self.assertRaises(self.m.StopPaid):self.budget().reserve('image')
  journal=json.loads((self.project/'artifacts/broll-costs.json').read_text());self.assertEqual(len(journal['attempts']),4);self.assertAlmostEqual(sum(x['reserved_usd'] for x in journal['attempts']),.40);self.assertTrue(all(x['actual_usd'] is None for x in journal['attempts']))
 def test_concurrent_reservation_maximum(self):
  winners=[]
  def run():
   try:winners.append(self.budget().reserve('image'))
   except self.m.StopPaid:pass
  threads=[threading.Thread(target=run) for _ in range(20)]
  for t in threads:t.start()
  for t in threads:t.join()
  self.assertEqual(len(winners),4)
 def test_relevance_cap_and_total_and_malformed_usage_never_negative(self):
  b=self.budget();r=b.reserve('relevance');b.receipt(r['id'],status='ok',usage={'input_tokens':-10,'output_tokens':'nan'})
  j=json.loads(b.path.read_text());self.assertEqual(j['attempts'][0]['estimated_usd'],r['reserved_usd']);self.assertTrue(j['attempts'][0]['usage_invalid'])
  with self.assertRaises(self.m.StopPaid):b.reserve('relevance')
  b.path.unlink()
  for _ in range(45):
    item=b.reserve('relevance');b.receipt(item['id'],'ok',{'input_tokens':1,'output_tokens':1})
  with self.assertRaises(self.m.StopPaid):b.reserve('relevance')
  self.assertLessEqual(sum(x['reserved_usd'] for x in json.loads(b.path.read_text())['attempts']),2)
 def test_total_budget_and_corrupt_journal_stop_without_refund(self):
  b=self.budget();b.path.parent.mkdir(parents=True,exist_ok=True);b.path.write_text(json.dumps({'project':str(self.project),'attempts':[{'kind':'image','reserved_usd':1.99}]}))
  with self.assertRaises(self.m.StopPaid):b.reserve('relevance')
  b.path.write_text(json.dumps({'project':str(self.project),'attempts':[{'kind':'image','reserved_usd':-1}]}))
  with self.assertRaises(self.m.StopPaid):b.reserve('image')
 def test_config_cannot_expand_caps_or_provider(self):
  self.c['caps']['image_attempts']=5
  with self.assertRaises(self.m.StopPaid):self.budget().reserve('image')
