"""Topics for the v2 channel (owner 15.11): global catastrophes and "what if" scenarios of the Earth, titled
the way people actually search - "What Would Happen If ...?", from YouTube's own search suggestions.

    python -X utf8 automation/topics_v2.py --min 8 --add 20     -> assets/topics_v2.json

1. YouTube autocomplete (suggestqueries.google.com, ds=yt) for "what would happen if" + seeds (the sun, the
   moon, the earth, the ocean, a volcano, an asteroid, the internet, gps, it rained, ...): real searches;
2. refused at once: politics, wars, weapons, countries and leaders, people's names, gore, anything for kids;
3. the text model keeps the global catastrophes and Earth scenarios (the sun vanishing for a week, the
   Earth stopping, a year of rain, a supervolcano, a mega-tsunami, the internet down for a month, GPS
   gone, a global blackout, the Moon twice as close ...), each as a title close to a real suggestion;
4. never twice: a title whose meaning repeats one queued, published or already listed is dropped
   (normalised words, and the text model's own check).
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import llm  # noqa: E402
from core.logger import get_logger  # noqa: E402
from pipeline import queue  # noqa: E402

log = get_logger("topics_v2")
OUT = ROOT / "assets" / "topics_v2.json"
UA = {"User-Agent": "whatif-channel/2.0 (topic research)"}
SEEDS = ["", "the sun", "the moon", "the earth", "earth stopped", "the ocean", "a volcano", "yellowstone",
         "an asteroid", "a meteor", "the internet", "gps", "it rained", "it snowed", "the ice", "a solar flare",
         "a tsunami", "a black hole", "the earth was", "all the", "the atmosphere", "the magnetic field",
         "electricity", "the power", "gravity", "the oceans", "earth had", "the sun disappeared", "a supervolcano"]
BANNED = re.compile(r"\b(war|wars|nuclear|nuke|bomb|army|military|soldier|weapon|gun|president|trump|biden|putin|"
                    r"election|china|russia|ukraine|usa|america|israel|iran|korea|india|pakistan|terror|kill|"
                    r"killed|murder|suicide|die|died|dead|death|kids|baby|minecraft|roblox|fortnite|gta|"
                    r"you|your|i|me|my|we|girlfriend|boyfriend|school|teacher|movie|anime|naruto|marvel)\b", re.I)

PICK = """You choose topics for a YouTube science channel about GLOBAL CATASTROPHES and "what would happen if" scenarios
of the Earth (the best performers of the niche: "What Would Happen If Earth Went Dark for 365 Days", "... an
Asteroid Hit the Mariana Trench", "... the Earth Stopped Spinning", "... It Rained on Earth for an Entire Year",
"... The Sun Disappeared For One Week"). Below are REAL YouTube search suggestions. Keep only those that make a
gripping, scientifically sound global catastrophe or planetary scenario (no politics, no wars or weapons, no
countries or people, no gore, no jokes, nothing about "you"). Rewrite each kept one as a title in Title Case:
"What Would Happen If ...?" - as close to the suggestion's own words as reads well. Do not keep two with the same
meaning, and none that means the same as one of these existing titles: {have}.
Answer as JSON: {{"topics": [{{"title": "What Would Happen If ...?", "from": "<the suggestion>"}}]}}
SUGGESTIONS:
{rows}"""


def suggestions(seed):
    q = f"what would happen if {seed}".strip()
    url = "https://suggestqueries.google.com/complete/search?" + urllib.parse.urlencode(
        {"client": "firefox", "ds": "yt", "q": q, "hl": "en"})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        return [s for s in d[1] if isinstance(s, str)]
    except Exception as e:                                               # noqa: BLE001
        log.warning("suggestions for %r: %s", q, e)
        return []


def norm(title):
    stop = {"what", "would", "happen", "if", "the", "a", "an", "for", "of", "on", "to", "in", "and", "was", "were",
            "is", "be", "earth's"}
    return frozenset(w for w in re.findall(r"[a-z0-9]+", title.lower()) if w not in stop)


def existing():
    titles = [e.get("title", "") for e in queue.episodes()]
    if OUT.exists():
        titles += [t["title"] for t in json.loads(OUT.read_text(encoding="utf-8"))["topics"]]
    return titles


def refill(min_left=8, add=20):
    data = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"topics": []}
    used = {e.get("title") for e in queue.episodes()}
    left = [t for t in data["topics"] if t["title"] not in used]
    if len(left) >= min_left:
        log.info("%d unused v2 topics; nothing to add", len(left))
        return 0
    raw = []
    for seed in SEEDS:
        raw += suggestions(seed)
        time.sleep(0.5)
    raw = [s for s in dict.fromkeys(raw) if not BANNED.search(s) and len(s.split()) >= 5]
    log.info("%d suggestions after the hard filter", len(raw))
    have = existing()
    seen = {norm(t) for t in have}
    ans = llm.complete_json(PICK.format(have=json.dumps(have[-80:]), rows="\n".join(raw[:300])), max_tokens=4000,
                            temperature=0.3)
    added = 0
    for t in (ans.get("topics") or []):
        title = str(t.get("title") or "").strip()
        if not re.match(r"^What Would Happen If .+\?$", title) or BANNED.search(title):
            continue
        n = norm(title)
        if not n or any(len(n & s) >= max(2, int(0.75 * min(len(n), len(s)))) for s in seen):
            continue                                       # the same idea as one there already
        data["topics"].append({"title": title, "from": t.get("from"), "added": time.strftime("%Y-%m-%d")})
        seen.add(n)
        added += 1
        if added >= add:
            break
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    log.info("added %d v2 topics (%d waiting)", added, len(left) + added)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=8)
    ap.add_argument("--add", type=int, default=20)
    a = ap.parse_args()
    sys.exit(refill(a.min, a.add))
