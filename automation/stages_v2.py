"""The v2 build (owner 15.11), in three jobs on GitHub Actions:

    python -X utf8 automation/stages_v2.py prep     --slug <slug>    narration, subtitles, shot list, real
                                                                      video found/checked/cut, cards and maps,
                                                                      FLUX (shots + thumbnails) on Kaggle,
                                                                      thumbnails composed and judged
    python -X utf8 automation/stages_v2.py blender  --slug <slug> --k 0 --n 8   the k-th share of the 3D shots
    python -X utf8 automation/stages_v2.py assemble --slug <slug>    the montage, sound (music under the
                                                                      voice, effects), QA, the package

Everything lands in output/<slug>/v2/. A shot that could not be filled (no clip, a 3D render that failed)
falls back to a 3D Earth or a card - never to a repeat. Every shot is cut to its own clip at 1920x1080,
30 fps; the montage dissolves 0.35 s between them.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.logger import get_logger  # noqa: E402

log = get_logger("v2")
W, H, FPS = 1920, 1080, 30
XF = 0.35
BLENDER = ROOT / "tools" / "blender" / "blender"


def work_of(slug):
    w = ROOT / "output" / slug / "v2"
    (w / "clips").mkdir(parents=True, exist_ok=True)
    return w


def episode_of(slug):
    from pipeline import queue
    for e in queue.episodes():
        if e["slug"] == slug:
            return e
    raise SystemExit(f"no queued episode {slug}")


def ff(*args, label="ffmpeg"):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"{label}: {r.stderr[-1500:]}")


def dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1",
                        str(path)], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


GRADE = "eq=contrast=1.06:saturation=1.12,unsharp=5:5:0.4"


def cut_video(src, need, out, at=0.1):
    """A stretch of a real clip, cover-scaled to 1920x1080, graded; slowed a little if it is short."""
    d = dur(src)
    speed = 1.0 if d * (1 - at) >= need else max(0.55, d * 0.95 / need)
    start = 0.0 if speed < 1.0 else min(d * at, max(0.0, d - need - 0.1))
    vf = (f"setpts={1 / speed:.4f}*PTS,fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
          f"crop={W}:{H},{GRADE},format=yuv420p")
    ff("-ss", f"{start:.2f}", "-i", src, "-t", f"{need:.3f}", "-vf", vf, "-an", "-c:v", "libx264", "-preset",
       "veryfast", "-crf", "17", "-r", FPS, out, label=f"cut {Path(src).name}")
    return {"speed": round(speed, 2), "in": round(start, 2)}


def still_clip(img, need, out, move=0):
    """A still (FLUX) with a slow camera move: push in, pull out or a pan, alternating."""
    n = int(round(need * FPS))
    z = ["min(zoom+0.0009,1.18)", "if(eq(on,0),1.18,max(zoom-0.0009,1.0))", "1.12", "1.12"][move % 4]
    x = ["iw/2-(iw/zoom/2)", "iw/2-(iw/zoom/2)", f"(iw-iw/zoom)*on/{n}", f"(iw-iw/zoom)*(1-on/{n})"][move % 4]
    vf = (f"scale=3840:2160:force_original_aspect_ratio=increase,crop=3840:2160,"
          f"zoompan=z='{z}':x='{x}':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps={FPS},{GRADE},format=yuv420p")
    ff("-loop", "1", "-i", img, "-vf", vf, "-frames:v", n, "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
       out, label=f"still {Path(img).name}")


# ------------------------------------------------------------------ prep
def prep(slug):
    from automation import stages
    from pipeline import v2plan, v2stock, v2info
    ep = episode_of(slug)
    w = work_of(slug)
    src = ep["_dir"]
    for name in ("script.txt", "sources.json"):
        if (src / name).exists():
            shutil.copy2(src / name, w.parent / name)
    stages.narrate(w.parent)
    stages.subtitles(w.parent)
    total = dur(w.parent / "narration.wav") + 1.5
    plan_p = w / "shots.json"
    if plan_p.exists():
        shots = json.loads(plan_p.read_text(encoding="utf-8"))["shots"]
    else:
        shots, _ = v2plan.plan(w.parent / "subs.srt", total, ep["title"], plan_p)

    # ---- real video: search each query, look at the candidates, one clip per shot, never twice
    pool, by_q = {}, {}
    for s in shots:
        if s["type"] == "video":
            q = s["query"]
            if q not in by_q:
                found = v2stock.search(q)
                if len(found) < 3:                         # a narrow query: its first two words as well
                    found += v2stock.search(" ".join(q.split()[:2]))
                by_q[q] = list(dict.fromkeys(it["id"] for it in found))
                for it in found:
                    pool.setdefault(it["id"], it)
    desc = v2stock.describe(list(pool.values()), w / "stock_describe.json")
    channel_used = v2stock.used_in_channel()
    used = set()
    for s in shots:
        if s["type"] != "video":
            continue
        need = s["end"] - s["start"] + XF
        ids = [i for i in by_q.get(s["query"], []) if v2stock.usable(pool[i], desc.get(i)) and i not in used]
        ids.sort(key=lambda i: (i in channel_used, (pool[i].get("duration") or 8) < need))
        got = None
        for cid in ids[:4]:
            try:
                f = v2stock.download(pool[cid], w / "src" / f"{cid}.mp4")
                out = w / "clips" / f"{s['index']:04d}.mp4"
                s["cut"] = cut_video(f, need, out)
                f.unlink(missing_ok=True)                   # used once in the film: the runner's disk stays free
                got = cid
                break
            except Exception as e:                                       # noqa: BLE001
                log.warning("shot %d: %s did not work (%s)", s["index"], cid, str(e)[:120])
        if got:
            used.add(got)
            it = pool[got]
            s.update({"clip": got, "what": (desc.get(got) or {}).get("what"), "source": it["source"],
                      "license": it["license"], "page": it.get("page"), "author": it.get("author")})
        else:
            s["was"], s["type"] = "video", "3d"
            s["template"] = "earth_day" if s["index"] % 2 else "earth_night"
            s["params"] = {}
            log.info("shot %d: no clip for %r; a 3D shot instead", s["index"], s.get("query"))

    # ---- cards and maps
    for s in shots:
        if s["type"] == "info":
            v2info.render(s["info"], s["end"] - s["start"] + XF, w / "clips" / f"{s['index']:04d}.mp4")

    # ---- FLUX on Kaggle: the shots' pictures and the thumbnails', one kernel
    flux_shots = [s for s in shots if s["type"] == "flux"]
    thumb_takes = []
    try:
        from tools import thumbs_v2
        cs = thumbs_v2.concepts(ep["title"])
        for i, c in enumerate(cs):
            for v, extra in enumerate(("", ", seen from a low angle, even more dramatic")):
                thumb_takes.append({"concept": i, "take": v, "prompt": f"{c['prompt']}{extra}, {thumbs_v2.STYLE}", **c})
    except Exception as e:                                               # noqa: BLE001
        log.warning("thumbnail concepts: %s", e)
    prompts = [f"{s['prompt']}, photorealistic, cinematic, natural light, no text, no people close up"
               for s in flux_shots] + [t["prompt"] for t in thumb_takes]
    images = []
    if prompts and os.environ.get("V2_NO_FLUX"):
        log.info("V2_NO_FLUX: no Kaggle tonight - FLUX shots become 3D, no thumbnails (a dry run)")
    elif prompts:
        from automation import frames
        try:
            ref = frames._submit(prompts, [{"extra": i} for i in range(len(prompts))], w, f"v2-{slug[:30]}-{int(time.time())}")
            images = frames._fetch(ref, w / "gpu") if frames._wait(ref) else []
        except Exception as e:                                           # noqa: BLE001
            log.warning("FLUX on Kaggle: %s", e)
    for k, s in enumerate(flux_shots):
        img = images[k] if k < len(images) else None
        if img:
            still_clip(img, s["end"] - s["start"] + XF, w / "clips" / f"{s['index']:04d}.mp4", move=k)
            s["image"] = str(img)
        else:
            s["was"], s["type"], s["template"], s["params"] = "flux", "3d", "earth_moon", {}
    for t, img in zip(thumb_takes, images[len(flux_shots):]):
        t["image"] = str(img)
    (w / "thumb_takes.json").write_text(json.dumps(thumb_takes, indent=1), encoding="utf-8")
    try:
        from tools import thumbs_v2
        if any(t.get("image") for t in thumb_takes):
            thumbs_v2.finish(ep["title"], [t for t in thumb_takes if t.get("image")], w / "thumbs")
    except Exception as e:                                               # noqa: BLE001
        log.warning("thumbnails: %s", e)
    # owner 17.11: the scene of the thumbnail is in the film (YouTube's rule on misleading thumbnails) - the
    # chosen picture (without its words) takes a FLUX shot, else the longest 3D shot of the middle of the film
    try:
        rep = json.loads((w / "thumbs" / "report.json").read_text(encoding="utf-8"))
        scene = rep.get("chosen_image")
        if scene and Path(scene).exists():
            mid = [s for s in shots if s["type"] == "3d" and total * 0.25 < s["start"] < total * 0.75]
            target = next((s for s in shots if s["type"] == "flux"), None) or \
                (max(mid, key=lambda s: s["end"] - s["start"]) if mid else None)
            if target:
                still_clip(scene, target["end"] - target["start"] + XF, w / "clips" / f"{target['index']:04d}.mp4",
                           move=0)
                target.update({"type": "flux", "image": scene, "thumb_scene": True})
                log.info("the thumbnail's scene is shot %d (%.0f s)", target["index"], target["start"])
    except Exception as e:                                               # noqa: BLE001
        log.warning("thumbnail scene in the film: %s", e)
    plan_p.write_text(json.dumps({"title": ep["title"], "shots": shots}, indent=1, ensure_ascii=False), encoding="utf-8")
    v2stock.remember(list(used))
    log.info("prep done: %s", {t: sum(1 for s in shots if s["type"] == t) for t in ("video", "3d", "info", "flux")})


# ------------------------------------------------------------------ blender
def blender(slug, k, n):
    w = work_of(slug)
    shots = json.loads((w / "shots.json").read_text(encoding="utf-8"))["shots"]
    mine = [s for s in shots if s["type"] == "3d"][k::n]
    exe = str(BLENDER) if BLENDER.exists() else "blender"
    for s in mine:
        out = w / "clips" / f"{s['index']:04d}_3d.mp4"
        need = s["end"] - s["start"] + XF
        args = {"template": s.get("template", "earth_day"), "seconds": need, "seed": s.get("seed", s["index"]),
                "out": str(out), "textures": str(ROOT / "assets" / "textures"), "samples": 12, "w": 1280, "h": 720,
                "fps": 15,
                **(s.get("params") or {})}
        t0 = time.time()
        r = subprocess.run([exe, "-b", "-noaudio", "-P", str(ROOT / "pipeline" / "blender" / "scene.py"), "--",
                            json.dumps(args)], capture_output=True, text=True, timeout=1800)
        if r.returncode or not out.exists():
            log.warning("3D shot %d (%s) failed: %s", s["index"], args["template"], (r.stderr or r.stdout)[-600:])
            continue
        final = w / "clips" / f"{s['index']:04d}.mp4"
        # rendered at 15 fps (16.11: Cycles on a runner's CPU), blended up to 30 - the camera moves slowly
        ff("-i", out, "-vf", f"minterpolate=fps={FPS}:mi_mode=blend,scale={W}:{H}:flags=lanczos,{GRADE},format=yuv420p",
           "-t", f"{need:.3f}",
           "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", final, label="3d upscale")
        out.unlink(missing_ok=True)
        log.info("3D shot %d (%s) in %.0f s", s["index"], args["template"], time.time() - t0)


# ------------------------------------------------------------------ assemble
def assemble(slug):
    from pipeline import render, v2info, v2sound
    ep = episode_of(slug)
    w = work_of(slug)
    shots = json.loads((w / "shots.json").read_text(encoding="utf-8"))["shots"]
    clips = []
    for s in shots:
        c = w / "clips" / f"{s['index']:04d}.mp4"
        if not c.exists():                     # a 3D render that failed: a card of the line's own words
            s["was"], s["type"] = s["type"], "info"
            s["info"] = {"kind": "map", "label": "", "places": []}
            v2info.render(s["info"], s["end"] - s["start"] + XF, c)
        clips.append(c)
    # the picture: dissolves in chunks of 20 (a graph of 250 inputs is too much for one ffmpeg)
    joined = []
    for k in range(0, len(clips), 20):
        part = clips[k:k + 20]
        outp = w / f"part_{k // 20:03d}.mp4"
        if len(part) == 1:
            shutil.copy(part[0], outp)
        else:
            ins, graph, label, length = [], [], "[0:v]", dur(part[0])
            for c in part:
                ins += ["-i", str(c)]
            for i in range(1, len(part)):
                off = length - XF
                graph.append(f"{label}[{i}:v]xfade=transition=fade:duration={XF}:offset={off:.3f}[v{i}]")
                label = f"[v{i}]"
                length = off + dur(part[i])
            ff(*ins, "-filter_complex", ";".join(graph), "-map", label, "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "17", "-pix_fmt", "yuv420p", "-r", FPS, outp, label=f"montage {k}")
        joined.append(outp)
    lst = w / "parts.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in joined), encoding="utf-8")
    silent = w / "silent.mp4"
    ff("-f", "concat", "-safe", "0", "-i", lst, "-c:v", "libx264", "-preset", "medium", "-crf", "19",
       "-pix_fmt", "yuv420p", "-r", FPS, silent, label="concat")
    # the sound: narration, music by mood, the effects of each shot; music and effects below the voice
    narration = w.parent / "narration.wav"
    total = dur(narration) + 1.5
    from automation import assemble as old
    bed, credits = old._music_bed(w.parent, dur(narration))
    sfx = v2sound.sfx_track(shots, total, w / "sfx.wav")
    bed2 = v2sound.bed_with_sfx(bed, sfx, w / "bed_sfx.wav")
    mixed = w / "mixed.m4a"
    render.mix_audio(narration, bed2, mixed)
    final = w.parent / "video.mp4"
    render.mux(silent, mixed, final)
    shares = {t: round(sum(s["end"] - s["start"] for s in shots if s["type"] == t) / total, 3)
              for t in ("video", "3d", "info", "flux")}
    (w / "shares.json").write_text(json.dumps({"shares": shares, "music": credits,
                                               "duration_s": dur(final)}, indent=1), encoding="utf-8")
    log.info("video %s: %.1f min, shares %s", final, dur(final) / 60, shares)
    return package(slug, ep, shots, final, shares, credits)


LICENCE = re.compile(r"pixabay content licen|pexels licen|public domain|cc0|cc[ -]by(?![ -]nc|[ -]nd)", re.I)


def package(slug, ep, shots, final, shares, music_credits):
    """QA in two tiers (owner 15.11) and the package the uploader takes (ready/<date>/<slug>/)."""
    from datetime import date
    from pipeline import qc, seo
    w = work_of(slug)
    thumb_src = w / "thumbs" / "chosen.jpg"
    if not thumb_src.exists():
        thumb_src = w / "thumbs" / "chosen.png"
    thumb = w.parent / ("thumbnail" + thumb_src.suffix)
    if thumb_src.exists():
        shutil.copy(thumb_src, thumb)
    report, problems = qc.check_video(final, thumbnail_path=thumb if thumb.exists() else None,
                                      srt_path=w.parent / "subs.srt", expected_min_s=14.5 * 60,
                                      expected_max_s=20.5 * 60)
    black = qc.find_black(final) if hasattr(qc, "find_black") else []
    tj = {}
    tr = w / "thumbs" / "report.json"
    if tr.exists():
        takes = json.loads(tr.read_text(encoding="utf-8")).get("takes") or []
        best = max(takes, key=lambda t: t.get("rank") or -99, default={})
        tj = best.get("judge") or {}
    unlicensed = [s["index"] for s in shots if s["type"] == "video" and not LICENCE.search(str(s.get("license") or ""))]
    low = [p.lower() for p in problems]
    blocking = {
        "black": not black,
        "silence_or_sound": not any(x in p for p in low for x in ("silence", "audio", "loudness", "clipping")),
        "text": thumb.exists() and tj.get("readable_small") is not False,
        "license": not unlicensed,
        "duration": 14.5 * 60 <= float(report.get("duration_s") or 0) <= 20.5 * 60,
        "picture": not any(x in p for p in low for x in ("resolution", "frame rate", "no video")),
    }
    clips = [s.get("clip") for s in shots if s.get("clip")]
    scores = {"video_share>=0.5": shares["video"] >= 0.5, "flux_share<=0.2": shares["flux"] <= 0.2,
              "cut_every_3_6s": all(2.5 <= s["end"] - s["start"] <= 9 for s in shots),
              "thumbnail_score": tj.get("score"), "no_repeats": len(set(clips)) == len(clips)}
    verdict = "PASS" if all(blocking.values()) else "FAIL"
    qcj = {"verdict": verdict, "problems": [k for k, v in blocking.items() if not v] + problems[:6],
           "blocking": blocking, "scores": scores, "shares": shares, "report": report, "black": black[:10],
           "unlicensed_shots": unlicensed}
    (w.parent / "qc.json").write_text(json.dumps(qcj, indent=1, default=str), encoding="utf-8")
    lines = ["Footage and pictures:"]
    for s in shots:
        if s["type"] == "video" and s.get("clip"):
            lines.append(f"- {s.get('source')}: {s.get('author') or ''} ({s.get('license')}) {s.get('page') or ''}")
    lines.append("- 3D scenes rendered in Blender with NASA textures (Blue Marble, Black Marble, LRO; public domain).")
    if shares["flux"] > 0:
        lines.append("- Some imagined scenes are AI-generated (FLUX.1-schnell, Apache-2.0).")
    music = "\n".join(music_credits or ["(no music)"])
    if music_credits:
        music += "\nLicensed under Creative Commons: By Attribution 4.0\nhttps://creativecommons.org/licenses/by/4.0/"
    desc = seo.build_description(ep.get("hook") or ep["title"], "", "\n".join(lines), music, "")
    from automation.assemble import TAGS, HASHTAGS
    seo.write_metadata(w.parent / "metadata.txt", ep["title"], desc, seo.build_tags(TAGS), HASHTAGS)
    (w.parent / "v2.json").write_text(json.dumps({"synthetic": shares["flux"] > 0, "shares": shares}),
                                      encoding="utf-8")
    day = ROOT / "ready" / date.today().isoformat() / slug
    day.mkdir(parents=True, exist_ok=True)
    for name in ("video.mp4", "thumbnail.jpg", "thumbnail.png", "metadata.txt", "subs.srt", "qc.json", "v2.json", "script.txt",
                 "sources.json"):
        if (w.parent / name).exists():
            shutil.copy2(w.parent / name, day / name)
    for f in (w / "thumbs").glob("candidate_*.png"):
        shutil.copy2(f, day / f.name)
    shutil.copy2(w / "shots.json", day / "shots.json")
    from pipeline import queue
    queue.set_status(ep["_dir"], "rendered", engine="v2", shares=shares)
    log.info("QA %s; blocking %s; scores %s", verdict, blocking, scores)
    return day


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["prep", "blender", "assemble"])
    ap.add_argument("--slug", required=True)
    ap.add_argument("--k", type=int, default=0)
    ap.add_argument("--n", type=int, default=1)
    a = ap.parse_args()
    if a.stage == "prep":
        prep(a.slug)
    elif a.stage == "blender":
        blender(a.slug, a.k, a.n)
    else:
        assemble(a.slug)
