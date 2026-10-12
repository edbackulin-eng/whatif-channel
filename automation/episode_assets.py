"""Pull an episode's approved material from its Kaggle dataset, if it has one.

Episode one was built and approved on a workstation. Its narration, its 223
frames and the chosen thumbnail exist nowhere else, so a CI runner starting from
the repository alone would regenerate all of it - including the thumbnail the
channel owner picked by hand.

So anything approved travels in a private Kaggle dataset, and a build that finds
one uses it verbatim. `episode.json` names the dataset; episodes without one are
built from scratch as usual.
"""
import json
import shutil
import sys
from pathlib import Path

from core.logger import get_logger

log = get_logger("episode-assets")

# Material that is approved and must never be regenerated when present.
APPROVED = ("narration.wav", "subs.srt", "script.txt", "scenes.json",
            "sources.json", "credits.json", "factcheck-log.md",
            "thumbnail.png", "metadata.txt")


def dataset_for(episode):
    return episode.get("kaggle_dataset")


def fetch(episode, work):
    """Download the episode's dataset into `work`. Returns True when used."""
    ref = dataset_for(episode)
    if not ref:
        log.info("episode has no dataset; building from scratch")
        return False

    work = Path(work)
    staging = work / "_dataset"
    staging.mkdir(parents=True, exist_ok=True)
    try:
        import kaggle
        kaggle.api.authenticate()
        log.info("downloading dataset %s", ref)
        kaggle.api.dataset_download_files(ref, path=str(staging), unzip=True, quiet=True)
    except Exception as e:
        log.error("could not fetch %s: %s", ref, e)
        return False

    # Kaggle sometimes nests everything one level down; flatten that.
    root = staging
    entries = [p for p in staging.iterdir()]
    if len(entries) == 1 and entries[0].is_dir() and not (staging / "scenes.json").exists():
        root = entries[0]

    copied = []
    for name in APPROVED:
        src = root / name
        if src.exists():
            shutil.copy2(src, work / name)
            copied.append(name)

    frames_src = root / "frames"
    frames_dst = work / "frames"
    if frames_src.is_dir():
        if frames_dst.exists():
            shutil.rmtree(frames_dst)
        shutil.copytree(frames_src, frames_dst)
        log.info("frames restored: %d", len(list(frames_dst.iterdir())))

    log.info("restored from dataset: %s", ", ".join(copied) or "(nothing)")
    return bool(copied)


def bind_frames(work, scenes):
    """Point each scene at its frame in the restored folder.

    The dataset stores frames named by scene index, so no mapping file is needed
    and the numbering cannot drift the way it did when frames were matched back
    by position after a re-plan.
    """
    frames = Path(work) / "frames"
    if not frames.is_dir():
        return scenes, 0
    by_stem = {}
    for p in frames.iterdir():
        if p.is_file():
            by_stem.setdefault(p.stem, p)
    bound = 0
    for s in scenes:
        p = by_stem.get(f"{s['index']:03d}")
        if p:
            s["image"] = str(p.resolve())
            bound += 1
    log.info("bound %d/%d scenes to restored frames", bound, len(scenes))
    return scenes, bound
