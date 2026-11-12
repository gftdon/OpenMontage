#!/usr/bin/env python3
"""Measure the encoded deliverable, not the normalization target."""
import argparse
import json
import math
from pathlib import Path
import re
import subprocess
import sys


def parse_loudnorm(text):
    objects=re.findall(r'\{[^{}]*\}',text)
    for raw in reversed(objects):
        try:
            d=json.loads(raw)
            keys=('input_i','input_tp','input_lra','input_thresh','target_offset')
            result={k:float(d[k]) for k in keys}
            if not all(math.isfinite(v) for v in result.values()): raise ValueError('nonfinite loudness / silent audio')
            if 'normalization_type' in d: result['normalization_type']=d['normalization_type']
            return result
        except (KeyError,TypeError,json.JSONDecodeError):continue
    raise ValueError('missing complete loudnorm JSON / no audio')


def acceptance(data):
    i,tp=data.get('input_i'),data.get('input_tp')
    return isinstance(i,(float,int)) and isinstance(tp,(float,int)) and math.isfinite(i) and math.isfinite(tp) and abs(i+14)<=.5+1e-8 and tp<=-1


def measurement_metrics(data):
    result=dict(data)
    mode=result.pop('normalization_type',None)
    if mode is not None:result['analysis_filter_mode']=mode
    return result


def measure(path):
    r=subprocess.run(['ffmpeg','-hide_banner','-nostats','-i',str(path),'-map','0:a:0','-af','loudnorm=I=-14:TP=-1.5:LRA=20:print_format=json','-f','null','-'],capture_output=True,text=True)
    if r.returncode:raise ValueError('ffmpeg audio analysis failed: '+r.stderr[-1500:])
    return parse_loudnorm(r.stderr)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('mp4');ap.add_argument('--report',required=True);args=ap.parse_args()
    try:
        data=measurement_metrics(measure(args.mp4));report={'pass':acceptance(data),'file':str(Path(args.mp4).resolve()),'measured':data,'limits':{'I':-14,'tolerance':.5,'TP':-1}}
    except (ValueError,OSError) as e:report={'pass':False,'error':str(e)}
    Path(args.report).write_text(json.dumps(report,indent=2));print(json.dumps(report));return 0 if report['pass'] else 1
if __name__=='__main__':sys.exit(main())
