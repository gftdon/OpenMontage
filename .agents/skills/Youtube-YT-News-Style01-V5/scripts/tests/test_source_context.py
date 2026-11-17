import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('source_context', SCRIPTS/'source_context.py')
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)

class SourceContextTests(unittest.TestCase):
    def test_supplied_untimed_original_wins_without_fetch(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); (p/'source').mkdir()
            (p/'source/source.json').write_text(json.dumps({'language':'en','url':'https://example.test/video'}))
            (p/'source/transcript.txt').write_text('Actual original words without timestamps.')
            r=sc.build_context(p, fallback_transcript='not selected')
            self.assertEqual(r['transcript']['origin'],'task/source/transcript.txt')
            self.assertEqual(r['transcript']['language'],'en')
            self.assertEqual(r['transcript']['text'],'Actual original words without timestamps.')
            self.assertEqual(r['narration_cues'],[])
            self.assertFalse(r['transcript']['timed'])
            self.assertEqual(len(r['transcript']['sha256']),64)
    def test_missing_source_reports_offline_fallback_and_real_srt_only(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); srt=p/'narration.srt';srt.write_text('1\n00:00:01,000 --> 00:00:02,000\nพูดจริง\n')
            r=sc.build_context(p,narration_srt=srt)
            self.assertEqual(r['narration_cues'],[])
            self.assertEqual(r['reference_srt_cues'],[{'id':'cue-1','start':1.0,'end':2.0,'text':'พูดจริง'}])
            self.assertIsNone(r['transcript'])
            self.assertEqual(r['fallback']['status'],'required-not-fetched')
            self.assertTrue(r['errors'])
    def test_local_fallback_records_origin_and_never_manufactures_timing(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);t=p/'transcript.txt';t.write_text('source context')
            r=sc.build_context(p,fallback_transcript=t,language='en')
            self.assertEqual(r['transcript']['origin'],'local-unverified-transcript')
            self.assertFalse(r['transcript']['timed'])
            self.assertEqual(r['narration_cues'],[])
    def test_approved_word_spine_keeps_srt_reference_separate(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);w=p/'words.json';s=p/'script.txt';v=p/'vendor.srt'
            w.write_text(json.dumps([{'w':'บอ','s':1,'e':1.2},{'w':'กว่า','s':1.2,'e':1.8}]))
            s.write_text('บอกว่า');v.write_text('1\n00:00:03,000 --> 00:00:04,000\nบอกว่า\n')
            r=sc.build_context(p,narration_srt=v,word_timing=w,exact_script=s,narration_end=2)
            self.assertEqual(r['narration_cues'][0]['end'],2)
            self.assertEqual(r['narration_cues'][0]['original_word_end'],1.8)
            self.assertEqual(r['reference_srt_cues'][0]['start'],3)
            self.assertEqual(r['timing_authority'],'existing-word-spine')
    def test_invalid_srt_fails_instead_of_fabricating(self):
        with self.assertRaises(ValueError):sc.parse_srt('1\n00:00:03,000 --> 00:00:01,000\nbad')
