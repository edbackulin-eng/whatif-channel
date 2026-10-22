"""Thumbnails in the channel's house style, with a legibility check at browse size.

The style came from the leaders in this niche and is now copied from the single
best-performing example of it: "What If You DIED on Every Planet" (16.9 M views).
Two things carry that image, and neither was in the old house style.

  A human face, close, lit, in one unmistakable emotion. It sits in the
  foreground looking slightly past the lens, not at it.

  The event itself, bright and saturated, filling the rest of the frame. Fire,
  lava, ice, deep space - never a darkened picture. The old preset dimmed the
  background to 52% brightness so white type would survive on top of it, which
  is what made every thumbnail a blue-grey rectangle at browse size. Type
  survives here on its outline and its dark halo instead, so the picture keeps
  its colour.

Two layouts: one face against the event, or - when the episode weighs two things
against each other - a split down the middle with a label over each half.
One to three enormous words, or none at all when the picture says it alone.

Two hard constraints:
  - the bottom right corner is YouTube's, not ours: the duration pill sits in
    roughly the last quarter across and the last fifth down, so nothing we draw
    goes in there (`safe_corner_clear`);
  - the words have to survive the downscale to a browse card, measured at
    336x189 rather than the old 168x94, which is the size a home-feed card is
    actually served at today (`text_legibility`).

The old layouts are kept at the bottom of this file: the KT2 and KT3 record
scripts reproduce what was shipped at the time and must keep working.
"""
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from core.logger import get_logger

log = get_logger("thumbnail")

W, H = 1280, 720
# A home-feed card, where the decision is actually made. The old 168x94 was a
# sidebar thumbnail and flattered type that then smeared in the feed.
BROWSE_W, BROWSE_H = 336, 189

# YouTube paints the duration pill over the bottom right of every card. Nothing
# we draw may enter it, as a fraction of the frame.
SAFE_X, SAFE_Y = 0.75, 0.80

ACCENT = (255, 184, 28)      # warm amber, the channel's one accent
WHITE = (255, 255, 255)
STROKE = (8, 10, 18)         # near-black outline, never pure black

# Thumbnails are bright on purpose, so a picture that comes back dark is lifted
# rather than used as it is. Measured as mean luminance over the whole frame.
TARGET_MEAN = 112
MAX_LIFT = 1.7

# YouTube rejects a thumbnail over 2 MB, and qc.py fails a build for it.
MAX_BYTES = 2 * 1024 * 1024

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"


def _font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def _cover(im, w, h):
    """Scale to cover w x h and crop the middle."""
    scale = max(w / im.width, h / im.height)
    im = im.resize((max(w, round(im.width * scale)), max(h, round(im.height * scale))),
                   Image.LANCZOS)
    left, top = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((left, top, left + w, top + h))


def _lift(im):
    """Raise a dark picture toward TARGET_MEAN. Returns (image, factor applied)."""
    import numpy as np
    mean = float(np.asarray(im.convert("L"), dtype=np.float32).mean())
    if mean >= TARGET_MEAN:
        return im, 1.0
    factor = min(MAX_LIFT, TARGET_MEAN / max(mean, 1.0))
    return ImageEnhance.Brightness(im).enhance(factor), factor


def _punch(source, w=W, h=H):
    """Cover-crop the source and push the colour, without darkening it.

    FLUX frames arrive flat, and `core/grade.py` is not in the path here - a
    thumbnail is not a frame of the video and is never graded with it.
    """
    with Image.open(source) as raw:
        im = _cover(raw.convert("RGB"), w, h)
    im, factor = _lift(im)
    if factor > 1.0:
        log.info("thumbnail source was dark; lifted by x%.2f", factor)
    im = ImageEnhance.Color(im).enhance(1.32)
    im = ImageEnhance.Contrast(im).enhance(1.14)
    return im


