"""The stages of a build, in order, each skippable when its output already exists.

Written so a re-run after a failure resumes rather than starting over: on a free
runner with a 6-hour ceiling, redoing a 20-minute narration because the GPU
queue was slow is time the build cannot spare.
"""
import json
import shutil
import time
from pathlib import Path

from core.logger import get_logger

log = get_logger("stages")
ROOT = Path(__file__).resolve().parent.parent


def _cfg():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def narrate(work):
    """Kokoro narration, unless an approved one was carried in."""
    out = work / "narration.wav"
    if out.exists():
        log.info("narration already present, reusing")
        return out
    import soundfile as sf
    from kokoro_onnx import Kokoro
    from core import voice as voice_mod

    cfg = _cfg()
    script = (work / "script.txt").read_text(encoding="utf-8")
    lines = [l for l in script.splitlines()
             if not (l.strip() and l.strip() == l.strip().upper()
                     and len(l.strip()) < 60 and l.strip().endswith("."))]
    kokoro = Kokoro(str(ROOT / "assets" / "models" / "kokoro-v1.0.onnx"),
                    str(ROOT / "assets" / "models" / "voices-v1.0.bin"))
    audio, rate = voice_mod.synthesize(kokoro, "\n".join(lines), cfg["voice"])
    sf.write(out, voice_mod.peak_normalize(audio), rate)
    log.info("narration: %.1f min", len(audio) / rate / 60)
    return out


def subtitles(work):
    out = work / "subs.srt"
    if out.exists():
        log.info("subtitles already present, reusing")
        return out
    from pipeline import subtitles as subs
    subs.transcribe(work / "narration.wav", out)
    return out


def plan(work):
    out = work / "scenes.json"
    if out.exists():
        log.info("scene plan already present, reusing")
        return json.loads(out.read_text(encoding="utf-8"))
    from pipeline import sceneplan
    scenes = sceneplan.group_scenes(sceneplan.parse_srt(work / "subs.srt"))
    scenes = sceneplan.plan(scenes)
    sceneplan.write(scenes, out)
    return scenes


def visual_check(work, scenes):
    """Inspect every frame before the render. Defects are regenerated once."""
    cfg = _cfg()
    if not cfg.get("visual_qc", True):
        log.info("visual QC disabled in config")
        return scenes
    from pipeline import visualqc

    paths, kinds = [], {}
    for s in scenes:
        img = s.get("image")
        if not img or not Path(img).exists():
            continue
        paths.append(img)
        kinds[img] = "card" if s["source"] == "infographic" else "photo"
    if not paths:
        return scenes

    verdicts = visualqc.inspect(paths, kinds=kinds)
    report = visualqc.write_report(verdicts, work / "visual_qc.json")
    log.info("visual QC: %d frames, %d flagged", report["frames"], report["flagged"])

    failed = {str(p) for p, v in verdicts.items() if not v["ok"]}
    if not failed:
        return scenes

    # One regeneration attempt, then fall back to a neighbouring frame rather
    # than stalling the build arguing with the image model. A GPU that is
    # unreachable must not sink a build that already has usable frames: the
    # first cloud run died here, twenty minutes in, because submission failed.
    from automation import frames
    try:
        retried = frames.regenerate(work, [s for s in scenes
                                           if s.get("image") in failed])
    except Exception as e:
        log.warning("could not regenerate flagged frames (%s); "
                    "replacing them from neighbours instead", e)
        retried = set()
    still_bad = [s for s in scenes
                 if s.get("image") in failed and s["index"] not in retried]
    for s in still_bad:
        s.pop("image", None)
        s["visual_qc_replaced"] = True
    if still_bad:
        log.warning("%d frame(s) replaced from neighbours after two attempts",
                    len(still_bad))
    return scenes


def run(episode, work):
    """The whole build. Each stage is a no-op when its output already exists."""
    from automation import episode_assets
    from automation import frames as frame_stage

    # Approved material first: whatever this restores, the stages below skip.
    restored = episode_assets.fetch(episode, work)

    narrate(work)
    subtitles(work)
    scenes = plan(work)
    if restored:
        scenes, bound = episode_assets.bind_frames(work, scenes)
        if bound == len(scenes):
            log.info("every frame came from the dataset; no generation needed")
    scenes = frame_stage.ensure(work, scenes)
    scenes = visual_check(work, scenes)
    (work / "scenes.json").write_text(
        json.dumps(scenes, indent=2, ensure_ascii=False), encoding="utf-8")

    from automation.assemble import assemble
    package = assemble(work, episode)
    log.info("packaged -> %s", package)
    return package
