"""How many episodes are already on YouTube with a publishAt still ahead.

    python automation/buffer.py --min 2

The rule is a standing stock, not a daily target: at least two videos uploaded and
scheduled ahead at any moment, so one failed build costs a day of stock rather than
a day of channel. A build therefore makes the next episode in the queue and takes
the nearest free slot; it does not try to make "today's".

Writes GitHub Actions outputs: ahead, short (fewer than --min), ready (scripts
waiting). Exit code is 1 only with --require and a shortfall.
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import queue  # noqa: E402


def ahead(now=None):
    now = now or datetime.now(timezone.utc)
    n = 0
    for e in queue.episodes():
        when = e.get("publish_at")
        if when and e.get("youtube_id"):
            if datetime.fromisoformat(when.replace("Z", "+00:00")) > now:
                n += 1
    return n


def emit(name, value):
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=2)
    ap.add_argument("--require", action="store_true")
    args = ap.parse_args()
    n, ready = ahead(), queue.health()["ready"]
    short = n < args.min
    print(f"scheduled ahead on YouTube: {n} (minimum {args.min}); scripts ready: {ready}")
    emit("ahead", n)
    emit("short", "true" if short else "false")
    emit("ready", ready)
    return 1 if (short and args.require) else 0


if __name__ == "__main__":
    sys.exit(main())
