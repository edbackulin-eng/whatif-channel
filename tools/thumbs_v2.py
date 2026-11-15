"""Thumbnails in the 2026-11 style (owner 15.11), after the niche's best performer (global catastrophes,
59 K - 798 K views a video): a photorealistic, cinematic shot of a famous city at the moment of the
catastrophe; one or two enormous white-to-light-grey words at the top, with depth and a hard shadow
("WHAT IF", "NO SUN", "365 DAYS OF RAIN?"); one yellow curved arrow on the key detail; saturated,
maximum contrast, readable at 210x118; no close faces, no text but the headline.

    python -X utf8 tools/thumbs_v2.py --title "What Would Happen If the Moon Came Twice as Close?"

1. three concepts (city, scene, key detail, words) - the text model, else the built-in plan;
2. FLUX.1-schnell on Kaggle, two takes of each concept, one kernel;
3. the vision model finds the key detail in each picture (where the arrow points) and rejects
   pictures with people close up, text, warped buildings;
4. composed in code: colour punch, the words, the arrow; measured at 210x118;
5. the judge scores every composed thumbnail against the rules; the best take of each concept is a
   candidate, the best candidate is chosen. -> output/thumbs_v2/<slug>/candidate_[123].png, chosen.png,
   report.json
"""
import argparse
import base64
import io
import json
import math
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.logger import get_logger  # noqa: E402

log = get_logger("thumbs_v2")
OUT = ROOT / "output" / "thumbs_v2"
W, H = 1280, 720
SMALL = (210, 118)
FONT = ROOT / "assets" / "fonts" / "Anton-Regular.ttf"
YELLOW = (255, 214, 0)
VISION = ("gemini-flash-latest", "gemini-flash-lite-latest")
SAFE_X, SAFE_Y = 0.78, 0.80          # YouTube's duration pill, bottom right

STYLE = ("photorealistic cinematic film still, ultra detailed, dramatic volumetric light, epic wide angle, "
         "saturated colours, high contrast, sharp focus, 8k, disaster movie, no text, no letters, no logos, "
         "no people in the foreground")

PLAN = """You design YouTube thumbnails for a science channel about global catastrophes ("What Would Happen
If ...?"). The winning style: a photorealistic cinematic shot of a FAMOUS CITY (New York, London, Tokyo, Paris,
Dubai, Sydney, Rio, Hong Kong ...) at the very moment of the catastrophe - the city in crisis, the event huge and
unmistakable - plus one or two enormous words at the top and one yellow arrow on the key detail.
Episode: "{title}".
Give 3 clearly different concepts (different city, different moment, different key detail). For each:
"city", "prompt": an English FLUX prompt (the scene only, 40-70 words, wide shot, the event filling the upper
half of the frame so the words have sky to sit on, no people close up, no text),
"detail": the one thing the arrow points at (a few English words, e.g. "the giant moon", "the wave crest"),
"words": 1-2 words, UPPER CASE, max 14 characters in all, e.g. "WHAT IF", "TOO CLOSE", "NO SUN".
Answer as JSON: {{"concepts": [{{"city": "...", "prompt": "...", "detail": "...", "words": "..."}}]}}"""

FALLBACK = {
    "moon": [
        {"city": "New York", "words": "WHAT IF",
         "detail": "the giant moon",
         "prompt": "Manhattan skyline at dusk seen from the Hudson River, a gigantic full Moon twice its normal "
                   "size hanging low between the skyscrapers filling the upper sky, enormous tidal surge flooding "
                   "the waterfront and streets, waves crashing over piers, glowing city lights, storm clouds lit "
                   "by moonlight"},
        {"city": "London", "words": "TOO CLOSE",
         "detail": "the giant moon",
         "prompt": "London at night, the River Thames bursting its banks, Big Ben and the Houses of Parliament "
                   "half under churning water, a colossal cratered Moon looming enormous above the city filling "
                   "the sky, silver moonlight, dramatic clouds, flooded bridges"},
        {"city": "Tokyo", "words": "WHAT IF?",
         "detail": "the tidal wave",
         "prompt": "Tokyo bay at twilight, a towering tidal wave rising over the neon skyscrapers, a huge Moon "
                   "twice as large as normal glowing above the wave, dark blue and cyan colours, spray and mist, "
                   "city lights reflecting, epic scale"},
    ],
}


