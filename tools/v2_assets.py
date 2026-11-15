"""The v2 build's assets: NASA textures (public domain) and Blender, cached by the workflow.

    python -X utf8 tools/v2_assets.py textures     -> assets/textures/blue_marble.jpg, black_marble.jpg, moon.jpg
    python -X utf8 tools/v2_assets.py blender      -> tools/blender/blender (Blender 4.2 LTS, Linux x64)

Each texture has NASA's own address first and a Wikimedia Commons copy of the same NASA picture after it;
the map card uses blue_marble_5400.jpg.
"""
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
TEX = ROOT / "assets" / "textures"
UA = {"User-Agent": "whatif-channel/2.0 (https://github.com/edbackulin-eng/whatif-channel)"}
Image.MAX_IMAGE_PIXELS = None

SOURCES = {
    "blue_marble.jpg": ["https://eoimages.gsfc.nasa.gov/images/imagerecords/74000/74142/world.topo.200412.3x5400x2700.jpg",
                        "commons:File:Whole world - land and oceans 12000.jpg"],
    "black_marble.jpg": ["https://eoimages.gsfc.nasa.gov/images/imagerecords/144000/144898/BlackMarble_2016_01deg.jpg",
                         "commons:File:Earth's City Lights by DMSP, 1994-1995 (large).jpg"],
    "moon.jpg": ["https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/lroc_color_poles_2k.tif",
                 "commons:File:Moon map (LRO).jpg"],
}
BLENDER_URL = "https://download.blender.org/release/Blender4.2/blender-4.2.3-linux-x64.tar.xz"


def _get(url, dest, timeout=300):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    return dest


def _commons_url(title, width=5400):
    q = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "format": "json", "titles": title, "prop": "imageinfo", "iiprop": "url",
         "iiurlwidth": width})
    d = json.loads(urllib.request.urlopen(urllib.request.Request(q, headers=UA), timeout=60).read())
    info = next(iter(d["query"]["pages"].values()))["imageinfo"][0]
    return info.get("thumburl") or info["url"]


def textures():
    TEX.mkdir(parents=True, exist_ok=True)
    for name, srcs in SOURCES.items():
        out = TEX / name
        if out.exists() and out.stat().st_size > 100_000:
            continue
        for src in srcs:
            try:
                url = _commons_url(src[8:]) if src.startswith("commons:") else src
                tmp = TEX / ("_dl" + Path(urllib.parse.urlparse(url).path).suffix)
                _get(url, tmp)
                im = Image.open(tmp).convert("RGB")
                if im.width > 5400:
                    im = im.resize((5400, 2700), Image.LANCZOS)
                im.save(out, quality=92)
                tmp.unlink(missing_ok=True)
                print(f"{name}: {im.size} from {url[:90]}")
                break
            except Exception as e:                                       # noqa: BLE001
                print(f"{name}: {src[:80]} failed ({e})")
    bm = TEX / "blue_marble.jpg"
    small = TEX / "blue_marble_5400.jpg"
    if bm.exists() and not small.exists():
        shutil.copy(bm, small)


def blender():
    dest = ROOT / "tools" / "blender"
    if (dest / "blender").exists():
        print("blender present")
        return
    tar = ROOT / "tools" / "blender.tar.xz"
    _get(BLENDER_URL, tar, timeout=1200)
    with tarfile.open(tar) as t:
        t.extractall(ROOT / "tools")
    tar.unlink()
    d = next((ROOT / "tools").glob("blender-4.2*-linux-x64"))
    if dest.exists():
        shutil.rmtree(dest)
    d.rename(dest)
    print(subprocess.run([str(dest / "blender"), "-b", "--version"], capture_output=True, text=True).stdout[:80])


if __name__ == "__main__":
    {"textures": textures, "blender": blender}[sys.argv[1]]()
