"""KT3: assemble the finished video and the upload package.

Run after the GPU batch has been pulled into kaggle/results/<slug>/images.
"""
import json
import shutil
import sys
import time
from pathlib import Path

from pipeline import qc, render, seo, thumbnail, visuals

ROOT = Path(__file__).resolve().parent
KT3 = ROOT / "output" / "kt3"
WORK = KT3 / "work"
TITLE = "What If the Moon Fell to Earth?"
THUMB_LINES = ["THE MOON", "IS FALLING"]

# Chapters are located in the finished narration rather than written by hand.
# Guessed timestamps drifted badly: the first set ran to 25:30 on a 19:45 video,
# which YouTube would simply refuse to render.
CHAPTER_ANCHORS = [
    ("The morning it starts", "imagine at 9"),
    ("Why this cannot actually happen", "let's be honest about one thing"),
    ("Week one: nothing happens", "nothing happens"),
    ("The ocean notices first", "tides are a tug of war"),
    ("Day nineteen", "half its original distance"),
    ("We lose the satellites", "sweeps through the region"),
    ("The planet starts flexing", "does not only move water"),
    ("The last week", "genuinely close"),
    ("It never reaches the ground", "does not hit the earth"),
    ("Earth gets a ring", "does not fall straight down"),
    ("The rain that lasts millennia", "ring is not permanent"),
    ("A million years later", "ring thins out"),
]


def locate_chapters(srt_path, duration_s):
    """Find each chapter's real start time in the transcript."""
    from pipeline.sceneplan import parse_srt
    cues = parse_srt(srt_path)
    found, previous = [], -1.0
    for label, needle in CHAPTER_ANCHORS:
        hit = next((t for t, _, text in cues
                    if needle in text.lower() and t > previous), None)
        if hit is None or hit >= duration_s:
            log_missing = f"chapter anchor not found: {label!r}"
            print(f"  ! {log_missing}")
            continue
        found.append((hit, label))
        previous = hit
    return found

TAGS = ["what if", "what if the moon fell", "moon", "space", "science",
        "astronomy", "hypothetical", "roche limit", "tidal forces",
        "earth", "nasa", "space documentary", "science explained",
        "what if scenarios", "physics"]
HASHTAGS = ["#WhatIf", "#Space", "#Science"]


def attach_generated(scenes, images_dir, mapping_path, attach_scenes=True):
    """Match the GPU batch back onto the scenes it was generated for.

    `attach_scenes=False` pulls out only the style probes and thumbnail
    backgrounds. That matters after a re-plan: the original mapping holds the OLD
    scene numbering, and applying it to a renumbered plan would silently paste
    each frame onto the wrong moment in the narration. Scene frames are instead
    carried across by tools/remap_generated.py, which matches on the narration
    text rather than on an index that no longer means the same thing.
    """
    mapping = json.loads(Path(mapping_path).read_text(encoding="utf-8"))
    images_dir = Path(images_dir)
    style_frames, thumb_frames, attached, missing = [], [], 0, 0
    by_index = {s["index"]: s for s in scenes}
    for i, entry in enumerate(mapping):
        img = images_dir / f"{i:03d}.png"
        if not img.exists():
            if entry["kind"] == "scene":
                missing += 1
            continue
        if entry["kind"] == "style":
            style_frames.append(img)
        elif entry["kind"] == "thumb":
            thumb_frames.append(img)
        elif attach_scenes:
            scene = by_index.get(entry["index"])
            if scene is not None:
                scene["image"] = str(img.resolve())
                attached += 1
    return style_frames, thumb_frames, attached, missing


def fill_gaps(scenes):
    """Any scene still without a picture borrows the nearest one that has one.

    A gap would otherwise become a black frame, which QC rejects and a viewer
    notices immediately.
    """
    filled = 0
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
    return filled


def check_freshness():
    """Refuse to build a video whose voice is older than the words.

    This exact mistake shipped once: the fact-check corrections were applied to
    script.txt after narration.wav had already been rendered, so the finished
    video narrated claims that had already been found wrong. The fact-check
    verifies the script; nothing verified that the audio matched it.
    """
    script = KT3 / "script.txt"
    narration = KT3 / "narration.wav"
    subs = KT3 / "subs.srt"
    problems = []
    if narration.stat().st_mtime < script.stat().st_mtime:
        problems.append("narration.wav is older than script.txt - re-run kt3_narrate.py")
    if subs.exists() and subs.stat().st_mtime < narration.stat().st_mtime:
        problems.append("subs.srt is older than narration.wav - re-run the transcription")
    if problems:
        for p in problems:
            print(f"STALE: {p}")
        raise SystemExit("refusing to build from stale inputs")
    print("freshness: script -> narration -> subtitles all in order")


