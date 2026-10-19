"""Smoke test for What If: the chain on ten seconds of a real script, in minutes.

    python -X utf8 scripts/smoke.py

Run by .github/workflows/smoke.yml on every push to dev; only a passing run
moves the code to main, where the builds run it.

  1. every module of pipeline/ and automation/ imports;
  2. a real script is cut into subtitle cues and grouped into scenes the way
     a build does it (narration timing stands in for the voice, which needs
     the GPU);
  3. placeholder stills are graded, moved, crossfaded and mixed with a music
     bed from the library over a stand-in narration, then muxed;
  4. the result is checked by the channel's own QC: length, resolution,
     loudness, black stretches, silence.
"""
import importlib
import pkgutil
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
W = ROOT / "work" / "smoke"
SECONDS = 10
failures = []


def check(name, ok, detail=""):
    print(f"[{'ok' if ok else 'FAIL'}] {name} {detail}")
    if not ok:
        failures.append(f"{name}: {detail}")


def shared_gpu():
    """The shared GPU lock reads every channel's kernels the same way."""
    sys.path.insert(0, str(ROOT / "kaggle"))
    import gpu_shared
    import push  # noqa: F401  - push.py must still import with the lock in it
    ok = (gpu_shared.channel_of("u/whatif-main") == "whatif"
          and gpu_shared.channel_of("u/closedtabs-stills-a") == "closedtabs"
          and gpu_shared.channel_of("u/prehistoric-recon") == "prehistoric"
          and gpu_shared.channel_of("u/other") is None
          and gpu_shared.CHANNELS["whatif"] == 0)
    check("shared GPU lock", ok)


def imports():
    for pkg in ("pipeline", "automation"):
        for m in pkgutil.iter_modules([str(ROOT / pkg)]):
            try:
                importlib.import_module(f"{pkg}.{m.name}")
            except Exception as e:                               # noqa: BLE001
                check(f"import {pkg}.{m.name}", False, repr(e)[:200])
    check("imports", not failures)


def srt_from_script():
    script = sorted(ROOT.glob("queue/*/script.txt"))[-1]
    text = re.sub(r"\[[^\]]*\]", " ", script.read_text(encoding="utf-8"))
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) > 3][:12]
    t, blocks = 0.0, []
    for i, s in enumerate(sents, 1):
        d = max(1.5, len(s.split()) / 2.7)
        a, b = t, t + d
        blocks.append(f"{i}\n{_ts(a)} --> {_ts(b)}\n{s}\n")
        t = b
    path = W / "subs.srt"
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path, script.parent.name


def _ts(t):
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)) % 1000:03d}"


def planning():
    from pipeline import sceneplan
    srt, slug = srt_from_script()
    cues = sceneplan.parse_srt(srt)
    scenes = sceneplan.group_scenes(cues)
    check("scene grouping", len(cues) > 3 and len(scenes) >= 1, f"{slug}: {len(cues)} cues -> {len(scenes)} scenes")


def stills(n=3):
    rng = np.random.default_rng(5)
    paths = []
    for k in range(n):
        y, x = np.mgrid[0:1080, 0:1920]
        c1, c2 = rng.integers(50, 220, 3), rng.integers(50, 220, 3)
        t = (x / 1920)[..., None]
        im = Image.fromarray((c1 * (1 - t) + c2 * t).astype(np.uint8))
        d = ImageDraw.Draw(im)
        for _ in range(5):
            x0, y0 = rng.integers(0, 1700), rng.integers(0, 900)
            d.ellipse((x0, y0, x0 + 200, y0 + 160), fill=tuple(int(v) for v in rng.integers(0, 255, 3)))
        p = W / f"still_{k}.png"
        im.save(p)
        paths.append(p)
    return paths


def render():
    from pipeline import music, render as r
    shots = r.plan_scenes(stills(), SECONDS, min_s=2.0, max_s=5.0)
    clips = r.build_scene_clips(shots, W / "clips")
    picture = r.crossfade(clips, W / "picture.mp4", work_dir=W / "xf")
    narration = W / "narration.wav"
    # a speech-like stand-in: a voiced tone broken into syllables, with gaps
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=f=150:d={SECONDS}", "-af",
                    "volume='0.5*(1+sin(2*PI*3*t))*gt(sin(2*PI*0.4*t),-0.6)':eval=frame",
                    "-ar", "48000", str(narration)], check=True)
    lib = music.load_library()
    track = next((Path(t["path"]) for t in lib if Path(t.get("path", "")).exists()), None) \
        if isinstance(lib, list) else None
    mixed = r.mix_audio(narration, track, W / "mix.m4a")
    out = r.mux(picture, mixed, W / "video.mp4")
    check("render + mix", out.exists(), f"music: {track.name if track else 'none on runner'}")
    return out


def checks(out):
    from pipeline import qc
    report, problems = qc.check_video(out, expected_min_s=SECONDS - 1.5, expected_max_s=SECONDS + 1.5)
    # flat placeholder gradients compress far below any real footage, so the
    # bitrate floor says nothing here; real builds keep the check
    problems = [p for p in problems if "bitrate" not in p]
    check("qc", not problems, f"{problems} {report.get('duration_s')} s")


def main():
    if W.exists():
        shutil.rmtree(W)
    W.mkdir(parents=True)
    imports()
    shared_gpu()
    if failures:
        print("SMOKE FAILED:", failures)
        return 1
    planning()
    out = render()
    checks(out)
    print("\nSMOKE", "PASSED" if not failures else f"FAILED: {failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
