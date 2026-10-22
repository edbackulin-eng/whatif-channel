"""Give an episode that already exists a thumbnail in the new house style.

New episodes get one from the build, because automation/frames.py puts the
thumbnail's own generations on the end of the scene batch. Episodes that were
already built - the ones scheduled and the ones already up - have a thumbnail
made the old way, from a still lifted out of the video, and this is how they are
replaced.

    python -X utf8 tools/restyle_thumbnail.py --slug 018-what-if-jupiter-vanished
    python -X utf8 tools/restyle_thumbnail.py --slug 017-... --slug 018-... --set-youtube

Every slug named in one run shares a single GPU kernel: the cost of a Kaggle job
is the FLUX load and the turn of the shared GPU lock, not the six images, so
restyling five episodes at once costs about what one costs.

When the judge says not one candidate shows the episode's own subject - a black
hole drawn as a sun, one moon where there should be two - there is ONE more
generation with a blunter event description, sharing a kernel again, and then
the best of both batches is used. One retry and no more: a second kernel is
already the expensive part of this, and a third that still missed would cost
more than shipping the best picture there is.

--set-youtube replaces the thumbnail on the live video too, and is the only part
of this that is visible outside the repository. Without it the run writes files
and nothing else.

A restyle can also be booked for later, in state/thumbnail_restyles.json, when
the GPU is not to be spent today. The workflow's schedule claims whatever is
due (--claim), runs it, and records how it went (--settle). A claimed entry is
never picked up again, even when its run fails: each one is exactly one kernel,
which is the point of booking it rather than running it now.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.logger import get_logger  # noqa: E402

log = get_logger("restyle")
OUT = ROOT / "output" / "thumbnails"
BOOKINGS = ROOT / "state" / "thumbnail_restyles.json"


def _episode(slug):
    path = ROOT / "queue" / slug / "episode.json"
    if not path.exists():
        raise SystemExit(f"no queued episode at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def plan(slugs, use_llm=True):
    """A brief, a cast and a set of prompts per slug.

    In feed order, not the order they were named: each episode is cast against
    the one before it, including one cast earlier in this same run, so the
    genders alternate down the feed whichever candidates the judge goes on to
    pick.
    """
    from pipeline import thumbplan
    episodes = sorted((_episode(s) for s in slugs), key=lambda e: e.get("position") or 0)
    jobs, planned = [], []
    for episode in episodes:
        slug = episode["slug"]
        work = OUT / slug
        work.mkdir(parents=True, exist_ok=True)
        brief = thumbplan.brief(episode, work, use_llm=use_llm)
        people = thumbplan.cast(episode, planned=planned)
        planned.append(thumbplan.as_planned(episode, people))
        jobs.append({"slug": slug, "episode": episode, "work": work, "brief": brief,
                     "people": people,
                     "candidates": thumbplan.candidates(brief, people)})
        log.info("%s: words=%s setting=%s/%s, cast %s", slug, brief["words"],
                 brief.get("setting"), brief.get("place"),
                 ", ".join(f"{p['look']} {p['gender']} {p['age']}" for p in people))
    return jobs


def generate(jobs):
    """One kernel for every candidate of every slug. Fills in each candidate's image."""
    from automation import frames
    prompts, owners = [], []
    for job in jobs:
        for c in job["candidates"]:
            prompts.append(c["prompt"])
            owners.append(c)
    if not prompts:
        return 0
    work = OUT / "_gpu"
    work.mkdir(parents=True, exist_ok=True)
    slug = f"thumbs-{int(time.time())}"
    ref = frames._submit(prompts, [{"extra": i} for i in range(len(prompts))], work, slug)
    log.info("submitted %d thumbnail prompts as %s", len(prompts), ref)
    if not frames._wait(ref):
        raise SystemExit(f"kernel {ref} did not complete")
    images = frames._fetch(ref, work / f"gpu_{slug}")
    for c, image in zip(owners, images):
        c["image"] = str(image.resolve())
    got = sum(1 for c in owners if c.get("image"))
    log.info("recovered %d/%d candidates", got, len(prompts))
    return got


