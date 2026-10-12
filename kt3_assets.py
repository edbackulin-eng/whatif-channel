"""KT3: fetch the archive stills and draw the infographic cards for the shot list.

Generated scenes are left for the GPU step; this fills in everything that can be
produced locally.
"""
import json
import re
import sys
from pathlib import Path

from pipeline import infographics, visuals

ROOT = Path(__file__).resolve().parent
KT3 = ROOT / "output" / "kt3"
SHOTS = KT3 / "shots"
CARDS = KT3 / "cards"


# Mission and instrument names make a query precise for a human and empty for
# NASA's search index, so they are the first thing dropped.
_NOISE = {"nasa", "spacecraft", "mission", "image", "photo", "view", "shot",
          "apollo", "galileo", "cassini", "voyager", "hubble", "iss",
          "landsat", "terra", "aqua", "goes", "modis", "lro"}


def _query_ladder(query):
    """Progressively broader versions of a query, most specific first."""
    words = [w for w in query.split() if w]
    ladder = [query]
    trimmed = [w for w in words if w.lower().strip(",.") not in _NOISE]
    if trimmed and trimmed != words:
        ladder.append(" ".join(trimmed))
    if len(trimmed) > 3:
        ladder.append(" ".join(trimmed[:3]))
    if len(trimmed) > 2:
        ladder.append(" ".join(trimmed[:2]))
    seen, out = set(), []
    for q in ladder:
        if q and q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out


_HAS_DIGIT = re.compile(r"\d")
# A headline is a figure or a short phrase. The card auto-shrinks the type to fit,
# so this only needs to stop a whole sentence being promoted to 400pt.
HEADLINE_MAX = 24
SUB_MAX = 46


def _clip_words(text, limit):
    """Trim to `limit` characters on a word boundary, never mid-word."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-")


def _normalise_card(card):
    """Decide what belongs on the card in big type.

    Returns None when the picture editor gave us nothing usable. An earlier
    version rendered "?" in that case, which put a literal question mark on
    screen in seven places - worse than having no card at all. Those scenes now
    fall back to a neighbouring image instead.

    The editor also tends to put the topic in `label` ("Lunar Drift") and the
    figure in `caption` ("3.8 cm per year"), so whichever field carries digits
    becomes the headline.
    """
    kind = (card.get("kind") or "number").lower()
    label = (card.get("label") or "").strip()
    caption = (card.get("caption") or "").strip()
    if not label and not caption:
        return None

    if _HAS_DIGIT.search(caption) and not _HAS_DIGIT.search(label):
        headline, sub = caption, label
    else:
        headline, sub = label, caption
    if not headline.strip():
        headline, sub = sub, ""

    # Split on a sentence end, not on any full stop: "3.8 cm per year" must not
    # become "3".
    headline = _clip_words(re.split(r"\.\s", headline)[0].rstrip("."), HEADLINE_MAX)
    sub = _clip_words(sub.rstrip("."), SUB_MAX)
    if not headline:
        return None
    return kind, headline, sub


def main():
    scenes = json.loads((KT3 / "scenes.json").read_text(encoding="utf-8"))
    credits, used = [], set()

    archive = [s for s in scenes if s["source"] == "archive"]
    print(f"archive scenes: {len(archive)}")
    for s in archive:
        query = s.get("query") or "earth from space"
        record = None
        # The picture editor writes queries that are often too specific for NASA's
        # search ("Io volcano plume Galileo spacecraft" returns nothing), so fall
        # back through progressively broader forms before giving up.
        for attempt in _query_ladder(query):
            try:
                candidates = visuals.search(attempt, limit=10)
            except Exception as e:
                print(f"  [{s['index']:3d}] search failed {attempt!r}: {e}")
                continue
            for c in candidates:
                if c["nasa_id"] in used:
                    continue
                try:
                    record = visuals.download(c, SHOTS, s["index"])
                except Exception:
                    continue
                if record:
                    used.add(c["nasa_id"])
                    query = attempt
                    break
            if record:
                break
        if record:
            record["scene"] = s["index"]
            record["query"] = query
            credits.append(record)
            s["image"] = str((SHOTS / record["file"]).resolve())
        else:
            print(f"  [{s['index']:3d}] no usable archive image for {query!r}")

    print(f"archive collected: {len(credits)}/{len(archive)}")

    cards = [s for s in scenes if s["source"] == "infographic"]
    print(f"infographic scenes: {len(cards)}")
    specs, carded, skipped = [], [], 0
    for scene in cards:
        result = _normalise_card(scene.get("card") or {})
        if result is None:
            # No usable card. Drop the stale image too: card files are rewritten
            # each run, so a leftover path would now point at a different card.
            scene["source"] = "generated"
            scene.pop("card", None)
            scene.pop("image", None)
            skipped += 1
            continue
        kind, headline, sub = result
        spec = (("timer", {"label": headline, "sublabel": sub}) if kind == "timer"
                else ("number", {"value": headline, "caption": sub}))
        specs.append(spec)
        # The renderer needs the spec, not just the PNG, to animate the reveal.
        scene["card_spec"] = spec
        carded.append(scene)
    if skipped:
        print(f"  {skipped} card(s) had no usable content; those scenes will borrow a frame")
    cards = carded
    paths = infographics.render_all(specs, CARDS)
    for s, p in zip(cards, paths):
        s["image"] = str(p.resolve())

    visuals.write_credits(credits, KT3 / "credits.json")
    (KT3 / "scenes.json").write_text(
        json.dumps(scenes, indent=2, ensure_ascii=False), encoding="utf-8")

    have = sum(1 for s in scenes if s.get("image"))
    print(f"\nscenes with an image: {have}/{len(scenes)}")
    print(f"still needing the GPU step: "
          f"{sum(1 for s in scenes if s['source'] == 'generated')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