def _glow_text(im, xy, text, font, fill, stroke_w, anchor="la", glow=18, boxes=None):
    """Text with a soft dark glow behind it, then a hard outline on top.

    Appends the drawn bounding box to `boxes`, which the legibility check and the
    safe-corner check both need in order to measure the type rather than the
    picture behind it.
    """
    halo = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(halo).text(xy, text, font=font, fill=(0, 0, 0, 225), anchor=anchor,
                              stroke_width=stroke_w + 7, stroke_fill=(0, 0, 0, 225))
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


# --- the house style ----------------------------------------------------------------

WORD_FONT = "Anton-Regular.ttf"
MARGIN = 54
TOP = 44                      # where the ink of the first line starts, high up
BOTTOM = H - 40               # and where the last line ends, low down
# Two lines, never three. Three read as a sentence and a sentence is not read
# at the size of a postage stamp.
MAX_WORDS = 2
# The words are half the thumbnail at most. Any more and they bury the face they
# are supposed to be shouting about.
MAX_BLOCK_FRACTION = 0.50
# How much of the width one side's block may use. Slightly over half, because
# the two halves of a thumbnail are rarely split exactly down the middle.
HALF = 0.54
START_SIZE = 260
FLOOR_SIZE = 56
LINE_GAP = 0.12               # of the tallest line's ink


def _line_width_limit(ink_bottom, margin=MARGIN):
    """How wide a line may be, given where its ink ends vertically.

    A line that reaches into the bottom fifth of the frame has to stop short of
    YouTube's duration pill; a line above it may use the full width.
    """
    if ink_bottom > H * SAFE_Y:
        return int(W * SAFE_X) - 2 * margin
    return W - 2 * margin


POSITIONS = ("bottom-left", "top-left", "bottom-right", "top-right")
SIDES = {"left": ("bottom-left", "top-left"),
         "right": ("bottom-right", "top-right"),
         # The split layout's own label bar owns the top of the frame.
         "bottom": ("bottom-left", "bottom-right")}


def _x_bounds(ink_bottom):
    """The leftmost and rightmost edge a line's ink may occupy at this height.

    A line whose ink reaches into the bottom fifth has to stop short of
    YouTube's duration pill, which is what keeps a right-aligned block out of
    the corner instead of merely narrowing a left-aligned one.
    """
    return MARGIN, _line_width_limit(ink_bottom) + MARGIN


def _layout_words(draw, lines, stroke_w, position="bottom-left"):
    """Place the word block by its ink, not by the font's em size.

    Measuring with the em size overflowed the frame: Anton's ascent and descent
    together run to about 1.25 em, so a three-line block sized that way ran off
    the bottom edge and the last word was cut in half. Every position here comes
    from the drawn bounding box instead.

    Returns (font, [(x, y) draw position per line], block ink box), or None when
    the lines cannot be made to fit in this corner at any size.
    """
    vertical, _, horizontal = position.partition("-")
    for size in range(START_SIZE, FLOOR_SIZE - 1, -4):
        font = _font(WORD_FONT, size)
        ink = [draw.textbbox((0, 0), l, font=font, stroke_width=stroke_w) for l in lines]
        heights = [b[3] - b[1] for b in ink]
        gap = LINE_GAP * max(heights)
        total = sum(heights) + gap * (len(lines) - 1)
        if total > H * MAX_BLOCK_FRACTION:
            continue
        top = TOP if vertical == "top" else BOTTOM - total
        y, places, edges, fits = top, [], [], True
        for box, h in zip(ink, heights):
            left, right = _x_bounds(y + h)
            # Keep the block inside its own half, with a little overlap at the
            # centre. Without this a long line simply spans the whole frame and
            # "which side" means nothing - which is how "DOUBLE MOON" ended up
            # lying across a face that was nowhere near the left edge.
            if horizontal == "left":
                right = min(right, int(W * HALF))
            else:
                left = max(left, int(W * (1 - HALF)))
            width = box[2] - box[0]
            if width > right - left:
                fits = False
                break
            x = left if horizontal == "left" else right - width
            places.append((x - box[0], y - box[1]))
            edges.append((x, x + width))
            y += h + gap
        if fits:
            return font, places, (min(e[0] for e in edges), top,
                                  max(e[1] for e in edges), top + total)
    return None


