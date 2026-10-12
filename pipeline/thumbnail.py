"""Thumbnails in the channel's house style, with a legibility check at browse size.

The style rules come from what the leaders in this niche actually do: one dramatic
focal image, two to four enormous words, a heavy dark outline so the type survives
any background, and a warm accent colour against a cold space-blue frame. Nothing
small, nothing centred-and-timid, no logo.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from core.logger import get_logger

log = get_logger("thumbnail")

W, H = 1280, 720
# YouTube's smallest common browse size. Type has to read here or it does not work.
BROWSE_W, BROWSE_H = 168, 94

ACCENT = (255, 184, 28)      # warm amber, the channel's one accent
WHITE = (255, 255, 255)
STROKE = (8, 10, 18)         # near-black outline, never pure black

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"


def _font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def _fit_lines(draw, lines, font_name, max_width, start_size):
    """Largest font size at which every line fits the usable width."""
    size = start_size
    while size > 24:
        font = _font(font_name, size)
        if all(draw.textlength(l, font=font) <= max_width for l in lines):
            return font
        size -= 4
    return _font(font_name, 24)


def _base_image(source, darken=0.55, blur=0):
    """Cover-crop the source to 16:9 and push it back so type sits on top of it."""
    im = Image.open(source).convert("RGB")
    scale = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    left, top = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((left, top, left + W, top + H))
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    im = ImageEnhance.Brightness(im).enhance(darken)
    # A touch more saturation and contrast: space photos are flat out of the archive.
    im = ImageEnhance.Color(im).enhance(1.25)
    im = ImageEnhance.Contrast(im).enhance(1.15)
    return im


def _vignette(im, strength=0.75):
    """Darken the edges so the centre reads first."""
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).ellipse((-W * 0.25, -H * 0.45, W * 1.25, H * 1.45), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(160))
    dark = ImageEnhance.Brightness(im).enhance(1 - strength)
    return Image.composite(im, dark, mask)


def _glow_text(im, xy, text, font, fill, stroke_w, anchor="la", glow=18, boxes=None):
    """Draw text with a soft dark glow behind it, then a hard outline on top.

    Appends the drawn bounding box to `boxes`, which the legibility check needs in
    order to measure the type itself rather than the picture behind it.
    """
    halo = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(halo).text(xy, text, font=font, fill=(0, 0, 0, 215), anchor=anchor,
                              stroke_width=stroke_w + 6, stroke_fill=(0, 0, 0, 215))
    im.alpha_composite(halo.filter(ImageFilter.GaussianBlur(glow)))
    draw = ImageDraw.Draw(im)
    draw.text(xy, text, font=font, fill=fill, anchor=anchor,
              stroke_width=stroke_w, stroke_fill=STROKE)
    if boxes is not None:
        boxes.append(draw.textbbox(xy, text, font=font, anchor=anchor,
                                   stroke_width=stroke_w))


def _bar(im, box, color, alpha=235):
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rectangle(box, fill=(*color, alpha))
    im.alpha_composite(layer)


def variant_a(source, lines, accent_line=-1):
    """Bottom-left stack, the workhorse: biggest type, most contrast."""
    im = _vignette(_base_image(source, darken=0.52)).convert("RGBA")
    draw = ImageDraw.Draw(im)
    boxes = []
    margin = 54
    font = _fit_lines(draw, lines, "Anton-Regular.ttf", W - 2 * margin, 168)
    line_h = font.size * 1.02
    total = line_h * len(lines)
    y = H - margin - total
    for i, line in enumerate(lines):
        fill = ACCENT if i == accent_line % len(lines) else WHITE
        _glow_text(im, (margin, y + i * line_h), line, font, fill, stroke_w=9, boxes=boxes)
    return im.convert("RGB"), boxes


def variant_b(source, lines, accent_line=-1):
    """Type left, subject right: a scrim that fades out instead of a solid band, so
    the focal point of the photo stays visible next to the words."""
    im = _base_image(source, darken=0.74).convert("RGBA")
    # Push the crop left so the subject sits in the right half, clear of the type.
    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = scrim.load()
    for x in range(W):
        # Opaque at the left edge, gone by about two thirds across.
        a = int(max(0.0, 1.0 - (x / (W * 0.66))) ** 1.4 * 232)
        for y_ in range(H):
            px[x, y_] = (5, 8, 20, a)
    im.alpha_composite(scrim)
    draw = ImageDraw.Draw(im)
    boxes = []
    margin = 52
    usable = int(W * 0.56)
    font = _fit_lines(draw, lines, "BebasNeue-Regular.ttf", usable, 180)
    line_h = font.size * 0.9
    total = line_h * len(lines)
    y = (H - total) / 2
    for i, line in enumerate(lines):
        fill = ACCENT if i == accent_line % len(lines) else WHITE
        _glow_text(im, (margin, y + i * line_h), line, font, fill,
                   stroke_w=8, glow=16, boxes=boxes)
    _bar(im, (margin, y + total + 16, margin + 210, y + total + 27), ACCENT, alpha=255)
    return im.convert("RGB"), boxes


def variant_c(source, lines, accent_line=-1):
    """Centred over a blurred plate: the dramatic one, fewest words."""
    im = _vignette(_base_image(source, darken=0.48, blur=3), strength=0.85).convert("RGBA")
    draw = ImageDraw.Draw(im)
    boxes = []
    margin = 70
    font = _fit_lines(draw, lines, "Anton-Regular.ttf", W - 2 * margin, 200)
    line_h = font.size * 1.0
    total = line_h * len(lines)
    y = (H - total) / 2
    for i, line in enumerate(lines):
        fill = ACCENT if i == accent_line % len(lines) else WHITE
        _glow_text(im, (W / 2, y + i * line_h), line, font, fill,
                   stroke_w=10, anchor="ma", glow=24, boxes=boxes)
    return im.convert("RGB"), boxes


VARIANTS = {"a": variant_a, "b": variant_b, "c": variant_c}


def text_legibility(img, boxes):
    """Luminance separation inside the type, measured at browse size.

    This measures ONLY whether the words survive the downscale. It says nothing
    about whether the composition is any good - that still needs human eyes.

    Shrinks to 168x94, then inside each text box takes the 90th percentile
    luminance (the letter faces) minus the 10th (their dark outline). Letters that
    stay crisp separate by roughly 180+; once the downscale smears face into
    outline the gap collapses, and under ~120 the words read as a grey smudge.
    """
    import numpy as np
    small = img.convert("L").resize((BROWSE_W, BROWSE_H), Image.LANCZOS)
    a = np.asarray(small, dtype=np.float32)
    sx, sy = BROWSE_W / W, BROWSE_H / H
    spreads = []
    for (x0, y0, x1, y1) in boxes:
        bx0, by0 = max(0, int(x0 * sx)), max(0, int(y0 * sy))
        bx1, by1 = min(BROWSE_W, int(x1 * sx) + 1), min(BROWSE_H, int(y1 * sy) + 1)
        region = a[by0:by1, bx0:bx1]
        if region.size < 12:
            continue
        spreads.append(float(np.percentile(region, 90) - np.percentile(region, 10)))
    return min(spreads) if spreads else 0.0


def render(source, lines, out_dir, stem="thumb"):
    """Write all three variants plus their browse-size previews."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for key, fn in VARIANTS.items():
        path = out_dir / f"{stem}_{key}.png"
        img, boxes = fn(source, lines)
        img.save(path)
        img.resize((BROWSE_W, BROWSE_H), Image.LANCZOS).save(
            out_dir / f"{stem}_{key}_browse.png")
        spread = text_legibility(img, boxes)
        log.info("%s: worst-line text spread %.0f at %dx%d",
                 path.name, spread, BROWSE_W, BROWSE_H)
        results.append({"variant": key, "path": str(path),
                        "text_spread": round(spread)})
    return results
