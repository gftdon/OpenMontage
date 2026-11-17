#!/usr/bin/env python3
"""Offline post-transcode identity of actual public bytes; raw provenance retained."""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from broll_plan import file_sha256,probe_duration,finite

def save_json(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.'+path.name)
 try:
  with os.fdopen(fd,'w') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
  os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)

def write_stock_manifest(raw_dir,public_dir,names,probe=probe_duration):
 raw=Path(raw_dir);public=Path(public_dir);records=json.loads((raw/'_manifest.json').read_text());out=public/'_manifest.json'
 result=json.loads(out.read_text()) if out.exists() else {}
 for name in names:
  r=records.get(name,{});p=public/(name+'.mp4')
  if not p.is_file() or not r.get('pixabay_id') or not r.get('raw_md5'):raise ValueError(name+': missing actual asset or raw provenance')
  duration=probe(p)
  if not finite(duration) or duration<=0:raise ValueError(name+': invalid duration')
  result[name]={**r,'schema':'a44-public-media-1','origin':'stock','path':str(p.resolve()),'sha256':file_sha256(p),'duration':duration,'provenance':{'raw_manifest':str((raw/'_manifest.json').resolve()),'raw_md5':r['raw_md5'],'transcode':'1080p25-cover-h264'}}
 # Existing check_broll freshness entry point reads the raw-directory manifest.
 # Keep raw_md5/id unchanged while binding final public bytes there automatically.
 for name in names:records[name]=result[name]
 save_json(raw/'_manifest.json',records);save_json(out,result);return result

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('raw');ap.add_argument('public');ap.add_argument('names',nargs='+');a=ap.parse_args();write_stock_manifest(a.raw,a.public,a.names)