# ------------------------------------------------------------------ the vision model
def _key():
    from core import llm
    k = llm.get_key("GEMINI_API_KEY")
    if not k:
        raise SystemExit("GEMINI_API_KEY is not set")
    return k


def _b64(path, side=1024):
    im = Image.open(path).convert("RGB")
    im.thumbnail((side, side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode()


def ask(prompt, images=(), models=VISION, tokens=2048):
    from core import llm
    parts = [{"text": prompt}] + [{"inline_data": {"mime_type": "image/jpeg", "data": _b64(p)}} for p in images]
    payload = json.dumps({"contents": [{"role": "user", "parts": parts}],
                          "generationConfig": {"temperature": 0.0, "maxOutputTokens": tokens,
                                               "responseMimeType": "application/json"}}).encode()
    last = None
    for m in models:
        for attempt in range(4):
            req = urllib.request.Request(llm.GEMINI_URL.format(model=m), data=payload, method="POST",
                                         headers={"Content-Type": "application/json", "x-goog-api-key": _key()})
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    d = json.loads(r.read().decode("utf-8", "replace"))
                text = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"] if "text" in p)
                return llm.extract_json(text)
            except urllib.error.HTTPError as e:
                last = f"{m}: {e.code}"
                if e.code in (429, 500, 502, 503, 504):
                    time.sleep(15 * (attempt + 1))
                    continue
                break
            except Exception as e:                                       # noqa: BLE001
                last = f"{m}: {e}"
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"no answer from the vision model ({last})")


LOCATE = """This picture will be a YouTube thumbnail. Find "{detail}" in it.
Answer as JSON: {{"found": true|false, "box": [x0, y0, x1, y1],   // fractions 0-1 of width and height
"people_close": true|false,   // a person's face or body large in the frame
"text_in_image": true|false,  // letters, signs, logos
"warped": true|false,         // melted or impossible buildings, broken anatomy
"sky_top": true|false}}       // the top quarter is calm enough (sky, clouds, space) for big words"""

JUDGE = """You are the strict art director of a YouTube channel about global catastrophes. Judge this thumbnail
for the episode "{title}" against the rules of the niche's best performer:
1. photorealistic cinematic scene of a recognisable famous city at the moment of the catastrophe;
2. the catastrophe matches the episode and is instantly clear;
3. 1-2 enormous words at the top, white/light grey with depth and shadow, readable;
4. one yellow curved arrow pointing at the key detail;
5. saturated colours, maximum contrast; still readable as a tiny 210x118 card (the second image);
6. no people close up, no text except the headline, nothing warped or AI-looking.
Answer as JSON: {{"score": <0-10>, "readable_small": true|false, "matches_episode": true|false,
"defects": ["..."], "why": "<one sentence>"}}"""


# ------------------------------------------------------------------ drawing
def cover(im, w=W, h=H):
    s = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def punch(im):
    im = ImageEnhance.Color(im).enhance(1.35)
    im = ImageEnhance.Contrast(im).enhance(1.18)
    return ImageEnhance.Sharpness(im).enhance(1.4)


def _fit(text, max_w, start=230):
    size = start
    while size > 40:
        f = ImageFont.truetype(str(FONT), size)
        if f.getlength(text) <= max_w:
            return f
        size -= 6
    return ImageFont.truetype(str(FONT), size)


def headline(im, text, top=18):
    """White-to-light-grey letters with depth (a stepped darker extrusion) and a soft hard shadow."""
    f = _fit(text, W * 0.86)
    box = f.getbbox(text)
    tw, th = box[2] - box[0], box[3] - box[1]
    x, y = (W - tw) // 2 - box[0], top - box[1]
    # shadow
    sh = Image.new("L", (W, H), 0)
    ImageDraw.Draw(sh).text((x + 10, y + 14), text, font=f, fill=200)
    sh = sh.filter(ImageFilter.GaussianBlur(14))
    im.paste((0, 0, 0), (0, 0), sh)
    d = ImageDraw.Draw(im)
    for k in range(9, 0, -1):                       # extrusion: the depth of the letters
        g = 70 + k * 6
        d.text((x + k * 0.7, y + k), text, font=f, fill=(g, g, g + 8))
    # the face: a vertical gradient white -> light grey
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).text((x, y), text, font=f, fill=255)
    grad = Image.new("RGB", (W, H))
    gd = ImageDraw.Draw(grad)
    for yy in range(H):
        t = min(1.0, max(0.0, (yy - y - box[1]) / max(1, th)))
        v = int(255 - 55 * t)
        gd.line([(0, yy), (W, yy)], fill=(v, v, min(255, v + 6)))
    im.paste(grad, (0, 0), mask)
    d.text((x, y), text, font=f, fill=None, stroke_width=3, stroke_fill=(40, 40, 48))
    im.paste(grad, (0, 0), mask)
    return (x + box[0], y + box[1], x + box[0] + tw, y + box[1] + th)


