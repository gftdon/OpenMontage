#!/usr/bin/env python3
"""Record ranges after successful local source cuts (no network)."""
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from broll_plan import cut_record, IDENTITY_VERSION

def main(argv):
    source,out=Path(argv[0]),Path(argv[1]);path=out/'_cuts.json'
    result=json.loads(path.read_text()) if path.exists() else {'schema':IDENTITY_VERSION,'clips':{}}
    for spec in argv[2:]:
        name,start,end=spec.split(':');clip=out/(name+'.mp4')
        duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(clip)],text=True).strip())
        result['clips'][name]=cut_record(source,clip,float(start),float(end),duration)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main(sys.argv[1:])
