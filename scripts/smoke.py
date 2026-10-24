"""Smoke test for What If: the chain on ten seconds of a real script, in minutes.

    python -X utf8 scripts/smoke.py

Run by .github/workflows/smoke.yml on every push to dev; only a passing run
moves the code to main, where the builds run it.

  1. every module of pipeline/ and automation/ imports;
  2. a real script is cut into subtitle cues and grouped into scenes the way
     a build does it (narration timing stands in for the voice, which needs
     the GPU);
  3. both thumbnail layouts are composed and measured: the words fit, they
     still read at browse size, and nothing enters YouTube's duration corner;
  4. placeholder stills are graded, moved, crossfaded and mixed with a music
     bed from the library over a stand-in narration, then muxed;
  5. the result is checked by the channel's own QC: length, resolution,
     loudness, black stretches, silence.
"""
import importlib
import json
import pkgutil
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
W = ROOT / "work" / "smoke"
SECONDS = 10
failures = []


def check(name, ok, detail=""):
    print(f"[{'ok' if ok else 'FAIL'}] {name} {detail}")
    if not ok:
        failures.append(f"{name}: {detail}")


def shared_gpu():
    """The shared GPU lock reads every channel's kernels the same way."""
    sys.path.insert(0, str(ROOT / "kaggle"))
    import gpu_shared
    import push  # noqa: F401  - push.py must still import with the lock in it
    ok = (gpu_shared.channel_of("u/whatif-main") == "whatif"
          and gpu_shared.channel_of("u/closedtabs-stills-a") == "closedtabs"
          and gpu_shared.channel_of("u/prehistoric-recon") is None
          and gpu_shared.channel_of("u/other") is None
          and gpu_shared.CHANNELS["whatif"] == 0)
    check("shared GPU lock", ok)


def imports():
    for pkg in ("pipeline", "automation"):
        for m in pkgutil.iter_modules([str(ROOT / pkg)]):
            try:
                importlib.import_module(f"{pkg}.{m.name}")
            except Exception as e:                               # noqa: BLE001
                check(f"import {pkg}.{m.name}", False, repr(e)[:200])
    check("imports", not failures)


def srt_from_script():
    script = sorted(ROOT.glob("queue/*/script.txt"))[-1]
    text = re.sub(r"\[[^\]]*\]", " ", script.read_text(encoding="utf-8"))
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) > 3][:12]
    t, blocks = 0.0, []
    for i, s in enumerate(sents, 1):
        d = max(1.5, len(s.split()) / 2.7)
        a, b = t, t + d
        blocks.append(f"{i}\n{_ts(a)} --> {_ts(b)}\n{s}\n")
        t = b
    path = W / "subs.srt"
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path, script.parent.name


def _ts(t):
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)) % 1000:03d}"


def planning():
    from pipeline import sceneplan
    srt, slug = srt_from_script()
    cues = sceneplan.parse_srt(srt)
    scenes = sceneplan.group_scenes(cues)
    check("scene grouping", len(cues) > 3 and len(scenes) >= 1, f"{slug}: {len(cues)} cues -> {len(scenes)} scenes")


def stills(n=3):
    rng = np.random.default_rng(5)
    paths = []
    for k in range(n):
        y, x = np.mgrid[0:1080, 0:1920]
        c1, c2 = rng.integers(50, 220, 3), rng.integers(50, 220, 3)
        t = (x / 1920)[..., None]
        im = Image.fromarray((c1 * (1 - t) + c2 * t).astype(np.uint8))
        d = ImageDraw.Draw(im)
        for _ in range(5):
            x0, y0 = rng.integers(0, 1700), rng.integers(0, 900)
            d.ellipse((x0, y0, x0 + 200, y0 + 160), fill=tuple(int(v) for v in rng.integers(0, 255, 3)))
        p = W / f"still_{k}.png"
        im.save(p)
        paths.append(p)
    return paths


