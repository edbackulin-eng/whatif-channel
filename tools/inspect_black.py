"""Find every black/flat segment in a finished video and show what is on screen.

    python tools/inspect_black.py <video.mp4> <out_dir>

For each segment ffmpeg's blackdetect reports, frames are pulled from 1.5 s
before it to 1.5 s after it, with their mean, 95th-percentile luma and spread,
so it is clear whether the dark stretch is a frame, a transition between two
dark shots, a card, or the tail of a clip.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def segments(video, pix_th=0.10, d=0.5):
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-vf",
                          f"blackdetect=d={d}:pix_th={pix_th}", "-an", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return [(float(a), float(b)) for a, b in
            re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", err)]


def grab(video, t, out):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.3f}",
                    "-i", str(video), "-frames:v", "1", str(out)], check=True)
    a = np.asarray(Image.open(out).convert("L").resize((320, 180)), np.float32)
    return {"t": round(t, 2), "mean": round(float(a.mean()), 1),
            "p95": round(float(np.percentile(a, 95)), 1), "std": round(float(a.std()), 1)}


def main(video, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = []
    for k, (a, b) in enumerate(segments(video)):
        frames = []
        for t in np.arange(max(0, a - 1.5), b + 1.6, 0.25):
            p = out / f"seg{k}_{t:08.2f}.png"
            frames.append({**grab(video, float(t), p), "file": p.name})
        report.append({"start": a, "end": b, "duration": round(b - a, 2), "frames": frames})
        print(f"segment {k}: {a:.2f}-{b:.2f} ({b - a:.2f}s)")
        for f in frames:
            print(f"   t={f['t']:8.2f}  mean={f['mean']:5.1f} p95={f['p95']:5.1f} std={f['std']:5.1f}")
    (out / "black_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
