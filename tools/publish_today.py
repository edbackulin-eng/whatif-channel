"""Make sure an episode is on YouTube for TODAY's slot.

    python tools/publish_today.py fix <video_id>            # move an upload to today
    python tools/publish_today.py upload <package_dir>      # upload a package for today
    python tools/publish_today.py status <video_id>         # what YouTube says now

Today's slot is 15:00 UTC. If that is less than thirty minutes away, the video is
scheduled thirty minutes from now instead, rounded up to five minutes: a late
video on the same day, never a skipped day.

`upload` rewrites the package's chapter list with real titles first, records the
upload in queue/<slug>/ (uploaded.json, episode.json) so no later build uploads
the same episode again, and confirms the schedule with the API.
"""
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import queue, youtube  # noqa: E402

SLOT_HOUR = 15
LEAD = timedelta(minutes=30)


def today_slot(now=None):
    now = now or datetime.now(timezone.utc)
    slot = now.replace(hour=SLOT_HOUR, minute=0, second=0, microsecond=0)
    if slot - now >= LEAD:
        return slot
    late = now + LEAD
    late += timedelta(minutes=(5 - late.minute % 5) % 5)
    late = late.replace(second=0, microsecond=0)
    if late.date() != now.date():
        raise RuntimeError("too late to publish today")
    return late


def status(video_id):
    yt = youtube.service()
    items = yt.videos().list(part="status,snippet", id=video_id).execute().get("items", [])
    if not items:
        return None
    st = items[0]["status"]
    return {"id": video_id, "title": items[0]["snippet"]["title"],
            "privacy": st.get("privacyStatus"), "publishAt": st.get("publishAt"),
            "upload": st.get("uploadStatus")}


def fix(video_id):
    """Move an uploaded, scheduled video to today's slot."""
    yt = youtube.service()
    v = yt.videos().list(part="status", id=video_id).execute()["items"][0]
    st = v["status"]
    slot = today_slot()
    if st.get("privacyStatus") == "public":
        print("already public; nothing to move")
        return status(video_id)
    st["privacyStatus"] = "private"
    st["publishAt"] = slot.strftime("%Y-%m-%dT%H:%M:%SZ")
    yt.videos().update(part="status", body={"id": video_id, "status": st}).execute()
    return status(video_id)


def _chapters_from_srt(srt, duration):
    from automation import assemble
    d = Path(tempfile.mkdtemp())
    shutil.copy(srt, d / "subs.srt")
    return assemble._chapters(d, duration)


def rewrite_chapters(pkg):
    """Replace the CHAPTERS block in metadata.txt with written titles."""
    from pipeline import render, seo
    meta = pkg / "metadata.txt"
    text = meta.read_text(encoding="utf-8")
    chapters = _chapters_from_srt(pkg / "subs.srt", render.probe_duration(pkg / "video.mp4"))
    block = seo.build_chapters(chapters)
    new = re.sub(r"(CHAPTERS\n)(?:\d+:\d\d(?::\d\d)? .*\n)+", lambda m: m.group(1) + block + "\n",
                 text, count=1)
    if new == text:
        raise RuntimeError("could not find the CHAPTERS block in metadata.txt")
    meta.write_text(new, encoding="utf-8")
    return block


def upload(pkg, keep_chapters=False):
    pkg = Path(pkg)
    slug = pkg.name
    d = ROOT / "queue" / slug
    marker = d / "uploaded.json"
    if marker.exists():
        raise SystemExit(f"{slug} already uploaded: {marker.read_text(encoding='utf-8')}")
    if not keep_chapters:
        print("chapters:")
        print(rewrite_chapters(pkg))
    slot = today_slot()
    print(f"uploading {slug} for {slot:%Y-%m-%d %H:%M} UTC")
    video_id, when = youtube.upload(pkg, publish_at=slot)
    stamp = {"youtube_id": video_id, "publish_at": when.strftime("%Y-%m-%dT%H:%M:%SZ")}
    marker.write_text(json.dumps(stamp), encoding="utf-8")
    m = json.loads((d / "episode.json").read_text(encoding="utf-8"))
    m.update(stamp)
    (d / "episode.json").write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    queue.set_status(d, "published")
    queue.log_entry(f"Uploaded {slug} as {video_id} from {pkg}, public at "
                    f"{stamp['publish_at']} (same-day slot).")
    return status(video_id)


if __name__ == "__main__":
    cmd, arg = sys.argv[1], sys.argv[2]
    if cmd == "upload" and "--keep-chapters" in sys.argv:
        out = upload(arg, keep_chapters=True)
    else:
        out = {"fix": fix, "upload": upload, "status": status}[cmd](arg)
    print(json.dumps(out, indent=1, ensure_ascii=False))
