"""Real video for the v2 montage (owner 15.11): at least half of every film is real footage.

Sources, each with its licence read from the source itself:
  Pixabay video   Pixabay Content License             PIXABAY_API_KEY (skipped without it)
  Pexels video    Pexels License                      PEXELS_API_KEY  (skipped without it)
  NASA video      public domain, minus anything NASA marks as third-party (visuals.THIRD_PARTY_MARKERS)
  Commons video   public domain, CC0, CC BY, CC BY-SA (author and licence credited)

Every candidate is looked at by the vision model before use (one frame): what it shows, and whether it
has people close up, text or logos, or looks computer-made. A clip is used once in a film and once in
the channel (state/used_footage.json).
"""
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from core.logger import get_logger

log = get_logger("v2stock")
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "output" / "_stock_cache"
USED = ROOT / "state" / "used_footage.json"
UA = {"User-Agent": "whatif-channel/2.0 (https://github.com/edbackulin-eng/whatif-channel; science videos)"}
MIN_W = 1280
CGI = re.compile(r"\b(3d|cgi|render(ed)?|animation|animated|cartoon|illustration|vector|ai[- ]generated|"
                 r"generated|game|toy|lego|logo|text|intro|title)\b", re.I)
LIC_OK = re.compile(r"^(public domain|pd\b|pd-|cc0|cc[ -]by(-sa)?[ -]?\d?(\.\d)?)", re.I)
LIC_BAD = re.compile(r"\b(NC|ND)\b|non.?commercial|no.?deriv", re.I)


def _env(name):
    if os.environ.get(name):
        return os.environ[name]
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == name:
                return v.strip().strip('"').strip("'")
    return None


def _get(url, headers=None, cache=True, timeout=60):
    CACHE.mkdir(parents=True, exist_ok=True)
    key = CACHE / ("q_" + hashlib.sha1(url.encode()).hexdigest() + ".json")
    if cache and key.exists():
        return json.loads(key.read_text(encoding="utf-8"))
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={**UA, **(headers or {})}),
                                        timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            key.write_text(json.dumps(data), encoding="utf-8")
            return data
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 4:
                time.sleep(10 * (attempt + 1))
                continue
            raise
        except Exception:                                                # noqa: BLE001
            if attempt == 4:
                raise
            time.sleep(4 * (attempt + 1))


def pixabay(query, n=30):
    key = _env("PIXABAY_API_KEY")
    if not key:
        return []
    d = _get("https://pixabay.com/api/videos/?" + urllib.parse.urlencode(
        {"key": key, "q": query, "per_page": n, "safesearch": "true"}))
    out = []
    for h in d.get("hits", []):
        if CGI.search(h.get("tags", "")) or (h.get("duration") or 0) < 4:
            continue
        sizes = [h["videos"][s] for s in ("large", "medium") if h["videos"].get(s, {}).get("url")]
        if not sizes:
            continue
        b = max(sizes, key=lambda x: x["width"])
        if b["width"] < MIN_W:
            continue
        out.append({"id": f"pixabay-{h['id']}", "source": "Pixabay", "query": query, "url": b["url"],
                    "page": h["pageURL"], "width": b["width"], "height": b["height"], "duration": h["duration"],
                    "thumb": b.get("thumbnail") or h["videos"].get("small", {}).get("thumbnail"),
                    "tags": h.get("tags", ""), "author": h.get("user"), "license": "Pixabay Content License",
                    "license_url": "https://pixabay.com/service/license-summary/"})
    return out