def _detail(im):
    """A low-resolution map of how busy each part of the picture is.

    Faces, debris and type score high; sky, haze, ice and deep space score low.
    It is a stand-in for "where is the face", good enough to keep the words off
    it without carrying a face detector into the build.
    """
    import numpy as np
    small = np.asarray(im.convert("L").resize((160, 90), Image.LANCZOS),
                       dtype=np.float32)
    gy, gx = np.gradient(small)
    return np.hypot(gx, gy)


def _region_detail(energy, box):
    x0, y0, x1, y1 = box
    sx, sy = 160 / W, 90 / H
    region = energy[max(0, int(y0 * sy)):max(1, int(y1 * sy)),
                    max(0, int(x0 * sx)):max(1, int(x1 * sx))]
    return float(region.mean()) if region.size else 0.0


def _choose_position(im, draw, lines, stroke_w, side=None):
    """Put the words over the event, never over the face.

    The words used to go bottom left always, which is where the face is: on two
    of the first four thumbnails the block landed across an open screaming
    mouth. `side` is the judge's reading of which half holds the event; without
    it the quietest corner wins, which comes to much the same thing.
    """
    wanted = SIDES.get(side, POSITIONS)
    energy = _detail(im)
    scored = []
    for position in wanted:
        fit = _layout_words(draw, lines, stroke_w, position)
        if fit:
            scored.append((_region_detail(energy, fit[2]), position, fit))
    if not scored:
        for position in POSITIONS:
            fit = _layout_words(draw, lines, stroke_w, position)
            if fit:
                scored.append((_region_detail(energy, fit[2]), position, fit))
    if not scored:
        return "bottom-left", None
    _, position, fit = min(scored, key=lambda s: s[0])
    return position, fit


def _draw_words(im, lines, boxes, stroke_w=10, glow=20, side=None):
    """The word block, over the event and as big as the safe corner allows."""
    draw = ImageDraw.Draw(im)
    position, fit = _choose_position(im, draw, lines, stroke_w, side)
    if fit is None:
        # Nothing fits anywhere: draw at the floor size rather than drop the words.
        font = _font(WORD_FONT, FLOOR_SIZE)
        step = FLOOR_SIZE * 1.15
        places = [(MARGIN, BOTTOM - step * (len(lines) - i)) for i in range(len(lines))]
    else:
        font, places, _ = fit
    for line, xy in zip(lines, places):
        _glow_text(im, xy, line, font, WHITE, stroke_w=stroke_w, glow=glow, boxes=boxes)
    return font.size, position


def _clean_words(words):
    return [str(w).strip().upper() for w in (words or []) if str(w).strip()][:MAX_WORDS]


def compose(source, words=(), side=None):
    """One face against the event: the workhorse layout. Returns (image, text boxes).

    `side` is which half of the frame holds the event rather than the face, as
    the vision judge read it; the words go there.
    """
    im = _punch(source).convert("RGBA")
    boxes = []
    words = _clean_words(words)
    if words:
        size, position = _draw_words(im, words, boxes, side=side)
        log.info("thumbnail: %d word line(s) at %dpx, %s (event side: %s)",
                 len(words), size, position, side or "unknown")
    else:
        log.info("thumbnail: no text, the picture carries it")
    return im.convert("RGB"), boxes


LABEL_FONT = "BebasNeue-Regular.ttf"
LABEL_MARGIN = 26
LABEL_SIZE = 118


