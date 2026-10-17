"""The hourly watchdog for What If: keeps the channel running with nobody watching.

    python automation/watchdog.py            (from .github/workflows/watchdog.yml)

Runs on GitHub Actions only. Each pass:

  1. a build that hangs past GitHub's own limit is cancelled;
  2. a build that failed BEFORE its upload is run again (once more, then a
     third time if that fails too). A build that failed at or after the upload
     is never rerun - rerunning it would upload the same episode twice - and
     the owner gets an email instead;
  3. if fewer than MIN_AHEAD episodes are scheduled and no build is running, a
     build is started - before 18:00 UTC only, the hour Closed Tabs' GPU window
     approaches (build-video.yml's gate refuses later starts anyway);
  4. if the next 15:00 UTC slot is under RESCUE_H hours away and empty, the
     earliest episode scheduled later is moved onto it;
  5. once a day state/heartbeat.json is committed, so the repository never goes
     60 days without a commit and loses its schedules.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline import queue  # noqa: E402

REPO = os.environ.get("GITHUB_REPOSITORY", "edbackulin-eng/whatif-channel")
OWNER = REPO.split("/")[0]
BUILD = "build-video.yml"
MIN_AHEAD = 2
RESCUE_H = 3
HUNG_H = 6.5
SETTLE_MIN = 12
MAX_ATTEMPTS = 3
LAST_START_H = 18
SLOT_HOUR = 15
# steps after which a rerun could upload a second copy
AFTER_UPLOAD = ("Upload to YouTube", "Record the outcome", "Count what is scheduled ahead",
                "Keep two scheduled ahead")
STATE = ROOT / "state" / "watchdog.json"
HEARTBEAT = ROOT / "state" / "heartbeat.json"


def now():
    return datetime.now(timezone.utc)


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def gh(*args, parse=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)}: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout) if parse and r.stdout.strip() else r.stdout


def memory():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"emailed": []}


def email(key, subject, body, mem):
    if key in mem["emailed"]:
        return
    issues = gh("issue", "list", "-R", REPO, "--label", "run-log", "--state", "open", "--json", "number")
    if issues:
        n = issues[0]["number"]
    else:
        subprocess.run(["gh", "label", "create", "run-log", "-R", REPO, "--color", "b60205"],
                       capture_output=True)
        url = gh("issue", "create", "-R", REPO, "--title", "Build failures", "--label", "run-log",
                 "--body", "A comment here mentioning the owner arrives as an email.", parse=False)
        n = url.strip().rsplit("/", 1)[-1]
    gh("issue", "comment", str(n), "-R", REPO, "--body", f"@{OWNER} **{subject}**\n\n{body}", parse=False)
    mem["emailed"].append(key)


def scheduled():
    out = []
    for e in queue.episodes():
        when = e.get("publish_at")
        if when and e.get("youtube_id") and ts(when) > now():
            out.append(e)
    return sorted(out, key=lambda e: e["publish_at"])


def check_runs(mem, actions):
    """Steps 1 and 2. True when a build is running or being recovered."""
    runs = gh("api", f"repos/{REPO}/actions/workflows/{BUILD}/runs?per_page=10")["workflow_runs"]
    for r in runs:
        if r["status"] != "completed":
            if now() - ts(r["run_started_at"] or r["created_at"]) > timedelta(hours=HUNG_H):
                gh("run", "cancel", str(r["id"]), "-R", REPO, parse=False)
                actions.append(f"cancelled hung build {r['id']}")
            else:
                return True
    latest = next((r for r in runs if r["status"] == "completed"), None)
    if not latest or latest["conclusion"] not in ("failure", "cancelled", "timed_out"):
        return False
    if now() - ts(latest["updated_at"]) < timedelta(minutes=SETTLE_MIN):
        return True
    rid, attempt = latest["id"], latest.get("run_attempt", 1)
    jobs = gh("api", f"repos/{REPO}/actions/runs/{rid}/jobs?per_page=20")["jobs"]
    build = next((j for j in jobs if j["name"] == "build"), None)
    if build is None:
        return False                      # the 18:00 gate stopped it: nothing failed
    bad = [s["name"] for s in build.get("steps", [])
           if s.get("conclusion") in ("failure", "cancelled", "timed_out")]
    uploaded = any(s["name"] == "Upload to YouTube" and s.get("conclusion") == "success"
                   for s in build.get("steps", []))
    if (uploaded or any(b in AFTER_UPLOAD for b in bad)) or attempt >= MAX_ATTEMPTS:
        email(f"build-{rid}", f"What If: build {rid} failed ({', '.join(bad) or latest['conclusion']})",
              f"Attempt {attempt}. {'It had already uploaded, so it is not rerun automatically. ' if uploaded else ''}"
              f"Run: https://github.com/{REPO}/actions/runs/{rid}", mem)
        return False
    if now().hour >= LAST_START_H:
        return False                      # the 03:17 cron will build instead
    gh("run", "rerun", str(rid), "-R", REPO, "--failed", parse=False)
    actions.append(f"reran build {rid} (failed at {', '.join(bad)}; attempt {attempt + 1})")
    return True


def check_buffer(busy, actions):
    have = scheduled()
    if len(have) >= MIN_AHEAD or busy or now().hour >= LAST_START_H:
        return have
    gh("workflow", "run", BUILD, "-R", REPO, parse=False)
    actions.append(f"only {len(have)} scheduled ahead; build started")
    return have


def next_slot():
    day = now().replace(hour=SLOT_HOUR, minute=0, second=0, microsecond=0)
    while day < now() or day.weekday() not in queue.PUBLISH_WEEKDAYS:
        day += timedelta(days=1)
        day = day.replace(hour=SLOT_HOUR)
    return day


def check_slot(have, mem, actions):
    slot = next_slot()
    if slot - now() > timedelta(hours=RESCUE_H):
        return
    if any(ts(e["publish_at"]).date() == slot.date() for e in have):
        return
    later = [e for e in have if ts(e["publish_at"]) > slot]
    if not later:
        email(f"empty-{slot:%Y%m%d}", f"What If: no video for the {slot:%a %d.%m %H:%M} UTC slot",
              "Nothing is scheduled for it and nothing later could be moved onto it.", mem)
        return
    e = later[0]
    from pipeline import youtube
    yt = youtube.service()
    st = yt.videos().list(part="status", id=e["youtube_id"]).execute()["items"][0]["status"]
    keep = {k: v for k, v in st.items() if k in ("privacyStatus", "embeddable", "license",
                                                 "publicStatsViewable", "selfDeclaredMadeForKids",
                                                 "containsSyntheticMedia")}
    keep["publishAt"] = slot.strftime("%Y-%m-%dT%H:%M:%SZ")
    yt.videos().update(part="status", body={"id": e["youtube_id"], "status": keep}).execute()
    d = ROOT / "queue" / e["slug"]
    meta = json.loads((d / "episode.json").read_text(encoding="utf-8"))
    meta.setdefault("moved_from", []).append(meta["publish_at"])
    meta["publish_at"] = keep["publishAt"]
    (d / "episode.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    actions.append(f"{e['youtube_id']} moved to the empty slot {keep['publishAt']}")


def main():
    mem = memory()
    actions = []
    try:
        busy = check_runs(mem, actions)
    except Exception as e:                                       # noqa: BLE001
        print(f"run check failed: {e}")
        busy = True
    have = check_buffer(busy, actions)
    try:
        check_slot(have, mem, actions)
    except Exception as e:                                       # noqa: BLE001
        email(f"slotcheck-{now():%Y%m%d}", "What If: the watchdog could not check the next slot",
              str(e)[:500], mem)
    mem["emailed"] = mem["emailed"][-200:]
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(mem, indent=1), encoding="utf-8")
    beat = {"date": f"{now():%Y-%m-%d}", "checked_at": f"{now():%Y-%m-%dT%H:%M:%SZ}",
            "scheduled_ahead": [[e["publish_at"], e["youtube_id"]] for e in scheduled()],
            "actions": actions}
    old = json.loads(HEARTBEAT.read_text(encoding="utf-8")) if HEARTBEAT.exists() else {}
    HEARTBEAT.write_text(json.dumps(beat, indent=1), encoding="utf-8")
    print(json.dumps(beat, indent=1))
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"commit={'true' if actions or old.get('date') != beat['date'] else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