def pexels(query, n=25):
    key = _env("PEXELS_API_KEY")
    if not key:
        return []
    try:
        d = _get("https://api.pexels.com/videos/search?" + urllib.parse.urlencode({"query": query, "per_page": n}),
                 headers={"Authorization": key})
    except Exception as e:                                               # noqa: BLE001
        log.warning("pexels %s: %s", query, e)
        return []
    out = []
    for v in d.get("videos", []):
        files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4"
                 and (f.get("width") or 0) >= MIN_W]
        if not files or (v.get("duration") or 0) < 4:
            continue
        f = min(files, key=lambda f: abs((f.get("width") or 0) - 1920))
        out.append({"id": f"pexels-{v['id']}", "source": "Pexels", "query": query, "url": f["link"],
                    "page": v.get("url"), "width": f["width"], "height": f["height"], "duration": v.get("duration"),
                    "thumb": v.get("image"), "tags": (v.get("url") or "").rstrip("/").rsplit("/", 1)[-1].replace("-", " "),
                    "author": (v.get("user") or {}).get("name"), "license": "Pexels License",
                    "license_url": "https://www.pexels.com/license/"})
    return out


def nasa(query, n=20):
    from pipeline import visuals
    try:
        d = _get("https://images-api.nasa.gov/search?" + urllib.parse.urlencode({"q": query, "media_type": "video"}))
    except Exception as e:                                               # noqa: BLE001
        log.warning("nasa %s: %s", query, e)
        return []
    out = []
    for item in d.get("collection", {}).get("items", [])[:n]:
        meta = item["data"][0]
        text = f"{meta.get('description', '')} {meta.get('secondary_creator', '')} {meta.get('photographer', '')}".lower()
        if any(m in text for m in visuals.THIRD_PARTY_MARKERS):
            continue
        thumb = next((l["href"] for l in item.get("links", []) if l.get("rel") == "preview"), None)
        out.append({"id": f"nasa-{meta['nasa_id']}", "source": "NASA", "query": query, "manifest": item.get("href"),
                    "page": f"https://images.nasa.gov/details/{urllib.parse.quote(meta['nasa_id'])}",
                    "thumb": thumb, "tags": meta.get("title", ""), "author": meta.get("center") or "NASA",
                    "license": "Public domain (NASA)",
                    "license_url": "https://www.nasa.gov/nasa-brand-center/images-and-media/"})
    return out


def nasa_url(item):
    files = _get(item["manifest"])
    vids = [f for f in files if f.lower().endswith(".mp4")]
    order = ("~orig", "~large", "~medium")
    vids.sort(key=lambda f: next((i for i, o in enumerate(order) if o in f), 9))
    return vids[0].replace("http://", "https://") if vids else None


