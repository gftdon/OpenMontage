import importlib.util
import unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('broll_plan',Path(__file__).resolve().parents[1]/'broll_plan.py')
bp=importlib.util.module_from_spec(spec);spec.loader.exec_module(bp)
def context(cues):return {'inputs':{'word':'a'*64,'script':'b'*64},'timing_inputs':{'wordTimingSha256':'a'*64,'scriptSha256':'b'*64},'timing_authority':'existing-word-spine','sync_verification':{'status':'accepted','reference':'test-anchor-record','wordTimingSha256':'a'*64,'scriptSha256':'b'*64},'narration_cues':cues}

class PlanTests(unittest.TestCase):
    def plan(self):
        return {'schema':bp.PLAN_SCHEMA,'beats':[{'id':'b1','t':9,'end':12,'cue_ids':['c1'],'spoken':'ทำโปสเตอร์','query':'poster design workflow','semantic_rationale':'Shows the poster use case spoken in this interval','candidates':[{'tier':'source','identity':'source:'+'a'*64,'path':'yt_a.mp4','available':True}],'selected':{'tier':'source','identity':'source:'+'a'*64,'path':'yt_a.mp4','source_range':[1,4]},'rejected_tiers':[]}]}
    def test_linked_plan_passes_and_wrong_cue_time_fails(self):
        cues=[{'id':'c1','start':8,'end':13,'text':'ทำโปสเตอร์'}];p=self.plan()
        self.assertEqual(bp.validate_plan(p,context(cues)),[])
        cues[0]['start']=14;cues[0]['end']=15
        self.assertTrue(any('overlap' in e for e in bp.validate_plan(p,context(cues))))
    def test_empty_query_spoken_and_skipped_source_without_reason_fail(self):
        p=self.plan();b=p['beats'][0];b['query']='';b['spoken']='';b['selected']['tier']='stock'
        errors=bp.validate_plan(p,context([{'id':'c1','start':8,'end':13,'text':'ทำโปสเตอร์'}]))
        self.assertTrue(any('query' in e for e in errors));self.assertTrue(any('spoken' in e for e in errors));self.assertTrue(any('priority' in e for e in errors))
    def test_source_present_without_timing_still_requires_priority_reason(self):
        p=self.plan();b=p['beats'][0];b['selected']['tier']='ai';b['selected']['identity']='image-sha256:'+'b'*64;b['rejected_tiers']=[{'tier':'source','reason':'Source contains no poster UI in reviewed contact sheet'}]
        self.assertEqual(bp.validate_plan(p,context([{'id':'c1','start':8,'end':13,'text':'ทำโปสเตอร์'}])),[])

class IdentityTests(unittest.TestCase):
    def use(self,t,end,**kw):return {'t':t,'end':end,'media':'broll','origin':'source','identity':'source:'+'a'*64,'source_range':[0,10],'duration':12,'from':0,**kw}
    def test_source_alias_overlap_rejected_but_continuation_passes(self):
        a=self.use(0,5,path='yt_a');b=self.use(30,35,path='yt_alias')
        self.assertTrue(bp.check_usage([a,b])['violations'])
        b['source_range']=[10,20];self.assertEqual(bp.check_usage([a,b])['violations'],[])
    def test_pixabay_reencode_at40_and_ai_image_hash_rejected(self):
        for origin,identity in [('stock','pixabay:123'),('ai','image-sha256:abc')]:
            self.assertTrue(bp.check_usage([self.use(0,5,origin=origin,identity=identity),self.use(40,45,origin=origin,identity=identity)])['violations'])
    def test_exact_decoded_alias_rejected_and_near_hash_warning_only(self):
        a=self.use(0,5,identity='source:'+'a'*64,decoded_sha256='exact',dhash='0000')
        b=self.use(40,45,identity='source:'+'b'*64,decoded_sha256='exact',dhash='0001')
        self.assertTrue(bp.check_usage([a,b])['violations']);b['decoded_sha256']='different'
        r=bp.check_usage([a,b]);self.assertEqual(r['violations'],[]);self.assertTrue(r['warnings'])
    def test_boundary_measured_from_previous_shown_end(self):
        a=self.use(0,5);self.assertTrue(bp.check_usage([a,self.use(64.95,70)])['violations'])
        self.assertEqual(bp.check_usage([a,self.use(65,70)])['violations'],[])
    def test_loop_rejected_respects_from_and_exempts_avatar_cards(self):
        self.assertTrue(bp.check_usage([self.use(0,6,duration=8,**{'from':3})])['violations'])
        self.assertEqual(bp.check_usage([self.use(0,6,duration=10,**{'from':3})])['violations'],[])
        self.assertEqual(bp.check_usage([self.use(0,100,media='typo'),self.use(0,100,mode='full')])['violations'],[])
    def test_actual_renderer_from_maps_to_underlying_source_interval(self):
        beats=[{'t':0,'end':5,'media':'broll','mode':'pip','src':'yt_alias','origin':'source','from':2}]
        records={'yt_alias':{'source_sha256':'a'*64,'source_in':10,'source_out':20,'duration':10}}
        uses=bp.derive_usage(beats,records)
        self.assertEqual(uses[0]['identity'],'source:'+'a'*64)
        self.assertEqual(uses[0]['source_range'],[12,17])
        self.assertEqual(uses[0]['from'],2)
    def test_cut_manifest_binds_actual_input_and_output_bytes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);source=p/'source.mp4';clip=p/'yt_demo.mp4';source.write_bytes(b'input');clip.write_bytes(b'output')
            r=bp.cut_record(source,clip,3,8,5)
            self.assertEqual(r['source_in'],3);self.assertEqual(r['source_out'],8)
            self.assertEqual(len(r['source_sha256']),64);self.assertEqual(len(r['sha256']),64)
    def test_missing_identity_and_nonfinite_bounds_fail_closed(self):
        self.assertTrue(bp.check_usage([self.use(0,5,identity=None)])['violations'])
        self.assertTrue(bp.check_usage([self.use(float('nan'),5)])['violations'])
