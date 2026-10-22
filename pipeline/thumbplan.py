"""What this episode's thumbnail should show: a face, the event, two or three words.

Until now the thumbnail was a still lifted out of the finished episode with the
title stacked on top of it. Stills are composed for a twenty-minute film - wide,
cool, restrained, people deliberately kept as distant silhouettes (core/style.py
asks for exactly that) - and at browse size they read as a blue-grey rectangle.

The channel that owns this niche does the opposite. "What If You DIED on Every
Planet" (16.9 M views) puts a human face at the front carrying the emotion, the
event itself filling the rest of the frame in saturated colour, and one shouted
word. When the episode sets two things against each other it splits down the
middle with a label over each half.

So a thumbnail now gets its own generations instead of a leftover frame, and this
module decides what to ask for:

  event        one bright visual phrase for the thing the episode is about
  words        nothing, or one to three enormous words
  comparison   two labelled halves, when the title weighs one thing against
               another

Gemini writes the brief. When it is unreachable the brief is derived from the
title instead, because an unimaginative thumbnail still ships and a build that
stopped for a missing API key does not.
"""
import json
import re
from pathlib import Path

from core.logger import get_logger

log = get_logger("thumbplan")

CANDIDATES = 6          # 4-6 is the useful range: enough that the judge has a choice
BRIEF_FILE = "thumbnail_brief.json"
MAX_WORD_CHARS = 11     # longer than this and the line cannot be enormous

SYSTEM = """You write briefs for YouTube thumbnails on a science channel about
what-if scenarios. A thumbnail has a human face in the foreground carrying the
emotion and the event itself filling the rest of the frame.

Return JSON only:
{"event":"<one vivid visual phrase, 8-18 words, of the EVENT the episode is
  about: what it looks like, bright and saturated - fire, lava, ice, storm,
  deep space, flood. Never dark, never empty, no people in it, no text in it>",
 "words":["<ONE WORD>","<one or two words>"],
 "comparison": null or
   {"left":{"label":"<ONE WORD>","event":"<visual phrase as above>"},
    "right":{"label":"<ONE WORD>","event":"<visual phrase as above>"}}}

Rules for "words": one to three entries, each one or two short words, UPPERCASE,
at most 11 characters per entry. They are read in a tenth of a second at the size
of a postage stamp, so pick the shock, not the sentence: DIED, NO OXYGEN,
8 MINUTES. Never the whole title. An empty list is allowed when the picture says
it on its own.

Set "comparison" only when the episode genuinely weighs two named things against
each other; otherwise null."""

# Enough of the channel's own subject matter that the fallback is not generic.
# Ordered so the more specific key is found first ("black hole" before "sun").
IMAGERY = (
    ("black hole", "a black hole's accretion disc blazing white and orange, light bending around it"),
    ("magnetic field", "solar wind stripping a planet's air away in sheets of green and red aurora"),
    ("photosynthesis", "a forest going grey and leafless under a hard white sky, dust in the air"),
    ("atmosphere", "the sky tearing open above a city, air rushing upward into black space"),
    ("satellite", "a storm of broken satellites and debris streaking over a lit city at night"),
    ("volcano", "a wall of orange lava and ash erupting into a glowing red sky"),
    ("gravity", "a city street buckling and collapsing, concrete cracking, dust blasting outward"),
    ("spinning", "a planet's oceans sliding into vast walls of water under a violent sky"),
    ("spun", "a planet's oceans sliding into vast walls of water under a violent sky"),
    ("orbit", "the earth seen from space with one hemisphere scorched orange and one iced white"),
    ("pacific", "a drained ocean floor of cracked mud and stranded ships under a burning sun"),
    ("ocean", "a drained ocean floor of cracked mud and stranded wrecks under a burning sun"),
    ("jupiter", "jupiter's banded storms filling the sky, the great red spot churning"),
    ("moon", "an enormous cracked moon low over a city, orange fissures glowing across it"),
    ("internet", "a city at night with every screen and light dead, only headlights moving"),
    ("venus", "the surface of venus under crushing orange cloud, lightning in the haze"),
    ("mars", "a red martian dust storm swallowing a habitat dome"),
    ("sun", "a dead black sun in a frozen sky above a city buried in blue ice"),
    ("ice", "a city locked in blue glacier ice, buildings swallowed to the roofline"),
    ("planet", "an alien planet filling the sky, storm bands and rings catching hard sunlight"),
)

# Words that carry the shock of a What If title, preferred over anything else
# when one of them appears in it.
PUNCH = ("died", "vanished", "disappeared", "stopped", "drained", "doubled",
         "erupted", "failed", "exploded", "collapsed", "froze", "frozen",
         "burned", "shifted", "fell", "lost")

STOP = {"what", "if", "the", "a", "an", "on", "in", "of", "to", "for", "and",
        "at", "its", "it", "was", "were", "had", "has", "every", "all", "over",
        "through", "with", "from", "as", "by", "did", "do", "would", "could",
        "s", "earth"}

_SPLIT_RE = re.compile(r"\s+(?:vs|versus)\s+", re.I)


def _core(title):
    """The title without its "What If" scaffolding or question mark."""
    t = re.sub(r"^\s*what\s+if\s+", "", title or "", flags=re.I)
    return t.strip().rstrip("?").strip()


def _imagery(text):
    low = (text or "").lower()
    return next((img for key, img in IMAGERY if key in low), None)


