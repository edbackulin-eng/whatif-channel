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
SMALL = (320, 180)                   # owner 17.11: the preview it must read at
FONT = ROOT / "assets" / "fonts" / "Anton-Regular.ttf"
YELLOW = (255, 214, 0)
VISION = ("gemini-flash-latest", "gemini-flash-lite-latest")
SAFE_X, SAFE_Y = 0.78, 0.80          # YouTube's duration pill, bottom right

# owner 18.11 (the niche's reference, second word): a REAL PHOTOGRAPH from a drone at bright midday - never a
# cartoon, a painting, a 3D render or a dark night; more steps, a bigger picture and a true negative prompt
STYLE = ("real photograph, aerial drone shot, bright midday sun, photorealistic, high detail, cinematic, "
         "clear bright sky, vivid natural colours, crisp sharp focus, lots of concrete detail (cars, buses, debris, "
         "ice, water), no text, no letters, no logos, no people in the foreground")
PHOTO = "real photograph, aerial drone shot, bright midday sun"     # first: the words that weigh most
NEGATIVE = "cartoon, illustration, painting, 3d render, anime, dark, night, drawing, cgi, video game, text, watermark"
THUMB_GEN = {"steps": 8, "width": 1536, "height": 864, "negative_prompt": NEGATIVE, "true_cfg_scale": 2.0}

PLAN = """You design YouTube thumbnails for a science channel about global catastrophes ("What Would Happen
If ...?"). The winning style: a REAL aerial drone PHOTOGRAPH at bright midday (never a cartoon, painting or 3D
render, never dark) of a FAMOUS CITY (New York, London, Tokyo, Paris,
Dubai, Sydney, Rio, Hong Kong ...) at the very moment of the catastrophe - the city in crisis, the event huge and
unmistakable - plus one or two enormous words at the top and one yellow arrow on the key detail.
Episode: "{title}".
THE LOGIC (owner 18.11): the picture shows the VISIBLE CONSEQUENCE of the premise on the city, so a viewer
understands the episode without reading - a year of rain -> the city drowned in brown flood water; no sun -> the
whole city frozen in ice, taxis and buses under snow; the Earth stops spinning -> a storm wind tearing the street
apart; an asteroid in the ocean -> a giant wave over the skyline; the Moon twice as close -> a huge Moon and the sea
flooding the streets. First decide what the premise DOES to a city, then draw that.
Give 3 clearly different concepts (different city, different moment, different key detail). For each:
"city", "prompt": an English FLUX prompt (the scene only, 40-70 words, wide shot; the top third of the frame is
calm empty BRIGHT sky for the words (owner 18.11: daylight or bright golden hour, never a dark night
scene - the reference thumbnails are light, vivid and full of concrete detail: frozen taxis and buses, a wave over
Manhattan, a tornado throwing a bus), and the event itself is HUGE and fully visible in the middle of the frame, between a
third and four fifths of the height, never behind the words (18.11: a giant moon hidden under the headline lost
every take), a strong contrast of cold and warm
colour (blue ice or water against fire, orange light or a yellow accent; grey city against a warm glow), no people
close up, no text). The scene must be one the film itself shows (it is used as a shot of the film),
"detail": the one thing the arrow points at (a few English words, e.g. "the giant moon", "the wave crest"),
"words": 1-3 words, UPPER CASE, max 16 characters in all, naming THIS episode's event (styles seen on other
episodes: "WHAT IF", "NO SUN", "365 DAYS OF RAIN?" - never one that belongs to another event, never one that
says something the episode does not (18.11: "DOUBLE MOON" for a Moon twice as close); "WHAT IF" is always right).
Answer as JSON: {{"concepts": [{{"city": "...", "prompt": "...", "detail": "...", "words": "..."}}]}}"""

