"""KT2: render the 60-second test fragment in several Kokoro voices and time each one."""
import sys
import time
from pathlib import Path

import soundfile as sf
from kokoro_onnx import Kokoro

from core import voice as voice_mod

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output" / "kt2"
OUT.mkdir(parents=True, exist_ok=True)

# ~165 words = ~65s at 145 wpm. Hook plus the first beats of the timeline, written
# to the channel's rules: present tense, concrete numbers, retention loop at the end.
FRAGMENT = """Imagine at nine o'clock tomorrow morning, the Moon stops holding its orbit.
Not an explosion. Not a collision. It simply begins to fall.

For the first week, you would barely notice. The Moon looks a little larger each night,
the way a car in your mirror looks closer without seeming to move.
But the ocean notices first.
Tides are a tug of war, and the Moon is winning harder every hour.

By day nineteen, it is twice its normal size in the sky,
and high tide is climbing six meters above the old line.
Coastal cities are not flooded yet. They are simply wet, twice a day, a little deeper each time.

And here is the part almost nobody expects.
The Moon never actually reaches the ground.
Something tears it apart long before that, and what happens next lasts a million years."""

CANDIDATES = [
    ("am_michael", "US male, warm documentary narrator"),
    ("am_fenrir", "US male, deeper and heavier"),
    ("bm_george", "UK male, classic science-documentary"),
    ("am_puck", "US male, brighter and more energetic"),
    ("af_heart", "US female, warm"),
]


def main():
    model = ROOT / "assets" / "models" / "kokoro-v1.0.onnx"
    voices = ROOT / "assets" / "models" / "voices-v1.0.bin"
    kokoro = Kokoro(str(model), str(voices))
    available = set(kokoro.get_voices())

    words = len(FRAGMENT.split())
    print(f"fragment: {words} words\n")

    for name, note in CANDIDATES:
        if name not in available:
            print(f"SKIP {name}: not in this voice pack")
            continue
        chunks = []
        t0 = time.monotonic()
        audio, rate = voice_mod.synthesize(
            kokoro, FRAGMENT, name,
            on_chunk=lambda i, text, dur: chunks.append(dur))
        elapsed = time.monotonic() - t0
        audio = voice_mod.peak_normalize(audio)
        audio_s = len(audio) / rate
        sf.write(OUT / f"voice_{name}.wav", audio, rate)
        print(f"{name:12s} | {audio_s:5.1f}s audio | {elapsed:5.1f}s gen "
              f"| {audio_s / elapsed:4.2f}x RT | {len(chunks)} chunks "
              f"| {words / (audio_s / 60):5.1f} wpm | {note}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
