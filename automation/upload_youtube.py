"""Upload every rendered episode that is not on YouTube yet, scheduled and private.

    python automation/upload_youtube.py [--dry-run]

This script did not exist. build-video.yml called it after every build, with
secrets (YT_CLIENT_SECRET, YT_REFRESH_TOKEN) that were never created, so a
scheduled build rendered for three and a half hours, uploaded its package as an
artifact, and then failed at the very last step. The 13 October build of episode
002 ended that way.

Rules, all of them there to stop a video being uploaded twice or lost:
  - the slot is the nearest free one of the channel's week (Mon, Tue, Thu, Fri,
    Sat at 15:00 UTC) that is at least thirty minutes away; "free" means no other
    episode of ours already holds that day;
  - the moment YouTube returns an id it is written to queue/<slug>/uploaded.json
    and to episode.json, before anything else can fail, and an episode with that
    marker is never uploaded again;
  - a package that is not on this runner is skipped and said so, never guessed at.

Owner 17.11 (core/ytguard.py, the same in every channel): before any upload the token's channel id is
checked against config youtube_channel_id and the channel's COMPLETE list of videos is read; a video
carrying "[ref: whatif/<slug>]" (or the same title) is that episode already - recorded, not uploaded.
Days already held on YouTube (publishAt, published) are never taken again. In doubt nothing is uploaded
and the owner gets one mail. The record is committed to git the moment YouTube returns the id. A film QC
holds is marked held_by_qc (one mail) and no new episode is built until it is fixed.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.logger import get_logger  # noqa: E402
from pipeline import queue  # noqa: E402

log = get_logger("upload-youtube")

SLOT_HOUR_UTC = 15
# Thirty minutes, not two hours: a slot that a long build just missed is still worth
# taking if YouTube has half an hour to process the file, and the alternative is a
# channel with no video that day.
MIN_LEAD = timedelta(minutes=30)


def scheduled():
    """Every publishAt already handed to YouTube, from the episode records."""
    out = []
    for e in queue.episodes():
        when = e.get("publish_at")
        if when and e.get("youtube_id"):
            out.append(datetime.fromisoformat(when.replace("Z", "+00:00")))
    return out


def next_slot(taken, now=None):
    now = now or datetime.now(timezone.utc)
    taken_days = {t.astimezone(timezone.utc).date() for t in taken}
    day = now.replace(hour=SLOT_HOUR_UTC, minute=0, second=0, microsecond=0)
    for _ in range(60):
        if (day.weekday() in queue.PUBLISH_WEEKDAYS and day - now >= MIN_LEAD
                and day.date() not in taken_days):
            return day
        day += timedelta(days=1)
    raise RuntimeError("no free slot in the next 60 days")


def qc_verdict(pkg):
    """(verdict, problems) from the package's own qc.json; a missing report is not a pass."""
    try:
        q = json.loads((pkg / "qc.json").read_text(encoding="utf-8"))
        return q.get("verdict", "UNKNOWN"), q.get("problems", [])
    except (OSError, json.JSONDecodeError):
        return "UNKNOWN", ["no qc.json in the package"]


