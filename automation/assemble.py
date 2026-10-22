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
        thumbnail.save(best_thumbnail(work, scenes, episode), thumb)

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

    # A black or flat stretch that got past every frame check is covered by the
    # neighbouring shot held a little longer, and the video is checked again.
    # Only what is still there afterwards holds the upload.
    from pipeline import autofix
    if qc.find_black(final):
        fixed = work / "video_fixed.mp4"
        fix = autofix.repair(final, fixed, work / "autofix")
        autofix.write(fix, work / "autofix.json")
        if fix["covered"] and fixed.exists() and                 abs(fix["duration_out"] - fix["duration_in"]) < 0.1:
            shutil.move(str(fixed), str(final))
            log.info("covered %d black stretch(es); %d left", len(fix["covered"]), len(fix["left"]))

    report, problems = qc.check_video(
        final, thumbnail_path=thumb, srt_path=work / "subs.srt",
        expected_min_s=16 * 60, expected_max_s=26 * 60)
    # The border check reads what the grader actually did (which scenes were set
    # on a blurred plate), not the pixels of the finished video: guessing from
    # pixels flagged 10 of 16 frames of episode 002 that were filling the screen
    # perfectly well, and the run was held for a defect it did not have.
    plated = qc.plated_frames(scenes)
    report["plated_frames"] = len(plated)
    if scenes and len(plated) / len(scenes) > qc.PLATED_FAIL_FRACTION:
        problems.append(f"{len(plated)} of {len(scenes)} scenes sit on a blurred plate "
                        f"instead of filling the frame")
    vq = work / "visual_qc.json"
    if vq.exists():
        left = json.loads(vq.read_text(encoding="utf-8")).get("unchecked", 0)
        report["frames_uninspected"] = left
        if left:
            problems.append(f"{left} frame(s) could not be inspected by visual QC "
                            f"after every retry")
    qc.contact_sheet(final, work / "contact_sheet.jpg", every_s=40)
    verdict = qc.write_report(work / "qc.json", report, problems)
    log.info("QC %s (%d problems)", verdict["verdict"], len(problems))

    day = ROOT / "ready" / date.today().isoformat() / episode["slug"]
    day.mkdir(parents=True, exist_ok=True)
    for name in ("video.mp4", "thumbnail.png", "metadata.txt", "subs.srt",
                 "credits.json", "sources.json", "factcheck-log.md",
                 "qc.json", "visual_qc.json", "contact_sheet.jpg", "script.txt",
                 "autofix.json", "thumbnail_report.json"):
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


# text_legibility measured at 336x189. Under this the words smear into their own
# outline on a browse card. A floor, not a target: the 24 real candidates of the
# first run measured 249-254 with this layout, so it only catches a composite
# that has gone wrong rather than ranking the good ones.
MIN_LEGIBILITY = 150
# Defects that disqualify a candidate even when nothing better is left. A melted
# face or a six-fingered hand on the one image every viewer sees first is worse
# than a dull thumbnail.
FATAL = ("face", "hands", "anatomy", "text", "empty", "blend", "card")


