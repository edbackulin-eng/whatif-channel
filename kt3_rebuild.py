"""Rebuild episode one from the corrected dataset, locally.

Uses the approved narration and subtitles untouched, and the frames as they now
stand after the reshoots and the card fixes. Nothing is regenerated here.
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

DS = ROOT / "dataset" / "ep001"
WORK = ROOT / "output" / "ep001"


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    for name in ("narration.wav", "subs.srt", "script.txt", "sources.json",
                 "credits.json", "factcheck-log.md", "thumbnail.png"):
        src = DS / name
        if src.exists():
            shutil.copy2(src, WORK / name)

    scenes = json.loads((DS / "scenes.json").read_text(encoding="utf-8"))
    frames = DS / "frames"
    bound = 0
    for s in scenes:
        p = frames / f"{s['index']:03d}.png"
        if not p.exists():
            matches = list(frames.glob(f"{s['index']:03d}.*"))
            p = matches[0] if matches else None
        if p:
            s["image"] = str(p.resolve())
            bound += 1
    (WORK / "scenes.json").write_text(
        json.dumps(scenes, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"scenes bound to frames: {bound}/{len(scenes)}")

    from automation.assemble import assemble, repeat_report
    repeats = repeat_report(scenes)
    print(f"frames repeating inside 10 scenes: {len(repeats)}")

    episode = {
        "slug": "001-moon-fell-to-earth",
        "title": "What If the Moon Fell to Earth?",
        "approved": {"thumbnail": "option_2"},
        "hook": ("What if the Moon stopped holding its orbit and began to fall? "
                 "The real physics says it never reaches the ground - and what "
                 "happens instead lasts a million years."),
        "thumbnail_lines": ["THE MOON", "IS FALLING"],
    }
    package = assemble(WORK, episode)
    print(f"\npackaged -> {package}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
