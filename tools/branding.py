"""Channel avatar and banner, in the same visual language as the thumbnails.

Same three devices as every thumbnail: Anton set very large, white with one
amber accent, and a dark field. A channel page that uses a different vocabulary
from its own thumbnails reads as two channels.

The banner's safe area is the hard constraint. YouTube shows 2560x1440 on a TV
and crops to roughly 1546x423 on a phone, so everything that must survive lives
inside that centre box and the rest is atmosphere.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FONTS = ROOT / "assets" / "fonts"
OUT = ROOT / "output" / "branding"

AVATAR = 800
BANNER_W, BANNER_H = 2560, 1440
SAFE_W, SAFE_H = 1546, 423

BG = (9, 12, 20)
INK = (244, 247, 252)
ACCENT = (255, 184, 28)
DIM = (120, 132, 154)


def _font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def _starfield(im, density=900, seed=7):
    """A faint scatter of stars. Deterministic, so re-runs are identical."""
    import random
    rng = random.Random(seed)
    d = ImageDraw.Draw(im)
    for _ in range(density):
        x, y = rng.randrange(im.width), rng.randrange(im.height)
        v = rng.randrange(40, 150)
        r = 1 if rng.random() < 0.88 else 2
        d.ellipse([x, y, x + r, y + r], fill=(v, v, min(255, v + 18)))
    return im


def _glow(im, cx, cy, radius, colour, strength=150):
    layer = Image.new("L", im.size, 0)
    ImageDraw.Draw(layer).ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius], fill=strength)
    layer = layer.filter(ImageFilter.GaussianBlur(radius * 0.55))
    im.paste(Image.new("RGB", im.size, colour), (0, 0), layer)
    return im


def avatar_wordmark():
    """Variant A: the letter H as a monogram, with the arc of a world behind it."""
    im = Image.new("RGB", (AVATAR, AVATAR), BG)
    _starfield(im, 260, seed=3)
    # A planet edge sweeping the lower third, lit from the right.
    _glow(im, AVATAR * 0.78, AVATAR * 1.02, AVATAR * 0.52, (40, 86, 150), 120)
    d = ImageDraw.Draw(im)
    d.ellipse([-AVATAR * 0.30, AVATAR * 0.72, AVATAR * 1.30, AVATAR * 1.95],
              fill=(20, 38, 64), outline=(78, 128, 190), width=5)
    f = _font("Anton-Regular.ttf", 460)
    d.text((AVATAR / 2, AVATAR * 0.42), "H", font=f, fill=INK, anchor="mm",
           stroke_width=0)
    # The accent rule, the same device the thumbnails use, kept short enough to
    # read as a deliberate mark rather than a stray line at 88px.
    d.rectangle([AVATAR * 0.33, AVATAR * 0.645, AVATAR * 0.67, AVATAR * 0.685],
                fill=ACCENT)
    return im


def avatar_question():
    """Variant B: a cracked moon, no wording.

    An avatar is 88px in a subscription list. A word set across it is unreadable
    there - the first version put HYPOTHETICA over the disc and it collapsed into
    a grey smear. One shape, read in a glance, is the whole job.
    """
    im = Image.new("RGB", (AVATAR, AVATAR), BG)
    _starfield(im, 300, seed=11)
    _glow(im, AVATAR * 0.5, AVATAR * 0.5, AVATAR * 0.46, (90, 96, 112), 95)
    d = ImageDraw.Draw(im)
    # The moon disc.
    r = AVATAR * 0.38
    cx, cy = AVATAR * 0.5, AVATAR * 0.5
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(176, 180, 190))
    for spot in ((-0.35, -0.22, 0.17), (0.28, 0.10, 0.12), (-0.08, 0.32, 0.09)):
        sx, sy, sr = spot
        d.ellipse([cx + r * sx - r * sr, cy + r * sy - r * sr,
                   cx + r * sx + r * sr, cy + r * sy + r * sr],
                  fill=(150, 154, 165))
    # The fissure, glowing from within.
    crack = [(cx - r * 0.52, cy - r * 0.88), (cx - r * 0.12, cy - r * 0.08),
             (cx + r * 0.22, cy + r * 0.28), (cx + r * 0.10, cy + r * 0.88)]
    halo = Image.new("RGB", im.size, BG)
    ImageDraw.Draw(halo).line(crack, fill=ACCENT, width=34, joint="curve")
    halo = halo.filter(ImageFilter.GaussianBlur(22))
    im = Image.blend(im, halo, 0.45)
    d = ImageDraw.Draw(im)
    d.line(crack, fill=ACCENT, width=16, joint="curve")
    return im


def _banner_base(seed):
    im = Image.new("RGB", (BANNER_W, BANNER_H), BG)
    _starfield(im, 2200, seed=seed)
    return im


def banner_horizon():
    """Variant A: name centred, a planet limb rising under it."""
    im = _banner_base(5)
    _glow(im, BANNER_W * 0.5, BANNER_H * 1.18, BANNER_W * 0.42, (36, 78, 140), 130)
    d = ImageDraw.Draw(im)
    d.ellipse([-BANNER_W * 0.2, BANNER_H * 0.86, BANNER_W * 1.2, BANNER_H * 2.4],
              fill=(17, 33, 56), outline=(72, 120, 180), width=6)
    cx, cy = BANNER_W // 2, BANNER_H // 2
    f = _font("Anton-Regular.ttf", 250)
    d.text((cx, cy - 70), "HYPOTHETICA", font=f, fill=INK, anchor="mm")
    w = d.textlength("HYPOTHETICA", font=f)
    d.rectangle([cx - w / 2, cy + 52, cx + w / 2, cy + 68], fill=ACCENT)
    d.text((cx, cy + 135), "WHAT IF  .  THE SCIENCE OF SCENARIOS THAT NEVER HAPPEN",
           font=_font("BebasNeue-Regular.ttf", 86), fill=DIM, anchor="mm")
    return im


def banner_eclipse():
    """Variant B: the name beside a cracked moon, weighted off-centre."""
    im = _banner_base(23)
    cx, cy = BANNER_W * 0.5, BANNER_H * 0.5
    # The moon sits just inside the safe box, on its right edge.
    mx, my, r = cx + SAFE_W * 0.33, cy, SAFE_H * 0.46
    _glow(im, mx, my, r * 2.1, (120, 96, 60), 110)
    d = ImageDraw.Draw(im)
    d.ellipse([mx - r, my - r, mx + r, my + r], fill=(168, 172, 182))
    d.line([(mx - r * 0.45, my - r * 0.92), (mx - r * 0.05, my - r * 0.05),
            (mx + r * 0.25, my + r * 0.3), (mx + r * 0.12, my + r * 0.9)],
           fill=ACCENT, width=9, joint="curve")
    f = _font("Anton-Regular.ttf", 232)
    tx = cx - SAFE_W * 0.47
    d.text((tx, cy - 60), "HYPOTHETICA", font=f, fill=INK, anchor="lm")
    w = d.textlength("HYPOTHETICA", font=f)
    d.rectangle([tx, cy + 58, tx + w * 0.42, cy + 74], fill=ACCENT)
    d.text((tx, cy + 138), "WHAT IF  .  REAL PHYSICS, IMPOSSIBLE PREMISES",
           font=_font("BebasNeue-Regular.ttf", 80), fill=DIM, anchor="lm")
    return im


def safe_overlay(im):
    """A copy with the phone-crop box drawn, to check what survives."""
    preview = im.copy()
    d = ImageDraw.Draw(preview)
    x0, y0 = (BANNER_W - SAFE_W) // 2, (BANNER_H - SAFE_H) // 2
    d.rectangle([x0, y0, x0 + SAFE_W, y0 + SAFE_H], outline=(255, 80, 80), width=5)
    d.text((x0 + 10, y0 + 8), "SAFE AREA 1546x423",
           font=_font("BebasNeue-Regular.ttf", 48), fill=(255, 120, 120))
    return preview


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in (("avatar_a_monogram", avatar_wordmark),
                     ("avatar_b_moon", avatar_question)):
        im = fn()
        im.save(OUT / f"{name}.png")
        im.resize((88, 88), Image.LANCZOS).save(OUT / f"{name}_small.png")
        print(f"  {name}.png  {im.size}")
    for name, fn in (("banner_a_horizon", banner_horizon),
                     ("banner_b_eclipse", banner_eclipse)):
        im = fn()
        im.save(OUT / f"{name}.png")
        safe_overlay(im).save(OUT / f"{name}_safe.png")
        print(f"  {name}.png  {im.size}  ({(OUT / f'{name}.png').stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
