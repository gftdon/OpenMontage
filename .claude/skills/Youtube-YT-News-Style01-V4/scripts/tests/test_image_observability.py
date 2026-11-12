import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import gen_stills as g
from broll_costs import Budget,load_config,config_sha256,StopPaid
def historical_config():return json.loads((Path(__file__).parent/'fixtures/recovery1-config.json').read_text())
def legacy_setup(self):
 from unittest.mock import patch
 mock=patch('broll_costs.load_config',side_effect=historical_config);mock.start();self.addCleanup(mock.stop)

class ImageObservabilityTests(unittest.TestCase):
 def setUp(self):legacy_setup(self)
 def test_sanitized_failure_categories_persist_and_stop_without_retry_refund(self):
  cases=[('404 Client Error for url: https://api.test/models/secret?key=DO_NOT_LOG','model_unavailable',404),('401 Unauthorized Bearer DO_NOT_LOG','auth',401),('429 Too Many Requests key=DO_NOT_LOG','rate_limit',429),('HTTPSConnectionPool https://host/?token=DO_NOT_LOG Read timed out','timeout',None),('No images returned from Imagen API','no_image',None),('unexpected private value DO_NOT_LOG','unknown',None)]
  for error,category,status in cases:
   with self.subTest(category=category),tempfile.TemporaryDirectory() as d:
    p=Path(d).resolve();c=historical_config();c['image']['provider']='google_imagen';legacy=patch('broll_costs.load_config',return_value=c);legacy.start();self.addCleanup(legacy.stop);approval={'approved':True,'project':str(p),'config_sha256':config_sha256(c),'caps':c['caps'],**{k:{x:c[k][x] for x in ('provider','model')} for k in ('image','relevance')}};budget=Budget(p,approval,today='2026-11-08');calls=[]
    class Tool:
     input_schema={'properties':{'model':{'enum':[c['image']['model']]}}}
     def execute(self,params):calls.append(params);return type('R',(),{'success':False,'error':error})()
    result=g.generate(budget,'ai_probe','abstract','style',p/'gen',p/'pub',5,tool=Tool())
    self.assertEqual(result['error_category'],category);self.assertEqual(result['http_status'],status);self.assertEqual(result['budget_status'],'STOP_PAID');self.assertEqual(len(calls),1)
    saved=json.loads((p/'gen/ai_probe.failure.json').read_text());self.assertEqual(saved['error_category'],category);self.assertNotIn('DO_NOT_LOG',json.dumps(saved));self.assertNotIn('https://',json.dumps(result))
    journal=json.loads(budget.path.read_text());self.assertEqual(len(journal['attempts']),1);self.assertEqual(journal['attempts'][0]['reserved_usd'],.10);self.assertEqual(journal['attempts'][0]['status'],'image_failed_'+category)
    with self.assertRaises(StopPaid):Budget(p,approval,today='2026-11-08').reserve('image')
 def test_raised_exception_has_safe_category_not_raw_payload(self):
  error=g.classify_image_error(TimeoutError('token=PRIVATE'))
  self.assertEqual(error['error_category'],'timeout');self.assertNotIn('PRIVATE',json.dumps(error))
 def test_success_without_file_is_no_image(self):
  self.assertEqual(g.classify_image_error('image output file missing')['error_category'],'no_image')
