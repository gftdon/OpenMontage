#!/usr/bin/env python3
"""Fail-closed V3 timing/provenance gate. punch is an instantaneous step; cam is not."""
import argparse
import json
import math
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import broll_ledger as bl


def number(v):
    try:
        n = float(v)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def lint_beats(beats, end_card_seconds, thresholds):
    issues = []
    def issue(code, t, detail): issues.append(dict(code=code,t=t,detail=detail))
    if not beats:
        issue('metadata',None,'BEATS must not be empty')
    end = number(end_card_seconds)
    if end is None or end < 0: issue('metadata',None,'invalid endcard duration')
    elif end > thresholds['maxEndcardSeconds']: issue('endcard',None,'endcard exceeds limit')
    previous_identity = None
    hold_start = None
    previous_end = None
    for b in beats:
        t, end = number(b.get('t')), number(b.get('end'))
        if t is None or end is None or t < 0 or end <= t or (previous_end is not None and abs(t-previous_end)>0.001):
            issue('metadata',t,'invalid/noncontiguous beat interval'); continue
        if b.get('mode') not in ('full','pip'): issue('metadata',t,'invalid mode')
        if b.get('captionLane','bottom') not in ('top','bottom'):issue('metadata',t,'invalid caption lane')
        media = b.get('media')
        if media is not None and media not in ('broll','clip','typo'): issue('metadata',t,'invalid media')
        if media:
            src=b.get('src')
            if not isinstance(src,str) or isinstance(src,bl.Raw) or not src: issue('metadata',t,'missing literal src')
            origin=b.get('origin')
            if origin not in ('source','stock','ai') or (isinstance(src,str) and (src.startswith('yt_') != (origin=='source') or src.startswith('ai_') != (origin=='ai'))):
                issue('origin',t,'origin must match yt_ source / ai_ AI convention')
            if b.get('layout') not in ('stage','full'): issue('metadata',t,'missing layout')
            chrome=b.get('chrome')
            # The tokenizer represents true/false as Raw, never eval source expressions.
            if isinstance(chrome,bl.Raw): chrome={'true':True,'false':False}.get(str(chrome))
            if type(chrome) is not bool: issue('metadata',t,'chrome must be literal boolean')
            if origin in ('stock','ai') and chrome is True: issue('stock-chrome',t,'stock/AI must not show source chrome')
        target='avatar' if b.get('mode')=='full' else 'source' if media in ('broll','clip') and b.get('origin')=='source' else None
        if b.get('mode')=='pip' and not media:issue('metadata',t,'pip requires rendered media')
        punches=b.get('punch',[])
        if punches and target is None:issue('punch-origin',t,'no rendered avatar/source punch target')
        if not isinstance(punches,list):issue('metadata',t,'punch must be array');punches=[]
        valid_punches=[];z,fx,fy=1.,.5,.5;last_pt=t
        for p in punches:
            if not isinstance(p,dict):issue('metadata',t,'invalid punch');continue
            pt,pz=number(p.get('t')),number(p.get('z'));px,py=number(p.get('fx',.5)),number(p.get('fy',.5))
            if None in (pt,pz,px,py) or not t<=pt<end or pt<last_pt or pz<1 or not (0<=px<=1 and 0<=py<=1):
                issue('metadata',t,'invalid punch geometry/time');continue
            old_left,old_top=fx*(1-1/z),fy*(1-1/z)
            left,top=px*(1-1/pz),py*(1-1/pz)
            cut=target is not None and (abs(pz/z-1)>=thresholds['scaleStep']-1e-8 or max(abs(left-old_left),abs(top-old_top))>=thresholds['cropStep']-1e-8)
            valid_punches.append((pt,cut,(pz,px,py)))
            z,fx,fy,last_pt=pz,px,py,pt
        cards=b.get('cards',[])
        valid_cards=[];last_time=t
        if cards and (media!='typo' or not isinstance(cards,list)):issue('metadata',t,'cards only allowed for typography')
        elif isinstance(cards,list):
            for card in cards:
                ct=number(card.get('t')) if isinstance(card,dict) else None;lines=card.get('lines') if isinstance(card,dict) else None
                if ct is None or not t<=ct<end or ct<last_time or not isinstance(lines,list) or not lines or not all(isinstance(x,str) and x for x in lines):
                    issue('metadata',t,'invalid typography card');continue
                valid_cards.append((ct,lines));last_time=ct
        lower=b.get('lower') if b.get('mode')=='full' else None
        lower_t=number(lower.get('t',t)) if isinstance(lower,dict) else None
        lower_dur=number(lower.get('dur',6)) if isinstance(lower,dict) else None
        if lower is not None and (lower_t is None or lower_dur is None or lower_dur<=0):issue('metadata',t,'invalid lower timing');lower=None
        times={t,end}
        times.update(pt for pt,_,_ in valid_punches)
        times.update(ct for ct,_ in valid_cards)
        # Overlays never reset holds, regardless of dwell or text changes.
        # Only primary shot/layout, primary typography cards and approved punches do.
        for now in sorted(times)[:-1]:
            if b.get('mode')=='full':base=['avatar']
            else:
                lines=[lines for ct,lines in valid_cards if ct<=now]
                base=[media,b.get('src') if media!='typo' else None,b.get('layout'),lines[-1] if media=='typo' and lines else []]
            identity=json.dumps(base,sort_keys=True)
            is_cut=any(pt==now and cut for pt,cut,_ in valid_punches)
            if previous_identity!=identity or is_cut:
                if hold_start is not None and now-hold_start>thresholds['maxHoldSeconds']+1e-8:issue('hold',hold_start,'rendered visual hold exceeds limit')
                hold_start=now
            previous_identity=identity
        if hold_start is not None and end-hold_start>thresholds['maxHoldSeconds']+1e-8:issue('hold',hold_start,'rendered visual hold exceeds limit')
        previous_end=end
    return issues


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('composition'); ap.add_argument('--report'); args=ap.parse_args()
    try:
        text=Path(args.composition).read_text()
        beats=bl.parse_beats(text)
        def constant(name):
            m=re.search(r'const\s+'+name+r'\s*=\s*([\d.]+)\s*;',text)
            if not m: raise ValueError('missing literal '+name)
            return float(m[1])
        vo,total=constant('VO_END_SEC'),constant('TOTAL_DURATION_SEC')
        for i,b in enumerate(beats): b['end']=beats[i+1]['t'] if i+1<len(beats) else vo
        thresholds=json.loads((Path(__file__).parent/'qc_thresholds.json').read_text())
        issues=lint_beats(beats,total-vo,thresholds)
        result=dict(pass_=not issues,issues=issues,beats=len(beats)); result['pass']=result.pop('pass_')
        output=json.dumps(result,ensure_ascii=False,indent=2)
        if args.report: Path(args.report).write_text(output)
        print(output); return 1 if issues else 0
    except (OSError,ValueError,bl.BeatsParseError) as e:
        print(json.dumps({'pass':False,'issues':[{'code':'parse','detail':str(e)}]})); return 2

if __name__=='__main__': sys.exit(main())
