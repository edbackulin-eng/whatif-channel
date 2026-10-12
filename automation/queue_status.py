"""Report queue depth, and tell the build workflow whether there is work.

Writes GitHub Actions outputs so the build job can skip cleanly on an empty
queue rather than failing, and warns when stock drops below a week.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import queue  # noqa: E402


def emit(name, value):
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def notice(level, message):
    """A GitHub Actions annotation, so it surfaces on the run summary."""
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::{level}::{message}")
    else:
        print(f"[{level}] {message}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--for-build", action="store_true")
    ap.add_argument("--fail-on-empty", default="false")
    args = ap.parse_args()

    h = queue.health()
    print(f"ready episodes : {h['ready']}")
    print(f"weeks of stock : {h['weeks_of_stock']}")
    for t in h["titles"]:
        print(f"   - {t}")

    if h["empty"]:
        notice("warning", "Script queue is empty - no video will be built today.")
        queue.log_entry("Queue empty: build skipped.")
    elif h["low"]:
        notice("warning",
               f"Script queue is low: {h['ready']} episodes "
               f"({h['weeks_of_stock']} weeks). Top it up.")

    if args.for_build:
        nxt = queue.next_episode()
        emit("has_work", "true" if nxt else "false")
        emit("slug", nxt["slug"] if nxt else "none")
        if not nxt:
            print("nothing to build today")

    if args.fail_on_empty.lower() == "true" and h["empty"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
