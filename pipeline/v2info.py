"""Animated cards and maps for the v2 montage (owner 15.11): exact numbers, drawn in code.

    render(shot, seconds, out)    shot["info"] = {"kind": ..., ...}

kinds
  counter  a number counting up (or down) to its value, with a label and a unit
  timer    "T+ 00:12:00" ticking from `from` to `to` (seconds of story time), with a label
  temp     a thermometer filling to a temperature in deg C
  compare  two bars growing to their values (e.g. today vs then)
  days     "DAY 1 ... DAY 365" with a progress line
  map      the Earth (NASA Blue Marble, public domain) with pulsing markers at lat/lon and labels

Every frame is drawn with Pillow and piped to ffmpeg at 1920x1080, 30 fps. The numbers come from the
script's own sourced claims; nothing here invents one.
"""
import math
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
W, H, FPS = 1920, 1080, 30
FONT = ROOT / "assets" / "fonts" / "Anton-Regular.ttf"
FONT2 = ROOT / "assets" / "fonts" / "BebasNeue-Regular.ttf"
AMBER = (255, 184, 28)
CYAN = (90, 210, 255)
RED = (255, 80, 60)
EARTH = ROOT / "assets" / "textures" / "blue_marble_5400.jpg"


def _f(size, bold=True):
    return ImageFont.truetype(str(FONT if bold else FONT2), size)


def _ease(t):
    t = min(1.0, max(0.0, t))
    return 1 - (1 - t) ** 3


_bg_cache = {}


def _background(seed=0):
    """A deep blue-black gradient with a faint grid and vignette."""
    if seed in _bg_cache:
        return _bg_cache[seed].copy()
    y = np.linspace(0, 1, H)[:, None]
    x = np.linspace(0, 1, W)[None, :]
    r = 6 + 10 * (1 - y) + 0 * x
    g = 12 + 18 * (1 - y) + 0 * x
    b = 24 + 40 * (1 - y) + 0 * x
    d = np.sqrt((x - 0.5) ** 2 + (y - 0.45) ** 2)
    v = np.clip(1.15 - d * 1.1, 0.35, 1.0)
    img = np.stack([r * v, g * v, b * v], -1).clip(0, 255).astype(np.uint8)
    im = Image.fromarray(img)
    dr = ImageDraw.Draw(im)
    for gx in range(0, W, 80):
        dr.line([(gx, 0), (gx, H)], fill=(20, 34, 52), width=1)
    for gy in range(0, H, 80):
        dr.line([(0, gy), (W, gy)], fill=(20, 34, 52), width=1)
    _bg_cache[seed] = im
    return im.copy()


def _glow_text(im, xy, text, font, fill, anchor="mm", glow=16):
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, text, font=font, fill=fill + (255,), anchor=anchor)
    blur = layer.filter(ImageFilter.GaussianBlur(glow))
    im.paste(blur, (0, 0), blur)
    im.paste(layer, (0, 0), layer)


def _fmt(v, unit=""):
    if abs(v) >= 1e9:
        s = f"{v / 1e9:.1f} billion"
    elif abs(v) >= 1e6:
        s = f"{v / 1e6:.1f} million"
    elif abs(v) >= 100:
        s = f"{int(round(v)):,}"
    else:
        s = f"{v:.1f}".rstrip("0").rstrip(".")
    return f"{s}{(' ' + unit) if unit else ''}"