def judge(jobs):
    """Gemini vision over every candidate, in one pass per slug.

    Per slug and not all at once, because the judge is told the episode's title
    and asked whether the picture shows that subject.
    """
    from automation import assemble
    from pipeline import visualqc
    for job in jobs:
        cands = [c for c in job["candidates"] if c.get("image")]
        try:
            verdicts = visualqc.judge_thumbnails(
                [c["image"] for c in cands], topic=job["episode"].get("title"),
                setting=job["brief"].get("setting"))
        except Exception as e:                                   # noqa: BLE001
            log.warning("%s: no vision judge (%s); every candidate counts as "
                        "unchecked", job["slug"], e)
            verdicts = {}
        for c in cands:
            c["verdict"] = verdicts.get(Path(c["image"])) or dict(assemble.UNJUDGED)
        off = [c for c in cands if not c["verdict"].get("matches", True)]
        if off:
            log.info("%s: %d/%d candidate(s) do not show the episode's subject",
                     job["slug"], len(off), len(cands))


def off_topic(job):
    """True when not one usable candidate shows the episode's own subject.

    Candidates the judge rejected outright do not count either way: a melted
    face that happens to sit in front of the right event is not a thumbnail.
    """
    from automation import assemble
    cands = [c for c in job["candidates"] if c.get("image")]
    usable = [c for c in cands if c["verdict"].get("defect") not in assemble.FATAL]
    return bool(cands) and not any(c["verdict"].get("matches", True)
                                   for c in (usable or cands))


def retry_off_topic(jobs, use_llm=True):
    """One more generation, with a blunter event description, for the slugs where
    nothing showed the subject. One only - a kernel is not cheap.

    The first pass is kept rather than thrown away: the ranking already puts a
    matching picture ahead of a non-matching one, so the second batch wins only
    where it deserves to.
    """
    from pipeline import thumbplan
    again = [job for job in jobs if off_topic(job)]
    if not again:
        return []
    log.info("%d slug(s) had no candidate showing the subject; one more generation "
             "with a blunter description", len(again))
    for job in again:
        notes = [c["verdict"].get("match_note", "") for c in job["candidates"]]
        job["first_pass"] = job["candidates"]
        job["brief"] = thumbplan.restate(job["brief"], notes, use_llm=use_llm)
        job["candidates"] = thumbplan.candidates(job["brief"], job["people"])
        (job["work"] / thumbplan.BRIEF_FILE).write_text(
            json.dumps(job["brief"], indent=2, ensure_ascii=False), encoding="utf-8")
    generate(again)
    judge(again)
    for job in again:
        job["candidates"] = job.pop("first_pass") + [c for c in job["candidates"]
                                                     if c.get("image")]
        matched = sum(1 for c in job["candidates"] if c["verdict"].get("matches"))
        log.info("%s: %d of %d candidates now show the subject", job["slug"],
                 matched, len(job["candidates"]))
        if not matched:
            log.warning("%s: still nothing on the subject after the retry; the best "
                        "available picture is used", job["slug"])
    return again


def compose(jobs):
    """Pick and draw, exactly as a build does, and write the result beside the queue."""
    from automation import assemble
    from pipeline import thumbnail
    written = []
    for job in jobs:
        cands = [c for c in job["candidates"] if c.get("image")]
        if not cands:
            log.error("%s: nothing was generated; skipped", job["slug"])
            continue
        brief, work = job["brief"], job["work"]
        words = brief.get("words") or []
        if brief.get("comparison") and any(c.get("role") in ("left", "right") for c in cands):
            img, report = assemble._compose_split(cands, brief, words, work)
        else:
            img, report = assemble._compose_single(cands, words, work)
        out = thumbnail.save(img, work / "thumbnail.png")
        img.resize((thumbnail.BROWSE_W, thumbnail.BROWSE_H)).save(
            work / "thumbnail_browse.png")
        legible = min((r["legibility"] for r in report
                       if r.get("used") and r.get("legibility") is not None),
                      default=None)
        (work / "thumbnail_report.json").write_text(
            json.dumps({"brief": brief, "min_legibility": assemble.MIN_LEGIBILITY,
                        "candidates": report}, indent=1, ensure_ascii=False),
            encoding="utf-8")
        log.info("%s -> %s (%.2f MB, legibility %s)", job["slug"], out,
                 out.stat().st_size / 1e6, legible)
        job["thumbnail"] = out
        from pipeline import thumbplan
        thumbplan.remember_person(job["episode"], assemble.used_person(cands, report))
        written.append(out)
    return written


