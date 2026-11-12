import base64
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

class NativeTests(unittest.TestCase):
 def setUp(self):legacy_setup(self)
 def setup_case(self,p):
  import native_paid as n
  c=bc.load_config();a={'approved':True,'project':str(p.resolve()),'config_sha256':bc.config_sha256(c),'caps':c['caps'],**{k:{x:c[k][x] for x in ('provider','model')} for k in ('image','relevance')}};b=bc.Budget(p,a,today='2026-11-08')
  body={'model':'models/'+c['image']['model'],'contents':[{'role':'user','parts':[{'text':'abstract scene, no letters or logos'}]}],'generationConfig':{'maxOutputTokens':1536,'responseModalities':['IMAGE'],'imageConfig':{'aspectRatio':'16:9','imageSize':'1K'}}};request=p/'request.json';request.write_text(json.dumps(body));count=p/'count.json';count.write_text(json.dumps({'operation':'countTokens','model':body['model'],'payload_sha256':bc.bytes_sha256(request.read_bytes()),'http_status':200,'totalTokens':178,'generate_called':False}));return n,b,request,count
 def test_count_binding_changed_payload_requires_recount_and_failure_zero_paid(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);n,b,request,count=self.setup_case(p);bound=n.bind_count_receipt(request,count,b.config,'image','existing-key-fingerprint');calls=[]
   request.write_text(request.read_text()+' ')
   with self.assertRaises(bc.StopPaid):n.execute_exact(b,'image',request,bound,'existing-key-fingerprint',lambda *_:calls.append(1))
   self.assertEqual(calls,[]);self.assertFalse(b.path.exists())
 def test_precheck_non200_or_wrong_key_model_stops(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);n,b,request,count=self.setup_case(p);bound=n.bind_count_receipt(request,count,b.config,'image','same-key')
   with self.assertRaises(bc.StopPaid):n.execute_exact(b,'image',request,bound,'different-key',lambda *_:self.fail('paid'))
   data=json.loads(count.read_text());data['http_status']=400;count.write_text(json.dumps(data))
   with self.assertRaises(bc.StopPaid):n.bind_count_receipt(request,count,b.config,'image','same-key')
 def test_exact_image_request_one_call_and_unknown_usage_stops_retains_reserve(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);n,b,request,count=self.setup_case(p);bound=n.bind_count_receipt(request,count,b.config,'image','same-key');calls=[]
   def run(raw,model):calls.append((raw,model));return {'candidates':[{'content':{'parts':[{'inlineData':{'mimeType':'image/png','data':base64.b64encode(b'png').decode()}}]}}]}
   result=n.execute_exact(b,'image',request,bound,'same-key',run)
   self.assertEqual(len(calls),1);self.assertEqual(calls[0][0],request.read_bytes());self.assertEqual(result['budget_status'],'STOP_PAID');self.assertEqual(result['image_bytes'],b'png')
   j=json.loads(b.path.read_text());self.assertEqual(j['attempts'][0]['reserved_usd'],.10)
 def test_native_image_cache_and_local_render_without_second_call(self):
  import gen_stills as g
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);n,b,request,count=self.setup_case(p);bound=n.bind_count_receipt(request,count,b.config,'image','same-key');calls=[]
   def run(*_):
    calls.append(1);return {'candidates':[{'content':{'parts':[{'inlineData':{'mimeType':'image/png','data':base64.b64encode(b'png').decode()}}]}}],'usageMetadata':{'promptTokenCount':178,'candidatesTokenCount':1120,'thoughtsTokenCount':0,'totalTokenCount':1298,'candidatesTokensDetails':[{'modality':'IMAGE','tokenCount':1120}]}}
   def transcode(i,o,duration):o.write_bytes(b'mp4')
   for _ in range(2):result=g.generate_native(b,'ai_native',request,bound,'same-key',p/'gen',p/'public',5,runner=run,transcode=transcode,probe=lambda _:5)
   self.assertEqual(len(calls),1);self.assertEqual(result['status'],'cache_hit');self.assertEqual(result['manifest']['model'],'gemini-3.1-flash-image')
   journal=json.loads(b.path.read_text());self.assertAlmostEqual(journal['attempts'][0]['estimated_usd'],.067289);self.assertIsNone(journal.get('stop_paid_reason'))
 def test_actual_relevance_input_count_reserves_less_but_keeps_output_bound(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);n,b,request,count=self.setup_case(p)
   # Counter binding itself remains kind/model-specific; image receipt cannot score.
   bound=n.bind_count_receipt(request,count,b.config,'image','same-key')
   with self.assertRaises(bc.StopPaid):n.execute_exact(b,'relevance',request,bound,'same-key',lambda *_:self.fail('paid'))
