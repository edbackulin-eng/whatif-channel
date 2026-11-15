"""Sound effects under the scenes (owner 15.11): a rumble, wind, an explosion, rain, the ocean - made in
code, so every one is ours (no licence to check) and none repeats exactly.

    sfx_track(shots, total_s, out)  -> a 48 kHz stereo wav, each shot's "sfx" laid under its own time
    bed_with_sfx(music_bed, sfx, out) -> music and effects together; pipeline/render.mix_audio then
                                         sets the whole bed below the voice (music quieter than the voice)
"""
import subprocess
from pathlib import Path

import numpy as np

SR = 48000
KINDS = ("rumble", "wind", "explosion", "rain", "ocean", "fire", "space", "none")


def _noise(n, rng, color="white"):
    w = rng.standard_normal(n).astype(np.float32)
    if color == "brown":
        x = np.cumsum(w)
        x -= np.convolve(x, np.ones(4801) / 4801, mode="same")      # no DC drift
        return x / (np.abs(x).max() + 1e-6)
    if color == "pink":
        f = np.fft.rfft(w)
        f /= np.sqrt(np.arange(len(f)) + 1)
        x = np.fft.irfft(f, n)
        return x / (np.abs(x).max() + 1e-6)
    return w / (np.abs(w).max() + 1e-6)


def _lowpass(x, cutoff):
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(0, len(x), 4096):                 # a one-pole filter, in blocks (fast enough)
        blk = x[i:i + 4096]
        out = np.empty_like(blk)
        for j, v in enumerate(blk):
            acc = (1 - a) * v + a * acc
            out[j] = acc
        y[i:i + 4096] = out
    return y


def _lp_fft(x, cutoff, hi=None):
    f = np.fft.rfft(x)
    fr = np.fft.rfftfreq(len(x), 1 / SR)
    f[fr > cutoff] *= np.exp(-(fr[fr > cutoff] - cutoff) / max(1.0, cutoff * 0.3))
    if hi:
        f[fr < hi] *= (fr[fr < hi] / hi) ** 2
    return np.fft.irfft(f, len(x)).astype(np.float32)


def make(kind, seconds, seed=0):
    rng = np.random.default_rng(seed)
    n = max(1, int(seconds * SR))
    t = np.arange(n) / SR
    if kind == "rumble":
        x = _lp_fft(_noise(n, rng, "brown"), 90) * (0.8 + 0.2 * np.sin(2 * np.pi * 0.13 * t))
    elif kind == "wind":
        g = 0.55 + 0.45 * np.sin(2 * np.pi * (0.07 + 0.05 * rng.random()) * t + rng.random() * 6)
        x = _lp_fft(_noise(n, rng, "pink"), 900, hi=120) * g
    elif kind == "explosion":
        env = np.exp(-t / 1.6) * (1 - np.exp(-t / 0.01))
        x = (_lp_fft(_noise(n, rng, "brown"), 160) * 1.0 + _lp_fft(_noise(n, rng), 2500) * 0.25) * env
    elif kind == "rain":
        x = _lp_fft(_noise(n, rng), 5000, hi=400) * 0.6
        drops = rng.random(n) > 0.9993
        x += np.convolve(drops.astype(np.float32), np.exp(-np.arange(400) / 60), mode="same") * 0.3
    elif kind == "ocean":
        swell = 0.35 + 0.65 * (0.5 + 0.5 * np.sin(2 * np.pi * (1 / 7.5) * t + rng.random() * 6)) ** 2
        x = _lp_fft(_noise(n, rng, "pink"), 1400, hi=60) * swell
    elif kind == "fire":
        x = _lp_fft(_noise(n, rng, "pink"), 600) * 0.5
        crack = rng.random(n) > 0.9996
        x += np.convolve(crack.astype(np.float32), rng.standard_normal(300).astype(np.float32), mode="same") * 0.4
    elif kind == "space":
        x = _lp_fft(_noise(n, rng, "brown"), 60) * 0.7 + 0.08 * np.sin(2 * np.pi * 55 * t) * (0.5 + 0.5 * np.sin(t))
    else:
        return np.zeros(n, np.float32)
    x = x.astype(np.float32)
    return x / (np.abs(x).max() + 1e-6)


LEVEL = {"rumble": 0.55, "wind": 0.35, "explosion": 0.9, "rain": 0.3, "ocean": 0.4, "fire": 0.3, "space": 0.35}


def sfx_track(shots, total_s, out, fade=0.6):
    """Each shot's effect under its own time, faded in and out; an explosion at its shot's start."""
    n = int(total_s * SR) + SR
    mix = np.zeros((n, 2), np.float32)
    for k, s in enumerate(shots):
        kind = s.get("sfx") or "none"
        if kind not in LEVEL:
            continue
        a, b = float(s["start"]), float(s["end"])
        dur = (b - a) + (2.5 if kind == "explosion" else fade)
        x = make(kind, dur, seed=1000 + k) * LEVEL[kind]
        f = int(fade * SR)
        if kind != "explosion" and len(x) > 2 * f:
            x[:f] *= np.linspace(0, 1, f)
            x[-f:] *= np.linspace(1, 0, f)
        i = int(a * SR)
        j = min(n, i + len(x))
        pan = 0.15 * np.sin(k)
        mix[i:j, 0] += x[: j - i] * (1 - pan)
        mix[i:j, 1] += x[: j - i] * (1 + pan)
    peak = np.abs(mix).max()
    if peak > 0.98:
        mix *= 0.98 / peak
    import soundfile as sf
    sf.write(str(out), mix, SR)
    return out


def bed_with_sfx(music_bed, sfx, out, music_db=0.0, sfx_db=-4.0):
    """Music and effects as one bed (render.mix_audio sets it below the voice)."""
    inputs = []
    if music_bed and Path(music_bed).exists():
        inputs += ["-i", str(music_bed)]
    inputs += ["-i", str(sfx)]
    if len(inputs) == 2:
        graph = f"[0:a]volume={sfx_db}dB[o]"
    else:
        graph = (f"[0:a]aresample={SR},volume={music_db}dB[m];[1:a]aresample={SR},volume={sfx_db}dB[s];"
                 f"[m][s]amix=inputs=2:duration=longest:normalize=0[o]")
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", graph,
                        "-map", "[o]", "-ar", str(SR), "-ac", "2", str(out)], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"bed with effects: {r.stderr[-800:]}")
    return out