def best_thumbnail(work, scenes, episode, out_dir=None):
    """The episode's own thumbnail, from its own generations.

    4-6 FLUX candidates of a face against the event (automation/frames.py put
    them on the end of the scene batch), each judged by Gemini vision for faces,
    hands, lettering and blends; the defective are dropped, and the best survivor
    is composed with the episode's one to three words.

    Two layouts, chosen by the brief: one face against the event, or a split with
    a label over each half when the episode weighs two things against each other.

    Falls back to the old behaviour - a still lifted out of the episode - when
    there are no candidates at all, because a plain thumbnail ships and a build
    that stopped for one does not.

    No retry here. When nothing shows the episode's own subject the build says
    so and uses the best picture it has: a second batch would be a second GPU
    kernel in the middle of a render that is already holding one, and the
    thumbnail can be replaced afterwards with tools/restyle_thumbnail.py, which
    does retry once.
    """
    from pipeline import thumbnail, thumbplan, visualqc
    work = Path(work)
    out_dir = Path(out_dir or work / "thumb_candidates")
    out_dir.mkdir(parents=True, exist_ok=True)

    brief, cands = {}, []
    sources = work / "thumbnail_sources.json"
    if sources.exists():
        data = json.loads(sources.read_text(encoding="utf-8"))
        brief = data.get("brief") or {}
        cands = [c for c in data.get("candidates") or []
                 if c.get("image") and Path(c["image"]).exists()]
    if not brief:
        brief = thumbplan.brief(episode, work, use_llm=False)
    if not cands:
        log.warning("no generated thumbnail candidate for this episode; falling back "
                    "to an episode frame")
        return _frame_thumbnail(work, scenes, episode)

    try:
        verdicts = visualqc.judge_thumbnails([c["image"] for c in cands],
                                             topic=brief.get("topic") or episode.get("title"))
    except Exception as e:                                       # noqa: BLE001
        log.warning("thumbnail judge unavailable (%s); every candidate counts as "
                    "unchecked", e)
        verdicts = {}
    for c in cands:
        c["verdict"] = verdicts.get(Path(c["image"])) or dict(UNJUDGED)

    words = brief.get("words") or []
    if brief.get("comparison") and any(c.get("role") in ("left", "right") for c in cands):
        img, report = _compose_split(cands, brief, words, out_dir)
    else:
        img, report = _compose_single(cands, words, out_dir)
    (work / "thumbnail_report.json").write_text(
        json.dumps({"brief": brief, "min_legibility": MIN_LEGIBILITY,
                    "candidates": report}, indent=1, ensure_ascii=False),
        encoding="utf-8")
    return img


UNJUDGED = {"ok": False, "defect": "unchecked", "note": "no verdict",
            "score": 0.0, "emotion": 0.0, "corner": True,
            "face_side": "", "event_side": "", "matches": True, "match_note": ""}


def _rank(c):
    """How good a surviving candidate is.

    Whether the picture is actually this episode's subject comes first: a clean,
    dramatic face in front of the wrong event is the wrong thumbnail however
    well it is made. Then the judge's score, the emotion it reads, and a clear
    bottom-right corner.
    """
    v = c["verdict"]
    return (bool(v.get("matches", True)), v.get("score", 0), v.get("emotion", 0),
            bool(v.get("corner", True)))


def _entry(c, legibility=None, used=False):
    v = c["verdict"]
    return {"source": Path(c["image"]).name, "role": c.get("role", "single"),
            "ok": v.get("ok", False), "defect": v.get("defect"),
            "note": v.get("note", ""), "score": v.get("score", 0),
            "emotion": v.get("emotion", 0), "corner": v.get("corner", True),
            "matches": v.get("matches", True), "match_note": v.get("match_note", ""),
            "face_side": v.get("face_side", ""), "event_side": v.get("event_side", ""),
            "legibility": None if legibility is None else round(legibility),
            "used": used}