FALLBACK = {
    "moon": [
        {"city": "New York", "words": "WHAT IF",
         "detail": "the giant moon",
         "prompt": "Manhattan skyline at dusk seen from the Hudson River, a gigantic full Moon twice its normal "
                   "size hanging low between the skyscrapers filling the upper sky, enormous tidal surge flooding "
                   "the waterfront and streets, waves crashing over piers, glowing city lights, storm clouds lit "
                   "by moonlight"},
        {"city": "London", "words": "WHAT IF?",
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
2. the picture shows the visible CONSEQUENCE of the episode's premise on the city, so the topic is understood
   without reading (a year of rain -> a drowned city; no sun -> a city in ice); a scene that does not follow from
   the premise means matches_episode false;
3. 1-3 big condensed words at the top (about a quarter of the height), white/light grey with depth and shadow;
4. one yellow curved arrow pointing at the key detail;
5. a BRIGHT, light picture (daylight), vivid saturated colours, rich concrete detail - a dark night scene is a
   defect; the words and the event still readable on the 320x180 preview (the second image);
6. no people close up, no text except the headline, nothing warped or AI-looking;
7. it must look like a REAL PHOTOGRAPH (owner 18.11): a cartoon, an illustration, a painting, a drawing, a 3D
   render / CGI / video-game look, or a dark / night picture is REJECTED whatever else it does well
   ("photoreal": false or "dark": true).
Answer as JSON: {{"score": <0-10>, "readable_small": true|false, "matches_episode": true|false,
"photoreal": true|false, "dark": true|false,
"defects": ["..."], "why": "<one sentence>"}}"""


# ------------------------------------------------------------------ drawing
def cover(im, w=W, h=H):
    s = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def split_tone(im, amount=0.22):
    """Cold shadows, warm highlights: the blue-against-fire contrast that reads at 320x180 (owner 17.11)."""
    import numpy as np
    a = np.asarray(im.convert("RGB")).astype(np.float32) / 255.0
    lum = (0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2])[..., None]
    cold, warm = np.array([0.10, 0.35, 0.75]), np.array([1.0, 0.62, 0.20])
    w = np.clip((lum - 0.25) / 0.5, 0, 1)
    tint = cold * (1 - w) + warm * w
    out = a * (1 - amount) + (a * 0.5 + tint * lum) * amount
    return Image.fromarray((np.clip(out, 0, 1) * 255).astype("uint8"))


# owner 18.11: the niche's six reference thumbnails measured at 320x180 (mean): brightness (mean luma 0-1),
# saturation (mean HSV S 0-1), contrast (luma std), sharpness (variance of the edge filter). Ours were darker,
# softer and far MORE saturated (0.55-0.85) - the cartoon look. Only the numbers are kept, not the pictures.
REF = {"bright": 0.408, "sat": 0.324, "contrast": 0.222, "sharp": 4733.0}
REJECT = {"bright": 0.85, "contrast": 0.80, "sharp": 0.75, "sat_low": 0.55, "sat_high": 1.75}


def measure(im):
    import numpy as np
    t = im.convert("RGB").resize(SMALL, Image.LANCZOS)
    a = np.asarray(t).astype("float32") / 255.0
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    sat = np.asarray(t.convert("HSV")).astype("float32")[..., 1] / 255.0
    edge = np.asarray(t.convert("L").filter(ImageFilter.FIND_EDGES)).astype("float32")
    return {"bright": round(float(lum.mean()), 3), "sat": round(float(sat.mean()), 3),
            "contrast": round(float(lum.std()), 3), "sharp": round(float(edge.var()), 1)}


def below_reference(m):
    """What makes a picture noticeably worse than the reference (owner 18.11): an empty list passes."""
    why = [f"{k} {m[k]} < {REJECT[k]:.0%} of {REF[k]}" for k in ("bright", "contrast", "sharp")
           if m[k] < REF[k] * REJECT[k]]
    if m["sat"] < REF["sat"] * REJECT["sat_low"]:
        why.append(f"sat {m['sat']} dull")
    if m["sat"] > REF["sat"] * REJECT["sat_high"]:
        why.append(f"sat {m['sat']} cartoon-saturated")
    return why


def grade(im):
    """A light correction toward the reference's level: brightness, saturation, contrast, sharpness."""
    m = measure(im)

    def clamp(v, lo, hi):
        return max(lo, min(hi, v))
    im = ImageEnhance.Brightness(im).enhance(clamp(REF["bright"] / max(m["bright"], 1e-3), 1.0, 1.25))
    im = ImageEnhance.Color(im).enhance(clamp(REF["sat"] * 1.15 / max(m["sat"], 1e-3), 0.65, 1.20))
    im = ImageEnhance.Contrast(im).enhance(clamp(REF["contrast"] / max(m["contrast"], 1e-3), 1.0, 1.15))
    # the reference's sharpness counts its words' edges too: a raw picture is held to about two thirds of it
    return ImageEnhance.Sharpness(im).enhance(clamp((REF["sharp"] * 0.65 / max(m["sharp"], 1.0)) ** 0.5, 1.1, 1.7))


def punch(im):
    im = split_tone(im, 0.10)
    im = ImageEnhance.Brightness(im).enhance(1.08)
    im = ImageEnhance.Color(im).enhance(1.30)
    im = ImageEnhance.Contrast(im).enhance(1.18)
    return ImageEnhance.Sharpness(im).enhance(1.4)


def _fit(text, max_w, max_h=H * 0.24, start=300):
    """The largest Anton size whose letters fit the width and stand about a third of the height (owner 17.11)."""
    size = start
    while size > 40:
        f = ImageFont.truetype(str(FONT), size)
        b = f.getbbox(text)
        if f.getlength(text) <= max_w and (b[3] - b[1]) <= max_h:
            return f
        size -= 6
    return ImageFont.truetype(str(FONT), size)


def headline(im, text, top=18):
    """White-to-light-grey letters with depth (a stepped darker extrusion) and a soft hard shadow."""
    # owner 18.11 reference: the words stand about a quarter of the height and leave the picture room
    f = _fit(text, W * (0.62 if len(text) <= 8 else 0.86))
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
    d.text((x, y), text, font=f, fill=(30, 30, 38), stroke_width=6, stroke_fill=(20, 20, 26))   # dark outline
    im.paste(grad, (0, 0), mask)
    return (x + box[0], y + box[1], x + box[0] + tw, y + box[1] + th)


def _bezier(p0, p1, p2, n=60):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]) for t in (i / n for i in range(n + 1))]


