"""Public-domain imagery from NASA, with rights screening and a credits ledger.

NASA's own material is not subject to copyright in the US, but NASA also republishes
third-party work under permission that does NOT extend to us, and it marks that
material in the description. Anything carrying such a mark is rejected here rather
than filtered later, because a single copyrighted frame is enough to draw a claim.
"""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from core.logger import get_logger

log = get_logger("visuals")

SEARCH_URL = "https://images-api.nasa.gov/search"
USER_AGENT = "whatif-channel/0.1 (educational science video pipeline)"
TIMEOUT = 90

# Phrases NASA uses when the asset is somebody else's property. Matched against the
# description and the credit line, case-insensitively.
THIRD_PARTY_MARKERS = (
    "copyright", "©", "(c)", "all rights reserved", "used with permission",
    "courtesy of", "reprinted", "getty", "reuters", "associated press", "ap photo",
    "shutterstock", "alamy", "adobe stock", "istock",
)

# Credit lines that are NASA or its standard partners: these are fine.
_SAFE_CREATOR = re.compile(
    r"^(nasa|esa|jpl|gsfc|jsc|ksc|msfc|arc|lrc|afrc|ssc|usgs|noaa|caltech|"
    r"arizona state|univ|university|sdo|soho|stsci|space telescope)",
    re.I,
)


class RightsRejected(Exception):
    pass


