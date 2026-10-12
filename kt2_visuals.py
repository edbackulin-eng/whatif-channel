"""KT2: fetch the shot list for the Moon fragment and write its credits ledger."""
import sys
from pathlib import Path

from pipeline import visuals

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output" / "kt2" / "shots"

# One query per beat of the 60-second fragment, in order. `require` and `exclude`
# keep NASA's keyword search on the right celestial body: without them it answers
# "full moon" with Io and "tidal forces" with Saturn's rings.
OTHER_BODIES = ["io ", "europa", "ganymede", "callisto", "titan", "enceladus",
                "saturn", "jupiter", "mars", "venus", "mercury", "pluto",
                "phobos", "deimos", "triton", "asteroid", "comet"]
MOON = ["moon", "lunar", "apollo"]
EARTH = ["earth", "ocean", "coast", "sea", "land", "cloud", "city", "continent"]

SHOTS = [
    ("full moon detailed surface",      MOON,  OTHER_BODIES),
    ("earth from the moon",             MOON,  OTHER_BODIES),
    ("moon rising over earth horizon",  MOON,  OTHER_BODIES),
    ("ocean from space",                EARTH, OTHER_BODIES),
    ("coastline from orbit",            EARTH, OTHER_BODIES),
    ("ocean waves shoreline",           EARTH, OTHER_BODIES),
    ("earth city lights at night",      EARTH, OTHER_BODIES),
    ("moon close up craters",           MOON,  OTHER_BODIES),
    ("earth atmosphere limb sunrise",   EARTH, OTHER_BODIES),
    ("earth ocean tides coastline",     EARTH, OTHER_BODIES),
    ("lunar surface terminator",        MOON,  OTHER_BODIES),
    ("earth blue marble full disk",     EARTH, OTHER_BODIES),
]


def main():
    records, used_ids = [], set()
    for i, (query, require, exclude) in enumerate(SHOTS, 1):
        try:
            candidates = visuals.search(query, limit=6, require=require, exclude=exclude)
        except Exception as e:
            print(f"[{i:2d}] SEARCH FAILED {query!r}: {e}")
            continue
        # Walk the candidates until one is both unused and big enough for 1080p.
        record = None
        for pick in candidates:
            if pick["nasa_id"] in used_ids:
                continue
            try:
                record = visuals.download(pick, OUT, i)
            except Exception as e:
                print(f"[{i:2d}] download failed {pick['nasa_id']}: {e}")
                continue
            if record:
                used_ids.add(pick["nasa_id"])
                break
        if not record:
            print(f"[{i:2d}] no usable result for {query!r}")
            continue
        record["query"] = query
        records.append(record)
        print(f"[{i:2d}] {record['file']:38s} | {record['dimensions']:>9s} | {record['credit']}")

    visuals.write_credits(records, OUT.parent / "credits.json")
    print(f"\n{len(records)}/{len(SHOTS)} shots collected")
    print("\n--- description attribution block ---")
    print(visuals.description_credits(records))


if __name__ == "__main__":
    sys.exit(main())