def _dense(pts, step=2.0):
    out = [pts[0]]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        out += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(1, n + 1)]
    return out


def arrow(im, target_box, avoid):
    """One short, thick, strongly curved yellow arrow with a black outline, coming from the side with
    room and ending at the edge of the key detail (as the niche's best thumbnails draw it)."""
    x0, y0, x1, y1 = [v * s for v, s in zip(target_box, (W, H, W, H))]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    side = 1 if cx < W * 0.55 else -1                # come in from the side with more room
    length = 210
    ex = cx + side * ((x1 - x0) / 2 + 14)            # the tip just short of the detail's edge
    ey = cy + 10
    if ey < avoid[3] + 30:                           # the detail reaches into the words: point below them
        ey = min(max(avoid[3] + 30, y0 + 10), max(y1 - 10, avoid[3] + 30))
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
        r = width / 2
        for px_, py_ in _dense(body):                # round brush along the curve: no jagged joints
            d.ellipse((px_ - r, py_ - r, px_ + r, py_ + r), fill=col)
        d.polygon(head(hs), fill=col)


GENERIC = {"WHAT", "IF", "NO", "TOO", "THE", "A", "OF"}


def safe_words(words, title):
    """Only words the episode says (a stem of a title word) or the generic ones; else WHAT IF? (owner 18.11:
    the model kept writing DOUBLE MOON for a Moon twice as close)."""
    stems = [w[:4] for w in re.findall(r"[A-Z0-9]+", title.upper()) if len(w) > 2]
    for tok in re.findall(r"[A-Z0-9]+", (words or "").upper()):
        if tok not in GENERIC and not any(tok[:4] == st for st in stems):
            log.info("words %r say what the episode does not (%s): WHAT IF?", words, tok)
            return "WHAT IF?"
    return words or "WHAT IF?"


def norm_box(b):
    """Fractions 0-1, x0 < x1, y0 < y1; a box in the vision model's 0-1000 scale is scaled down."""
    try:
        b = [float(v) for v in b]
    except (TypeError, ValueError):
        return None
    if max(b) > 1.5:
        b = [v / 1000 for v in b]
    x0, y0, x1, y1 = (min(max(v, 0.0), 1.0) for v in b)
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    return [x0, y0, x1, y1] if x1 - x0 > 0.01 and y1 - y0 > 0.01 else None


