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

--set-youtube replaces the thumbnail on the live video too, and is the only part
of this that is visible outside the repository. Without it the run writes files
and nothing else.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.logger import get_logger  # noqa: E402

log = get_logger("restyle")
OUT = ROOT / "output" / "thumbnails"


def _episode(slug):
    path = ROOT / "queue" / slug / "episode.json"
    if not path.exists():
        raise SystemExit(f"no queued episode at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def plan(slugs, use_llm=True):
    """A brief and a set of prompts per slug."""
    from pipeline import thumbplan
    jobs = []
    for slug in slugs:
        episode = _episode(slug)
        work = OUT / slug
        work.mkdir(parents=True, exist_ok=True)
        brief = thumbplan.brief(episode, work, use_llm=use_llm)
        jobs.append({"slug": slug, "episode": episode, "work": work,
                     "brief": brief, "candidates": thumbplan.candidates(brief)})
        log.info("%s: words=%s comparison=%s", slug, brief["words"],
                 bool(brief["comparison"]))
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
                [c["image"] for c in cands], topic=job["episode"].get("title"))
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", action="append", required=True,
                    help="queue slug; repeat for several in one GPU run")
    ap.add_argument("--no-llm", action="store_true",
                    help="derive the brief from the title instead of asking Gemini")
    ap.add_argument("--set-youtube", action="store_true",
                    help="also replace the thumbnail on the live video")
    args = ap.parse_args()

    jobs = plan(args.slug, use_llm=not args.no_llm)
    if not generate(jobs):
        raise SystemExit("no candidate came back from the GPU")
    judge(jobs)
    written = compose(jobs)
    if args.set_youtube:
        publish(jobs)
    print("\n".join(str(p) for p in written))
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
