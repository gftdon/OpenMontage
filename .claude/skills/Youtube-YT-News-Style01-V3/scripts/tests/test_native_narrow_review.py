import base64
import http.client
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import broll_costs as bc
import native_paid as n
import score_relevance as sr
JPEG=b'\xff\xd8\xff\xc0\x00\x0b\x08\x02\x40\x04\x00\x01\x01\x11\x00\xff\xd9'
def historical_config():return json.loads((Path(__file__).parent/'fixtures/recovery1-config.json').read_text())
def legacy_setup(self):
 from unittest.mock import patch
 mock=patch('broll_costs.load_config',side_effect=historical_config);mock.start();self.addCleanup(mock.stop)

class NarrowReviewTests(unittest.TestCase):
 def setUp(self):legacy_setup(self)
 def fixture(self,p,kind):
  c=bc.load_config();a={'approved':True,'project':str(p.resolve()),'config_sha256':bc.config_sha256(c),'caps':c['caps'],**{k:{x:c[k][x] for x in ('provider','model')} for k in ('image','relevance')}};b=bc.Budget(p,a,today='2026-11-08')
  if kind=='image':body={'model':'models/'+c[kind]['model'],'contents':[{'role':'user','parts':[{'text':'no letters or logos'}]}],'generationConfig':{'maxOutputTokens':1536,'responseModalities':['IMAGE'],'imageConfig':{'aspectRatio':'16:9','imageSize':'1K'}}}
  else:
   r=sr.request_body(JPEG,'spoken',c);body={'model':'models/'+c[kind]['model'],'contents':[{'role':'user','parts':[{'text':r['input'][0]['text']},{'inlineData':{'mimeType':'image/jpeg','data':base64.b64encode(JPEG).decode()}}]}],'systemInstruction':{'parts':[{'text':sr.SYSTEM}]},'generationConfig':{'maxOutputTokens':1024,'responseMimeType':'application/json','responseJsonSchema':r['response_format']['schema'],'thinkingConfig':{'thinkingLevel':'LOW'}}}
  request=p/'request.json';request.write_text(json.dumps(body));count=p/'count.json';count.write_text(json.dumps({'operation':'countTokens','model':body['model'],'payload_sha256':bc.bytes_sha256(request.read_bytes()),'generate_called':False,'http_status':200,'totalTokens':11}));binding=n.bind_count_receipt(request,count,c,kind,'same-key');identity={'origin':'stock','identity':'pixabay:1','cue_ids':['c1'],'context_sha256':'a'*64}
  return b,request,binding,identity
 def test_execute_both_kinds_missing_thoughts_only_when_totals_prove_zero(self):
  for kind in ('image','relevance'):
   for mismatch in (False,True):
    with self.subTest(kind=kind,mismatch=mismatch),tempfile.TemporaryDirectory() as d:
     p=Path(d);b,request,binding,identity=self.fixture(p,kind);calls=[]
     part={'inlineData':{'mimeType':'image/png','data':base64.b64encode(b'png').decode()}} if kind=='image' else {'text':'{"score":2,"reason":"relevant"}'}
     reply={'candidates':[{'content':{'parts':[part]}}],'usageMetadata':{'promptTokenCount':11,'candidatesTokenCount':73,'totalTokenCount':85 if mismatch else 84,'candidatesTokensDetails':[{'modality':'IMAGE' if kind=='image' else 'TEXT','tokenCount':73}]}}
     def run(*_):calls.append(1);return reply
     result=n.execute_exact(b,kind,request,binding,'same-key',run,identity=identity)
     self.assertEqual(len(calls),1);self.assertEqual(result['budget_status'],'STOP_PAID' if mismatch else 'reserved_with_usage')
     if not mismatch:self.assertEqual(result['usage']['output_tokens'],73)
 def test_explicit_invalid_thoughts_not_inferred_zero(self):
  for thought in (None,'0',-1,False):self.assertIsNone(n.native_usage({'usageMetadata':{'promptTokenCount':11,'candidatesTokenCount':73,'totalTokenCount':84,'thoughtsTokenCount':thought}}))
 def test_transport_os_and_http_exceptions_are_redacted_and_stop_once(self):
  for error in (OSError('PRIVATE_KEY'),ConnectionResetError('PRIVATE_KEY'),http.client.RemoteDisconnected('PRIVATE_KEY'),http.client.IncompleteRead(b'PRIVATE_KEY')):
   with self.subTest(error=type(error).__name__),tempfile.TemporaryDirectory() as d:
    p=Path(d);b,request,binding,identity=self.fixture(p,'relevance');runner=n.transport_for_key('PRIVATE_KEY')
    with patch('urllib.request.urlopen',side_effect=error) as call:result=n.execute_exact(b,'relevance',request,binding,'same-key',runner,identity=identity)
    self.assertEqual(call.call_count,1);self.assertEqual(result['wire_diagnostic']['error_category'],'transport_unknown');self.assertNotIn('PRIVATE_KEY',json.dumps(result));self.assertEqual(result['budget_status'],'STOP_PAID')
    with self.assertRaises(bc.StopPaid):b.reserve('image')