def _get(url, params=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _rights_problem(data):
    """Return the marker that makes this asset unusable, or None when it is clean."""
    haystack = " ".join(filter(None, [
        data.get("description", ""),
        data.get("description_508", ""),
        data.get("secondary_creator", ""),
    ])).lower()
    for marker in THIRD_PARTY_MARKERS:
        if marker in haystack:
            return marker
    creator = (data.get("secondary_creator") or "").strip()
    # An empty credit is NASA's default and fine; a named one must look institutional.
    if creator and not _SAFE_CREATOR.match(creator):
        return f"unrecognised credit: {creator}"
    return None


def _subject_problem(data, require, exclude):
    """Reject a result whose subject is not the thing the scene is about.

    NASA's keyword search happily answers "full moon detailed surface" with Io, and
    "tidal forces" with Saturn's rings. Narrating Earth's Moon over a picture of a
    moon of Jupiter is the kind of mistake a science channel does not survive, so
    the subject is checked against the text rather than trusted to the ranking.
    """
    title = (data.get("title") or "").lower()
    keywords = " ".join(data.get("keywords") or []).lower()
    haystack = f"{title} {keywords} {(data.get('description') or '').lower()}"
    # Only the title and keywords decide the subject. A long caption often mentions
    # another planet in passing ("...as Mars was 127 million miles away...") and
    # that must not disqualify an otherwise perfect frame.
    subject = f"{title} {keywords}"
    for term in exclude or ():
        if term.lower() in subject:
            return f"subject is {term.strip()}"
    if require and not any(term.lower() in haystack for term in require):
        return f"mentions none of {list(require)}"
    return None


def search(query, limit=10, media_type="image", require=None, exclude=None):
    """Rights-screened, subject-screened search results."""
    payload = _get(SEARCH_URL, {"q": query, "media_type": media_type, "page_size": 40})
    items = payload.get("collection", {}).get("items", [])
    clean, rejected, off_topic = [], 0, 0
    for item in items:
        data = (item.get("data") or [{}])[0]
        problem = _rights_problem(data)
        if problem:
            rejected += 1
            log.info("rejected %s (%s)", data.get("nasa_id", "?"), problem)
            continue
        subject = _subject_problem(data, require, exclude)
        if subject:
            off_topic += 1
            log.info("off-topic %s (%s)", data.get("nasa_id", "?"), subject)
            continue
        clean.append({
            "nasa_id": data.get("nasa_id"),
            "title": (data.get("title") or "").strip(),
            "credit": (data.get("secondary_creator") or "NASA").strip(),
            "center": data.get("center"),
            "date": data.get("date_created"),
            "collection": item.get("href"),
        })
        if len(clean) >= limit:
            break
    log.info("query %r: %d usable, %d rejected on rights, %d off-topic",
             query, len(clean), rejected, off_topic)
    return clean


_PREFERRED = ("~orig", "~large", "~medium")


def _best_asset(collection_url):
    """Pick the highest-quality still from an item's asset list.

    collection.json is a flat JSON array of URL strings, not a Collection+JSON
    document like the search endpoint returns.
    """
    assets = _get(collection_url)
    if isinstance(assets, dict):  # tolerate the other shape if it ever appears
        assets = [u.get("href") for u in assets.get("collection", {}).get("items", [])
                  if isinstance(u, dict)]
    hrefs = [u for u in assets if isinstance(u, str)]
    for tag in _PREFERRED:
        for href in hrefs:
            if tag in href and href.lower().endswith((".jpg", ".jpeg", ".png", ".tif")):
                return href
    for href in hrefs:
        if href.lower().endswith((".jpg", ".jpeg", ".png")):
            return href
    return None


# A Ken Burns move zooms in up to ~1.35x, so a frame with headroom above 1080p is
# ideal. But holding out for that throws away much of the best archive material:
# NASA's own "high-resolution" Earthrise release is 952x952. Anything at or above
# this floor is kept and composited over a blurred enlargement of itself by
# core.grade, which keeps the subject sharp instead of upscaling it to mush.
MIN_WIDTH = 900
MIN_HEIGHT = 500


# Space archives are full of near-empty frames: a distant probe against black sky
# is a perfectly good photograph and a terrible shot. On screen it reads as a
# video fault, and blackdetect flags it in QC. These thresholds reject a frame
# whose content is essentially nothing.
# Calibrated against real material rather than guessed. The frame that actually
# broke a render measured mean 1.8 / p95 1.0 - a probe against empty sky. Genuine
# night shots in the same batch sit at mean 11-17 with p95 34-39 and look fine,
# so the bar has to sit well below them or the channel loses every night scene.
MIN_MEAN_LUMA = 6.0
MIN_P95_LUMA = 15.0


def _dimensions_ok(path):
    """Reject stills too small to survive a 1080p zoom. Returns (ok, 'WxH')."""
    from PIL import Image
    try:
        with Image.open(path) as im:
            w, h = im.size
    except Exception as e:
        log.warning("unreadable image %s: %s", path.name, e)
        return False, "unreadable"
    return (w >= MIN_WIDTH and h >= MIN_HEIGHT), f"{w}x{h}"


def _has_content(path):
    """Reject a frame that is almost entirely black. Returns (ok, description)."""
    import numpy as np
    from PIL import Image
    try:
        with Image.open(path) as im:
            im.draft("L", (512, 512))
            small = im.convert("L").resize((256, 256))
    except Exception as e:
        return False, f"unreadable ({e})"
    a = np.asarray(small, dtype=np.float32)
    mean, p95 = float(a.mean()), float(np.percentile(a, 95))
    ok = mean >= MIN_MEAN_LUMA and p95 >= MIN_P95_LUMA
    return ok, f"mean luma {mean:.1f}, p95 {p95:.1f}"


def download(item, dest_dir, index):
    """Fetch one screened item. Returns a credits record, or None when it fails."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    href = _best_asset(item["collection"])
    if not href:
        log.warning("no usable asset for %s", item["nasa_id"])
        return None
    href = href.replace("http://", "https://")
    suffix = Path(urllib.parse.urlparse(href).path).suffix.lower() or ".jpg"
    if suffix == ".tif":
        suffix = ".tif"
    path = dest_dir / f"{index:03d}_{item['nasa_id']}{suffix}"
    req = urllib.request.Request(href, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp, open(path, "wb") as fh:
            fh.write(resp.read())
    except Exception:
        # A truncated transfer (IncompleteRead is common on the bigger originals)
        # otherwise leaves a half-written file that later reads as a corrupt image.
        path.unlink(missing_ok=True)
        raise
    ok, dims = _dimensions_ok(path)
    if not ok:
        log.info("discarded %s: %s is below %dx%d", path.name, dims, MIN_WIDTH, MIN_HEIGHT)
        path.unlink(missing_ok=True)
        return None
    bright, detail = _has_content(path)
    if not bright:
        log.info("discarded %s: nearly black (%s)", path.name, detail)
        path.unlink(missing_ok=True)
        return None
    size = path.stat().st_size
    log.info("downloaded %s (%s, %.1f MB)", path.name, dims, size / 1e6)
    return {
        "file": path.name,
        "dimensions": dims,
        "source": "NASA Image and Video Library",
        "nasa_id": item["nasa_id"],
        "title": item["title"],
        "credit": item["credit"],
        "license": "Public domain (NASA media usage guidelines) - credit required, no endorsement implied",
        "source_url": f"https://images.nasa.gov/details/{item['nasa_id']}",
        "asset_url": href,
        "retrieved": time.strftime("%Y-%m-%d"),
    }


def write_credits(records, path):
    """The ledger every video ships with; the description text is generated from it."""
    path = Path(path)
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("wrote %d credit records to %s", len(records), path.name)


def description_credits(records):
    """Attribution block for the YouTube description, one line per distinct credit."""
    seen, lines = set(), []
    for r in records:
        key = (r["credit"], r["source"])
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {r['credit']} ({r['source']})")
    return "\n".join(lines)