def thumbnails():
    """Both thumbnail layouts, on bright synthetic stills.

    What this proves: the brief produces usable words, the type fits without
    running off the frame, it survives the downscale to a browse card, and
    nothing is drawn into the corner YouTube paints its duration pill on.

    What it cannot prove: that the picture underneath is any good. That is the
    vision judge in pipeline/visualqc.py, and it needs a key and real
    candidates, so it runs in the build and not here.
    """
    from automation import assemble
    from pipeline import thumbnail, thumbplan

    brief = thumbplan.fallback_brief("What If the Oceans Vanished?")
    check("thumbnail brief", 1 <= len(brief["words"]) <= thumbplan.MAX_LINES
          and len(brief["event"].split()) >= 4, f"words={brief['words']}")
    split = thumbplan.fallback_brief("What If Venus vs Neptune?")
    check("thumbnail comparison brief", bool(split["comparison"]) and not split["words"],
          f"labels={[s['label'] for s in (split['comparison'] or {}).values()]}")
    check("thumbnail prompts", len(thumbplan.candidates(brief)) == thumbplan.CANDIDATES
          and all("no text" in c["prompt"] for c in thumbplan.candidates(brief)))
    # A generic line, and a line another episode already used, are both refused.
    generic = thumbplan._clean({"event": brief["event"], "words": ["CHAOS", "NO ESCAPE"]},
                               "What If the Oceans Vanished?")
    taken = thumbplan._clean({"event": brief["event"], "words": ["NO WATER"]},
                             "What If the Oceans Vanished?", avoid={"nowater"})
    # Who is in the picture: no spacesuit on Earth, one in space, never blood,
    # and the cast alternates and does not repeat a type.
    from core import style
    earth = thumbplan.fallback_brief("What If Earth Had Two Moons?")
    space = thumbplan.fallback_brief("What If a Black Hole Passed Through the Solar System?")
    people = thumbplan.cast({"slug": "smoke", "position": 99}, root=W)
    on_earth = thumbplan.candidates(earth, people)
    in_space = thumbplan.candidates(space, people)
    check("thumbnail setting", earth["setting"] == "earth" and space["setting"] == "space"
          and thumbplan._clean({"event": earth["event"], "setting": "space"},
                               "What If Earth Had Two Moons?")["setting"] == "earth",
          f"two moons -> {earth['setting']}/{earth['place']}, black hole -> {space['setting']}")
    check("thumbnail costume",
          all("spacesuit" not in c["prompt"].split(", behind")[0] and "no spacesuit" in c["prompt"]
              for c in on_earth)
          and all("spacesuit" in c["prompt"].split(", behind")[0] for c in in_space))
    check("thumbnail never shows blood",
          all("no blood" in c["prompt"] and "no red streaks" in c["prompt"]
              for c in on_earth + in_space))
    queue_dir = W / "queue"
    for pos, person in ((1, {"gender": "man", "age": 42, "look": "white", "angle": "x"}),
                        (2, None)):
        d = queue_dir / f"{pos:03d}-ep"
        d.mkdir(parents=True, exist_ok=True)
        entry = {"slug": d.name, "position": pos, "title": "t"}
        if person:
            entry["thumbnail_person"] = person
        (d / "episode.json").write_text(json.dumps(entry), encoding="utf-8")
    second = thumbplan.cast({"slug": "002-ep", "position": 2}, root=W)
    check("thumbnail cast alternates and varies",
          all(p["gender"] == "woman" for p in second)
          # the type ignores gender: no white woman in her 40s after a white man in his
          and ("40s", "white") not in {style.person_type(p) for p in second}
          and len({style.person_type(p) for p in second}) == len(second)
          and len({p["look"] for p in second}) == len(second),
          f"after a white man in his 40s: {[(p['look'], p['age']) for p in second]}")
    restated = thumbplan.restate({**brief, "topic": "What If Jupiter Vanished?"},
                                 ["looks like a generic explosion"], use_llm=False)
    check("thumbnail restates an off-topic event",
          "gas giant" in restated["event"] and restated["event"] != brief["event"]
          and restated["event_first_pass"] == brief["event"],
          f"-> {restated['event'][:60]}...")
    check("thumbnail refuses generic lines",
          not {"CHAOS", "NO ESCAPE"} & set(generic["words"])
          and "NO WATER" not in taken["words"],
          f"generic -> {generic['words']}, already used -> {taken['words']}")

    srcs = stills(2)
    worst = 255.0
    for words in ([], brief["words"], ["2X GRAVITY"], ["NO MORE ICE", "TWO MOONS?"]):
        for side in (None, "left", "right"):
            img, boxes = thumbnail.compose(srcs[0], words, side=side)
            legible = thumbnail.text_legibility(img, boxes)
            worst = min(worst, legible)
            check(f"thumbnail {len(words)} line(s), event side {side or 'unknown'}",
                  img.size == (thumbnail.W, thumbnail.H)
                  and thumbnail.safe_corner_clear(boxes)
                  and legible >= assemble.MIN_LEGIBILITY,
                  f"legibility {legible:.0f} (floor {assemble.MIN_LEGIBILITY}), "
                  f"safe corner {thumbnail.safe_corner_clear(boxes)}")
    # The words go where the event is. A picture that is busy on the left and
    # flat on the right must put them on the right, and the other way round.
    busy = Image.new("RGB", (1360, 768), (20, 30, 60))
    d = ImageDraw.Draw(busy)
    for i in range(0, 768, 7):
        d.line((0, i, 680, i + 40), fill=(240, 230, 210), width=3)
    p = W / "half_busy.png"
    busy.save(p)
    img, boxes = thumbnail.compose(p, ["TWO MOONS?"])
    on_right = all(b[0] >= thumbnail.W * 0.4 for b in boxes)
    check("thumbnail words avoid the busy half", on_right and boxes,
          f"text starts at x={min(b[0] for b in boxes) if boxes else '-'}")
    img, boxes = thumbnail.compose_split(srcs[0], srcs[1], ["VENUS", "NEPTUNE"], [])
    legible = thumbnail.text_legibility(img, boxes)
    check("thumbnail split layout",
          img.size == (thumbnail.W, thumbnail.H)
          and thumbnail.safe_corner_clear(boxes)
          and legible >= assemble.MIN_LEGIBILITY,
          f"legibility {legible:.0f}")
    out = thumbnail.save(img, W / "thumbnail.png")
    size = out.stat().st_size
    check("thumbnail under YouTube's 2 MB", size <= thumbnail.MAX_BYTES,
          f"{size / 1e6:.2f} MB, worst legibility this run {worst:.0f}")


