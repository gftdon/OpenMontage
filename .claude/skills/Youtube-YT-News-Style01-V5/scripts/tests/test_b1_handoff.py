import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
S=Path(__file__).resolve().parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,S/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
sc=load('source_context');bp=load('broll_plan')
class HandoffTests(unittest.TestCase):
 def test_sync_bound_to_word_and_script_hashes(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);w=p/'words.json';s=p/'script.txt';w.write_text('[{"w":"hello","s":0,"e":1}]');s.write_text('hello')
   accepted={'status':'accepted','reference':'qc/anchors.json','wordTimingSha256':sc.sha256(w),'scriptSha256':sc.sha256(s)}
   c=sc.build_context(p,word_timing=w,exact_script=s,narration_end=2,sync_verification=accepted)
   self.assertEqual(bp.validate_sync(c),[])
   s.write_text('changed');self.assertTrue(bp.validate_sync(c));s.write_text('hello')
   c['sync_verification']['scriptSha256']='b'*64;self.assertTrue(bp.validate_sync(c))
   c['sync_verification']={'status':'accepted','reference':'qc/anchors.json'};self.assertTrue(bp.validate_sync(c))
 def test_metadata_only_is_not_transcript_and_explicit_fallback_unverified(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'source').mkdir();(p/'source/transcript.txt').write_text('# title: example\n# duration:87 uploader:OpenAI')
   c=sc.build_context(p);self.assertIsNone(c['transcript']);self.assertTrue(any(e['code']=='metadata-only-transcript' for e in c['errors']))
   f=p/'chapters.txt';f.write_text('[00:00 - 01:31.28] English spoken text')
   c=sc.build_context(p,fallback_transcript=f)
   self.assertEqual(c['transcript']['origin'],'local-unverified-transcript');self.assertEqual(c['transcript']['sha256'],sc.sha256(f))
   c=sc.build_context(p,fallback_transcript=f,source_duration=87)
   self.assertTrue(any(e['code']=='transcript-extent-exceeds-source' for e in c['errors']))
 def test_post_transcode_manifest_updates_final_hash_not_raw_identity(self):
  m=load('media_manifest')
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);raw=p/'raw';pub=p/'public';raw.mkdir();pub.mkdir();(raw/'_manifest.json').write_text(json.dumps({'desk':{'pixabay_id':'91','raw_md5':'raw','page_url':'https://pixabay.com/91'}}));f=pub/'desk.mp4';f.write_bytes(b'one')
   r=m.write_stock_manifest(raw,pub,['desk'],probe=lambda _:8.0);self.assertEqual(r['desk']['pixabay_id'],'91');self.assertEqual(r['desk']['sha256'],bp.file_sha256(f));self.assertEqual(r['desk']['duration'],8);self.assertEqual(json.loads((raw/'_manifest.json').read_text())['desk']['sha256'],bp.file_sha256(f))
   f.write_bytes(b'two');r2=m.write_stock_manifest(raw,pub,['desk'],probe=lambda _:9.0);self.assertNotEqual(r['desk']['sha256'],r2['desk']['sha256'])
   f.unlink()
   with self.assertRaises(ValueError):m.write_stock_manifest(raw,pub,['desk'],probe=lambda _:9.0)
