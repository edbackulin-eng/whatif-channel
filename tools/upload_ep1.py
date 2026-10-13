"""Upload episode one and schedule it, with a fallback slot if the clock runs out.

publishAt has to be chosen before the upload starts, but a 405 MB upload takes
an unknown time. So it is set to the preferred slot, and if the upload lands too
close to it the schedule is moved to the later slot afterwards - the video is
private until its moment, so the time can still be changed.
"""
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.logger import get_logger  # noqa: E402
from pipeline import youtube  # noqa: E402

log = get_logger("upload-ep1")

PACKAGE = ROOT / "ready" / "2026-10-13" / "001-moon-fell-to-earth"
PREFERRED = datetime(2026, 10, 13, 15, 30, tzinfo=timezone.utc)
FALLBACK = datetime(2026, 10, 13, 16, 0, tzinfo=timezone.utc)
SAFETY_MINUTES = 10


def main():
    started = datetime.now(timezone.utc)
    log.info("starting at %s, aiming for %s",
             started.strftime("%H:%M UTC"), PREFERRED.strftime("%H:%M UTC"))

    video_id, scheduled = youtube.upload(PACKAGE, publish_at=PREFERRED)
    finished = datetime.now(timezone.utc)
    took = (finished - started).total_seconds() / 60
    log.info("upload finished at %s (%.1f min)", finished.strftime("%H:%M UTC"), took)

    margin = (PREFERRED - finished).total_seconds() / 60
    if margin < SAFETY_MINUTES:
        log.warning("only %.1f min of margin before %s; moving to %s",
                    margin, PREFERRED.strftime("%H:%M"), FALLBACK.strftime("%H:%M"))
        yt = youtube.service()
        yt.videos().update(part="status", body={
            "id": video_id,
            "status": {
                "privacyStatus": "private",
                "publishAt": FALLBACK.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "selfDeclaredMadeForKids": False,
                "containsSyntheticMedia": True,
            },
        }).execute()
        scheduled = FALLBACK
        log.info("rescheduled to %s", FALLBACK.strftime("%H:%M UTC"))
    else:
        log.info("%.1f min of margin, keeping %s", margin,
                 PREFERRED.strftime("%H:%M UTC"))

    print("\n" + "=" * 56)
    print(f"  video id    : {video_id}")
    print(f"  url         : https://youtu.be/{video_id}")
    print(f"  publishes at: {scheduled:%Y-%m-%d %H:%M UTC}  "
          f"({scheduled + timedelta(hours=3):%H:%M} Kyiv)")
    print(f"  status now  : {youtube.is_public(video_id)}")
    print("=" * 56)

    (ROOT / "output" / "ep1_upload.json").write_text(
        f'{{"video_id": "{video_id}", '
        f'"publish_at": "{scheduled:%Y-%m-%dT%H:%M:%SZ}"}}', encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
