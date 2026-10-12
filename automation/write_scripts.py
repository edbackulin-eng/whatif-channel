"""Weekly: top the queue up with fact-checked scripts.

Each script is written, then its claims are extracted and passed to Gemini as a
second reader. Gemini only flags; nothing is rewritten automatically, and a
flagged episode is queued with the flags attached so a human can look.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.logger import get_logger  # noqa: E402
from pipeline import queue, scriptwriter  # noqa: E402

log = get_logger("write-scripts")

TOPICS = ROOT / "assets" / "topics.json"
TARGET_STOCK_WEEKS = 2


def load_topics():
    used = {e.get("title") for e in queue.episodes()}
    topics = json.loads(TOPICS.read_text(encoding="utf-8"))
    return [t for t in topics if t not in used]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=queue.PER_WEEK)
    args = ap.parse_args()

    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    order = scriptwriter.provider_order(cfg)
    log.info("provider order: %s", " -> ".join(order))

    h = queue.health()
    target = queue.PER_WEEK * TARGET_STOCK_WEEKS
    wanted = max(0, min(args.count, target - h["ready"]))
    if wanted == 0:
        queue.log_entry(f"Queue already holds {h['ready']} episodes; nothing written.")
        print(f"queue has {h['ready']} ready; target {target}. Nothing to do.")
        return 0

    available = load_topics()
    if not available:
        queue.log_entry("No unused topics left in assets/topics.json.")
        print("no unused topics remain")
        return 1

    written, failed = 0, []
    for title in available[:wanted]:
        try:
            text, provider, claims = scriptwriter.write(title, order)
        except Exception as e:
            log.error("could not write %r: %s", title, e)
            failed.append(title)
            continue
        # The writer sourced its own figures; Gemini reads the list once and
        # flags, in a single request, on its own quota bucket.
        extra = {"sourced_claims": len(claims)}
        if claims:
            try:
                from core import llm
                from pipeline import factcheck
                opinions = factcheck.second_opinion(claims, model=llm.GEMINI_BULK_MODEL)
                claims = factcheck.merge(claims, opinions)
                extra["flagged_claims"] = sum(1 for c in claims if c.get("needs_human"))
            except Exception as e:
                log.warning("second opinion unavailable for %r: %s", title, e)
                extra["flagged_claims"] = None

        d = queue.add(title, text, provider, extra)
        if claims:
            (d / "sources.json").write_text(
                json.dumps(claims, indent=2, ensure_ascii=False), encoding="utf-8")
        if extra.get("flagged_claims"):
            (d / "flagged.json").write_text(
                json.dumps(claims, indent=2, ensure_ascii=False), encoding="utf-8")
        written += 1

    h = queue.health()
    queue.log_entry(
        f"Wrote {written} script(s). Queue now {h['ready']} "
        f"({h['weeks_of_stock']} weeks)." +
        (f" Failed: {', '.join(failed)}." if failed else ""))
    print(f"written {written}, queue now {h['ready']}")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
