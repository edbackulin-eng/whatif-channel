"""Put a thumbs-v2 run's chosen thumbnail on its episode's video - only a video that is still private and only a
take the judge passed (matches the episode, score >= 6). Owner 18.11: thumbnails redone in the reference style.

    python -X utf8 tools/set_thumb_v2.py --title "What Would Happen If the Sun Exploded?"
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import ytguard  # noqa: E402
from core.logger import get_logger  # noqa: E402
from pipeline import queue, youtube  # noqa: E402

log = get_logger("set_thumb_v2")
MIN_SCORE = 6


def slug_of(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]


def main(title):
    work = ROOT / "output" / "thumbs_v2" / slug_of(title)
    rep = json.loads((work / "report.json").read_text(encoding="utf-8"))
    best = max(rep["takes"], key=lambda t: t.get("rank") or -99) if rep.get("takes") else None
    j = (best or {}).get("judge") or {}
    if not best or not j.get("matches_episode") or float(j.get("score") or 0) < MIN_SCORE:
        log.warning("no take good enough (%s): the video keeps its thumbnail", j)
        return 0
    ep = next((e for e in queue.episodes() if e.get("title") == title), None)
    if not ep or not ep.get("youtube_id"):
        log.warning("no uploaded episode titled %r", title)
        return 0
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    yt = youtube.service()
    ytguard.check_channel(yt, cfg["youtube_channel_id"])
    st = yt.videos().list(part="status", id=ep["youtube_id"]).execute()["items"][0]["status"]
    if st.get("privacyStatus") != "private":
        log.warning("%s is %s: a public video is never changed", ep["youtube_id"], st.get("privacyStatus"))
        return 0
    from PIL import Image
    jpg = work / "set.jpg"
    Image.open(work / "chosen.png").convert("RGB").save(jpg, quality=92, optimize=True)
    from googleapiclient.http import MediaFileUpload
    yt.thumbnails().set(videoId=ep["youtube_id"], media_body=MediaFileUpload(str(jpg), mimetype="image/jpeg")).execute()
    log.info("thumbnail set on %s (%s, score %s)", ep["youtube_id"], best.get("words"), j.get("score"))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    sys.exit(main(ap.parse_args().title))
