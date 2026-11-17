import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'transcode_broll.sh'
class TranscodeSelectionTests(unittest.TestCase):
 def run_case(self,files,names=()):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);p=Path(tmp.name);src=p/'raw';out=p/'out';tools=p/'bin';src.mkdir();tools.mkdir();shutil.copyfile(SCRIPT,p/'transcode_broll.sh')
  for name in files:(src/name).write_bytes(name.encode())
  (p/'media_manifest.py').write_text('import sys,json\nfrom pathlib import Path\np=Path(sys.argv[2])/"manifest-calls.json"\na=json.loads(p.read_text()) if p.exists() else []\na.append(sys.argv[3]);p.write_text(json.dumps(a))\n')
  (tools/'ffmpeg').write_text('#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\na=sys.argv;src=a[a.index("-i")+1];Path(a[-1]).write_bytes(Path(src).read_bytes())\n')
  (tools/'ffprobe').write_text('#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\nif not Path(sys.argv[-1]).exists():raise SystemExit(1)\nif "-show_entries" in sys.argv:print("8.00")\n')
  for f in tools.iterdir():f.chmod(0o755)
  env={**os.environ,'PATH':str(tools)+os.pathsep+os.environ['PATH']};r=subprocess.run(['bash',str(p/'transcode_broll.sh'),str(src),str(out),*names],capture_output=True,text=True,env=env);return r,out
 def test_explicit_mp4_only_webm_only_and_both_prefer_mp4(self):
  for files,expected in [(['clip.mp4'],b'clip.mp4'),(['clip.webm'],b'clip.webm'),(['clip.mp4','clip.webm'],b'clip.mp4')]:
   with self.subTest(files=files):
    r,out=self.run_case(files,['clip']);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual((out/'clip.mp4').read_bytes(),expected);self.assertEqual(json.loads((out/'manifest-calls.json').read_text()),['clip'])
 def test_explicit_missing_fails_clearly(self):
  r,_=self.run_case([],['missing']);self.assertNotEqual(r.returncode,0);self.assertIn('missing missing',r.stderr)
 def test_default_empty_success_and_space_filename_deduplicated(self):
  r,out=self.run_case([]);self.assertEqual(r.returncode,0,r.stderr);self.assertFalse((out/'manifest-calls.json').exists())
  r,out=self.run_case(['with space.mp4','with space.webm','other.webm']);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual((out/'with space.mp4').read_bytes(),b'with space.mp4');self.assertEqual(sorted(json.loads((out/'manifest-calls.json').read_text())),['other','with space'])