def _compose_single(cands, words, out_dir):
    """One face against the event: compose every candidate, keep the best that the
    judge passed and whose words still read at browse size."""
    from pipeline import thumbnail
    report, ranked, composed = [], [], {}
    for k, c in enumerate(cands):
        img, boxes = thumbnail.compose(c["image"], words,
                                       side=c["verdict"].get("event_side") or None)
        img.save(out_dir / f"candidate_{k}.png")
        img.resize((thumbnail.BROWSE_W, thumbnail.BROWSE_H)).save(
            out_dir / f"candidate_{k}_browse.png")
        legible = thumbnail.text_legibility(img, boxes)
        composed[k] = (img, boxes, legible)
        if not thumbnail.safe_corner_clear(boxes):
            # A layout bug, not a picture problem: the words must never reach the
            # duration pill. Reported rather than silently shipped.
            log.error("candidate %d draws into YouTube's corner; layout is wrong", k)
        if c["verdict"].get("ok") and legible >= MIN_LEGIBILITY:
            ranked.append((_rank(c), k))
        report.append(_entry(c, legible))
    if ranked:
        _, k = max(ranked, key=lambda r: r[0])
        img, _, legible = composed[k]
        v = cands[k]["verdict"]
        log.info("thumbnail: candidate %d of %d (matches %s, score %.0f, emotion %.0f, "
                 "legibility %.0f); %d rejected", k, len(cands),
                 v.get("matches", True), v.get("score", 0), v.get("emotion", 0),
                 legible, len(cands) - len(ranked))
        if not v.get("matches", True):
            log.warning("no candidate showed the episode's own subject; the best "
                        "available is off-topic (%s)", v.get("match_note", ""))
        report[k]["used"] = True
        return img, report
    k = _least_bad(cands, composed)
    log.warning("no thumbnail candidate passed the judge; using candidate %d (%s)",
                k, cands[k]["verdict"].get("defect"))
    report[k]["used"] = True
    return composed[k][0], report


def _least_bad(cands, composed):
    """Nothing passed. Prefer a candidate the judge did not reject outright, and
    among those the one whose words read best."""
    usable = [k for k, c in enumerate(cands)
              if c["verdict"].get("defect") not in FATAL]
    return max(usable or list(range(len(cands))), key=lambda k: composed[k][2])


def _compose_split(cands, brief, words, out_dir):
    """A comparison: the best surviving face on each side, labelled, side by side."""
    from pipeline import thumbnail
    report = []
    picked = {}
    for side in ("left", "right"):
        side_cands = [c for c in cands if c.get("role") == side]
        passed = [c for c in side_cands if c["verdict"].get("ok")]
        pool = passed or [c for c in side_cands
                          if c["verdict"].get("defect") not in FATAL] or side_cands
        if pool:
            picked[side] = max(pool, key=_rank)
    if len(picked) < 2:
        log.warning("a comparison thumbnail needs a usable face on both sides and has "
                    "%d; composing a single instead", len(picked))
        return _compose_single(cands, words, out_dir)
    labels = [brief["comparison"][side]["label"] for side in ("left", "right")]
    img, boxes = thumbnail.compose_split(picked["left"]["image"],
                                         picked["right"]["image"], labels, words)
    img.save(out_dir / "candidate_split.png")
    img.resize((thumbnail.BROWSE_W, thumbnail.BROWSE_H)).save(
        out_dir / "candidate_split_browse.png")
    legible = thumbnail.text_legibility(img, boxes)
    if not thumbnail.safe_corner_clear(boxes):
        log.error("the split layout draws into YouTube's corner; layout is wrong")
    log.info("thumbnail: split %s / %s, legibility %.0f", labels[0], labels[1], legible)
    for c in cands:
        report.append(_entry(c, used=c in picked.values()))
    report.append({"source": "candidate_split.png", "role": "split",
                   "labels": labels, "legibility": round(legible), "used": True})
    if legible < MIN_LEGIBILITY:
        log.warning("the split labels measure %.0f at browse size, under %d",
                    legible, MIN_LEGIBILITY)
    return img, report


def _frame_thumbnail(work, scenes, episode):
    """The old thumbnail: a still from the episode with the title over it.

    Only reached when no candidate was generated at all - no GPU, or an
    archive-only build.
    """
    from pipeline import thumbnail
    lines = episode.get("thumbnail_lines") or _headline(episode["title"])
    pool = _thumb_candidates(work, scenes)
    source = pool[0] if pool else _thumbnail_background(work, scenes)
    return thumbnail.variant_b(source, lines)[0]


THUMB_CANDIDATES = 6


