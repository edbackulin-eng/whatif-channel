"""Build the next queued episode, end to end, with no language model in the loop.

Order matters here. Visual QC runs BEFORE the render, not after: a defective
frame caught at this point costs one regeneration, and caught afterwards costs
the whole 35-minute render.

Episode one is a special case. Its script, narration and thumbnail are approved
and must not be regenerated, so if the queue entry carries them they are reused
verbatim and only the picture is rebuilt.
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.logger import get_logger  # noqa: E402
from pipeline import queue  # noqa: E402

log = get_logger("build-next")


def pick(slug):
    if slug and slug not in ("", "none"):
        for e in queue.episodes():
            if e["slug"] == slug:
                return e
        raise SystemExit(f"no queued episode with slug {slug!r}")
    return queue.next_episode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default="")
    args = ap.parse_args()

    episode = pick(args.slug)
    if not episode:
        queue.log_entry("Build ran with an empty queue; nothing produced.")
        print("queue empty, nothing to build")
        return 0

    d = episode["_dir"]
    print(f"building {episode['slug']}: {episode['title']}")
    started = time.monotonic()

    work = ROOT / "output" / episode["slug"]
    work.mkdir(parents=True, exist_ok=True)

    # Approved material is reused, never regenerated.
    reused = []
    for name in ("script.txt", "narration.wav", "subs.srt", "scenes.json",
                 "sources.json", "credits.json", "factcheck-log.md"):
        src = d / name
        if src.exists():
            shutil.copy2(src, work / name)
            reused.append(name)
    if reused:
        print("reusing approved material:", ", ".join(reused))

    try:
        from automation import stages
        stages.run(episode, work)
    except Exception as e:
        log.error("build failed: %s", e)
        queue.set_status(d, "failed", error=str(e)[:300])
        queue.log_entry(f"Build FAILED for {episode['slug']}: {str(e)[:160]}")
        raise

    minutes = (time.monotonic() - started) / 60
    queue.set_status(d, "rendered", rendered_minutes=round(minutes, 1))
    queue.log_entry(f"Built {episode['slug']} in {minutes:.0f} min.")
    print(f"done in {minutes:.0f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
