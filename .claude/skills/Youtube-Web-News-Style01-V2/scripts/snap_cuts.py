#!/usr/bin/env python3
"""Snap VO cut points to the nearest low-energy moment.
usage: snap_cuts.py WAV16K t1 t2 ... [--win 0.3]
Prints, per candidate: snapped time, RMS at candidate vs snapped, and the silent span around it.
"""
import sys, wave, numpy as np
args=[a for a in sys.argv[1:] if not a.startswith('--')]
win=0.3
for a in sys.argv[1:]:
    if a.startswith('--win='): win=float(a.split('=')[1])
w=wave.open(args[0]); sr=w.getframerate(); n=w.getnframes()
x=np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32)/32768
hop=int(sr*0.01)  # 10 ms
frames=len(x)//hop
rms=np.sqrt(np.mean(x[:frames*hop].reshape(frames,hop)**2,axis=1)+1e-12)
db=20*np.log10(rms+1e-9)
for t in args[1:]:
    t=float(t); i=int(t/0.01); lo=max(0,int((t-win)/0.01)); hi=min(frames-1,int((t+win)/0.01))
    seg=db[lo:hi+1]; j=lo+int(np.argmin(seg)); ts=j*0.01
    # silent span (< -45 dB) around snapped point
    a=j
    while a>0 and db[a-1]<-45: a-=1
    b=j
    while b<frames-1 and db[b+1]<-45: b+=1
    print(f"{t:8.2f} -> {ts:8.2f}  dB@cand {db[i]:6.1f}  dB@snap {db[j]:6.1f}  quiet {a*0.01:7.2f}..{b*0.01:7.2f}")
