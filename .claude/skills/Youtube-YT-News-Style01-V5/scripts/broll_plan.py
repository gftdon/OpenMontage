#!/usr/bin/env python3
"""Validate agent-authored semantics and underlying media identity, without AI calls.
Validation proves linkage/contracts, NOT semantic relevance. No keyword mapper.

V4 input: `--beats` is the episode JSON (`episode.json`, schema yt-news-v4-episode/1) read through
episode_data.load_episode (see load_v4_episode). Top-level `voEndSec`, `brollDur` and `assetDir` come from
that file; there is no per-episode TSX and no text parsing here.
"""
import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path

PLAN_SCHEMA='a44-broll-plan-1'
IDENTITY_VERSION='a44-underlying-60s-1'
TIERS=('source','ai','stock')

def finite(n):return isinstance(n,(int,float)) and not isinstance(n,bool) and math.isfinite(n)
def interval(a,b):return isinstance(a,(list,tuple)) and len(a)==2 and all(finite(x) for x in a) and a[0]>=0 and a[1]>a[0] and (b is None or a[1]<=b)
def overlap(a,b):return a[0]<b[1] and b[0]<a[1]

def validate_sync(context):
    v=context.get('sync_verification',{});actual=context.get('timing_inputs',{});errors=[]
    if context.get('timing_authority')!='existing-word-spine' or v.get('status')!='accepted' or not v.get('reference'):errors.append('accepted word spine sync verification reference required')
    for key in ('wordTimingSha256','scriptSha256','avatarSha256'):
        expected=actual.get(key)
        if key=='avatarSha256' and not expected and not v.get(key):continue
        if key=='avatarSha256' and v.get(key) and not context.get('timing_input_paths',{}).get(key):errors.append('accepted avatar hash requires actual avatar path')
        if not isinstance(expected,str) or len(expected)!=64 or v.get(key)!=expected:errors.append('sync verification stale/missing '+key)
        path=context.get('timing_input_paths',{}).get(key)
        if path:
            try:
                if file_sha256(path)!=expected:errors.append('changed timing input bytes '+key)
            except OSError:errors.append('missing timing input file '+key)
    inputs=context.get('inputs',{})
    for key in ('wordTimingSha256','scriptSha256'):
        if actual.get(key) not in inputs.values():errors.append('timing input hash absent from context inputs '+key)
    return errors

def validate_plan(plan,context):
    errors=[]
    if not isinstance(context,dict):return ['context with accepted word spine required (bare cues are not authority)']
    errors+=validate_sync(context)
    cues=context.get('narration_cues',[])
    lookup={c['id']:c for c in cues};seen=set()
    if plan.get('schema')!=PLAN_SCHEMA:errors.append('invalid plan schema')
    for beat in plan.get('beats',[]):
        name=beat.get('id');prefix=f'beat {name}: '
        if not name or name in seen:errors.append(prefix+'missing/duplicate id')
        seen.add(name)
        valid=interval([beat.get('t'),beat.get('end')],None)
        if not valid:errors.append(prefix+'invalid time interval')
        selected_cues=[]
        for cid in beat.get('cue_ids',[]):
            cue=lookup.get(cid)
            if cue is None:errors.append(prefix+'unknown cue '+str(cid));continue
            if valid and not overlap([beat['t'],beat['end']],[cue['start'],cue['end']]):errors.append(prefix+'cue does not overlap beat '+cid)
            selected_cues.append(cue)
        expected=sorted([c for c in cues if valid and overlap([beat['t'],beat['end']],[c['start'],c['end']])],key=lambda c:(c['start'],c['end'],c['id']))
        if beat.get('cue_ids')!=[c['id'] for c in expected]:errors.append(prefix+'cue coverage/order must include all positive-overlap cues exactly once')
        spoken='\n'.join(c['text'] for c in expected)
        if not beat.get('spoken') or beat.get('spoken')!=spoken:errors.append(prefix+'spoken must exactly match linked overlapping cues')
        for key in ('query','semantic_rationale'):
            if not isinstance(beat.get(key),str) or not beat[key].strip():errors.append(prefix+'missing '+key)
        selection=beat.get('selected',{});tier=selection.get('tier')
        if tier not in TIERS:errors.append(prefix+'invalid selected tier');continue
        if not stable_identity(tier,selection.get('identity')) or not selection.get('path'):errors.append(prefix+'missing/invalid selected stable identity/path for origin')
        if tier=='source' and not interval(selection.get('source_range'),None):errors.append(prefix+'missing source range')
        reasons={r.get('tier'):r.get('reason') for r in beat.get('rejected_tiers',[]) if isinstance(r,dict)}
        for higher in TIERS[:TIERS.index(tier)]:
            if not isinstance(reasons.get(higher),str) or not reasons[higher].strip():errors.append(prefix+'source priority requires rejection reason for '+higher)
    if not plan.get('beats'):errors.append('empty plan')
    return errors

