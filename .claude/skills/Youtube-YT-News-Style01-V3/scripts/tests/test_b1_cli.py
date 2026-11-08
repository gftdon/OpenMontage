import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import broll_plan as bp
class CliTests(unittest.TestCase):
 def test_ceil_beat_and_js_round_from_boundary(self):
  r=bp.shown_timing(1.201,2.001,.02,5)
  self.assertEqual(r['beat_start_frame'],31);self.assertEqual(r['end_frame_exclusive'],51);self.assertEqual(r['from_frame'],1)
  self.assertEqual(r['shown_frames'],20);self.assertAlmostEqual(r['source_end'],.84)
  uses=bp.derive_usage([{'t':1.201,'end':2.001,'from':.02,'mode':'pip','media':'clip','origin':'source','src':'yt_x'}],{'yt_x':{'source_sha256':'a','source_in':3,'source_out':8,'duration':5}})
  self.assertEqual(uses[0]['source_range'],[3.04,3.84])

 def test_literal_parser_numeric_strings_normalized_at_boundary(self):
  b=bp.normalize_beats([{'t':'1.2','from':'2','chrome':'false','punch':[{'t':'1.4','z':'1.2'}],'mode':'pip','media':'broll','src':'x','origin':'stock'}])
  self.assertEqual(b[0]['t'],1.2);self.assertEqual(b[0]['from'],2);self.assertFalse(b[0]['chrome']);self.assertEqual(b[0]['punch'][0]['z'],1.2)
  with self.assertRaises(ValueError):bp.normalize_beats([{'t':'NaN'}])
