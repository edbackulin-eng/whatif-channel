"""What the channel's audience watches: our own videos by views, and the niche's hits.

    python automation/topic_research.py        # writes assets/topic_models.json

Reads with the YouTube Data API (YT_API_KEY, from the environment only): the
views of every video of ours in the queue (queue/*/episode.json youtube_id),
and the most viewed "What if" videos of the last two years in English. The
refill (automation/refill_topics.py) writes new topics in the manner of both.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "topic_models.json"
API = "https://www.googleapis.com/youtube/v3/"


def _get(path, **q):
    q["key"] = os.environ["YT_API_KEY"]
    with urllib.request.urlopen(API + path + "?" + urllib.parse.urlencode(q), timeout=60) as r:
        return json.loads(r.read())


def _iso_min(d):
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    return round((int(m[1] or 0) * 60 + int(m[2] or 0) + int(m[3] or 0) / 60), 1) if m else 0


def videos(ids):
    out = []
    for k in range(0, len(ids), 50):
        d = _get("videos", part="snippet,statistics,contentDetails", id=",".join(ids[k:k + 50]))
        for v in d.get("items", []):
            out.append({"id": v["id"], "title": v["snippet"]["title"], "channel": v["snippet"]["channelTitle"],
                        "published": v["snippet"]["publishedAt"][:10], "views": int(v["statistics"].get("viewCount", 0)),
                        "minutes": _iso_min(v["contentDetails"].get("duration"))})
    return out


def ours():
    ids = []
    for f in sorted((ROOT / "queue").glob("*/episode.json")):
        e = json.loads(f.read_text(encoding="utf-8"))
        if e.get("youtube_id"):
            ids.append(e["youtube_id"])
    return sorted(videos(ids), key=lambda v: -v["views"])


def niche():
    after = (datetime.now(timezone.utc) - timedelta(days=730)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = []
    for q in ("what if earth", "what if the sun", "what if the moon", "what if science", "what would happen if"):
        d = _get("search", part="id", q=q, type="video", order="viewCount", maxResults=50, publishedAfter=after,
                 relevanceLanguage="en", videoDuration="medium")
        ids += [i["id"]["videoId"] for i in d.get("items", [])]
    rows = videos(list(dict.fromkeys(ids)))
    rows = [v for v in rows if re.search(r"\bwhat (if|would happen)\b", v["title"], re.I)]
    return sorted(rows, key=lambda v: -v["views"])[:60]


def main():
    data = {"made": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "ours": ours(), "niche": niche()}
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"ours: {len(data['ours'])}, niche: {len(data['niche'])} -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
