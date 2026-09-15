#!/usr/bin/env python3
"""Build the V2 soundtrack from the timeline export (events.json):
  VO   = source take re-cut per segment (teaser pieces, silence under the sting, main)
  BED  = music loop with gain automation (teaser / sting / base / dips) then ducked by VO
  SFX  = one-shots placed at event times with per-event gain
Output: a 48 kHz stereo WAV (final.wav) + the mix stems, then optional mux.

usage: build_audio.py EVENTS.json AVATAR.mp4 BED.mp3 SFX_DIR OUT_DIR [--mux VISUAL.mp4 OUT.mp4]
"""
import json, os, subprocess, sys, numpy as np

SR = 48000

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-2000:]); raise SystemExit(f"ffmpeg failed: {' '.join(cmd[:4])}")

def load(path, mono=False):
    """Decode any media to float32 PCM at SR (stereo unless mono)."""
    ch = 1 if mono else 2
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", str(ch), "-ar", str(SR), "-f", "f32le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    return x.reshape(-1, ch) if not mono else x

def write(path, x):
    x = np.clip(x, -1, 1).astype(np.float32)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", str(x.shape[1]), "-i", "-", "-c:a", "pcm_s16le", path], input=x.tobytes(), check=True)

def fade_edges(seg, ms=8):
    n = int(SR * ms / 1000)
    if len(seg) > 2 * n:
        ramp = np.linspace(0, 1, n, dtype=np.float32)[:, None]
        seg[:n] *= ramp; seg[-n:] *= ramp[::-1]
    return seg

def main():
    ev_path, avatar, bed_path, sfx_dir, out_dir = sys.argv[1:6]
    mux = None
    if "--mux" in sys.argv:
        i = sys.argv.index("--mux"); mux = (sys.argv[i + 1], sys.argv[i + 2])
    ev = json.load(open(ev_path))
    total = ev["total"]; vo_end = ev["voEnd"]
    N = int(total * SR) + SR
    os.makedirs(out_dir, exist_ok=True)

    # ---- VO ---------------------------------------------------------------
    src = load(avatar)
    vo = np.zeros((N, 2), dtype=np.float32)
    segs = list(ev["segments"]["teaser"]) + [ev["segments"]["main"]]
    for s in segs:
        a = int(s["src"] * SR); b = int(s["end"] * SR); d = int(s["dst"] * SR)
        piece = fade_edges(src[a:b].copy())
        vo[d:d + len(piece)] += piece[: max(0, N - d)]
    print(f"VO segments: {len(segs)}  main src {segs[-1]['src']:.2f}->{segs[-1]['end']:.2f} at dst {segs[-1]['dst']:.2f}")

    # ---- BED with automation ----------------------------------------------
    bed = load(bed_path)
    reps = int(np.ceil(N / len(bed))) + 1
    bed = np.tile(bed, (reps, 1))[:N]
    m = ev["music"]
    t = np.arange(N, dtype=np.float32) / SR
    gain = np.full(N, m["base"], dtype=np.float32)
    st = ev["segments"]["stingStart"]; md = ev["segments"]["mainDst"]
    gain[t < st] = m["teaser"]
    gain[(t >= st) & (t < md)] = m["sting"]
    gain[t >= vo_end] = m["endcard"]
    for dip in m["dips"]:
        a = dip["t"] - dip["pre"]; b = dip["t"] + dip["hold"]
        # cosine in/out over 0.25 s
        w = 0.25
        idx = (t >= a - w) & (t < b + w)
        tt = t[idx]
        g = np.where(tt < a, 1 - (1 - np.cos(np.pi * (tt - (a - w)) / w)) / 2 * (1 - dip["level"] / m["base"]),
             np.where(tt < b, dip["level"] / m["base"], 1 - (1 - np.cos(np.pi * (b + w - tt) / w)) / 2 * (1 - dip["level"] / m["base"])))
        gain[idx] = gain[idx] * g
    # smooth the step changes (teaser/sting/main/endcard) with a 300 ms ramp
    k = int(SR * 0.3); kern = np.ones(k, dtype=np.float32) / k
    gain = np.convolve(gain, kern, mode="same").astype(np.float32)
    # fade out over the last 2.5 s
    fo = int(SR * 2.5); end = int(total * SR)
    gain[end - fo:end] *= np.linspace(1, 0, fo, dtype=np.float32); gain[end:] = 0
    bed = bed * gain[:, None]
    # sidechain-style ducking by VO envelope (extra safety on top of the level plan)
    env = np.abs(vo).max(axis=1)
    win = int(SR * 0.05); env = np.convolve(env, np.ones(win, dtype=np.float32) / win, mode="same")
    duck = 1 - 0.55 * np.clip(env / 0.08, 0, 1)
    duck = np.convolve(duck, np.ones(int(SR * 0.12), dtype=np.float32) / int(SR * 0.12), mode="same").astype(np.float32)
    bed = bed * duck[:, None]

    # ---- SFX ----------------------------------------------------------------
    cache = {}
    sfx = np.zeros((N, 2), dtype=np.float32)
    used = 0
    for e in ev["sfx"]:
        p = os.path.join(sfx_dir, f"{e['name']}.mp3")
        if not os.path.exists(p):
            continue
        if e["name"] not in cache:
            x = load(p)
            x = x / (np.abs(x).max() + 1e-6) * 0.9  # normalise each one-shot
            cache[e["name"]] = fade_edges(x, 4)
        x = cache[e["name"]]
        g = 10 ** (e["gain"] / 20)
        d = int(e["t"] * SR)
        n = min(len(x), N - d)
        if n > 0:
            sfx[d:d + n] += x[:n] * g; used += 1
    print(f"SFX placed: {used}/{len(ev['sfx'])}")

    # ---- MIX ----------------------------------------------------------------
    mix = vo + bed + sfx
    peak = np.abs(mix).max()
    # soft limiter above 0.85 (keeps the VO untouched, tames stacked one-shots)
    thr = 0.85
    over = np.abs(mix) > thr
    mix[over] = np.sign(mix[over]) * (thr + (1 - thr) * np.tanh((np.abs(mix[over]) - thr) / (1 - thr)))
    write(os.path.join(out_dir, "vo_cut.wav"), vo)
    write(os.path.join(out_dir, "bed_auto.wav"), bed)
    write(os.path.join(out_dir, "sfx_mix.wav"), sfx)
    final = os.path.join(out_dir, "final.wav")
    write(final, mix[: int(total * SR)])
    print(f"final.wav {total:.2f}s peak {20*np.log10(peak+1e-9):.1f} dBFS")

    if mux:
        visual, out = mux
        run(["ffmpeg", "-v", "error", "-y", "-i", visual, "-i", final, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out])
        print("muxed ->", out)

if __name__ == "__main__":
    main()
