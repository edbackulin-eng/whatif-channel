"""Get every scene a picture: archive, drawn card, or generated on Kaggle.

The GPU work is the only part of a build that leaves the runner. Actions submits
a kernel, waits, and pulls the images back; the runner itself never loads an
image model, which is what keeps the build inside a free 2-core box.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

from core.logger import get_logger

log = get_logger("frames")
ROOT = Path(__file__).resolve().parent.parent

POLL_S = 60
GPU_TIMEOUT_S = 3 * 3600


def _slug(episode_slug, suffix):
    base = f"whatif-{episode_slug}-{suffix}".lower()
    return base[:50].strip("-")


def _submit(prompts, mapping, work, slug):
    """Push a generation kernel and return its Kaggle reference."""
    sys.path.insert(0, str(ROOT / "kaggle"))
    import push as kpush
    from core import style

    job = {
        "image_prompts": prompts,
        "style": "",
        "steps": style.STEPS,
        "width": style.ASPECT["width"],
        "height": style.ASPECT["height"],
        "seed": 4400,
    }
    job_path = work / f"job_{slug}.json"
    job_path.write_text(json.dumps(job, indent=2), encoding="utf-8")
    (work / f"mapping_{slug}.json").write_text(
        json.dumps(mapping, indent=2), encoding="utf-8")
    title = f"whatif {slug}"
    return kpush.push(job, slug, title)


def _wait(ref):
    started = time.time()
    while time.time() - started < GPU_TIMEOUT_S:
        r = subprocess.run([sys.executable, "-m", "kaggle", "kernels", "status", ref],
                           capture_output=True, text=True)
        status = (r.stdout + r.stderr).lower()
        if "complete" in status:
            return True
        if "error" in status or "cancel" in status:
            log.error("kernel %s failed: %s", ref, status[:200])
            return False
        time.sleep(POLL_S)
    log.error("kernel %s timed out", ref)
    return False


def _fetch(ref, dest):
    dest.mkdir(parents=True, exist_ok=True)
    import kaggle
    kaggle.api.authenticate()
    kaggle.api.kernels_output(ref, path=str(dest), quiet=True)
    return sorted((dest / "images").glob("*.png")) if (dest / "images").exists() else []


def _generate(scenes_needing, work, slug, extra_prompts=()):
    """Generate frames for the given scenes, plus any prompts riding along.

    Returns ({scene_index: path}, [path per extra prompt, None where missing]).

    The extras exist for the thumbnail, which needs its own generations rather
    than a leftover frame. They are appended to the same kernel because the cost
    of a GPU job is almost entirely the FLUX load and the turn of the shared GPU
    lock, not the six images: a second kernel for them would cost minutes, and
    tacking them onto this one costs seconds.
    """
    from core import style
    prompts, mapping = [], []
    for s in scenes_needing:
        desc = s.get("prompt") or s.get("text", "")[:160]
        people = any(w in desc.lower() for w in
                     ("people", "crowd", "figure", "silhouette", "operators"))
        prompts.append(style.scene_prompt(desc, people))
        mapping.append({"index": s["index"]})
    for k, prompt in enumerate(extra_prompts):
        prompts.append(prompt)
        mapping.append({"extra": k})
    if not prompts:
        return {}, []
    ref = _submit(prompts, mapping, work, slug)
    log.info("submitted %d prompts as %s (%d scene, %d thumbnail)", len(prompts), ref,
             len(scenes_needing), len(extra_prompts))
    extras = [None] * len(extra_prompts)
    if not _wait(ref):
        return {}, extras
    images = _fetch(ref, work / f"gpu_{slug}")
    out = {}
    for i, entry in enumerate(mapping):
        if i >= len(images):
            continue
        if "index" in entry:
            out[entry["index"]] = str(images[i].resolve())
        else:
            extras[entry["extra"]] = str(images[i].resolve())
    log.info("recovered %d/%d generated frames and %d/%d thumbnail candidates",
             len(out), len(scenes_needing),
             sum(1 for p in extras if p), len(extra_prompts))
    return out, extras


def _drop_missing(scenes):
    """Forget image paths that do not resolve on this machine.

    Scene plans travel with the queue, and their paths are absolute and from
    whichever machine wrote them. On a CI runner those files do not exist, but
    the field is still truthy - so without this every stage would believe the
    frames were already in hand and the build would render nothing but gaps.
    """
    dropped = 0
    for s in scenes:
        img = s.get("image")
        if img and not Path(img).exists():
            s.pop("image", None)
            dropped += 1
    if dropped:
        log.info("dropped %d image path(s) that do not exist here", dropped)
    return scenes


THUMB_SOURCES = "thumbnail_sources.json"


def _thumbnail_plan(work, episode):
    """The thumbnail's own prompts, to ride along with the scene batch.

    Empty when there is nothing to do: no episode handed in, a thumbnail that is
    already approved by hand, or candidates already generated by an earlier run
    of this build.
    """
    if not episode:
        return None, []
    if (episode.get("approved") or {}).get("thumbnail"):
        log.info("this episode's thumbnail is approved; generating none for it")
        return None, []
    if (Path(work) / THUMB_SOURCES).exists():
        log.info("thumbnail candidates already generated, reusing them")
        return None, []
    from pipeline import thumbplan
    try:
        brief = thumbplan.brief(episode, work)
        return brief, thumbplan.candidates(brief, thumbplan.cast(episode))
    except Exception as e:                                       # noqa: BLE001
        log.warning("could not plan the thumbnail (%s); it will fall back to an "
                    "episode frame", e)
        return None, []


def ensure(work, scenes, episode=None):
    """Fill in archive stills, cards and generated frames for every scene.

    `episode` is only used to plan the thumbnail's own generations; without it
    the thumbnail falls back to the old behaviour of picking an episode frame.
    """
    from pipeline import infographics, visuals

    _drop_missing(scenes)

    # Archive
    used = set()
    for s in scenes:
        if s["source"] != "archive" or s.get("image"):
            continue
        record = None
        for query in _ladder(s.get("query") or "earth from space"):
            try:
                for c in visuals.search(query, limit=10):
                    if c["nasa_id"] in used:
                        continue
                    record = visuals.download(c, work / "shots", s["index"])
                    if record:
                        used.add(c["nasa_id"])
                        break
            except Exception as e:
                log.warning("archive search failed for %r: %s", query, e)
            if record:
                break
        if record:
            s["image"] = str((work / "shots" / record["file"]).resolve())

    # Cards
    sys.path.insert(0, str(ROOT))
    from kt3_assets import _normalise_card
    specs, carded = [], []
    for s in scenes:
        if s["source"] != "infographic" or s.get("image"):
            continue
        result = _normalise_card(s.get("card") or {})
        if result is None:
            s["source"] = "generated"
            s.pop("card", None)
            continue
        kind, headline, sub = result
        spec = (("timer", {"label": headline, "sublabel": sub}) if kind == "timer"
                else ("number", {"value": headline, "caption": sub}))
        specs.append(spec)
        s["card_spec"] = spec
        carded.append(s)
    if specs:
        paths = infographics.render_all(specs, work / "cards")
        for s, p in zip(carded, paths):
            s["image"] = str(p.resolve())

    # Generated, with the thumbnail's own candidates on the end of the same batch
    need = [s for s in scenes if s["source"] == "generated" and not s.get("image")]
    brief, thumbs = _thumbnail_plan(work, episode)
    if need or thumbs:
        produced, extras = _generate(need, work, "main",
                                     [t["prompt"] for t in thumbs])
        for s in scenes:
            if s["index"] in produced:
                s["image"] = produced[s["index"]]
        if thumbs:
            for t, path in zip(thumbs, extras):
                t["image"] = path
            kept = [t for t in thumbs if t.get("image")]
            (Path(work) / THUMB_SOURCES).write_text(
                json.dumps({"brief": brief, "candidates": kept}, indent=2,
                           ensure_ascii=False), encoding="utf-8")
            log.info("%d thumbnail candidate(s) generated for this episode", len(kept))
    return scenes


def regenerate(work, scenes_failed):
    """One more attempt at frames the visual check rejected."""
    if not scenes_failed:
        return set()
    produced, _ = _generate(scenes_failed, work, "retry")
    fixed = set()
    for s in scenes_failed:
        if s["index"] in produced:
            s["image"] = produced[s["index"]]
            fixed.add(s["index"])
    log.info("regenerated %d/%d rejected frames", len(fixed), len(scenes_failed))
    return fixed


_NOISE = {"nasa", "spacecraft", "mission", "image", "photo", "view",
          "apollo", "galileo", "cassini", "voyager", "hubble", "iss", "lro"}


def _ladder(query):
    words = [w for w in query.split() if w]
    out = [query]
    trimmed = [w for w in words if w.lower().strip(",.") not in _NOISE]
    if trimmed and trimmed != words:
        out.append(" ".join(trimmed))
    if len(trimmed) > 3:
        out.append(" ".join(trimmed[:3]))
    if len(trimmed) > 2:
        out.append(" ".join(trimmed[:2]))
    seen, uniq = set(), []
    for q in out:
        if q and q.lower() not in seen:
            seen.add(q.lower())
            uniq.append(q)
    return uniq
