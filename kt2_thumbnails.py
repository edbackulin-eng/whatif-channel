"""KT2: three thumbnail variants for "What If the Moon Fell to Earth?"."""
import sys
from pathlib import Path

from pipeline import thumbnail

ROOT = Path(__file__).resolve().parent
SHOTS = ROOT / "output" / "kt2" / "shots"
OUT = ROOT / "output" / "kt2" / "thumbnails"

LINES = ["THE MOON", "IS FALLING"]


def main():
    # The most dramatic frame we pulled: Earth above the lunar horizon.
    source = SHOTS / "003_as11-44-6552.jpg"
    if not source.exists():
        candidates = sorted(SHOTS.glob("*.jpg"))
        if not candidates:
            print("no shots available; run kt2_visuals.py first")
            return 1
        source = candidates[0]
    print(f"source: {source.name}\ntext:   {' / '.join(LINES)}\n")

    results = thumbnail.render(source, LINES, OUT, stem="moon")
    print(f"\n{'variant':8s} {'text spread @168x94':>20s}   verdict")
    for r in results:
        verdict = ("crisp" if r["text_spread"] >= 180 else
                   "readable" if r["text_spread"] >= 120 else "SMUDGED at browse size")
        print(f"{r['variant']:8s} {r['text_spread']:20d}   {verdict}")
    print("\nNote: this checks the type only. Composition is a human call.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
