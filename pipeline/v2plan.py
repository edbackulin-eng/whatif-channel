"""The v2 shot list (owner 15.11): a cut every 3-6 s, at least half the film real video, FLUX at most a
fifth, the rest Blender 3D and animated maps/cards; no shot twice.

    plan(subs_srt, script_text, title, out_json) -> [{start, end, text, type, ...}]

1. shots: the subtitle cues grouped into stretches of 3-6 s, cut at sentence ends where possible;
2. the text model reads the shots in chunks and says what each should show:
     video  "query": an English stock-footage search ("hurricane from space", "flooded street")
     3d     "template": earth_day | earth_night | earth_moon | moon_rise | sun | asteroid | orbits | ocean |
            ocean_moon, with "params" (moon_closeness, wave_scale)
     info   "info": {"kind": counter|timer|temp|compare|days|map, ...} - only numbers the line says
     flux   "prompt": a photoreal scene no camera can film (no faces close, no text)
   and "sfx": rumble | wind | explosion | rain | ocean | fire | space | none;
3. the shares are put right in code: FLUX over 20 % gives way to 3D/cards, video under 50 % takes
   shots from 3D first (stock is searched widely; what cannot be filled falls back in the render).
"""
import json
import re
from pathlib import Path

from core import llm
from core.logger import get_logger

log = get_logger("v2plan")
MIN_S, MAX_S = 3.0, 6.0
SHARE = {"video_min": 0.50, "flux_max": 0.20}
TEMPLATES = ["earth_day", "earth_night", "earth_moon", "moon_rise", "sun", "asteroid", "orbits", "ocean",
             "ocean_moon"]
SFX = ["rumble", "wind", "explosion", "rain", "ocean", "fire", "space", "none"]

PROMPT = """You are the picture editor of a YouTube science documentary "{title}" (global catastrophe, told as a
timeline of consequences). Below are numbered shots, each 3-6 seconds of narration. Say what each shot shows.
Mix them like a fast, gripping documentary: mostly REAL VIDEO, with 3D space shots, animated number cards
and maps, and a few photoreal generated scenes. Never the same idea twice in a row.
Types:
- "video": real stock or NASA footage - give "query": 2-5 English words a stock site would match
  (e.g. "storm waves hitting coast", "city at night aerial", "earth from space station", "ice sheet cracking").
  No identifiable people close up, no news or war footage, no real politics.
- "3d": a Blender scene - "template" from {templates}, optional "params": {{"moon_closeness": <1-3>,
  "wave_scale": <1-6>}}. For space, the Earth, the Moon, the Sun, orbits, an asteroid, a huge wave.
- "info": an animated card - "info": {{"kind": "counter|timer|temp|compare|days|map", "label": "<3-6 words>",
  "value": <number the narration says>, "unit": "...", "from": <start>, "to": <end, for timer in seconds>,
  "items": [{{"label": "...", "value": n}}] for compare, "places": [{{"name": "...", "lat": n, "lon": n}}] for map}}.
  ONLY numbers the shot's own narration states.
- "flux": a photoreal generated scene no camera could film (a city flooded by giant tides under a huge Moon) -
  "prompt": 25-50 English words, wide shot, no people close up, no text, no signs.
Each shot also gets "sfx" from {sfx}.
Answer as JSON: {{"shots": [{{"i": <n>, "type": "...", ...}}]}}
SHOTS:
{rows}"""


def parse_srt(path):
    text = Path(path).read_text(encoding="utf-8")
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        a, b = [x.strip() for x in lines[1].split("-->")]

        def sec(s):
            h, m, rest = s.replace(",", ".").split(":")
            return int(h) * 3600 + int(m) * 60 + float(rest)
        cues.append({"start": sec(a), "end": sec(b), "text": " ".join(lines[2:]).strip()})
    return cues


def group(cues, total_s):
    """Shots of MIN_S-MAX_S, cut where a sentence ends if one falls in range; covering 0..total_s."""
    shots, cur = [], None
    for c in cues:
        if cur is None:
            cur = {"start": 0.0 if not shots else shots[-1]["end"], "end": c["end"], "text": c["text"]}
        else:
            cur["end"], cur["text"] = c["end"], f"{cur['text']} {c['text']}"
        dur = cur["end"] - cur["start"]
        if dur >= MAX_S or (dur >= MIN_S and re.search(r"[.!?]\s*$", c["text"])):
            while cur["end"] - cur["start"] > MAX_S * 1.6:              # a long cue: cut in two
                mid = cur["start"] + (cur["end"] - cur["start"]) / 2
                shots.append({"start": cur["start"], "end": mid, "text": cur["text"]})
                cur["start"] = mid
            shots.append(cur)
            cur = None
    if cur:
        shots.append(cur)
    if shots:
        shots[-1]["end"] = max(shots[-1]["end"], total_s)
        if len(shots) > 1 and shots[-1]["end"] - shots[-1]["start"] < MIN_S:
            shots[-2]["end"] = shots[-1]["end"]
            shots[-2]["text"] += " " + shots[-1]["text"]
            shots.pop()
    for s in shots:
        s["start"], s["end"] = round(s["start"], 3), round(s["end"], 3)
    return shots