def fallback_brief(title):
    """A brief from the title alone, for when no model answers."""
    core = _core(title)
    event = _imagery(core) or (
        f"{core}, filling the frame, vivid saturated colour, hard dramatic light")
    comparison = None
    parts = _SPLIT_RE.split(core, maxsplit=1)
    if len(parts) == 2 and all(p.strip() for p in parts):
        comparison = {
            side: {"label": part.strip().upper()[:MAX_WORD_CHARS],
                   "event": _imagery(part) or
                   f"{part.strip()}, vivid saturated colour, hard dramatic light"}
            for side, part in zip(("left", "right"), parts)}
    # A split already has a label over each half; a word block on top of that is
    # three pieces of type on one card and none of them is read.
    words = [] if comparison else _fallback_words(core)
    return {"event": event, "words": words, "comparison": comparison,
            "source": "title"}


def _fallback_words(core):
    """One or two shouted lines from the title's own words."""
    low = core.lower()
    hit = next((p for p in PUNCH if p in low), None)
    if hit:
        subject = " ".join(w for w in low.split(hit)[0].split() if w not in STOP)
        lines = [hit.upper()]
        if subject and len(subject) <= MAX_WORD_CHARS:
            lines.insert(0, subject.upper())
        return lines
    content = [w.strip(",.'") .upper() for w in core.split()
               if w.lower().strip(",.'") not in STOP]
    return _pack(content[:3])


def _pack(words, limit=MAX_WORD_CHARS):
    """Group words into lines of at most `limit` characters, at most three lines."""
    lines, current = [], ""
    for w in words:
        candidate = f"{current} {w}".strip()
        if current and len(candidate) > limit:
            lines.append(current)
            current = w
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines[:3]


def _clean(raw, title):
    """Keep a model's brief only where it obeys the rules; patch the rest."""
    fb = fallback_brief(title)
    event = (raw.get("event") or "").strip()
    words = [str(w).strip().upper() for w in (raw.get("words") or []) if str(w).strip()]
    words = [w for w in words if len(w) <= MAX_WORD_CHARS and len(w.split()) <= 2][:3]
    comparison = raw.get("comparison") or None
    if isinstance(comparison, dict) and {"left", "right"} <= set(comparison):
        sides = {}
        for side in ("left", "right"):
            s = comparison.get(side) or {}
            label = str(s.get("label") or "").strip().upper()[:MAX_WORD_CHARS]
            ev = str(s.get("event") or "").strip()
            if not label or len(ev.split()) < 3:
                sides = {}
                break
            sides[side] = {"label": label, "event": ev}
        comparison = sides or None
    else:
        comparison = None
    return {"event": event if 4 <= len(event.split()) <= 30 else fb["event"],
            "words": words,            # an empty list is a legitimate answer
            # "model", not "gemini": core/llm.py falls back to Groq, and on the
            # first real run Gemini answered 503 and Groq wrote all four briefs.
            # A field that names the wrong provider is worse than a vague one.
            "comparison": comparison, "source": "model"}


def brief(episode, work=None, use_llm=True):
    """The thumbnail brief for an episode, cached beside the build when `work` is given."""
    work = Path(work) if work else None
    if work and (work / BRIEF_FILE).exists():
        cached = json.loads((work / BRIEF_FILE).read_text(encoding="utf-8"))
        log.info("thumbnail brief already present (%s)", cached.get("source", "?"))
        return cached
    episode = episode or {}
    title = episode.get("title", "")
    out = None
    if use_llm:
        from core import llm
        try:
            prompt = (f'Episode title: "{title}"\n'
                      f'Hook: "{episode.get("hook", "")}"\n\n'
                      "Write the thumbnail brief.")
            out = _clean(llm.complete_json(prompt, system=SYSTEM, max_tokens=700,
                                           temperature=0.6), title)
        except Exception as e:                                   # noqa: BLE001
            log.warning("no thumbnail brief from the model (%s); deriving it from "
                        "the title", e)
    if out is None:
        out = fallback_brief(title)
    # thumbnail_lines in the queue entry is a human override and outranks any model.
    override = [str(w).strip().upper() for w in episode.get("thumbnail_lines") or []
                if str(w).strip()]
    if override:
        out["words"] = (override[:3] if all(len(w) <= MAX_WORD_CHARS for w in override)
                        else _pack(" ".join(override).split()))
        out["words_source"] = "queue entry"
    log.info("thumbnail brief (%s): words=%s, comparison=%s", out["source"],
             out["words"], bool(out["comparison"]))
    if work:
        (work / BRIEF_FILE).write_text(json.dumps(out, indent=2, ensure_ascii=False),
                                       encoding="utf-8")
    return out


def candidates(brief_, n=CANDIDATES):
    """The FLUX prompts for one episode's thumbnail, as a list of
    {"role": "single"|"left"|"right", "label": str, "prompt": str}.

    A comparison brief spends its budget on both halves, alternating, so the
    split can be assembled from the best surviving face on each side.
    """
    from core import style
    comparison = brief_.get("comparison")
    out = []
    if comparison:
        for i in range(max(2, n // 2)):
            for side in ("left", "right"):
                out.append({"role": side, "label": comparison[side]["label"],
                            "prompt": style.thumbnail_prompt(
                                comparison[side]["event"], i, centred=True)})
    else:
        for i in range(n):
            out.append({"role": "single", "label": "",
                        "prompt": style.thumbnail_prompt(brief_["event"], i)})
    return out[:n]