def main():
    check_freshness()
    batch = ROOT / "kaggle" / "results" / "kt3_batch" / "images"
    scenes = json.loads((KT3 / "scenes.json").read_text(encoding="utf-8"))

    # Only the style probes and thumbnail backgrounds come from the first batch;
    # its scene numbering is stale after the re-plan.
    style_frames, thumb_frames, attached, missing = attach_generated(
        scenes, batch, KT3 / "flux_mapping.json", attach_scenes=False)
    carried = sum(1 for s in scenes
                  if s["source"] == "generated" and s.get("image"))
    print(f"frames carried by remapper: {carried}")
    # Frames regenerated after a script correction live in their own batch and
    # overwrite whatever the first pass attached to those scenes.
    for name, mapping_name in (("kt3_topup", "topup_mapping.json"),
                               ("kt3_reshoot", "reshoot_mapping.json")):
        extra_dir = ROOT / "kaggle" / "results" / name / "images"
        extra_map = KT3 / mapping_name
        if extra_dir.exists() and extra_map.exists():
            _, _, added, miss = attach_generated(scenes, extra_dir, extra_map)
            print(f"{name:12s} frames attached: {added} (missing {miss})")
    print(f"generated frames attached : {attached}")
    print(f"generated frames missing  : {missing}")
    print(f"style probes              : {len(style_frames)}")
    print(f"thumbnail backgrounds     : {len(thumb_frames)}")
    borrowed = fill_gaps(scenes)
    if borrowed:
        print(f"gaps filled from neighbours: {borrowed}")
    (KT3 / "scenes.json").write_text(
        json.dumps(scenes, indent=2, ensure_ascii=False), encoding="utf-8")

    # Every crossfade overlaps two clips, so the finished video is shorter than
    # the sum of its scenes by xfade x (N-1). Left uncompensated on a 216-scene
    # cut that is 107 seconds, and since the mux runs -shortest it silently
    # truncates the narration - the whole ending disappears. Each scene is
    # lengthened by its share of the overlap so the picture matches the audio.
    n = len(scenes)
    overlap_share = render.XFADE_S * (n - 1) / n if n > 1 else 0.0
    shots = [{"path": s["image"], "duration": s["duration"] + overlap_share,
              "motion": "static" if s["source"] == "infographic" else "full",
              "card_spec": s.get("card_spec")}
             for s in scenes]
    narration_s = render.probe_duration(KT3 / "narration.wav")
    projected = sum(s["duration"] for s in shots) - render.XFADE_S * (n - 1)
    print(f"narration {narration_s:.1f}s | projected video {projected:.1f}s "
          f"| drift {projected - narration_s:+.1f}s")
    WORK.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()
    clips = render.build_scene_clips(shots, WORK)
    print(f"clips: {len(clips)} in {(time.monotonic() - t0) / 60:.1f} min")

    silent = WORK / "silent.mp4"
    t0 = time.monotonic()
    render.crossfade(clips, silent, work_dir=WORK)
    print(f"crossfade in {(time.monotonic() - t0) / 60:.1f} min")

    mixed = WORK / "mixed.m4a"
    music = ROOT / "assets" / "music" / "echoes-of-time.mp3"
    render.mix_audio(KT3 / "narration.wav", music if music.exists() else None, mixed)

    final = KT3 / "video.mp4"
    render.mux(silent, mixed, final)

    # Thumbnails: KT2 variant B typography over the new generated backgrounds.
    thumbs = []
    for i, bg in enumerate(thumb_frames):
        img, boxes = thumbnail.variant_b(bg, THUMB_LINES)
        p = KT3 / f"thumbnail_{i + 1}.png"
        img.save(p)
        img.resize((thumbnail.BROWSE_W, thumbnail.BROWSE_H)).save(
            KT3 / f"thumbnail_{i + 1}_browse.png")
        thumbs.append({"path": str(p),
                       "text_spread": round(thumbnail.text_legibility(img, boxes))})
    print("thumbnails:", [(t["path"].split("\\")[-1], t["text_spread"]) for t in thumbs])

    # Metadata
    chapters = locate_chapters(KT3 / "subs.srt", render.probe_duration(final))
    print(f"chapters located: {len(chapters)}/{len(CHAPTER_ANCHORS)}")
    credits = json.loads((KT3 / "credits.json").read_text(encoding="utf-8"))
    credit_block = visuals.description_credits(credits)
    credit_block += ("\n- Imagined scenes generated with FLUX.1-schnell "
                     "(Apache-2.0), styled to match the archive material.")
    music_credits = ("Echoes of Time v2 by Kevin MacLeod (incompetech.com)\n"
                     "Licensed under Creative Commons: By Attribution 4.0\n"
                     "https://creativecommons.org/licenses/by/4.0/")
    hook = ("What if the Moon stopped holding its orbit and began to fall? "
            "The real physics says it never reaches the ground - and what "
            "happens instead lasts a million years.")
    description = seo.build_description(
        hook, seo.build_chapters(chapters), credit_block, music_credits,
        seo.sources_note(KT3 / "sources.json"))
    seo.write_metadata(KT3 / "metadata.txt", TITLE, description,
                       seo.build_tags(TAGS), HASHTAGS)

    # QC
    report, problems = qc.check_video(
        final, thumbnail_path=thumbs[0]["path"] if thumbs else None,
        srt_path=KT3 / "subs.srt",
        expected_min_s=18 * 60, expected_max_s=25 * 60)
    qc.contact_sheet(final, KT3 / "contact_sheet.jpg", every_s=40)
    verdict = qc.write_report(KT3 / "qc.json", report, problems)
    print("\nQC:", verdict["verdict"])
    for p in problems:
        print("  -", p)

    # Package
    day = ROOT / "ready" / time.strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    for src, dst in [
        (final, "video.mp4"),
        (thumbs[0]["path"] if thumbs else None, "thumbnail.png"),
        (KT3 / "metadata.txt", "metadata.txt"),
        (KT3 / "subs.srt", "subs.srt"),
        (KT3 / "credits.json", "credits.json"),
        (KT3 / "sources.json", "sources.json"),
        (KT3 / "factcheck-log.md", "factcheck-log.md"),
        (KT3 / "qc.json", "qc.json"),
        (KT3 / "contact_sheet.jpg", "contact_sheet.jpg"),
        (KT3 / "script.txt", "script.txt"),
    ]:
        if src and Path(src).exists():
            shutil.copy2(src, day / dst)
    for i in range(len(thumbs)):
        shutil.copy2(KT3 / f"thumbnail_{i + 1}.png", day / f"thumbnail_option_{i + 1}.png")
    print(f"\npackaged -> {day}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