def _ask(title, chunk, offset):
    rows = "\n".join(f"{offset + i}. ({s['end'] - s['start']:.1f}s) {s['text'][:240]}" for i, s in enumerate(chunk))
    prompt = PROMPT.format(title=title, templates=TEMPLATES, sfx=SFX, rows=rows)
    try:
        ans = llm.complete_json(prompt, max_tokens=6000, temperature=0.5)
    except Exception as e:                                               # noqa: BLE001
        log.warning("shot planning for %d-%d failed (%s); defaults", offset, offset + len(chunk), e)
        return {}
    items = ans.get("shots") if isinstance(ans, dict) else ans
    return {int(r["i"]): r for r in (items or []) if isinstance(r, dict) and str(r.get("i", "")).lstrip("-").isdigit()}


def _default(s, k):
    """When the model gave nothing: real video of the line's own words, else Earth from space."""
    words = [w for w in re.findall(r"[a-zA-Z]{4,}", s["text"].lower())
             if w not in {"that", "this", "with", "would", "could", "there", "their", "about", "every", "which",
                          "into", "from", "your", "have", "they", "then", "than", "when", "what", "will"}]
    if words:
        return {"type": "video", "query": " ".join(words[:3]), "sfx": "none"}
    return {"type": "3d", "template": TEMPLATES[k % 3], "sfx": "space"}


def balance(shots):
    """The owner's shares, put right: FLUX <= 20 %, video >= 50 % (by time)."""
    total = sum(s["end"] - s["start"] for s in shots) or 1

    def share(t):
        return sum(s["end"] - s["start"] for s in shots if s["type"] == t) / total
    flux = [s for s in shots if s["type"] == "flux"]
    k = 0
    while share("flux") > SHARE["flux_max"] and flux:
        s = flux.pop()                                     # the later ones give way first
        s["type"], s["template"] = "3d", TEMPLATES[k % len(TEMPLATES)]
        s["was"] = "flux"
        k += 1
    others = [s for s in shots if s["type"] == "3d"] + [s for s in shots if s["type"] == "flux"]
    while share("video") < SHARE["video_min"] and others:
        s = others.pop(0)
        s["was"] = s["type"]
        s["type"] = "video"
        s["query"] = s.get("query") or _default(s, 0).get("query") or "earth from space"
    return {t: round(share(t), 3) for t in ("video", "3d", "info", "flux")}


def plan(subs_srt, total_s, title, out_json, chunk=40):
    cues = parse_srt(subs_srt)
    shots = group(cues, total_s)
    for k in range(0, len(shots), chunk):
        got = _ask(title, shots[k:k + chunk], k)
        for i in range(k, min(k + chunk, len(shots))):
            r = got.get(i) or _default(shots[i], i)
            t = r.get("type") if r.get("type") in ("video", "3d", "info", "flux") else "video"
            s = shots[i]
            s["type"] = t
            s["sfx"] = r.get("sfx") if r.get("sfx") in SFX else "none"
            if t == "video":
                s["query"] = str(r.get("query") or _default(s, i).get("query") or "earth from space")[:80]
            elif t == "3d":
                s["template"] = r.get("template") if r.get("template") in TEMPLATES else TEMPLATES[i % len(TEMPLATES)]
                s["params"] = {k2: v for k2, v in (r.get("params") or {}).items()
                               if k2 in ("moon_closeness", "wave_scale") and isinstance(v, (int, float))}
            elif t == "info":
                s["info"] = r.get("info") if isinstance(r.get("info"), dict) and r["info"].get("kind") else \
                    {"kind": "counter", "label": "", "value": 0}
            else:
                s["prompt"] = str(r.get("prompt") or s["text"])[:400]
            s["index"] = i
            s["seed"] = 1000 + i
    shares = balance(shots)
    Path(out_json).write_text(json.dumps({"title": title, "shares_planned": shares, "shots": shots}, indent=1,
                                         ensure_ascii=False), encoding="utf-8")
    log.info("%d shots planned; shares %s", len(shots), shares)
    return shots, shares
