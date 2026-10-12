"""KT2: assemble the 60-second montage sample from the pieces built so far."""
import json
import sys
import time
from pathlib import Path

from pipeline import render

ROOT = Path(__file__).resolve().parent
KT2 = ROOT / "output" / "kt2"
WORK = KT2 / "work"
VOICE = KT2 / "voice_am_michael.wav"
MUSIC = ROOT / "assets" / "music" / "echoes-of-time.mp3"


def main():
    shots_dir = KT2 / "shots"
    # NASA originals are not always JPEG; some archive scans come back as TIFF.
    images = sorted(p for p in shots_dir.iterdir()
                    if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".tif", ".tiff"})
    if not images:
        print("no shots; run kt2_visuals.py first")
        return 1
    if not VOICE.exists():
        print(f"no narration at {VOICE}; run kt2_voices.py first")
        return 1

    WORK.mkdir(parents=True, exist_ok=True)
    narration_s = render.probe_duration(VOICE)
    shots = render.plan_scenes(images, narration_s)
    print(f"narration {narration_s:.1f}s across {len(shots)} shots "
          f"({min(s['duration'] for s in shots):.1f}-"
          f"{max(s['duration'] for s in shots):.1f}s each)\n")

    t0 = time.monotonic()
    clips = render.build_scene_clips(shots, WORK)
    t_clips = time.monotonic() - t0

    silent = WORK / "silent.mp4"
    t0 = time.monotonic()
    render.crossfade(clips, silent)
    t_xfade = time.monotonic() - t0

    mixed = WORK / "mixed.m4a"
    music = MUSIC if MUSIC.exists() else None
    if music is None:
        print("NOTE: no music track found, rendering narration only")
    t0 = time.monotonic()
    render.mix_audio(VOICE, music, mixed)
    t_audio = time.monotonic() - t0

    final = KT2 / "montage_sample.mp4"
    render.mux(silent, mixed, final)

    total = t_clips + t_xfade + t_audio
    out_s = render.probe_duration(final)
    report = render.write_report(KT2 / "render_report.json", shots, final, mixed)
    print(json.dumps(report, indent=2))
    print(f"\nscene clips {t_clips:.0f}s | crossfade {t_xfade:.0f}s | audio {t_audio:.0f}s")
    print(f"total {total:.0f}s for {out_s:.1f}s of video -> {out_s / total:.2f}x realtime")
    print(f"extrapolated to a 20-min video: ~{20 * 60 / (out_s / total) / 60:.0f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