def publish(jobs):
    """Replace the thumbnail on the live video. Outward-facing, hence opt-in."""
    from pipeline import youtube
    yt = youtube.service()
    for job in jobs:
        video_id = job["episode"].get("youtube_id")
        if not video_id:
            log.info("%s has no youtube_id; nothing to replace", job["slug"])
            continue
        if not job.get("thumbnail"):
            log.warning("%s has no new thumbnail; not touching the live video",
                        job["slug"])
            continue
        yt.thumbnails().set(videoId=video_id,
                            media_body=str(job["thumbnail"])).execute()
        log.info("%s: thumbnail replaced on https://youtu.be/%s", job["slug"], video_id)


def _bookings():
    if not BOOKINGS.exists():
        return []
    return json.loads(BOOKINGS.read_text(encoding="utf-8"))


def _save_bookings(entries):
    BOOKINGS.parent.mkdir(parents=True, exist_ok=True)
    BOOKINGS.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _output(**values):
    """Hand values to the next workflow step, or print them when run by hand."""
    path = os.environ.get("GITHUB_OUTPUT")
    lines = [f"{k}={v}" for k, v in values.items()]
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


def claim(today=None):
    """Mark the bookings that are due as running, and say which they are.

    One kernel per run: bookings due on the same day that also share their flags
    go together, the rest wait for the next scheduled run.
    """
    entries = _bookings()
    today = today or datetime.now(timezone.utc).date().isoformat()
    due = [e for e in entries
           if e.get("status", "pending") == "pending" and e["not_before"] <= today]
    if not due:
        _output(slugs="", set_youtube="false", retry="false")
        log.info("no thumbnail restyle due on %s", today)
        return []
    flags = (bool(due[0].get("set_youtube")), bool(due[0].get("retry", True)))
    batch = [e for e in due
             if (bool(e.get("set_youtube")), bool(e.get("retry", True))) == flags]
    for e in batch:
        e["status"] = "running"
        e["claimed"] = _now()
    _save_bookings(entries)
    _output(slugs=" ".join(e["slug"] for e in batch),
            set_youtube=str(flags[0]).lower(), retry=str(flags[1]).lower())
    log.info("claimed %d booked restyle(s): %s", len(batch),
             ", ".join(e["slug"] for e in batch))
    return batch


def settle(outcome, run_url=""):
    """Record how the claimed bookings went. Never puts one back to pending."""
    entries = _bookings()
    for e in entries:
        if e.get("status") == "running":
            e["status"] = "done" if outcome == "success" else "failed"
            e["finished"] = _now()
            if run_url:
                e["run"] = run_url
    _save_bookings(entries)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", action="append",
                    help="queue slug; repeat for several in one GPU run")
    ap.add_argument("--no-llm", action="store_true",
                    help="derive the brief from the title instead of asking Gemini")
    ap.add_argument("--no-retry", action="store_true",
                    help="do not spend a second kernel when nothing matched the topic")
    ap.add_argument("--set-youtube", action="store_true",
                    help="also replace the thumbnail on the live video")
    ap.add_argument("--claim", action="store_true",
                    help="mark the booked restyles that are due as running")
    ap.add_argument("--settle", choices=("success", "failure"),
                    help="record how the claimed restyles went")
    ap.add_argument("--run-url", default="")
    args = ap.parse_args()

    if args.claim:
        claim()
        return 0
    if args.settle:
        settle(args.settle, args.run_url)
        return 0
    if not args.slug:
        ap.error("--slug is required unless --claim or --settle is given")

    jobs = plan(args.slug, use_llm=not args.no_llm)
    if not generate(jobs):
        raise SystemExit("no candidate came back from the GPU")
    judge(jobs)
    if not args.no_retry:
        retry_off_topic(jobs, use_llm=not args.no_llm)
    written = compose(jobs)
    if args.set_youtube:
        publish(jobs)
    print("\n".join(str(p) for p in written))
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