def stable_identity(origin,identity):
    import re
    patterns={'source':r'source:[a-f0-9]{64}','ai':r'image-sha256:[a-f0-9]{64}','stock':r'pixabay:[0-9]+'}
    return origin in patterns and isinstance(identity,str) and re.fullmatch(patterns[origin],identity) is not None

def manifest_identity(origin,record):
    if origin=='source':value='source:'+str(record.get('source_sha256',''))
    elif origin=='ai':value='image-sha256:'+str(record.get('image_sha256',''))
    elif origin=='stock':value='pixabay:'+str(record.get('pixabay_id',''))
    else:raise ValueError('invalid cutaway origin')
    if not stable_identity(origin,value):raise ValueError('missing/invalid manifest stable identity')
    return value

def check_usage(usages,window=60):
    violations=[];warnings=[];previous=[]
    for u in sorted(usages,key=lambda u:u.get('t',0) if finite(u.get('t')) else -1):
        if u.get('mode')=='full' or u.get('origin') in ('avatar','presenter') or u.get('media')=='typo':continue
        name=u.get('path',u.get('identity','unknown'));bounds=[u.get('t'),u.get('end')]
        if not interval(bounds,None):violations.append(f'{name}: invalid shown interval');continue
        if not stable_identity(u.get('origin'),u.get('identity')):violations.append(f'{name}: invalid origin or missing stable underlying identity; decoded hash is supplemental only')
        duration=u.get('duration');offset=u.get('from',0)
        if not finite(duration) or not finite(offset) or offset<0 or offset>=duration:violations.append(f'{name}: missing/invalid duration/from')
        # Mirrors renderer floor((duration-from)*25)-2 Loop duration, not nominal MP4 length.
        elif math.ceil(bounds[1]*25)-math.ceil(bounds[0]*25)>max(1,math.floor((duration-offset)*25)-2):violations.append(f'{name}: shown range loops within beat')
        for prior in previous:
            if math.ceil(bounds[0]*25)/25-math.ceil(prior['end']*25)/25>=window-1e-8:continue
            same_id=bool(u.get('identity') and u.get('identity')==prior.get('identity'))
            if same_id and u.get('origin')=='source' and prior.get('origin')=='source':
                a,b=u.get('source_range'),prior.get('source_range')
                # Unknown ranges cannot establish non-overlap.
                same_id=not (interval(a,None) and interval(b,None)) or overlap(a,b)
            exact=bool(u.get('decoded_sha256') and u.get('decoded_sha256')==prior.get('decoded_sha256'))
            if same_id or exact:violations.append(f'{name}: repeated underlying media within {window}s of shown end')
            elif u.get('dhash') and prior.get('dhash'):
                try:
                    if bin(int(u['dhash'],16)^int(prior['dhash'],16)).count('1')<=4:warnings.append(f'{name}: near dHash similarity (unverified, not rejection)')
                except ValueError:warnings.append(f'{name}: invalid optional dHash')
        previous.append(u)
    return {'version':IDENTITY_VERSION,'violations':violations,'warnings':warnings}

