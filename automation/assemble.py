"""Render, check and package an episode. Generalised from the episode-one build.

Everything here was proven on "What If the Moon Fell to Earth?" - the crossfade
overlap compensation, the static cards, the cover-fill grade and the border
check all exist because that build got them wrong first.
"""
import json
import shutil
import time
from datetime import date
from pathlib import Path

from core.logger import get_logger

log = get_logger("assemble")
ROOT = Path(__file__).resolve().parent.parent

TAGS = ["what if", "science", "space", "astronomy", "hypothetical",
        "physics", "earth", "what if scenarios", "science explained",
        "space documentary"]
HASHTAGS = ["#WhatIf", "#Space", "#Science"]


def fill_gaps(scenes):
    """A scene without a picture borrows the nearest one that has one."""
    filled = 0
    for s in scenes:
        if s.get("image") and not Path(s["image"]).exists():
            s.pop("image", None)
    for i, s in enumerate(scenes):
        if s.get("image"):
            continue
        for step in range(1, len(scenes)):
            for j in (i - step, i + step):
                if 0 <= j < len(scenes) and scenes[j].get("image"):
                    s["image"] = scenes[j]["image"]
                    s["borrowed"] = True
                    filled += 1
                    break
            if s.get("image"):
                break
    if filled:
        log.info("filled %d gap(s) from neighbours", filled)
    return filled


def assemble(work, episode):
    from pipeline import qc, render, seo, thumbnail, visuals

    work = Path(work)
    scenes = json.loads((work / "scenes.json").read_text(encoding="utf-8"))
    fill_gaps(scenes)

    n = len(scenes)
    overlap = render.XFADE_S * (n - 1) / n if n > 1 else 0.0
    shots = [{"path": s["image"], "duration": s["duration"] + overlap,
              "motion": "static" if s["source"] == "infographic" else "full",
              "card_spec": s.get("card_spec")} for s in scenes]

    narration = work / "narration.wav"
    projected = sum(s["duration"] for s in shots) - render.XFADE_S * (n - 1)
    log.info("narration %.1fs | projected %.1fs | drift %+.1fs",
             render.probe_duration(narration), projected,
             projected - render.probe_duration(narration))

    t0 = time.monotonic()
    clips = render.build_scene_clips(shots, work / "work")
    silent = work / "work" / "silent.mp4"
    render.crossfade(clips, silent, work_dir=work / "work")
    mixed = work / "work" / "mixed.m4a"
    music = ROOT / "assets" / "music" / "echoes-of-time.mp3"
    render.mix_audio(narration, music if music.exists() else None, mixed)
    final = work / "video.mp4"
    render.mux(silent, mixed, final)
    log.info("render took %.0f min", (time.monotonic() - t0) / 60)

    # Thumbnail: the channel's fixed typography over the episode's best frame.
    lines = episode.get("thumbnail_lines") or _headline(episode["title"])
    bg = _thumbnail_background(work, scenes)
    img, boxes = thumbnail.variant_b(bg, lines)
    thumb = work / "thumbnail.png"
    img.save(thumb)
    spread = thumbnail.text_legibility(img, boxes)
    log.info("thumbnail text spread %d", round(spread))

    chapters = _chapters(work, render.probe_duration(final))
    credits_path = work / "credits.json"
    credit_block = ""
    if credits_path.exists():
        credit_block = visuals.description_credits(
            json.loads(credits_path.read_text(encoding="utf-8")))
    credit_block += ("\n- Imagined scenes generated with FLUX.1-schnell "
                     "(Apache-2.0).")
    music_credits = ("Echoes of Time v2 by Kevin MacLeod (incompetech.com)\n"
                     "Licensed under Creative Commons: By Attribution 4.0\n"
                     "https://creativecommons.org/licenses/by/4.0/")
    sources_note = ""
    if (work / "sources.json").exists():
        try:
            sources_note = seo.sources_note(work / "sources.json")
        except Exception as e:
            log.warning("could not summarise sources: %s", e)
    description = seo.build_description(
        episode.get("hook") or episode["title"],
        seo.build_chapters(chapters), credit_block, music_credits, sources_note)
    seo.write_metadata(work / "metadata.txt", episode["title"], description,
                       seo.build_tags(TAGS), HASHTAGS)

    report, problems = qc.check_video(
        final, thumbnail_path=thumb, srt_path=work / "subs.srt",
        expected_min_s=16 * 60, expected_max_s=26 * 60)
    qc.contact_sheet(final, work / "contact_sheet.jpg", every_s=40)
    verdict = qc.write_report(work / "qc.json", report, problems)
    log.info("QC %s (%d problems)", verdict["verdict"], len(problems))

    day = ROOT / "ready" / date.today().isoformat() / episode["slug"]
    day.mkdir(parents=True, exist_ok=True)
    for name in ("video.mp4", "thumbnail.png", "metadata.txt", "subs.srt",
                 "credits.json", "sources.json", "factcheck-log.md",
                 "qc.json", "visual_qc.json", "contact_sheet.jpg", "script.txt"):
        src = work / name
        if src.exists():
            shutil.copy2(src, day / name)
    return day


def _headline(title):
    """Two short lines for the thumbnail, from the episode title."""
    core = title.replace("What If ", "").rstrip("?")
    words = core.split()
    if len(words) <= 2:
        return [core.upper(), "WHAT IF?"]
    mid = (len(words) + 1) // 2
    return [" ".join(words[:mid]).upper(), " ".join(words[mid:]).upper()]


def _thumbnail_background(work, scenes):
    """Prefer a generated frame; they are composed for drama, archive is not."""
    for s in scenes:
        img = s.get("image")
        if img and s["source"] == "generated" and Path(img).exists():
            return img
    for s in scenes:
        if s.get("image") and Path(s["image"]).exists():
            return s["image"]
    raise RuntimeError("no usable frame for the thumbnail")


def _chapters(work, duration, wanted=10):
    """Evenly spaced chapters anchored on real cue times."""
    from pipeline.sceneplan import parse_srt
    cues = parse_srt(work / "subs.srt")
    if not cues:
        return [(0, "Start")]
    step = duration / wanted
    out, used = [], set()
    for i in range(wanted):
        target = i * step
        cue = min(cues, key=lambda c: abs(c[0] - target))
        if cue[0] in used:
            continue
        used.add(cue[0])
        label = cue[2].strip().rstrip(".,")[:48] or "Continued"
        out.append((0 if i == 0 else cue[0], label))
    return out
