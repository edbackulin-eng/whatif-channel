"""Keep assets/topics.json from running dry: when fewer than --min unused topics are
left, write --add new ones in the manner of what works (owner 04.11).

    python automation/refill_topics.py --min 10 --add 30

"What works" is assets/topic_models.json (automation/topic_research.py): our own
videos by views and the niche's most viewed "What if" videos. The text model is
given both, every title already used or waiting, and the channel's rules; what it
returns is kept only if it reads "What If ...?" and repeats no earlier topic.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import llm  # noqa: E402
from pipeline import queue  # noqa: E402

TOPICS = ROOT / "assets" / "topics.json"
MODELS = ROOT / "assets" / "topic_models.json"

SYSTEM = """You plan topics for "What If", an English science documentary channel: one
hypothetical a video, told about Earth, space or the physical world, 20-25 minutes,
grounded in real science that can be sourced. Titles read "What If ...?" in title case,
4-10 words, concrete and visual (an event the viewer can picture), no people's names,
no politics, no gore, nothing for children only. Return JSON only:
{"topics": ["What If ...?", ...]}"""


def words(title):
    return {w for w in re.findall(r"[a-z]+", title.lower()) if w not in
            {"what", "if", "the", "a", "an", "of", "for", "to", "at", "on", "in", "was", "were", "had", "became"}}


def unused():
    used = {e.get("title") for e in queue.episodes()}
    return [t for t in json.loads(TOPICS.read_text(encoding="utf-8")) if t not in used]


def is_new(title, known):
    w = words(title)
    return all(len(w & words(k)) < max(2, round(0.7 * min(len(w), len(words(k))))) for k in known)


def refill(n, known):
    m = json.loads(MODELS.read_text(encoding="utf-8")) if MODELS.exists() else {"ours": [], "niche": []}
    ours = "\n".join(f"- {v['title']} ({v['views']} views)" for v in m["ours"][:10])
    hits = "\n".join(f"- {v['title']} ({v['views']:,} views, {v['channel']})" for v in m["niche"][:25])
    prompt = (f"OUR VIDEOS, MOST WATCHED FIRST:\n{ours}\n\nTHE NICHE'S HITS:\n{hits}\n\n"
              f"TOPICS WE ALREADY HAVE (do not repeat or near-repeat any):\n" + "\n".join(f"- {k}" for k in known) +
              f"\n\nWrite {n + 10} new topics in the manner of what is watched most.")
    got = llm.complete_json(prompt, system=SYSTEM, max_tokens=4000, temperature=0.8).get("topics", [])
    out = []
    for t in got:
        t = re.sub(r"\s+", " ", str(t)).strip()
        if re.fullmatch(r"What If [^?]{6,80}\?", t) and is_new(t, known + out):
            out.append(t)
    return out[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=10)
    ap.add_argument("--add", type=int, default=30)
    args = ap.parse_args()
    left = unused()
    if len(left) >= args.min:
        print(f"{len(left)} unused topics; no refill needed")
        return 0
    topics = json.loads(TOPICS.read_text(encoding="utf-8"))
    known = topics + [e.get("title") for e in queue.episodes() if e.get("title") not in topics]
    new = refill(args.add, known)
    TOPICS.write_text(json.dumps(topics + new, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    queue.log_entry(f"Topics refilled: {len(new)} new ({len(left)} were left).")
    print(f"{len(left)} unused topics; added {len(new)}:")
    for t in new:
        print("  ", t)
    return 0 if new else 1


if __name__ == "__main__":
    sys.exit(main())