def package_for(slug):
    found = sorted((ROOT / "ready").glob(f"*/{slug}"))
    return found[-1] if found and (found[-1] / "video.mp4").exists() else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="only prove the credentials work: refresh the token, name the channel")
    args = ap.parse_args()

    if args.check:
        from pipeline import youtube
        try:
            name, cid = youtube.channel_name()
        except Exception as err:                                 # noqa: BLE001
            print(f"YouTube credentials DO NOT work: {str(err)[:300]}")
            return 1
        print(f"YouTube credentials work: channel {name!r} ({cid})")
        return 0 if name else 1

    todo = [e for e in queue.episodes()
            if e.get("status") == "rendered" and not e.get("youtube_id")]
    todo.sort(key=lambda e: e.get("position", 0))
    if not todo:
        print("nothing to upload")
        return 0

    from core import ytguard
    if not args.dry_run:
        try:
            from pipeline import youtube
            yt = youtube.service()
            cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
            ytguard.check_channel(yt, cfg.get("youtube_channel_id"))
            known = [e.get("youtube_id") for e in queue.episodes() if e.get("youtube_id")]
            videos = ytguard.all_uploads(yt, known)
        except ytguard.Doubt as err:
            note = f"Upload cancelled - not sure about the channel: {err}"
            log.error(note)
            queue.log_entry(note)
            ytguard.notify("What If: upload cancelled (not sure about the channel)", str(err))
            return 1
    else:
        yt, videos = None, []
    failed = held = 0
    for e in todo:
        slug = e["slug"]
        d = ROOT / "queue" / slug
        marker = d / "uploaded.json"
        if marker.exists():
            log.warning("%s already has uploaded.json; not uploading again", slug)
            continue
        pkg = package_for(slug)
        if not pkg:
            log.warning("%s is rendered but its package is not on this runner; skipped", slug)
            continue
        # A video the automatic checks flagged is held, not uploaded: the QC
        # report says what to look at, and "fix it, do not ship it" is the rule.
        # Set UPLOAD_ATTENTION=1 to publish one anyway after looking at it.
        same = ytguard.find_existing(videos, ytguard.ref("whatif", slug))
        if same:
            # already on YouTube (17.11: never twice) - the record is written, nothing is sent
            stamp = {"youtube_id": same["id"], "publish_at": same["publish_at"] or same["published_at"]}
            marker.write_text(json.dumps(stamp), encoding="utf-8")
            meta = json.loads((d / "episode.json").read_text(encoding="utf-8"))
            meta.update(stamp)
            (d / "episode.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            queue.set_status(d, "published")
            queue.log_entry(f"{slug} is already on YouTube as {same['id']}; recorded, not uploaded again.")
            ytguard.persist([f"queue/{slug}", "queue/journal.md"], f"upload: {slug} already {same['id']}")
            continue
        verdict, problems = qc_verdict(pkg)
        # an episode the owner cleared by name ("owner_upload_despite_qc") goes up on an ATTENTION
        if verdict != "PASS" and os.environ.get("UPLOAD_ATTENTION") != "1"                 and not (verdict == "ATTENTION" and e.get("owner_upload_despite_qc")):
            note = f"{slug} held for review, QC says {verdict}: {'; '.join(problems)[:240]}"
            log.warning(note)
            queue.log_entry(note)
            meta = json.loads((d / "episode.json").read_text(encoding="utf-8"))
            first = not meta.get("held_by_qc")
            meta["held_by_qc"] = {"verdict": verdict, "problems": problems[:6],
                                  "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}
            (d / "episode.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            if first and not args.dry_run:
                ytguard.notify(f"What If: {slug} held by QC", note + "\nNo new episode is built until it is fixed.")
            print(f"::warning::{note}" if os.environ.get("GITHUB_ACTIONS") else note)
            held += 1
            continue
        taken = scheduled() + [datetime.fromisoformat(t.replace("Z", "+00:00"))
                               for t in ytguard.channel_dates(videos)]
        slot = next_slot(taken)
        print(f"{slug}: scheduling for {slot:%Y-%m-%d %H:%M} UTC")
        if args.dry_run:
            continue
        from pipeline import youtube
        try:
            v2 = json.loads((pkg / "v2.json").read_text(encoding="utf-8")) if (pkg / "v2.json").exists() else {}
            # containsSyntheticMedia: true only when the film holds an AI picture (v2.json, stages_v2.package)
            video_id, when = youtube.upload(pkg, publish_at=slot, synthetic_media=bool(v2.get("synthetic", True)),
                                            marker=ytguard.ref("whatif", slug), yt=yt)
        except Exception as err:                                 # noqa: BLE001
            failed += 1
            queue.log_entry(f"Upload FAILED for {slug}: {str(err)[:160]}")
            log.error("upload of %s failed: %s", slug, err)
            continue
        stamp = {"youtube_id": video_id,
                 "publish_at": when.strftime("%Y-%m-%dT%H:%M:%SZ")}
        marker.write_text(json.dumps(stamp), encoding="utf-8")
        meta = json.loads((d / "episode.json").read_text(encoding="utf-8"))
        meta.update(stamp)
        meta.pop("held_by_qc", None)
        (d / "episode.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                                        encoding="utf-8")
        queue.set_status(d, "published")
        queue.log_entry(f"Uploaded {slug} as {video_id}, public at {stamp['publish_at']}.")
        videos.append({"id": video_id, "title": "", "description": ytguard.ref("whatif", slug),
                       "privacy": "private", "publish_at": stamp["publish_at"], "published_at": None})
        # in git at once, or the run fails with a mail (owner 17.11)
        ytguard.persist([f"queue/{slug}", "queue/journal.md"], f"upload: {slug} as {video_id}")
        print(f"  https://youtu.be/{video_id} public at {stamp['publish_at']}")
    if held:
        print(f"{held} episode(s) held for review")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