def render():
    from pipeline import music, render as r
    shots = r.plan_scenes(stills(), SECONDS, min_s=2.0, max_s=5.0)
    clips = r.build_scene_clips(shots, W / "clips")
    picture = r.crossfade(clips, W / "picture.mp4", work_dir=W / "xf")
    narration = W / "narration.wav"
    # a speech-like stand-in: a voiced tone broken into syllables, with gaps
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=f=150:d={SECONDS}", "-af",
                    "volume='0.5*(1+sin(2*PI*3*t))*gt(sin(2*PI*0.4*t),-0.6)':eval=frame",
                    "-ar", "48000", str(narration)], check=True)
    lib = music.load_library()
    track = next((Path(t["path"]) for t in lib if Path(t.get("path", "")).exists()), None) \
        if isinstance(lib, list) else None
    mixed = r.mix_audio(narration, track, W / "mix.m4a")
    out = r.mux(picture, mixed, W / "video.mp4")
    check("render + mix", out.exists(), f"music: {track.name if track else 'none on runner'}")
    return out


def checks(out):
    from pipeline import qc
    report, problems = qc.check_video(out, expected_min_s=SECONDS - 1.5, expected_max_s=SECONDS + 1.5)
    # flat placeholder gradients compress far below any real footage, so the
    # bitrate floor says nothing here; real builds keep the check
    problems = [p for p in problems if "bitrate" not in p]
    check("qc", not problems, f"{problems} {report.get('duration_s')} s")


def main():
    if W.exists():
        shutil.rmtree(W)
    W.mkdir(parents=True)
    imports()
    shared_gpu()
    if failures:
        print("SMOKE FAILED:", failures)
        return 1
    planning()
    thumbnails()
    out = render()
    checks(out)
    print("\nSMOKE", "PASSED" if not failures else f"FAILED: {failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