def _bezier(p0, p1, p2, n=60):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]) for t in (i / n for i in range(n + 1))]


def arrow(im, target_box, avoid):
    """One short, thick, strongly curved yellow arrow with a black outline, coming from the side with
    room and ending at the edge of the key detail (as the niche's best thumbnails draw it)."""
    x0, y0, x1, y1 = [v * s for v, s in zip(target_box, (W, H, W, H))]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    side = 1 if cx < W * 0.55 else -1                # come in from the side with more room
    length = 210
    ex = cx + side * ((x1 - x0) / 2 + 14)            # the tip just short of the detail's edge
    ey = cy + 10
    sx, sy = ex + side * length * 0.85, ey + length * 0.55
    sy = min(sy, H * SAFE_Y - 30)
    sx = min(max(sx, 50), W * SAFE_X - 30)
    if sy - ey < 60 and avoid[3] + 50 < ey:          # little room below: come from above instead
        sy = max(avoid[3] + 40, ey - length * 0.55)
    mx, my = (sx + ex) / 2, (sy + ey) / 2
    dx, dy = ex - sx, ey - sy
    n = math.hypot(dx, dy) or 1
    px, py = -dy / n, dx / n                        # perpendicular: the bulge of the curve
    bulge = 0.42 * n * (1 if side > 0 else -1)
    pts = _bezier((sx, sy), (mx + px * bulge, my + py * bulge), (ex, ey), 50)
    a2 = math.atan2(pts[-1][1] - pts[-4][1], pts[-1][0] - pts[-4][0])
    d = ImageDraw.Draw(im)

    def head(size):
        return [(ex + math.cos(a2) * size * 0.9, ey + math.sin(a2) * size * 0.9),
                (ex + math.cos(a2 + 2.5) * size, ey + math.sin(a2 + 2.5) * size),
                (ex + math.cos(a2 - 2.5) * size, ey + math.sin(a2 - 2.5) * size)]
    body = pts[:-6]
    for width, col, hs in ((36, (0, 0, 0), 62), (24, YELLOW, 50)):
        d.line(body, fill=col, width=width, joint="curve")
        r = width / 2
        d.ellipse((body[0][0] - r, body[0][1] - r, body[0][0] + r, body[0][1] + r), fill=col)
        d.polygon(head(hs), fill=col)


def compose(src, words, box):
    im = punch(cover(Image.open(src).convert("RGB")))
    # a gentle darkening at the very top so the white words hold on a bright sky
    top = Image.new("L", (W, H), 0)
    for yy in range(int(H * 0.38)):
        ImageDraw.Draw(top).line([(0, yy), (W, yy)], fill=int(110 * (1 - yy / (H * 0.38))))
    im.paste((10, 14, 24), (0, 0), top)
    hb = headline(im, words)
    if box:
        arrow(im, box, hb)
    return im