def decoded_fingerprint(path,start=0,duration=None):
    """Exact SHA of every decoded frame in the shown range, not compressed bytes.
    Re-encodes usually alter decoded pixels: provider identity remains authoritative.
    """
    cmd=['ffmpeg','-v','error','-ss',str(start),'-i',str(path)]
    if duration is not None:cmd+=['-t',str(duration)]
    cmd+=['-an','-f','framemd5','-']
    result=subprocess.run(cmd,check=True,capture_output=True,text=True)
    frame_hashes=[line.rsplit(',',1)[-1].strip() for line in result.stdout.splitlines() if line and not line.startswith('#')]
    if not frame_hashes:raise ValueError('no decoded frames')
    return hashlib.sha256('\n'.join(frame_hashes).encode()).hexdigest()

def file_sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def cut_record(source,output,start,end,duration):
    if not interval([start,end],None) or not finite(duration) or duration<=0:raise ValueError('invalid cut bounds')
    return {'schema':IDENTITY_VERSION,'origin':'source','identity':'source:'+file_sha256(source),'source_path':str(Path(source).resolve()),'source_sha256':file_sha256(source),'source_in':start,'source_out':end,'path':str(Path(output).resolve()),'sha256':file_sha256(output),'duration':duration}

def shown_timing(start,end,offset,duration,fps=25):
    if not interval([start,end],None) or not finite(offset) or not finite(duration) or not 0<=offset<duration:raise ValueError('invalid shown timing')
    first=math.ceil(start*fps);stop=math.ceil(end*fps);from_frame=math.floor(offset*fps+.5);loop=max(1,math.floor((duration-offset)*fps)-2)
    return {'policy':'a44-beat-local-ceil-1','beat_start_frame':first,'end_frame_exclusive':stop,'from_frame':from_frame,'loop_frames':loop,'shown_frames':stop-first,'source_start':from_frame/fps,'source_end':(from_frame+stop-first)/fps,'shown_start':first/fps,'shown_end':stop/fps}

def derive_usage(beats,records,vo_end=None,actual_durations=None,renderer_durations=None):
    uses=[]
    for i,b in enumerate(beats):
        if b.get('mode')=='full' or b.get('media') not in ('broll','clip'):continue
        src=b.get('src');r=records.get(src,{})
        end=b.get('end',beats[i+1]['t'] if i+1<len(beats) else vo_end)
        offset=b.get('from',0);origin=b.get('origin');identity=None
        try:identity=manifest_identity(origin,r)
        except ValueError:identity=None
        duration=r.get('duration')
        if actual_durations is not None or renderer_durations is not None:
            actual=(actual_durations or {}).get(src);rendered=(renderer_durations or {}).get(src)
            if not finite(actual) or not finite(rendered) or abs(actual-rendered)>1/25+1e-8:raise ValueError(f'{src}: missing/mismatched actual duration and brollDur (>1 frame)')
            duration=rendered
        u={**b,'end':end,'path':src,'identity':identity,'duration':duration,'actual_duration':(actual_durations or {}).get(src),'decoded_sha256':r.get('decoded_sha256'),'dhash':r.get('dhash')}
        if finite(duration) and finite(end):
            timing=shown_timing(b['t'],end,offset,duration);u['shown_timing']=timing
        if origin=='source' and finite(r.get('source_in')) and finite(end) and finite(duration):
            u['source_range']=[r['source_in']+timing['source_start'],r['source_in']+timing['source_end']]
            if finite(r.get('source_out')) and u['source_range'][1]>r['source_out']+1/25:raise ValueError(f'{src}: shown range exceeds original source cut')
        uses.append(u)
    return uses

def reconcile_plan(plan,beats,records,diagnostic_subset=False,vo_end=None):
    errors=[];usages=derive_usage(beats,records,vo_end);matched=set()
    for item in plan.get('beats',[]):
        candidates=[(i,u) for i,u in enumerate(usages) if u['t']==item.get('t') and u['end']==item.get('end')]
        if len(candidates)!=1:errors.append(f"{item.get('id')}: plan interval does not match one rendered cutaway");continue
        i,u=candidates[0];matched.add(i);selected=item.get('selected',{});record=records.get(u['src'],{})
        expected_path=u['src']+'.mp4'
        if selected.get('path')!=expected_path or selected.get('tier')!=u.get('origin') or selected.get('from',0)!=u.get('from',0):errors.append(f"{item.get('id')}: selected path/origin/from differs from BEATS")
        if not record.get('sha256') or len(record['sha256'])!=64 or not u.get('identity') or selected.get('identity')!=u['identity']:errors.append(f"{item.get('id')}: identity must derive from actual hashed manifest record")
        if u.get('origin')=='source' and selected.get('source_range')!=u.get('source_range'):errors.append(f"{item.get('id')}: source range differs from actual cut offset")
    if not diagnostic_subset and matched!=set(range(len(usages))):errors.append('full plan must cover every rendered cutaway')
    return errors

