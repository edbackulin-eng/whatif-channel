"""KT3: render the full script to narration with the channel voice."""
import sys
import time
from pathlib import Path

import soundfile as sf
from kokoro_onnx import Kokoro

from core import text as textmod
from core import voice as voice_mod

ROOT = Path(__file__).resolve().parent
KT3 = ROOT / "output" / "kt3"
VOICE = "bm_george"          # chosen at KT2


def main():
    script = (KT3 / "script.txt").read_text(encoding="utf-8")
    # Section headings are screen directions, not narration; drop them so the
    # narrator never reads "WEEK ONE." as a sentence.
    lines = []
    for line in script.splitlines():
        s = line.strip()
        if s and s == s.upper() and len(s) < 60 and s.endswith("."):
            continue
        lines.append(line)
    narration = "\n".join(lines)
    narration = textmod.clean(narration) if False else narration

    words = textmod.word_count(narration)
    print(f"narrating {words} words with {VOICE}")

    kokoro = Kokoro(str(ROOT / "assets" / "models" / "kokoro-v1.0.onnx"),
                    str(ROOT / "assets" / "models" / "voices-v1.0.bin"))

    done = [0]
    t0 = time.monotonic()

    def progress(i, chunk, dur):
        done[0] += dur
        if i % 20 == 0:
            el = time.monotonic() - t0
            print(f"  chunk {i:4d} | {done[0] / 60:5.1f} min audio | "
                  f"{el / 60:5.1f} min elapsed | {done[0] / el:4.2f}x RT", flush=True)

    audio, rate = voice_mod.synthesize(kokoro, narration, VOICE, on_chunk=progress)
    audio = voice_mod.peak_normalize(audio)
    out = KT3 / "narration.wav"
    sf.write(out, audio, rate)
    elapsed = time.monotonic() - t0
    dur = len(audio) / rate
    print(f"\nwrote {out.name}: {dur / 60:.1f} min audio in {elapsed / 60:.1f} min "
          f"({dur / elapsed:.2f}x realtime)")
    print(f"effective pace: {words / (dur / 60):.0f} wpm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