# ------------------------------------------------------------------ the run
def concepts(title):
    try:
        from core import llm
        ans = llm.complete_json(PLAN.format(title=title), max_tokens=1500, temperature=0.8)
        cs = [c for c in (ans.get("concepts") or []) if isinstance(c, dict) and c.get("prompt")][:3]
        if len(cs) == 3:
            return cs
    except Exception as e:                                               # noqa: BLE001
        log.warning("concepts: %s; the built-in plan", e)
    key = "moon" if "moon" in title.lower() else "moon"
    return FALLBACK[key]


def generate(prompts, work, slug):
    from automation import frames
    ref = frames._submit(prompts, [{"extra": i} for i in range(len(prompts))], work, slug)
    log.info("submitted %d prompts as %s", len(prompts), ref)
    if not frames._wait(ref):
        raise SystemExit(f"kernel {ref} did not complete")
    return frames._fetch(ref, work / "gpu")


def main(title, images_dir=None):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
    work = OUT / slug
    work.mkdir(parents=True, exist_ok=True)
    cs = concepts(title)
    takes = []
    for i, c in enumerate(cs):
        for v, extra in enumerate(("", ", seen from a low angle, even more dramatic")):
            takes.append({"concept": i, "take": v, "prompt": f"{c['prompt']}{extra}, {STYLE}", **c})
    if images_dir:
        imgs = sorted(Path(images_dir).glob("*.png"))
    else:
        imgs = generate([t["prompt"] for t in takes], work, f"tv2-{int(time.time())}")
    for t, p in zip(takes, imgs):
        t["image"] = str(p)
    return finish(title, takes, work)


def finish(title, takes, work):
    """Locate the key detail, compose, judge; the best take of each concept is a candidate."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    report = []
    for t in [t for t in takes if t.get("image")]:
        try:
            loc = ask(LOCATE.format(detail=t["detail"]), [t["image"]])
        except Exception as e:                                           # noqa: BLE001
            loc = {"found": False, "error": str(e)[:120]}
        t["locate"] = loc
        box = loc.get("box") if loc.get("found") and isinstance(loc.get("box"), list) and len(loc["box"]) == 4 else None
        out = work / f"take_{t['concept']}_{t['take']}.png"
        img = compose(t["image"], t["words"], box)
        img.save(out)
        small = work / f"take_{t['concept']}_{t['take']}_small.png"
        img.resize(SMALL, Image.LANCZOS).save(small)
        try:
            j = ask(JUDGE.format(title=title), [str(out), str(small)])
        except Exception as e:                                           # noqa: BLE001
            j = {"score": 0, "why": f"no judge: {str(e)[:100]}"}
        bad = loc.get("people_close") or loc.get("text_in_image") or loc.get("warped")
        t["judge"], t["file"] = j, str(out)
        t["rank"] = float(j.get("score") or 0) - (3 if bad else 0) - (1 if not box else 0) \
            + (0.5 if j.get("readable_small") else -1) + (0.5 if j.get("matches_episode") else -2)
        report.append({k: t.get(k) for k in ("concept", "take", "city", "words", "detail", "locate", "judge", "rank",
                                             "file")})
        log.info("take %d.%d %s: %.1f (%s)", t["concept"], t["take"], t["city"], t["rank"], j.get("why"))
    best_of = {}
    for t in takes:
        if t.get("file") and t["rank"] > best_of.get(t["concept"], {"rank": -99})["rank"]:
            best_of[t["concept"]] = t
    finals = sorted(best_of.values(), key=lambda t: -t["rank"])
    for n, t in enumerate(finals, 1):
        Image.open(t["file"]).save(work / f"candidate_{n}.png")
    if finals:
        Image.open(finals[0]["file"]).save(work / "chosen.png")
    (work / "report.json").write_text(json.dumps({"title": title, "takes": report,
                                                  "candidates": [t["file"] for t in finals]},
                                                 indent=1, ensure_ascii=False), encoding="utf-8")
    log.info("candidates: %s", [(t["city"], round(t["rank"], 1)) for t in finals])
    return 0 if finals else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--images", help="already generated pictures (a test): no kernel")
    a = ap.parse_args()
    sys.exit(main(a.title, a.images))
