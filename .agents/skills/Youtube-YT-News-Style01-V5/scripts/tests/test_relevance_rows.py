import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import score_relevance as s
from broll_costs import Budget,load_config,config_sha256
EPISODE=Path(__file__).resolve().parent/'fixtures/a67/broll/two-stock-beats.json'
JPEG=b'\xff\xd8\xff\xc0\x00\x0b\x08\x02\x40\x04\x00\x01\x01\x11\x00\xff\xd9'
class RowTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name).resolve();c=load_config();self.a={'approved':True,'project':str(self.p),'caps':c['caps'],'config_sha256':config_sha256(c),**{k:{x:c[k][x] for x in ('provider','model')} for k in ('image','relevance')}}
 def identity(self,asset='1',cues=None):return {'origin':'stock','identity':'pixabay:'+asset,'cue_ids':cues or ['c1'],'context_sha256':'b'*64}
 def score(self,b,ident,score):
  return s.score_asset(b,JPEG,'spoken',ident,runner=lambda *_:{'outputs':[{'type':'text','text':json.dumps({'score':score,'reason':'verdict'})}],'usage':{'total_input_tokens':1,'total_output_tokens':1,'total_thought_tokens':0,'total_tokens':2}},exposure_verified=True)
 def test_overlap_zero_survives_expanded_cues_and_valid_rescore_records_resolution(self):
  b=Budget(self.p,self.a,today='2026-11-08');self.score(b,self.identity(),0)
  expanded=self.identity(cues=['c1','c2']);r=s.score_asset(b,JPEG,'changed',expanded);self.assertEqual(r['score'],0)
  self.assertIsNone(s.score_asset(b,JPEG,'spoken',self.identity(cues=['c3']))['score'])
  self.assertIsNone(s.score_asset(b,JPEG,'spoken',self.identity('2',['c1','c2']))['score'])
  self.score(b,expanded,2);self.assertIsNone(s.score_asset(b,JPEG,'new text',self.identity())['score'])
  ledger=json.loads((self.p/'artifacts/relevance-outcomes.json').read_text());self.assertTrue(ledger['resolutions']);self.assertTrue(any(e.get('cue_ids')==['c1'] for e in ledger['entries'].values()))
 def test_main_multirow_cached_stop_cannot_hide_second_known_zero(self):
  context={'timing_inputs':{},'narration_cues':[]};ctx=s.digest(json.dumps(context,sort_keys=True,ensure_ascii=False).encode())
  records={};beats=[];items=[]
  b=Budget(self.p,self.a,today='2026-11-08')
  for i,score in enumerate((2,0)):
   name='asset'+str(i);media=self.p/(name+'.mp4');media.write_bytes(b'media');records[name]={'sha256':s.file_sha256(media),'pixabay_id':str(i+1),'duration':3};beat={'t':i*4,'end':i*4+2,'origin':'stock','src':name,'layout':'stage'};beats.append(beat)
   ident={'origin':'stock','identity':'pixabay:'+str(i+1),'cue_ids':['c'+str(i)],'context_sha256':ctx,'sha256':records[name]['sha256'],'frame_spec':s.frame_spec(beat,3)}
   self.score(b,ident,score)
   items.append({'id':name,'t':beat['t'],'end':beat['end'],'spoken':'spoken','cue_ids':ident['cue_ids'],'selected':{'identity':ident['identity']}})
  # Simulate historical cache containing stale accounting state; verdict must not drive stop.
  for f in (self.p/'artifacts/relevance-cache').glob('*.json'):
   data=json.loads(f.read_text());data['stop_paid_reason']='historical auth';data['budget_status']='STOP_PAID';f.write_text(json.dumps(data))
  b.stop('observed usage exceeded reservation')
  values={'plan':{'beats':items},'context':context,'manifest':records,'cuts':{}}
  argv=['score_relevance']
  for name,v in values.items():f=self.p/(name+'.json');f.write_text(json.dumps(v));argv+=['--'+name,str(f)]
  comp=self.p/'episode.json';shutil.copy(EPISODE,comp);out=self.p/'report.json';argv+=['--beats',str(comp),'--project',str(self.p),'--public',str(self.p),'--out',str(out)]
  with patch.object(sys,'argv',argv),patch.object(s,'validate_plan',return_value=[]),patch.object(s,'reconcile_plan',return_value=[]),patch.object(s,'probe_duration',return_value=3),patch.object(s,'extract_frame',return_value=JPEG):
   self.assertEqual(s.main(),1)
  report=json.loads(out.read_text());self.assertEqual(report['results'][1]['score'],0);self.assertNotEqual(report['results'][1]['status'],'unverified_auth');self.assertNotIn('stop_paid_reason',report['results'][0]);self.assertEqual(report['budget_stop_reason'],'observed usage exceeded reservation')
