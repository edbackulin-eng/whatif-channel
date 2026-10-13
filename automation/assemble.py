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


# No frame may appear twice inside this many scenes. Borrowing from the
# immediate neighbour produced "Roche Limit" four scenes running - over twenty
# seconds of one motionless card.
REPEAT_WINDOW = 10


def fill_gaps(scenes):
    """Give every scene a picture, without repeating one inside the window.

    A gap is filled from the furthest usable frame rather than the nearest, so a
    borrowed frame lands far from its original. Scenes that still cannot be
    filled without a repeat are reported, not papered over - the caller should
    generate a new frame for those.
    """
    for s in scenes:
        if s.get("image") and not Path(s["image"]).exists():
            s.pop("image", None)

    filled, unresolved = 0, []
    for i, s in enumerate(scenes):
        if s.get("image"):
            continue
        # What is already on screen near this scene.
        lo, hi = max(0, i - REPEAT_WINDOW), min(len(scenes), i + REPEAT_WINDOW + 1)
        nearby = {scenes[j].get("image") for j in range(lo, hi) if scenes[j].get("image")}
        candidate = None
        # Search outward from the far edge of the window inward, so the frame we
        # borrow is one the viewer saw longest ago.
        for step in range(len(scenes), 0, -1):
            for j in (i - step, i + step):
                if 0 <= j < len(scenes):
                    img = scenes[j].get("image")
                    if img and img not in nearby:
                        candidate = img
                        break
            if candidate:
                break
        if candidate:
            s["image"] = candidate
            s["borrowed"] = True
            filled += 1
        else:
            unresolved.append(s["index"])
    if filled:
        log.info("filled %d gap(s), none repeating inside %d scenes",
                 filled, REPEAT_WINDOW)
    # Absolute last resort. An empty scene renders as nothing at all, which is
    # worse than a repeat; but this only runs after generation has already been
    # given its chance, so reaching it means something upstream failed.
    if unresolved:
        log.warning("%d scene(s) need a frame that generation did not supply: %s",
                    len(unresolved), unresolved[:10])
        pool = [x.get("image") for x in scenes if x.get("image")]
        for s in scenes:
            if s.get("image") or not pool:
                continue
            i = s["index"]
            lo, hi = max(0, i - REPEAT_WINDOW), min(len(scenes), i + REPEAT_WINDOW + 1)
            nearby = {scenes[j].get("image") for j in range(lo, hi)
                      if 0 <= j < len(scenes) and scenes[j].get("image")}
            choice = next((p for p in pool if p not in nearby), pool[0])
            s["image"] = choice
            s["borrowed"] = True
            s["last_resort"] = True
            filled += 1
    return filled


def repeat_report(scenes, window=REPEAT_WINDOW):
    """Frames that appear more than once inside `window` scenes."""
    hits = []
    for i, s in enumerate(scenes):
        img = s.get("image")
        if not img:
            continue
        for j in range(i + 1, min(len(scenes), i + window + 1)):
            if scenes[j].get("image") == img:
                hits.append((s["index"], scenes[j]["index"]))
    return hits



def _music_bed(work, narration_s):
    """Build the mood-matched bed for this episode. Returns (path, credits).

    Falls back to a single track, and then to no music at all, rather than
    failing a render: a video with a flat bed is worth shipping, a video that
    did not build is not.
    """
    from pipeline import music as music_mod

    try:
        library = music_mod.load_library()
    except Exception as e:                                       # noqa: BLE001
        log.warning("no music library (%s); rendering without a bed", e)
        return None, []

    script = work / "script.txt"
    text = script.read_text(encoding="utf-8") if script.exists() else ""
    try:
        plan = music_mod.plan(text, narration_s, tracks=library,
                              use_llm=bool(text))
        bed = music_mod.build_bed(plan, work / "work" / "bed.wav")
        return bed, music_mod.attribution(plan)
    except Exception as e:                                       # noqa: BLE001
        log.warning("could not build the mood bed (%s); using one track", e)
        first = library[0]
        return first["path"], music_mod.attribution(
            [{"mood": "n/a", "track": first}])


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
    bed, bed_credits = _music_bed(work, render.probe_duration(narration))
    render.mix_audio(narration, bed, mixed)
    final = work / "video.mp4"
    render.mux(silent, mixed, final)
    log.info("render took %.0f min", (time.monotonic() - t0) / 60)

    # An approved thumbnail is never regenerated. Episode one's was chosen by
    # hand from three candidates; rebuilding it would quietly discard that
    # choice on every re-render.
    thumb = work / "thumbnail.png"
    if thumb.exists() and episode.get("approved", {}).get("thumbnail"):
        log.info("using the approved thumbnail as-is (%s)",
                 episode["approved"]["thumbnail"])
    else:
        lines = episode.get("thumbnail_lines") or _headline(episode["title"])
        bg = _thumbnail_background(work, scenes)
        img, boxes = thumbnail.variant_b(bg, lines)
        img.save(thumb)
        log.info("thumbnail text spread %d",
                 round(thumbnail.text_legibility(img, boxes)))

    chapters = _chapters(work, render.probe_duration(final))
    credits_path = work / "credits.json"
    credit_block = ""
    if credits_path.exists():
        credit_block = visuals.description_credits(
            json.loads(credits_path.read_text(encoding="utf-8")))
    credit_block += ("\n- Imagined scenes generated with FLUX.1-schnell "
                     "(Apache-2.0).")
    # Every track the bed actually used, not a single hard-coded line: the
    # bed is assembled by mood now, so which tracks appear varies by
    # episode and CC BY requires each of them to be named.
    music_credits = "\n".join(
        bed_credits or ["(no music in this episode)"])
    if bed_credits:
        music_credits += (
            "\nLicensed under Creative Commons: By Attribution 4.0"
            "\nhttps://creativecommons.org/licenses/by/4.0/")
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