def _caption(im, label, t):
    if not label:
        return
    a = int(255 * _ease(t * 3))
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((W // 2, int(H * 0.22)), label.upper(), font=_f(64, False),
                               fill=(220, 230, 240, a), anchor="mm")
    im.paste(layer, (0, 0), layer)


def counter(info, t):
    im = _background()
    a, b = float(info.get("from", 0)), float(info.get("value", 0))
    v = a + (b - a) * _ease(t / 0.75)
    _caption(im, info.get("label"), t)
    _glow_text(im, (W // 2, H // 2 + 20), _fmt(v, info.get("unit", "")), _f(190), AMBER)
    return im


def timer(info, t):
    im = _background(1)
    a, b = float(info.get("from", 0)), float(info.get("to", info.get("value", 3600)))
    v = int(a + (b - a) * _ease(t / 0.85))
    d, r = divmod(v, 86400)
    hh, r = divmod(r, 3600)
    mm, ss = divmod(r, 60)
    txt = (f"T+ {d}d {hh:02d}:{mm:02d}:{ss:02d}" if d else f"T+ {hh:02d}:{mm:02d}:{ss:02d}")
    _caption(im, info.get("label"), t)
    _glow_text(im, (W // 2, H // 2 + 20), txt, _f(170), CYAN)
    return im


def temp(info, t):
    im = _background(2)
    v_to = float(info.get("value", 0))
    v_from = float(info.get("from", 15))
    v = v_from + (v_to - v_from) * _ease(t / 0.8)
    lo, hi = min(-80, v_to, v_from), max(60, v_to, v_from)
    dr = ImageDraw.Draw(im)
    x0, y0, x1, y1 = W // 2 - 520, 300, W // 2 - 440, 900
    dr.rounded_rectangle((x0, y0, x1, y1), 40, outline=(180, 200, 220), width=6)
    frac = (v - lo) / (hi - lo)
    col = RED if v > 25 else (CYAN if v < 0 else AMBER)
    dr.rounded_rectangle((x0 + 12, y1 - 12 - (y1 - y0 - 24) * frac, x1 - 12, y1 - 12), 30, fill=col)
    _caption(im, info.get("label"), t)
    _glow_text(im, (W // 2 + 150, H // 2 + 40), f"{v:+.0f} °C".replace("+", "+" if v > 0 else ""), _f(200), col)
    return im


def compare(info, t):
    im = _background(3)
    items = info.get("items") or [{"label": "today", "value": 1}, {"label": "then", "value": 2}]
    mx = max(float(i["value"]) for i in items) or 1
    dr = ImageDraw.Draw(im)
    n = len(items)
    for k, it in enumerate(items[:4]):
        cx = W // 2 + int((k - (n - 1) / 2) * 420)
        hgt = 560 * float(it["value"]) / mx * _ease(t / 0.8 - k * 0.1)
        col = [CYAN, AMBER, RED, (150, 255, 150)][k % 4]
        dr.rectangle((cx - 110, 900 - hgt, cx + 110, 900), fill=col)
        dr.text((cx, 950), str(it["label"]).upper(), font=_f(54, False), fill=(220, 230, 240), anchor="mm")
        dr.text((cx, 870 - hgt), _fmt(float(it["value"]) * min(1, _ease(t / 0.8)), info.get("unit", "")),
                font=_f(64), fill=(255, 255, 255), anchor="mm")
    _caption(im, info.get("label"), t)
    return im


def days(info, t):
    im = _background(4)
    total = int(info.get("value", 365))
    d = max(1, int(round(total * _ease(t / 0.85))))
    _caption(im, info.get("label"), t)
    _glow_text(im, (W // 2, H // 2), f"DAY {d}", _f(220), AMBER)
    dr = ImageDraw.Draw(im)
    dr.rectangle((360, 760, W - 360, 776), fill=(40, 60, 80))
    dr.rectangle((360, 760, 360 + (W - 720) * d / total, 776), fill=AMBER)
    return im


_earth = {}


def _map_base():
    if "im" not in _earth:
        if EARTH.exists():
            e = Image.open(EARTH).convert("RGB").resize((W, H), Image.LANCZOS)
        else:                                          # no texture: a plain ocean-blue plate
            e = Image.new("RGB", (W, H), (18, 40, 80))
        from PIL import ImageEnhance
        _earth["im"] = ImageEnhance.Brightness(e).enhance(0.8)
    return _earth["im"].copy()


def map_(info, t):
    im = _map_base()
    places = info.get("places") or []
    over = Image.new("RGBA", im.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(over)
    for k, p in enumerate(places[:6]):
        try:
            x = (float(p["lon"]) + 180) / 360 * W
            y = (90 - float(p["lat"])) / 180 * H
        except (KeyError, TypeError, ValueError):
            continue
        ph = (t * 2.2 + k * 0.3) % 1.0
        r = 18 + 90 * ph
        dr.ellipse((x - r, y - r, x + r, y + r), outline=RED + (int(255 * (1 - ph)),), width=6)
        dr.ellipse((x - 14, y - 14, x + 14, y + 14), fill=RED + (255,))
        if p.get("name"):
            dr.text((x + 26, y - 30), str(p["name"]).upper(), font=_f(46, False), fill=(255, 255, 255, 255),
                    stroke_width=4, stroke_fill=(0, 0, 0, 255))
    if info.get("zone"):                               # a band of latitudes shaded (e.g. the tides' bulge)
        z0, z1 = info["zone"]
        y0, y1 = (90 - float(z1)) / 180 * H, (90 - float(z0)) / 180 * H
        dr.rectangle((0, y0, W, y1), fill=(255, 80, 60, int(70 + 40 * math.sin(t * 6))))
    im.paste(over, (0, 0), over)
    _caption(im, info.get("label"), t)
    return im


KINDS = {"counter": counter, "timer": timer, "temp": temp, "compare": compare, "days": days, "map": map_}


def render(info, seconds, out, zoom=0.06):
    """The card as an mp4 (yuv420p, 30 fps), with a slow push in."""
    fn = KINDS.get(info.get("kind"), counter)
    n = max(1, int(round(seconds * FPS)))
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt",
                          "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset",
                          "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
    for k in range(n):
        t = k / max(1, n - 1)
        im = fn(info, t)
        z = 1 + zoom * t
        if z > 1.0001:
            w2, h2 = int(W / z), int(H / z)
            im = im.crop(((W - w2) // 2, (H - h2) // 2, (W - w2) // 2 + w2, (H - h2) // 2 + h2)).resize((W, H))
        p.stdin.write(np.asarray(im.convert("RGB")).tobytes())
    p.stdin.close()
    if p.wait():
        raise RuntimeError(f"card render failed: {out}")
    return out