def _thumb_candidates(work, scenes, n=THUMB_CANDIDATES):
    """Up to n stills spread across the episode, generated first: frames visual QC
    flagged and frames with nothing in them are left out."""
    from pipeline import visualqc
    flagged = set()
    vq = Path(work) / "visual_qc.json"
    if vq.exists():
        flagged = {d["file"] for d in json.loads(vq.read_text(encoding="utf-8")).get("details", [])}
    pool = [s["image"] for s in scenes
            if s.get("image") and Path(s["image"]).exists() and s.get("source") == "generated"
            and Path(s["image"]).name not in flagged and not visualqc.is_empty(s["image"])]
    if len(pool) < n:
        pool += [s["image"] for s in scenes
                 if s.get("image") and Path(s["image"]).exists() and s.get("source") == "archive"
                 and s["image"] not in pool and Path(s["image"]).name not in flagged]
    if not pool:
        return []
    step = max(1, len(pool) // n)
    return list(dict.fromkeys(pool[::step]))[:n]


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


def _title_ok(title, span_text):
    """2-5 words, short, no trailing punctuation, and not a slice of the narration."""
    t = (title or "").strip().strip('"').strip()
    n = len(t.split())
    if not (2 <= n <= 5) or len(t) > 40 or t[-1:] in ".,;:!?":
        return False
    return t.lower() not in span_text.lower()


CHAPTER_PROMPT = (
    "Write a chapter title for each stretch of narration below, from a science video "
    "about the question in its title. Rules: 2 to 5 words, Title Case, no punctuation "
    "at the end, specific to that stretch, and never reveal the final answer. "
    'Return JSON only: {"titles": ["...", "..."]} with exactly {n} titles, in order.')


def _chapters(work, duration, wanted=10):
    """Chapters anchored on real cue times, each with a short written title.

    The anchors are evenly spaced cue times. The titles used to be the first 48
    characters of the sentence at each anchor ("you are standing on the equator at
    noon. The sky"), which are not titles. One model call now writes all of them
    from the stretch of narration each chapter covers, and a title that comes back
    too long, too short or lifted from the narration is replaced from the text.
    """
    from pipeline.sceneplan import parse_srt
    cues = parse_srt(work / "subs.srt")
    if not cues:
        return [(0, "Start")]
    step = duration / wanted
    anchors, used = [], set()
    for i in range(wanted):
        cue = min(cues, key=lambda c: abs(c[0] - i * step))
        if cue[0] in used:
            continue
        used.add(cue[0])
        anchors.append(0 if i == 0 else cue[0])
    spans = []
    for k, start in enumerate(anchors):
        end = anchors[k + 1] if k + 1 < len(anchors) else duration + 1
        spans.append(" ".join(c[2].strip() for c in cues if start <= c[0] < end))

    titles = [None] * len(anchors)
    try:
        from core import llm
        listing = chr(10).join(f"{k}: {t[:700]}" for k, t in enumerate(spans))
        answer = llm.complete_json(
            CHAPTER_PROMPT.replace("{n}", str(len(spans))) + chr(10) + chr(10) + listing,
            max_tokens=1200, temperature=0.4, model=llm.GEMINI_BULK_MODEL)
        got = answer.get("titles", []) if isinstance(answer, dict) else answer
        if isinstance(got, list) and len(got) == len(spans):
            titles = [str(t) for t in got]
    except Exception as e:                                       # noqa: BLE001
        log.warning("chapter titles from the model failed (%s); writing them from the text", e)
    # When no model can write a title the chapter is "Part N", which says nothing
    # false. A first version built titles from the longest words of each span and
    # produced "Kilometers Everything Kilopascals", which is worse than a number.
    out = []
    for k, (start, text, t) in enumerate(zip(anchors, spans, titles)):
        out.append((start, t.strip().strip('"') if t and _title_ok(t, text)
                    else ("Introduction" if k == 0 else f"Part {k + 1}")))
    return out
