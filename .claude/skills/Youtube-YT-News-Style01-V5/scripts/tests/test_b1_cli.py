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

 def test_numeric_strings_normalized_at_boundary(self):
  # V4 field names: punch[].at (presenter beats), stats[].at/dur, srcCrop x/y/w/h
  b=bp.normalize_beats([{'t':'1.2','from':'2','punch':[{'at':'1.4','z':'1.2'}],'stats':[{'at':'1.5','dur':'3','label':'x'}],'srcCrop':{'x':'10','y':'20','w':'1280','h':'720'},'mode':'pip','media':'broll','src':'x','origin':'stock'}])
  self.assertEqual(b[0]['t'],1.2);self.assertEqual(b[0]['from'],2);self.assertEqual(b[0]['punch'][0]['at'],1.4);self.assertEqual(b[0]['punch'][0]['z'],1.2)
  self.assertEqual((b[0]['stats'][0]['at'],b[0]['stats'][0]['dur']),(1.5,3));self.assertEqual(b[0]['srcCrop'],{'x':10,'y':20,'w':1280,'h':720});self.assertEqual(b[0]['src'],'x')
  with self.assertRaises(ValueError):bp.normalize_beats([{'t':'NaN'}])