def compose_split(left_source, right_source, labels, words=()):
    """Two halves with a label over each: the comparison layout.

    Which is how the reference does a two-sided question - VENUS on the left
    half, NEPTUNE on the right, one face in each.
    """
    half = W // 2
    im = Image.new("RGB", (W, H))
    with Image.open(left_source) as raw:
        im.paste(_lift(_cover(raw.convert("RGB"), half, H))[0], (0, 0))
    with Image.open(right_source) as raw:
        im.paste(_lift(_cover(raw.convert("RGB"), W - half, H))[0], (half, 0))
    im = ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(1.32)).enhance(1.14)
    im = im.convert("RGBA")
    boxes = []

    left_label, right_label = (list(labels) + ["", ""])[:2]
    draw = ImageDraw.Draw(im)
    usable = half - 2 * LABEL_MARGIN
    shown = [l for l in (left_label, right_label) if l] or [" "]
    size, font = LABEL_SIZE, _font(LABEL_FONT, LABEL_SIZE)
    while size > 40:
        font = _font(LABEL_FONT, size)
        if max(draw.textlength(l, font=font) for l in shown) <= usable:
            break
        size -= 4
    ink = max(draw.textbbox((0, 0), l, font=font, stroke_width=6)[3] for l in shown)
    bar_h = int(ink + 2 * LABEL_MARGIN)
    _bar(im, (0, 0, W, bar_h), (6, 9, 20), alpha=170)
    for i, label in enumerate((left_label, right_label)):
        if label:
            _glow_text(im, (half * 0.5 + i * half, bar_h * 0.5), label, font, WHITE,
                       stroke_w=6, anchor="mm", glow=12, boxes=boxes)
    # A hard seam, so the two halves read as a comparison and not as one picture.
    ImageDraw.Draw(im).rectangle((half - 3, 0, half + 2, H), fill=WHITE)

    words = _clean_words(words)
    if words:
        # The label bar owns the top of both halves, so the words stay low.
        _draw_words(im, words, boxes, stroke_w=9, glow=18, side="bottom")
    log.info("thumbnail: split %s / %s, label %dpx, %d word line(s)",
             left_label or "-", right_label or "-", size, len(words))
    return im.convert("RGB"), boxes


# --- the checks ---------------------------------------------------------------------

SAFE_BOX = (W * SAFE_X, H * SAFE_Y, W, H)


def safe_corner_clear(boxes):
    """True when nothing we drew reaches into YouTube's duration pill."""
    x0, y0, x1, y1 = SAFE_BOX
    return all(not (b[2] > x0 and b[3] > y0 and b[0] < x1 and b[1] < y1) for b in boxes)


def text_legibility(img, boxes):
    """Luminance separation inside the type, measured at browse size.

    This measures ONLY whether the words survive the downscale. It says nothing
    about whether the composition is any good - that still needs human eyes, or
    the vision judge in pipeline/visualqc.py.

    Shrinks to BROWSE_W x BROWSE_H, then inside each text box takes the 90th
    percentile luminance (the letter faces) minus the 10th (their dark outline).
    Letters that stay crisp separate widely; once the downscale smears face into
    outline the gap collapses. A thumbnail with no text at all is not illegible,
    so it scores the maximum.
    """
    import numpy as np
    if not boxes:
        return 255.0
    small = img.convert("L").resize((BROWSE_W, BROWSE_H), Image.LANCZOS)
    a = np.asarray(small, dtype=np.float32)
    sx, sy = BROWSE_W / img.width, BROWSE_H / img.height
    spreads = []
    for (x0, y0, x1, y1) in boxes:
        bx0, by0 = max(0, int(x0 * sx)), max(0, int(y0 * sy))
        bx1, by1 = min(BROWSE_W, int(x1 * sx) + 1), min(BROWSE_H, int(y1 * sy) + 1)
        region = a[by0:by1, bx0:bx1]
        if region.size < 12:
            continue
        spreads.append(float(np.percentile(region, 90) - np.percentile(region, 10)))
    return min(spreads) if spreads else 0.0


