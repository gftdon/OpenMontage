import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
def historical_config():return json.loads((Path(__file__).parent/'fixtures/recovery1-config.json').read_text())
def legacy_setup(self):
 from unittest.mock import patch
 mock=patch('broll_costs.load_config',side_effect=historical_config);mock.start();self.addCleanup(mock.stop)

class StillsTests(unittest.TestCase):
 def setUp(self):legacy_setup(self)
 def test_registry_pinned_inputs_cache_hash_and_stale_consumes_attempt(self):
  import gen_stills as g
  from broll_costs import Budget,load_config,config_sha256
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);c=load_config();c['image']['provider']='google_imagen';legacy=patch('broll_costs.load_config',return_value=c);legacy.start();self.addCleanup(legacy.stop);a={'config_sha256':config_sha256(c),'approved':True,'project':str(p.resolve()),'caps':c['caps'],**{k:{x:c[k][x] for x in ('provider','model')} for k in ('image','relevance')}};b=Budget(p,a,today='2026-11-08');b.config['image']['provider']='google_imagen';calls=[]
   class Tool:
    input_schema={'properties':{'model':{'enum':[c['image']['model']]}}}
    def execute(self,x):
     calls.append(x);Path(x['output_path']).write_bytes(b'image');return type('R',(),{'success':True})()
   def transcode(i,o,d):o.write_bytes(b'video')
   args=(b,'ai_concept','abstract concept','editorial',p/'images',p/'public',6)
   one=g.generate(*args,tool=Tool(),transcode=transcode,probe=lambda _:6);two=g.generate(*args,tool=Tool(),transcode=transcode,probe=lambda _:6)
   self.assertEqual(len(calls),1);self.assertEqual(calls[0]['number_of_images'],1);self.assertEqual(calls[0]['aspect_ratio'],'16:9');self.assertEqual(calls[0]['model'],c['image']['model']);self.assertEqual(two['status'],'cache_hit');self.assertEqual(one['manifest']['origin'],'ai')
   (p/'images/ai_concept.png').write_bytes(b'changed');g.generate(*args,tool=Tool(),transcode=transcode,probe=lambda _:6);self.assertEqual(len(calls),2)
 def test_retired_model_fallback_without_call_or_reservation(self):
  import gen_stills as g
  from broll_costs import Budget
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)
   class Tool:input_schema={'properties':{'model':{'enum':['other']}}}
   r=g.generate(Budget(p,None),'ai_a','abstract','style',p/'gen',p/'pub',5,tool=Tool())
   self.assertEqual(r['fallback'],'stock');self.assertFalse((p/'artifacts/broll-costs.json').exists())
