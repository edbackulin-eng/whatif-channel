"""Carry generated frames across a re-plan, matching by narration text.

When the script is corrected the narration changes length, so scene boundaries
have to be recomputed from the new subtitles - which renumbers every scene. The
131 GPU frames were made for the OLD numbering, and re-generating them all costs
another ~83 minutes of GPU for material that is ~95% unchanged.

So each new generated scene is matched to the old scene whose narration it most
resembles, and inherits that frame. Anything without a close match is reported
for a small top-up batch rather than silently reused, because a frame attached to
the wrong narration is exactly the failure this pipeline keeps almost shipping.
"""
import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KT3 = ROOT / "output" / "kt3"

# Below this the texts are different enough that the picture probably does not fit.
MATCH_FLOOR = 0.72


def similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def remap(old_scenes, new_scenes):
    """Attach old generated images to the new scenes that best match them."""
    pool = [s for s in old_scenes if s.get("source") == "generated" and s.get("image")]
    used, matched, weak = set(), 0, []
    for s in new_scenes:
        if s.get("source") != "generated":
            continue
        best, best_score = None, 0.0
        for old in pool:
            if id(old) in used:
                continue
            score = similarity(s["text"], old["text"])
            if score > best_score:
                best, best_score = old, score
        if best is not None and best_score >= MATCH_FLOOR:
            s["image"] = best["image"]
            s["match_score"] = round(best_score, 3)
            used.add(id(best))
            matched += 1
        else:
            weak.append((s["index"], round(best_score, 3), s["text"][:70]))
    return matched, weak


def main():
    old = json.loads((KT3 / "scenes_old.json").read_text(encoding="utf-8"))
    new = json.loads((KT3 / "scenes.json").read_text(encoding="utf-8"))
    need = sum(1 for s in new if s.get("source") == "generated")
    matched, weak = remap(old, new)
    (KT3 / "scenes.json").write_text(
        json.dumps(new, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"generated scenes in new plan : {need}")
    print(f"frames carried over          : {matched}")
    print(f"needing a fresh frame        : {len(weak)}")
    for idx, score, text in weak[:20]:
        print(f"   [{idx:3d}] best match {score:.2f}  {text}")
    if weak:
        (KT3 / "needs_frames.json").write_text(
            json.dumps([w[0] for w in weak], indent=2), encoding="utf-8")
        print(f"\nwrote needs_frames.json ({len(weak)} scenes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
