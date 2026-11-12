#!/usr/bin/env python3
"""Offline source-first context acquisition. Never fetch, translate or infer timing."""
import argparse
import hashlib
import json
import re
from pathlib import Path

SCHEMA = 'a44-source-context-1'

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def parse_srt(text):
    cues=[]
    def seconds(s):
        h,m,sec=re.split('[:,.]',s)[:3];ms=re.split('[:,.]',s)[3]
        return int(h)*3600+int(m)*60+int(sec)+int(ms)/1000
    for block in re.split(r'\n\s*\n',text.strip()):
        if not block.strip():continue
        lines=block.splitlines();at=next((i for i,l in enumerate(lines) if '-->' in l),None)
        if at is None:raise ValueError('SRT block has no timing')
        match=re.fullmatch(r'(\d{2}:\d{2}:\d{2}[,.]\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}[,.]\d{3})',lines[at].strip())
        if not match:raise ValueError('invalid SRT timestamp')
        start,end=map(seconds,match.groups());spoken='\n'.join(lines[at+1:])
        if end<=start or not spoken.strip() or (cues and start<cues[-1]['start']):raise ValueError('invalid SRT cue bounds/text/order')
        cues.append({'id':f'cue-{len(cues)+1}','start':start,'end':end,'text':spoken})
    return cues

def word_cues(words,script,narration_end):
    """Exact sequential line alignment; whitespace from script, no skipped characters."""
    norm=lambda text:re.sub(r'\s','',text)
    stream=''.join(norm(w['w']) for w in words)
    if stream!=norm(script):raise ValueError('word spine/script mismatch; no cue timing inferred')
    spans=[];pos=0;last=-1
    for w in words:
        if not all(isinstance(w.get(k),(int,float)) for k in ('s','e')) or w['s']<last or w['s']<0 or w['e']<w['s']:raise ValueError('invalid word timestamp')
        n=len(norm(w['w']));spans.append((pos,pos+n,w));pos+=n;last=w['s']
    cues=[];pos=0
    for line in script.splitlines():
        n=len(norm(line))
        if not n:continue
        selected=[w for a,b,w in spans if a<pos+n and b>pos]
        if any(a<pos<b or a<pos+n<b for a,b,w in spans):raise ValueError('word spans script line boundary; explicit alignment needed')
        cues.append({'id':f'word-cue-{len(cues)+1}','start':min(w['s'] for w in selected),'end':max(w['e'] for w in selected),'text':line});pos+=n
    if not isinstance(narration_end,(int,float)) or not cues or narration_end<=cues[-1]['start']:raise ValueError('explicit narration end bound required')
    return [{**c,'original_word_end':c['end'],'end':cues[i+1]['start'] if i+1<len(cues) else narration_end,'display_bound_reason':'next phrase word start' if i+1<len(cues) else 'explicit narration media duration'} for i,c in enumerate(cues)]

def build_context(task_dir,source_video=None,narration_srt=None,fallback_transcript=None,language=None,word_timing=None,exact_script=None,narration_end=None,sync_verification=None,avatar_video=None,source_duration=None):
    task=Path(task_dir);errors=[];metadata={};inputs={}
    meta=task/'source/source.json';supplied=task/'source/transcript.txt'
    if meta.exists():
        try:metadata=json.loads(meta.read_text());inputs[str(meta)]=sha256(meta)
        except (ValueError,OSError) as e:errors.append({'code':'invalid-source-metadata','error':str(e)})
    else:errors.append({'code':'missing-source-metadata','path':str(meta)})
    transcript=None
    candidates=[(supplied,'task/source/transcript.txt')]
    if fallback_transcript:candidates.append((Path(fallback_transcript),'local-original-fallback'))
    for path,origin in candidates:
        if not path.is_file():continue
        text=path.read_text(encoding='utf-8')
        if not text.strip():errors.append({'code':'empty-transcript','path':str(path)});continue
        if not any(line.strip() and not line.lstrip().startswith('#') for line in text.splitlines()):
            errors.append({'code':'metadata-only-transcript','path':str(path)});continue
        if origin=='local-original-fallback':
            origin='local-unverified-transcript'
            errors.append({'code':'unverified-transcript-time-extent','path':str(path),'warning':'Local transcript timing and source duration not reconciled; not official subtitles'})
        if source_duration is not None:
            stamps=re.findall(r'(?<!\d)(\d{1,2}):(\d{2}(?:\.\d+)?)(?!\d)',text)
            seconds=[float(end) for end in re.findall(r'^\s*\d+(?:\.\d+)?\s*-\s*(\d+(?:\.\d+)?)\s*:',text,re.M)]
            extent=max([int(m)*60+float(s) for m,s in stamps]+seconds,default=0)
            if extent>source_duration:errors.append({'code':'transcript-extent-exceeds-source','path':str(path),'extent_seconds':extent,'source_duration_seconds':source_duration,'warning':'Untested local transcript; timestamps are not source-range authority'})
        digest=sha256(path);inputs[str(path)]=digest
        transcript={'path':str(path),'sha256':digest,'text':text,'origin':origin,'language':metadata.get('language',metadata.get('original_language',language)),'timed':False}
        break
    if transcript is None:errors.append({'code':'missing-original-transcript','path':str(supplied)})
    cues=[]
    if narration_srt:
        path=Path(narration_srt);cues=parse_srt(path.read_text(encoding='utf-8'));inputs[str(path)]=sha256(path)
    reference_cues=cues
    cues=[]
    authority='none'
    if word_timing:
        if not exact_script:raise ValueError('word timing requires exact script')
        path=Path(word_timing);script_path=Path(exact_script);data=json.loads(path.read_text())
        words=[w for page in data for w in page['words']] if data and 'words' in data[0] else data
        cues=word_cues(words,script_path.read_text(),narration_end);authority='existing-word-spine'
        inputs[str(path)]=sha256(path);inputs[str(script_path)]=sha256(script_path)
    if source_video:inputs[str(source_video)]=sha256(source_video)
    timing_inputs={'wordTimingSha256':sha256(word_timing) if word_timing else None,'scriptSha256':sha256(exact_script) if exact_script else None,'avatarSha256':sha256(avatar_video) if avatar_video else None}
    return {'timing_input_paths':{k:str(Path(v).resolve()) for k,v in [('wordTimingSha256',word_timing),('scriptSha256',exact_script),('avatarSha256',avatar_video)] if v},'timing_inputs':timing_inputs,'sync_verification':sync_verification or {'status':'unverified','reference':None},'timing_authority':authority,'reference_srt_cues':reference_cues,'schema':SCHEMA,'inputs':inputs,'source':metadata,'transcript':transcript,'narration_cues':cues,'errors':errors,'fallback':{'status':'not-needed' if transcript else 'required-not-fetched','policy':'original-language-only; explicit local input or future approved acquisition; no network in Phase A'}}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--task-dir',required=True);ap.add_argument('--source-video');ap.add_argument('--narration-srt');ap.add_argument('--fallback-transcript');ap.add_argument('--language');ap.add_argument('--out',required=True)
    ap.add_argument('--source-duration',type=float);ap.add_argument('--avatar-video');ap.add_argument('--word-timing');ap.add_argument('--exact-script');ap.add_argument('--narration-end',type=float)
    ap.add_argument('--sync-verification',help='local verification record JSON; does not perform sync verification')
    args=vars(ap.parse_args())
    if args.get('sync_verification'):args['sync_verification']=json.loads(Path(args['sync_verification']).read_text())
    out=Path(args.pop('out'));result=build_context(**args);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
