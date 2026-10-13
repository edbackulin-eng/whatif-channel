"""Turn timed narration into a shot list, and decide where each shot comes from.

Scene boundaries come from the subtitle timings rather than from the script text,
because the voice sets the real pace. Gemini then decides, per scene, whether the
shot should be a real archive photograph, a generated frame, or a drawn card, and
writes the search query or the prompt for it.

This replaces the hand-maintained keyword lists from KT2, which could not scale
past a dozen shots and kept rejecting good frames.
"""
import json
import math
import re
from pathlib import Path

from core import llm
from core.logger import get_logger

log = get_logger("sceneplan")

MIN_SCENE_S = 4.0
MAX_SCENE_S = 7.0

SYSTEM = """You are the picture editor for a science documentary about a
hypothetical scenario: the Moon falling toward Earth.

For each scene you are given the narration text. Decide what the viewer should be
looking at, and where that image comes from.

Choose exactly one source per scene:
- "archive": a real photograph exists. Only for real space or Earth-observation
  subjects: the Moon, the lunar surface, Earth from orbit, oceans, coastlines,
  cities from space, the atmosphere, storms, ice. NASA has these.
- "generated": the shot is imaginary, or is at ground level with people, cities,
  flooding, destruction, interiors, or the Moon breaking apart. No real
  photograph of it can exist.
- "infographic": the scene states a number, a ratio, a time marker or a
  mechanism that is clearer drawn than photographed.

Rules:
- Prefer "archive" only when a genuine NASA photograph would actually show it.
- Never choose "archive" for anything happening on the ground among people.
- Consecutive scenes should not repeat the same subject.

Rules for "generated" prompts, which exist because the image model cannot do
these things convincingly and they mark a video as machine-made:
- NEVER ask for an object whose whole purpose is to carry writing. The image
  model renders all of them as unreadable letter-soup, and it is the single
  clearest sign a video was machine-made. That means: shop fronts, signage,
  billboards, monitors, screens, phones, tickers, departure boards, dashboards
  with readouts, number plates, whiteboards, books, newspapers, documents,
  posters, labels and packaging.
  If a scene genuinely needs one, say so explicitly in the prompt as out of
  focus, seen at a sharp angle, or far away - never legible, never centred.
- NEVER ask for a close-up of a human face, a portrait, or a named expression
  such as "terrified". People appear as distant figures, silhouettes, from
  behind, or as hands only.
- Describe what a camera would see: a place, an object, weather, light.

Reply with valid JSON only."""

PROMPT = """For each scene, return an object:
{{"id":<int>,"source":"archive|generated|infographic",
"query":"<3-8 word NASA image search, archive only, else empty>",
"prompt":"<one concrete visual sentence, generated only, else empty>",
"card":{{"kind":"timer|number","label":"<short>","caption":"<short>"}} or null}}

Return {{"scenes":[...]}}.

Scenes:
{scenes}"""


def parse_srt(path):
    """[(start_s, end_s, text)] from an SRT file."""
    blocks = re.split(r"\n\s*\n", Path(path).read_text(encoding="utf-8").strip())
    cues = []
    for b in blocks:
        lines = [l for l in b.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        m = re.search(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)",
                      lines[1])
        if not m:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(x) for x in m.groups())
        start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
        end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000
        cues.append((start, end, " ".join(lines[2:]).replace("\n", " ").strip()))
    return cues


def group_scenes(cues, min_s=MIN_SCENE_S, max_s=MAX_SCENE_S):
    """Merge cues into scenes of 4-7 seconds, never splitting a cue."""
    scenes, start, texts = [], None, []
    for c_start, c_end, text in cues:
        if start is None:
            start = c_start
        texts.append(text)
        span = c_end - start
        if span >= min_s:
            # Close the scene unless the next cue would still fit inside max_s.
            scenes.append({"start": round(start, 2), "end": round(c_end, 2),
                           "duration": round(c_end - start, 2),
                           "text": " ".join(texts)})
            start, texts = None, []
    if texts and start is not None:
        last_end = cues[-1][1]
        if scenes and last_end - start < min_s / 2:
            scenes[-1]["end"] = round(last_end, 2)
            scenes[-1]["duration"] = round(last_end - scenes[-1]["start"], 2)
            scenes[-1]["text"] += " " + " ".join(texts)
        else:
            scenes.append({"start": round(start, 2), "end": round(last_end, 2),
                           "duration": round(last_end - start, 2),
                           "text": " ".join(texts)})
    # Split anything that overran the cap. Each part keeps the full narration:
    # two different shots across one long sentence is normal cutting, and the
    # picture editor needs the text to choose the second shot at all. Parts are
    # only created when each one still clears the minimum.
    out = []
    for s in scenes:
        if s["duration"] <= max_s:
            out.append(s)
            continue
        parts = max(1, math.ceil(s["duration"] / max_s))
        while parts > 1 and s["duration"] / parts < min_s:
            parts -= 1
        step = s["duration"] / parts
        for i in range(parts):
            out.append({"start": round(s["start"] + i * step, 2),
                        "end": round(s["start"] + (i + 1) * step, 2),
                        "duration": round(step, 2),
                        "text": s["text"],
                        "continues": i > 0})
    for i, s in enumerate(out):
        s["index"] = i
    return out


SOURCES = ("archive", "generated", "infographic")


def _valid_source(result, scene):
    """Coerce the model's answer to one of the three real sources.

    It sometimes answers with a card KIND ("timer") instead of a source, which
    then flows downstream as an unknown bucket and leaves the scene with no
    picture at all. A card kind means an infographic; anything else unrecognised
    falls back to a generated frame, which is always producible.
    """
    raw = (result.get("source") or "").strip().lower()
    if raw in SOURCES:
        return raw
    if raw in ("timer", "number", "card", "diagram", "chart"):
        card = scene.get("card") or result.get("card") or {}
        if not card.get("kind"):
            scene["card"] = {"kind": raw if raw in ("timer", "number") else "number",
                             "label": "", "caption": ""}
        return "infographic"
    if raw:
        log.warning("scene %s: unknown source %r, treating as generated",
                    scene.get("index"), raw)
    return "generated"


def plan(scenes, batch_size=27):
    """Ask Gemini for a source and a query/prompt per scene."""
    for start in range(0, len(scenes), batch_size):
        batch = scenes[start:start + batch_size]
        listing = "\n".join(
            f"{s['index']}. ({s['duration']:.1f}s) {s['text'][:170] or '(continues)'}"
            for s in batch)
        try:
            data = llm.complete_json(PROMPT.format(scenes=listing), system=SYSTEM,
                                     max_tokens=8192, temperature=0.4,
                                     model=llm.GEMINI_BULK_MODEL)
            by_id = {r.get("id"): r for r in data.get("scenes", [])}
        except Exception as e:
            log.error("plan batch at %d failed: %s", start, e)
            by_id = {}
        for s in batch:
            r = by_id.get(s["index"], {})
            s["source"] = _valid_source(r, s)
            s["query"] = (r.get("query") or "").strip()
            s["prompt"] = (r.get("prompt") or "").strip()
            s["card"] = r.get("card")
        log.info("planned %d/%d scenes", min(start + batch_size, len(scenes)),
                 len(scenes))
    return scenes


def summarise(scenes):
    counts = {}
    for s in scenes:
        counts[s.get("source", "?")] = counts.get(s.get("source", "?"), 0) + 1
    return counts


def write(scenes, path):
    Path(path).write_text(json.dumps(scenes, indent=2, ensure_ascii=False),
                          encoding="utf-8")
    log.info("wrote %d scenes to %s", len(scenes), Path(path).name)
