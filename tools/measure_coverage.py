"""Measure how much of a video's shot list the free archives can actually cover.

Counts DISTINCT rights-clean NASA assets per topic, because a scene list needs
distinct frames: the same Earthrise reused eight times is one usable image, not
eight. Run before committing to a topic, so the FLUX budget is known up front.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import visuals  # noqa: E402

# A 20-minute video at 4-7s per scene.
VIDEO_MIN = 20
SCENE_S_MIN, SCENE_S_MAX = 4.0, 7.0

# Share of first-choice NASA assets that cleared the 1920x1080 gate in KT2
# (9 of 12 originals were big enough; the rest were archive thumbnails).
RESOLUTION_PASS = 0.75

TOPICS = {
    "What If the Moon Fell to Earth?": [
        "moon surface craters", "earthrise from lunar orbit", "full moon",
        "lunar terminator", "earth from space ocean", "coastline from orbit",
        "ocean waves from space", "city lights at night from orbit",
        "earth atmosphere limb", "hurricane from space", "tsunami coastline",
        "earthquake damage", "volcanic eruption from space", "tidal flats",
        "lunar far side", "apollo lunar surface", "moon orbiting earth",
        "earth terminator day night", "meteor entering atmosphere",
        "impact crater earth", "lunar regolith close up", "earth polar ice",
    ],
    "What If the Internet Disappeared?": [
        "data center servers", "fiber optic cable", "undersea cable ship",
        "server room racks", "people using smartphones", "office workers computers",
        "city traffic intersection", "stock exchange trading floor",
        "hospital equipment room", "power grid substation",
    ],
    "What If Earth Stopped Spinning?": [
        "earth rotation from space", "earth day night terminator",
        "jet stream clouds", "ocean currents from space", "desert landscape",
        "atmospheric circulation", "earth equator from orbit",
        "wind erosion landscape", "frozen landscape", "city skyline daytime",
    ],
}


def scenes_needed():
    total_s = VIDEO_MIN * 60
    return round(total_s / SCENE_S_MAX), round(total_s / SCENE_S_MIN)


def measure(name, queries):
    seen, rights_rejected, offtopic = set(), 0, 0
    per_query = []
    for q in queries:
        try:
            results = visuals.search(q, limit=40)
        except Exception as e:
            print(f"    ! {q!r}: {e}")
            per_query.append((q, 0))
            continue
        new = {r["nasa_id"] for r in results} - seen
        seen |= new
        per_query.append((q, len(results)))
    return seen, per_query


def main():
    lo, hi = scenes_needed()
    print(f"A {VIDEO_MIN}-minute video at {SCENE_S_MIN:.0f}-{SCENE_S_MAX:.0f}s per scene")
    print(f"needs {lo}-{hi} distinct scenes.\n")
    print(f"(NASA assets are also filtered by resolution; in KT2 "
          f"{RESOLUTION_PASS:.0%} of first-choice originals cleared 1920x1080.)\n")

    for name, queries in TOPICS.items():
        print("=" * 72)
        print(name)
        print("=" * 72)
        seen, per_query = measure(name, queries)
        thin = [q for q, n in per_query if n < 5]
        usable = int(len(seen) * RESOLUTION_PASS)
        print(f"  queries run           : {len(queries)}")
        print(f"  distinct clean assets : {len(seen)}")
        print(f"  after resolution gate : ~{usable}")
        print(f"  covers                : {usable / lo:5.0%} of a {lo}-scene cut")
        print(f"  FLUX + infographics   : ~{max(0, lo - usable)} scenes")
        if thin:
            print(f"  thin queries (<5 hits): {len(thin)}/{len(queries)}")
            for q in thin[:6]:
                print(f"      - {q}")
        print()


if __name__ == "__main__":
    sys.exit(main())
