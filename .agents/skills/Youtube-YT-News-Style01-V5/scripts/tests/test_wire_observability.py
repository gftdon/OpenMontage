import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import score_relevance as s
class WireObservabilityTests(unittest.TestCase):
 def test_exit_error_preserves_allowlisted_http_category_no_headers_or_keys(self):
  response=subprocess.CompletedProcess([],1,'{"error":{"code":404,"message":"model unavailable https://api.test/?key=PRIVATE"}}','Authorization: Bearer PRIVATE')
  with patch.object(s.subprocess,'run',return_value=response):
   with self.assertRaises(s.WireError) as caught:s.cli_run({},'gemini-3.8-flash')
  e=caught.exception;self.assertEqual(e.diagnostic['error_category'],'model_unavailable');self.assertEqual(e.diagnostic['exit_code'],1);self.assertEqual(e.diagnostic['http_status'],404);self.assertNotIn('PRIVATE',json.dumps(e.diagnostic));self.assertNotIn('Authorization',json.dumps(e.diagnostic))
 def test_parse_failure_preserves_bounded_redacted_stdout_not_request_data(self):
  raw='{"score":0, "api_key":"PRIVATE", "data":"'+'A'*300+'", broken https://api.test/?token=PRIVATE'
  with patch.object(s.subprocess,'run',return_value=subprocess.CompletedProcess([],0,raw,'')):
   with self.assertRaises(s.WireError) as caught:s.cli_run({'input':'REQUEST_PRIVATE'},'gemini-3.8-flash')
  d=caught.exception.diagnostic;self.assertEqual(d['error_category'],'unparseable_response');self.assertEqual(d['exit_code'],0);self.assertLessEqual(len(d['stdout_redacted']),2048);self.assertNotIn('PRIVATE',json.dumps(d));self.assertNotIn('A'*100,json.dumps(d));self.assertIn('score',d['stdout_redacted'])
 def test_auth_429_timeout_and_missing_cli_safe_diagnostics(self):
  for exitcode,output,expected in [(3,'HTTP 401 key=PRIVATE','auth'),(1,'HTTP 429 Too many requests','rate_limit')]:
   with patch.object(s.subprocess,'run',return_value=subprocess.CompletedProcess([],exitcode,output,'')):
    with self.assertRaises(s.WireError) as caught:s.cli_run({},'model')
   self.assertEqual(caught.exception.diagnostic['error_category'],expected)
  for error,expected in [(subprocess.TimeoutExpired('cli',95,output='token=PRIVATE'),'timeout'),(FileNotFoundError(),'missing_cli')]:
   with patch.object(s.subprocess,'run',side_effect=error):
    with self.assertRaises(s.WireError) as caught:s.cli_run({},'model')
   self.assertEqual(caught.exception.diagnostic['error_category'],expected);self.assertNotIn('PRIVATE',json.dumps(caught.exception.diagnostic))
