"""Guarantee today's video: watch the running build, step in if it is late.

    python tools/watch_today.py <run_id> <package_dir> [deadline HH:MM UTC]

Every two minutes:
  - if the build has uploaded the episode, make sure its publishAt is today
    (moving it with publish_today.fix when it is not), and stop;
  - at the deadline (14:00 UTC) with no upload yet, cancel the build so it cannot
    upload the same episode later, wait for the cancellation, upload the package
    from the 13 October build for today, and push the queue record so no later
    build repeats it.
"""
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import publish_today as pt  # noqa: E402
from pipeline import youtube  # noqa: E402

REPO = "edbackulin-eng/whatif-channel"
TITLE = "What If Earth Stopped Spinning?"


def gh(*args):
    return subprocess.run(["gh", *args, "--repo", REPO], capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


def new_upload(since):
    """The id of a video with the episode title uploaded after `since`, if any."""
    yt = youtube.service()
    ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    pl = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    r = yt.playlistItems().list(part="snippet,contentDetails", playlistId=pl, maxResults=15).execute()
    for it in r.get("items", []):
        sn = it["snippet"]
        when = datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
        if sn["title"].strip() == TITLE and when >= since:
            return it["contentDetails"]["videoId"]
    return None


def fetch_artifact(pkg):
    """On a runner the 13 October package is not on disk: pull it from the run."""
    import os
    import zipfile
    art = os.environ["ARTIFACT_ID"]
    z = ROOT / "ready" / "_artifact.zip"
    z.parent.mkdir(parents=True, exist_ok=True)
    with open(z, "wb") as fh:
        subprocess.run(["gh", "api", f"repos/{REPO}/actions/artifacts/{art}/zip"],
                       stdout=fh, check=True)
    zipfile.ZipFile(z).extractall(ROOT / "ready")
    found = sorted((ROOT / "ready").glob(f"*/{pkg.name}/video.mp4"))
    if not found:
        raise RuntimeError(f"artifact {art} holds no {pkg.name}")
    pkg.parent.mkdir(parents=True, exist_ok=True)
    if found[0].parent != pkg:
        import shutil
        shutil.copytree(found[0].parent, pkg, dirs_exist_ok=True)
    print(f"package fetched from artifact {art}", flush=True)


def is_today(publish_at):
    if not publish_at:
        return False
    when = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
    return when.date() == datetime.now(timezone.utc).date()


def push_queue(msg):
    subprocess.run(["git", "-C", str(ROOT), "add", "queue/", "tools/"], check=True)
    subprocess.run(["git", "-C", str(ROOT), "-c", "user.name=edbackulin-eng",
                    "-c", "user.email=ed.backulin@gmail.com", "commit", "-q", "-m", msg], check=False)
    for _ in range(5):
        subprocess.run(["git", "-C", str(ROOT), "pull", "-q", "--rebase", "origin", "main"])
        if subprocess.run(["git", "-C", str(ROOT), "push", "-q", "origin", "main"]).returncode == 0:
            return True
        time.sleep(10)
    return False


def main(run_id, package, deadline="14:00"):
    started = datetime(2026, 10, 15, 9, 16, tzinfo=timezone.utc)
    dh, dm = map(int, deadline.split(":"))
    while True:
        now = datetime.now(timezone.utc)
        vid = None
        try:
            vid = new_upload(started)
        except Exception as e:                                   # noqa: BLE001
            print(f"{now:%H:%M}Z api check failed: {e}", flush=True)
        if vid:
            try:
                st = pt.status(vid)
            except Exception as e:                               # noqa: BLE001
                print(f"{now:%H:%M}Z status read failed ({e}); retrying", flush=True)
                time.sleep(60)
                continue
            print(f"{now:%H:%M}Z build uploaded {vid}: {st}", flush=True)
            if not is_today(st.get("publishAt")) and st.get("privacy") != "public":
                st = pt.fix(vid)
                print(f"moved to today: {st}", flush=True)
            print("RESULT " + json.dumps(st), flush=True)
            return 0
        state = gh("run", "view", run_id, "--json", "status,conclusion", "-q",
                   '"\\(.status)/\\(.conclusion)"')
        print(f"{now:%H:%M}Z build {state}, no upload yet", flush=True)
        failed = state.startswith("completed/") and not state.endswith("success")
        finished_without = state.startswith("completed/success")
        if (now.hour, now.minute) >= (dh, dm) or failed or finished_without:
            if state.startswith("in_progress") or state.startswith("queued"):
                print("deadline reached; cancelling the build so it cannot upload a duplicate",
                      flush=True)
                gh("run", "cancel", run_id)
                for _ in range(30):
                    time.sleep(10)
                    if gh("run", "view", run_id, "--json", "status", "-q", ".status") == "completed":
                        break
                try:
                    if new_upload(started):      # it got there in the last seconds
                        continue
                except Exception:                                # noqa: BLE001
                    pass
            pkg = Path(package)
            if not (pkg / "video.mp4").exists():
                fetch_artifact(pkg)
            st = pt.upload(pkg)
            print(f"uploaded from the 13 October build: {st}", flush=True)
            pushed = push_queue("Upload 002 from the 13 October build for today's slot\n\n"
                                "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
            print(f"queue record pushed: {pushed}", flush=True)
            print("RESULT " + json.dumps(st), flush=True)
            return 0
        time.sleep(120)


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