def commons(query, n=20):
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{query} filetype:video",
        "gsrnamespace": 6, "gsrlimit": n, "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 640})
    try:
        time.sleep(1.2)
        d = _get(url)
    except Exception as e:                                               # noqa: BLE001
        log.warning("commons %s: %s", query, e)
        return []
    out = []
    for page in ((d.get("query") or {}).get("pages") or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        lic = re.sub(r"<[^>]+>", "", meta.get("LicenseShortName", {}).get("value", "")).strip()
        if not LIC_OK.search(lic) or LIC_BAD.search(lic) or (info.get("width") or 0) < MIN_W:
            continue
        if (info.get("duration") or 0) < 4:
            continue
        out.append({"id": "commons-" + hashlib.sha1(page["title"].encode()).hexdigest()[:10],
                    "source": "Wikimedia Commons", "query": query, "url": info.get("url"),
                    "page": info.get("descriptionurl"), "width": info.get("width"), "height": info.get("height"),
                    "duration": info.get("duration"), "thumb": info.get("thumburl"), "title": page["title"],
                    "tags": page["title"],
                    "author": re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", ""))[:150] or "unknown",
                    "license": lic, "license_url": meta.get("LicenseUrl", {}).get("value", "")})
    return out


def search(query):
    out = []
    for fn in (pixabay, pexels, nasa, commons):
        try:
            out += fn(query)
        except Exception as e:                                           # noqa: BLE001
            log.warning("%s %s: %s", fn.__name__, query, e)
    return out


# ------------------------------------------------------------------ the vision check
DESCRIBE = """Each numbered picture is one frame of a stock video clip for a science documentary.
For each: "what": 4-10 English words describing what it shows; "people_close": true if a person's face or
body fills much of the frame; "text": true if letters, logos, watermarks or subtitles are visible; "cgi": true if
it looks like a 3D render, game, cartoon or AI picture; "quality": 1-5.
Answer as JSON: {"items": [{"i": 0, "what": "...", "people_close": false, "text": false, "cgi": false, "quality": 4}]}"""


def _b64(path, side=640):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    im.thumbnail((side, side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _vision(prompt, paths, models=("gemini-flash-lite-latest", "gemini-flash-latest")):
    from core import llm
    key = llm.get_key("GEMINI_API_KEY")
    parts = [{"text": prompt}]
    for i, p in enumerate(paths):
        parts += [{"text": f"picture {i}:"}, {"inline_data": {"mime_type": "image/jpeg", "data": _b64(p)}}]
    payload = json.dumps({"contents": [{"role": "user", "parts": parts}],
                          "generationConfig": {"temperature": 0, "maxOutputTokens": 3000,
                                               "responseMimeType": "application/json"}}).encode()
    for m in models:
        for attempt in range(4):
            req = urllib.request.Request(llm.GEMINI_URL.format(model=m), data=payload, method="POST",
                                         headers={"Content-Type": "application/json", "x-goog-api-key": key})
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    d = json.loads(r.read())
                text = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"] if "text" in p)
                return llm.extract_json(text)
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504):
                    time.sleep(20 * (attempt + 1))
                    continue
                break
            except Exception:                                            # noqa: BLE001
                time.sleep(5 * (attempt + 1))
    return {}


def describe(items, cache_path):
    cache = json.loads(Path(cache_path).read_text(encoding="utf-8")) if Path(cache_path).exists() else {}
    todo = []
    for it in items:
        if it["id"] in cache or not it.get("thumb"):
            continue
        dest = CACHE / "thumbs" / f"{it['id']}.jpg"
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            if not dest.exists():
                with urllib.request.urlopen(urllib.request.Request(it["thumb"], headers=UA), timeout=60) as r:
                    dest.write_bytes(r.read())
            todo.append((it, dest))
        except Exception:                                                # noqa: BLE001
            cache[it["id"]] = {"error": "no picture"}
    for k in range(0, len(todo), 10):
        part = todo[k:k + 10]
        ans = _vision(DESCRIBE, [str(p) for _, p in part])
        res = {int(r.get("i", -1)): r for r in (ans.get("items") or []) if isinstance(r, dict)}
        for j, (it, _) in enumerate(part):
            if j in res:
                cache[it["id"]] = res[j]
        Path(cache_path).write_text(json.dumps(cache, indent=1), encoding="utf-8")
    Path(cache_path).write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return cache


def usable(it, d):
    return bool(d) and not d.get("error") and not d.get("people_close") and not d.get("text") \
        and not d.get("cgi") and int(d.get("quality") or 0) >= 3


def used_in_channel():
    return set(json.loads(USED.read_text(encoding="utf-8"))) if USED.exists() else set()


def remember(ids):
    USED.parent.mkdir(parents=True, exist_ok=True)
    have = used_in_channel()
    USED.write_text(json.dumps(sorted(have | set(ids)), indent=0), encoding="utf-8")


def download(it, dest):
    """The clip to dest (NASA: the largest mp4 of its manifest)."""
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size > 100_000:
        return dest
    url = it.get("url") or (nasa_url(it) if it.get("manifest") else None)
    if not url:
        raise RuntimeError(f"no file for {it['id']}")
    tmp = dest.with_suffix(".part")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r, open(tmp, "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            break
        except Exception:                                                # noqa: BLE001
            if attempt == 3:
                raise
            time.sleep(10 * (attempt + 1))
    tmp.replace(dest)
    return dest


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,avg_frame_rate:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True)
    d = json.loads(r.stdout or "{}")
    s = (d.get("streams") or [{}])[0]
    num, den = (s.get("avg_frame_rate") or "30/1").split("/")
    return {"w": s.get("width"), "h": s.get("height"), "fps": float(num) / float(den or 1) if float(den or 1) else 30,
            "duration": float((d.get("format") or {}).get("duration") or 0)}