def save(img, path, max_bytes=MAX_BYTES):
    """Write the thumbnail as a PNG that YouTube will accept.

    A bright, detailed 1280x720 photograph can compress to more than 2 MB as a
    PNG, which qc.py fails the build for. Rather than change the format every
    other stage expects, the picture is passed through a JPEG encode to shed the
    high-frequency noise and written out as a PNG again - the same pixels, minus
    the grain nothing can see at browse size.
    """
    path = Path(path)
    img.save(path, optimize=True)
    for quality in (88, 78, 68):
        size = path.stat().st_size
        if size <= max_bytes:
            return path
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality, subsampling=0)
        buf.seek(0)
        with Image.open(buf) as reduced:
            reduced.convert("RGB").save(path, optimize=True)
        log.info("thumbnail was %.2f MB; re-encoded at q%d -> %.2f MB",
                 size / 1e6, quality, path.stat().st_size / 1e6)
    return path


# --- the old house style ------------------------------------------------------------
#
# Superseded by compose()/compose_split() above. Kept because kt2_thumbnails.py
# and kt3_build.py reproduce what those milestones actually shipped, and a record
# that no longer runs is not a record.

def _fit_lines(draw, lines, font_name, max_width, start_size):
    size = start_size
    while size > 24:
        font = _font(font_name, size)
        if all(draw.textlength(l, font=font) <= max_width for l in lines):
            return font
        size -= 4
    return _font(font_name, 24)


def _base_image(source, darken=0.55, blur=0):
    im = Image.open(source).convert("RGB")
    im = _cover(im, W, H)
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    im = ImageEnhance.Brightness(im).enhance(darken)
    im = ImageEnhance.Color(im).enhance(1.25)
    im = ImageEnhance.Contrast(im).enhance(1.15)
    return im


def _vignette(im, strength=0.75):
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).ellipse((-W * 0.25, -H * 0.45, W * 1.25, H * 1.45), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(160))
    dark = ImageEnhance.Brightness(im).enhance(1 - strength)
    return Image.composite(im, dark, mask)


def variant_a(source, lines, accent_line=-1):
    """Bottom-left stack."""
    im = _vignette(_base_image(source, darken=0.52)).convert("RGBA")
    draw = ImageDraw.Draw(im)
    boxes = []
    margin = 54
    font = _fit_lines(draw, lines, "Anton-Regular.ttf", W - 2 * margin, 168)
    line_h = font.size * 1.02
    y = H - margin - line_h * len(lines)
    for i, line in enumerate(lines):
        fill = ACCENT if i == accent_line % len(lines) else WHITE
        _glow_text(im, (margin, y + i * line_h), line, font, fill, stroke_w=9, boxes=boxes)
    return im.convert("RGB"), boxes


def variant_b(source, lines, accent_line=-1):
    """Type left, subject right, behind a scrim that fades out."""
    im = _base_image(source, darken=0.74).convert("RGBA")
    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = scrim.load()
    for x in range(W):
        a = int(max(0.0, 1.0 - (x / (W * 0.66))) ** 1.4 * 232)
        for y_ in range(H):
            px[x, y_] = (5, 8, 20, a)
    im.alpha_composite(scrim)
    draw = ImageDraw.Draw(im)
    boxes = []
    margin = 52
    font = _fit_lines(draw, lines, "BebasNeue-Regular.ttf", int(W * 0.56), 180)
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
    """Centred over a blurred plate."""
    im = _vignette(_base_image(source, darken=0.48, blur=3), strength=0.85).convert("RGBA")
    draw = ImageDraw.Draw(im)
    boxes = []
    margin = 70
    font = _fit_lines(draw, lines, "Anton-Regular.ttf", W - 2 * margin, 200)
    line_h = font.size * 1.0
    y = (H - line_h * len(lines)) / 2
    for i, line in enumerate(lines):
        fill = ACCENT if i == accent_line % len(lines) else WHITE
        _glow_text(im, (W / 2, y + i * line_h), line, font, fill,
                   stroke_w=10, anchor="ma", glow=24, boxes=boxes)
    return im.convert("RGB"), boxes


VARIANTS = {"a": variant_a, "b": variant_b, "c": variant_c}


def render(source, lines, out_dir, stem="thumb"):
    """Write all three old variants plus their browse-size previews."""
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
