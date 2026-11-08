import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]

class BeatTests(unittest.TestCase):
    def lint(self, beats, end=4.5):
        spec = importlib.util.spec_from_file_location('lint_beats', SCRIPTS / 'lint_beats.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.lint_beats(beats, end, {'maxHoldSeconds':10,'maxEndcardSeconds':5,'cropStep':0.15,'scaleStep':0.15})

    def beat(self, t=0, end=10, **kw):
        return dict(t=t,end=end,mode='pip',media='broll',src='desk',origin='stock',layout='stage',chrome=False,**kw)

    def test_hold_over_limit(self):
        self.assertIn('hold', [x['code'] for x in self.lint([self.beat(end=10.01)])])

    def test_adjacent_identical_cannot_evade_hold(self):
        self.assertIn('hold', [x['code'] for x in self.lint([self.beat(end=6),self.beat(t=6,end=12)])])

    def test_endcard_limit(self):
        self.assertIn('endcard', [x['code'] for x in self.lint([self.beat()],5.01)])

    def test_stock_chrome_and_source_mismatch(self):
        b=self.beat(); b['chrome']=True
        self.assertIn('stock-chrome', [x['code'] for x in self.lint([b])])
        b=self.beat(); b['src']='yt_demo'
        self.assertIn('origin', [x['code'] for x in self.lint([b])])

    def test_missing_invalid_metadata(self):
        for b in [{},self.beat(end=float('nan')),{**self.beat(),'origin':None},{**self.beat(),'chrome':'false'}]:
            self.assertTrue(self.lint([b]))

    def test_step_punch_resets_hold_but_slow_zoom_does_not(self):
        self.assertEqual([],self.lint([{**self.beat(end=18,punch=[{'t':9,'z':1.2}]),'src':'yt_demo','origin':'source'}]))
        self.assertTrue(self.lint([self.beat(end=18,cam=[{'t':0,'z':1},{'t':9,'z':1.2}])]))

    def test_crop_step_and_small_step(self):
        self.assertTrue(self.lint([{**self.beat(end=18,punch=[{'t':9,'z':1,'fx':0.7}]),'src':'yt_demo','origin':'source'}]))
        self.assertTrue(self.lint([self.beat(end=18,punch=[{'t':9,'z':1.1}])]))

    def test_punch_restricted_to_avatar_and_source(self):
        for b in [self.beat(end=18,punch=[{'t':9,'z':1.2}]),{**self.beat(end=18,punch=[{'t':9,'z':1.2}]),'media':'typo'}]:
            self.assertIn('punch-origin',[x['code'] for x in self.lint([b])])
        self.assertEqual([],self.lint([{**self.beat(end=18,punch=[{'t':9,'z':1.2}]),'src':'yt_demo','origin':'source'}]))

    def test_typo_cards_reset_only_on_real_content_change(self):
        b={**self.beat(end=18),'media':'typo','cards':[{'t':0,'lines':['Flare']},{'t':9,'lines':['Sunburst']}]}
        self.assertEqual([],self.lint([b]))
        b['cards'][1]['lines']=['Flare']
        self.assertIn('hold',[x['code'] for x in self.lint([b])])

    def test_avatar_and_typography_hold(self):
        for b in [dict(t=0,end=11,mode='full'),dict(t=0,end=11,mode='pip',media='typo',src='desk',origin='stock',layout='stage',chrome=False)]:
            self.assertTrue(self.lint([b]))

    def test_effective_crop_not_raw_focal_delta(self):
        for punch in [[{'t':9,'z':1,'fx':.7}],[{'t':0,'z':1.2,'fx':.5},{'t':9,'z':1.2,'fx':.7}]]:
            b={**self.beat(end=18,punch=punch),'src':'yt_demo','origin':'source'}
            self.assertIn('hold',[x['code'] for x in self.lint([b])])
        b={**self.beat(end=18,punch=[{'t':0,'z':2,'fx':.1},{'t':9,'z':2,'fx':.5}]),'src':'yt_demo','origin':'source'}
        self.assertEqual([],self.lint([b]))

    def test_hidden_avatar_metadata_does_not_cut(self):
        beats=[{'t':0,'end':8,'mode':'full','headline':'A'},{'t':8,'end':16,'mode':'full','headline':'B','src':'hidden'}]
        self.assertIn('hold',[x['code'] for x in self.lint(beats)])

    def test_no_render_target_cannot_punch(self):
        b={'t':0,'end':18,'mode':'pip','punch':[{'t':9,'z':1.2}]}
        self.assertTrue(self.lint([b]))

    def test_lower_third_effective_time_not_metadata_boundary(self):
        beats=[{'t':0,'end':8,'mode':'full'},{'t':8,'end':18,'mode':'full','lower':{'t':12,'dur':3,'title':'News','sub':'Detail'}}]
        self.assertIn('hold',[x['code'] for x in self.lint(beats)])

    def test_flash_overlay_never_resets_twenty_second_hold(self):
        for mode in ['full','pip']:
            b={'t':0,'end':20,'mode':'full','lower':{'t':9.9,'dur':.1,'title':'Flash','sub':'News'}} if mode=='full' else {**self.beat(end=20),'lower':{'t':9.9,'dur':.1,'title':'Flash','sub':'News'}}
            self.assertIn('hold',[x['code'] for x in self.lint([b])])

    def test_headline_and_chip_change_on_same_media_do_not_reset(self):
        beats=[{**self.beat(end=8),'headline':'A','stats':[{'t':1,'label':'one'}]},{**self.beat(t=8,end=16),'headline':'B','stats':[{'t':9,'label':'two'}]}]
        self.assertIn('hold',[x['code'] for x in self.lint(beats)])

    def test_caption_lane_contract(self):
        for lane in ['top','bottom']:
            self.assertEqual([],self.lint([{**self.beat(),'captionLane':lane}]))
        self.assertTrue(self.lint([{**self.beat(),'captionLane':'middle'}]))

    def test_negative_cli(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.tsx'; p.write_text('const VO_END_SEC = 11; const TOTAL_DURATION_SEC = 15.5; const BEATS = [{t:0, mode:"full"}];')
            r=subprocess.run([sys.executable,str(SCRIPTS/'lint_beats.py'),str(p)],capture_output=True,text=True)
            self.assertEqual(1,r.returncode,r.stderr)
            self.assertFalse(json.loads(r.stdout)['pass'])

if __name__ == '__main__': unittest.main()
