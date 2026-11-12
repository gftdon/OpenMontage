"""Actual-frame diagnostic assertions; MORPH_QC_REPORT selects a retained run.

V4: the beats are read from the episode JSON of that run (MORPH_QC_EPISODE, default: the engine sample
remotion-composer/src/ytNewsStyle01V4Sample.json); the engine no longer contains `const BEATS`."""
import json
import os
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[5]
REPORT=os.environ.get('MORPH_QC_REPORT')
EPISODE=Path(os.environ.get('MORPH_QC_EPISODE') or ROOT/'remotion-composer/src/ytNewsStyle01V4Sample.json')

def overlaps(a,b):
 return min(a['x']+a['width'],b['x']+b['width'])>max(a['x'],b['x']) and min(a['y']+a['height'],b['y']+b['height'])>max(a['y'],b['y'])

@unittest.skipUnless(REPORT,'select actual diagnostic report with MORPH_QC_REPORT')
class ActualMorphBackingTests(unittest.TestCase):
 def test_visible_headline_backing_never_overlaps_avatar_and_settles(self):
  report=json.loads(Path(REPORT).read_text());run=Path(report['artifactDirectory'])
  beats=json.loads(EPISODE.read_text())['beats'];checked=0;settled=0
  for frame in report['requestedFrames']:
   data=json.loads((run/f'{frame}.json').read_text());t=frame/25
   index=max(i for i,b in enumerate(beats) if b['t']<=t);beat=beats[index]
   if not index or beats[index-1]['mode']!='full' or beat['mode']=='full':continue
   checked+=1;avatar=next(o for o in data['occluders'] if o['id']=='avatar')
   fields=[f for f in data['fields'] if f['id'] in ('headline','description') or f['id'].startswith('stat-')]
   for field in fields:
    with self.subTest(frame=frame,field=field['id']):
     backing=field.get('backing')
     if backing and backing['opacity']>=.05 and avatar['opacity']>=.05:self.assertFalse(overlaps(backing['box'],avatar['box']),'visible backing paints over moving avatar')
     if t>=beat['t']+.9 and field['id']=='headline':self.assertGreater(field['opacity'],.95);settled+=1
   if beat.get('origin')=='source':
    credit=next(f for f in data['fields'] if f['id']=='source-credit');self.assertGreater(credit['opacity'],.95)
  self.assertGreater(checked,0)
  if len(report['requestedFrames'])>2:self.assertGreater(settled,0)