def probe_duration(path):
    value=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(path)],text=True))
    return float(value['format']['duration'])

NO_TSX_MESSAGE='V4 has no per-episode TSX; pass --episode <episode.json>'
# Numeric fields of a V4 beat that must be finite numbers (JSON numbers, or numeric strings from hand-edited input).
NUMERIC_KEYS=('t','end','from','at','dur','z','fx','fy','x','y','w','h')

def normalize_beats(beats):
    def convert(value,key=None):
        if isinstance(value,list):return [convert(v) for v in value]
        if isinstance(value,dict):return {k:convert(v,k) for k,v in value.items()}
        if key in NUMERIC_KEYS:
            number=float(value)
            if not math.isfinite(number):raise ValueError('nonfinite beat field '+key)
            return number
        return value
    return convert(beats)

def load_v4_episode(path):
    """Read a V4 episode.json through the shared loader (episode_data.load_episode).

    Returns {'beats':[{t,end,...}], 'vo_end', 'total', 'broll_dur':{src:seconds}, 'asset_dir', 'sha256', 'path'}.
    Raises ValueError (EpisodeFormatError is one) for anything that is not a V4 episode object; schema rules
    (S01..S20) are NOT re-checked here, that is episode_schema.mjs.
    """
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    import episode_data as ed
    p=Path(path)
    if p.suffix.lower() in ('.tsx','.ts','.jsx','.js'):raise ValueError(NO_TSX_MESSAGE)
    episode=ed.load_episode(p)
    top=episode.get('top') or {}
    if episode.get('format')!='json-object' or top.get('schema')!='yt-news-v4-episode/1':raise ValueError('not a V4 episode.json (expected an object with "schema": "yt-news-v4-episode/1")')
    table=top.get('brollDur')
    if not isinstance(table,dict) or not table:raise ValueError('episode.json has no brollDur table')
    broll_dur={}
    for key,value in table.items():
        number=ed.num(value)
        if number is None or number<=0:raise ValueError('brollDur['+str(key)+'] must be a positive number')
        broll_dur[key]=number
    asset_dir=top.get('assetDir')
    if not isinstance(asset_dir,str) or not asset_dir:raise ValueError('episode.json has no assetDir')
    return {'beats':normalize_beats(episode['beats']),'vo_end':episode['vo_end'],'total':ed.num(top.get('totalDurationSec')),'broll_dur':broll_dur,'asset_dir':asset_dir,'sha256':file_sha256(p),'path':str(p)}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--plan',required=True);ap.add_argument('--context',required=True);ap.add_argument('--out',required=True)
    ap.add_argument('--beats',required=True,help='episode.json (yt-news-v4-episode/1)');ap.add_argument('--manifest',required=True);ap.add_argument('--cuts',required=True);ap.add_argument('--diagnostic-subset',action='store_true');args=ap.parse_args()
    plan=json.loads(Path(args.plan).read_text());context=json.loads(Path(args.context).read_text());errors=validate_plan(plan,context)
    episode=load_v4_episode(args.beats);beats=episode['beats'];vo=episode['vo_end']
    records=json.loads(Path(args.manifest).read_text());cuts=json.loads(Path(args.cuts).read_text());records.update(cuts.get('clips',cuts))
    errors+=reconcile_plan(plan,beats,records,args.diagnostic_subset,vo)
    Path(args.out).write_text(json.dumps({'schema':PLAN_SCHEMA,'pass':not errors and not args.diagnostic_subset,'diagnosticPass':not errors,'complete':not args.diagnostic_subset,'semantic_relevance':'not-evaluated','errors':errors},ensure_ascii=False,indent=2)+'\n')
    return 1 if errors else 0
if __name__=='__main__':raise SystemExit(main())