def lower(im, shift):
    """The picture moved down by `shift` px, the top filled with its own sky stretched and blurred."""
    out = Image.new("RGB", (W, H))
    out.paste(im.crop((0, 0, W, H - shift)), (0, shift))
    sky = im.crop((0, 0, W, max(8, H // 12))).resize((W, shift + 40), Image.BICUBIC).filter(ImageFilter.GaussianBlur(18))
    out.paste(sky.crop((0, 0, W, shift)), (0, 0))
    seam = Image.new("L", (W, 40), 0)
    for yy in range(40):
        ImageDraw.Draw(seam).line([(0, yy), (W, yy)], fill=int(255 * (1 - yy / 40)))
    out.paste(sky.crop((0, shift, W, shift + 40)), (0, shift), seam)
    return out


def compose(src, words, box, graded=True):
    im = cover(Image.open(src).convert("RGB"))
    if graded:
        im = grade(im)                                      # 18.11: toward the reference, no cartoon punch
    box = norm_box(box) if box else None
    if box:
        # 18.11: the event must not hide under the words - move the picture down when it reaches into them
        f = _fit(words, W * (0.62 if len(words) <= 8 else 0.86))
        bb = f.getbbox(words)
        words_bottom = 18 + (bb[3] - bb[1]) + 24
        if box[1] * H < words_bottom and (box[1] + box[3]) / 2 < 0.5:
            shift = int(min(words_bottom - box[1] * H, H * 0.3))
            im = lower(im, shift)
            box = [box[0], box[1] + shift / H, box[2], min(1.0, box[3] + shift / H)]
    # a gentle darkening at the very top so the white words hold on a bright sky
    top = Image.new("L", (W, H), 0)
    for yy in range(int(H * 0.45)):
        ImageDraw.Draw(top).line([(0, yy), (W, yy)], fill=int(45 * (1 - yy / (H * 0.45))))   # 18.11: barely - the reference is light
    im.paste((10, 14, 24), (0, 0), top)
    hb = headline(im, words)
    if box:
        arrow(im, box, hb)
    return im


# ------------------------------------------------------------------ the run
def _generic(title):
    """The built-in plan for any title (18.11: it used to be the Moon's for every episode - the Sun got moons):
    the visible consequence of the premise on three famous cities, in daylight, WHAT IF?."""
    premise = re.sub(r"(?i)^what would happen if\s*", "", title).rstrip("?").strip() or title
    scenes = [("New York", "Manhattan seen from across the river"), ("London", "central London along the Thames"),
              ("Tokyo", "a wide Tokyo avenue")]
    return [{"city": c, "words": "WHAT IF?", "detail": "the catastrophe",
             "prompt": f"{view} in bright daylight, wide shot, the city at the very moment of this catastrophe: "
                       f"{premise} - its visible consequence for the city shown huge and unmistakable in the middle "
                       "of the frame, lots of concrete detail (cars, buses, debris), the top third calm bright sky"}
            for c, view in scenes]


def concepts(title):
    from core import llm
    prompt = PLAN.format(title=title)
    for how in ("json", "text"):                 # 18.11: Groq refused its own JSON mode; plain text parsed here
        try:
            if how == "json":
                ans = llm.complete_json(prompt, max_tokens=2500, temperature=0.8)
            else:
                ans = llm.extract_json(llm.complete(prompt + " Reply with the JSON only.", max_tokens=2500,
                                                    temperature=0.6))
            cs = [c for c in (ans.get("concepts") or []) if isinstance(c, dict) and c.get("prompt")][:3]
            if len(cs) == 3:
                return cs
        except Exception as e:                                           # noqa: BLE001
            log.warning("concepts (%s): %s", how, str(e)[:200])
    log.warning("concepts: the built-in plan from the title")
    return FALLBACK["moon"] if "moon" in title.lower() else _generic(title)


def generate(prompts, work, slug):
    from automation import frames
    ref = frames._submit(prompts, [{"extra": i} for i in range(len(prompts))], work, slug,
                         overrides={i: THUMB_GEN for i in range(len(prompts))})
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
        for v, extra in enumerate(("", ", a closer aerial view, even more dramatic")):
            takes.append({"concept": i, "take": v, "prompt": f"{PHOTO}, {c['prompt']}{extra}, {STYLE}", **c})
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
        t["words"] = safe_words(t["words"], title)
        # owner 18.11: the thumbnail as it would be, before any correction, measured against the reference
        t["metrics"] = measure(compose(t["image"], t["words"], box, graded=False))
        t["below_ref"] = below_reference(t["metrics"])
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
            + (0.5 if j.get("readable_small") else -1) + (0.5 if j.get("matches_episode") else -4)
        # owner 18.11: below the reference in numbers, or a cartoon / painted / dark picture - out
        t["rejected"] = list(t["below_ref"]) + (["judge: not a photograph"] if j.get("photoreal") is False else []) \
            + (["judge: dark"] if j.get("dark") else [])
        report.append({k: t.get(k) for k in ("concept", "take", "city", "words", "detail", "locate", "judge", "rank",
                                             "metrics", "rejected", "file")})
        log.info("take %d.%d %s: %.1f (%s)", t["concept"], t["take"], t["city"], t["rank"], j.get("why"))
    best_of = {}
    for t in takes:
        if t.get("file") and not t.get("rejected") and t["rank"] > best_of.get(t["concept"], {"rank": -99})["rank"]:
            best_of[t["concept"]] = t
    finals = sorted(best_of.values(), key=lambda t: -t["rank"])
    for n, t in enumerate(finals, 1):
        im = Image.open(t["file"]).convert("RGB")
        im.save(work / f"candidate_{n}.png")
        im.resize(SMALL, Image.LANCZOS).save(work / f"candidate_{n}_320.png")
    if finals:
        im = Image.open(finals[0]["file"]).convert("RGB")
        im.save(work / "chosen.png")
        im.save(work / "chosen.jpg", quality=92, optimize=True)          # YouTube takes thumbnails up to 2 MB
    (work / "report.json").write_text(json.dumps({"title": title, "takes": report,
                                                  "candidates": [t["file"] for t in finals],
                                                  "chosen_image": finals[0]["image"] if finals else None,
                                                  "chosen_detail": finals[0]["detail"] if finals else None},
                                                 indent=1, ensure_ascii=False), encoding="utf-8")
    log.info("candidates: %s", [(t["city"], round(t["rank"], 1)) for t in finals])
    return 0 if finals else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--images", help="already generated pictures (a test): no kernel")
    a = ap.parse_args()
    sys.exit(main(a.title, a.images))
