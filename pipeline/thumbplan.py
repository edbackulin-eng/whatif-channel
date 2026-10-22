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
MAX_LINES = 2           # three lines read as a sentence; a sentence is not read

SYSTEM = """You write briefs for YouTube thumbnails on a science channel about
what-if scenarios. A thumbnail has a human face in the foreground carrying the
emotion and the event itself filling the rest of the frame.

Return JSON only:
{"event":"<one vivid visual phrase, 8-18 words, of the EVENT the episode is
  about: what it looks like, bright and saturated - fire, lava, ice, storm,
  deep space, flood. Never dark, never empty, no people in it, no text in it>",
 "words":["<ONE OR TWO WORDS>","<one or two words, optional>"],
 "comparison": null or
   {"left":{"label":"<ONE WORD>","event":"<visual phrase as above>"},
    "right":{"label":"<ONE WORD>","event":"<visual phrase as above>"}}}

"event" must be recognisable as the SPECIFIC thing in the title, not a generic
catastrophe. A black hole is a black circle with a bright orange accretion disc
around it and starlight bending at its edge - not a sun and not an explosion.
Two moons means two moons, both visible in the sky. Antarctica melting is ice
cliffs calving into turquoise water. A viewer who knows the subject must be able
to name it from the picture alone.

Rules for "words": ONE or TWO entries, never three. Each is one or two short
words, UPPERCASE, at most 11 characters. They name THIS episode's subject
concretely, the way these do: "2X GRAVITY", "BLACK HOLE?", "NO MORE ICE",
"TWO MOONS?", "8 MINUTES", "NO OXYGEN". Never the whole title.

Banned, because they say nothing and could sit on any video on the channel:
CHAOS, NO ESCAPE, DESTROYED, DOOMED, DOOM, THE END, IT'S OVER, DANGER,
DISASTER, CATASTROPHE, SHOCKING, INSANE, CRAZY, TERROR, NIGHTMARE, APOCALYPSE,
GAME OVER, YOU DIE, WE DIE, THE TRUTH, WHAT HAPPENS, FOREVER. Do not use a
synonym of these either. An empty list is better than a generic one.

Set "comparison" only when the episode genuinely weighs two named things against
each other; otherwise null."""

# Lines already on another episode's thumbnail are passed to the model to avoid,
# and dropped if it uses one anyway: two cards side by side in a feed reading the
# same two words is the channel looking automated.
AVOID_HEADER = ("Lines already used on this channel's other thumbnails. Do not "
                "use any of them, or anything close to them: ")

# Checked against a line with its spaces removed, so "NO ESCAPE" and "NOESCAPE"
# both go. Generic shock words carry no information about which video this is.
BANNED = {
    "chaos", "noescape", "destroyed", "doomed", "doom", "theend", "itsover",
    "danger", "disaster", "catastrophe", "shocking", "insane", "crazy",
    "terror", "nightmare", "apocalypse", "gameover", "youdie", "wedie",
    "thetruth", "whathappens", "forever", "deadly", "extinction", "theworst",
}

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


def fallback_brief(title, avoid=()):
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
    words = [] if comparison else _fallback_words(core, avoid)
    return {"event": event, "words": words, "comparison": comparison,
            "source": "title"}


def _fallback_words(core, avoid=()):
    """One or two lines from the title's own words.

    The title names the subject, so lines taken from it are specific by
    construction - which is the one thing a generic shock word is not.
    """
    low = core.lower()
    hit = next((p for p in PUNCH if p in low), None)
    if hit:
        subject = " ".join(w for w in low.split(hit)[0].split() if w not in STOP)
        lines = [hit.upper()]
        if subject and len(subject) <= MAX_WORD_CHARS:
            lines.insert(0, subject.upper())
    else:
        content = [w.strip(",.'").upper() for w in core.split()
                   if w.lower().strip(",.'") not in STOP]
        lines = _pack(content[:4])
    kept = [l for l in lines if _acceptable(l, avoid)]
    # Everything was banned or already used. A question out of the subject is
    # still this episode's and nobody else's.
    if not kept:
        subject = " ".join(w for w in core.split()
                           if w.lower().strip(",.'") not in STOP)[:MAX_WORD_CHARS - 1]
        kept = [f"{subject.upper().strip()}?"] if subject.strip() else []
    return kept[:MAX_LINES]


def _pack(words, limit=MAX_WORD_CHARS):
    """Group words into lines of at most `limit` characters, at most two lines."""
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
    return lines[:MAX_LINES]


def _key(line):
    return "".join(ch for ch in str(line).lower() if ch.isalnum())


def _acceptable(line, avoid):
    """A line that is neither a generic shock word nor another episode's."""
    k = _key(line)
    return bool(k) and k not in BANNED and k not in avoid


def used_words(exclude_slug=None, root=None):
    """Every line already on another episode's thumbnail, as comparison keys.

    Read from the queue entries themselves, which the build commits anyway, so
    there is no new file to keep in step with them.
    """
    root = Path(root or Path(__file__).resolve().parent.parent)
    out = set()
    for path in sorted((root / "queue").glob("*/episode.json")):
        if exclude_slug and path.parent.name == exclude_slug:
            continue
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.update(_key(w) for w in entry.get("thumbnail_words") or [])
    return {k for k in out if k}


def remember(episode, words, root=None):
    """Record the lines this episode used, so the next one does not repeat them."""
    root = Path(root or Path(__file__).resolve().parent.parent)
    slug = (episode or {}).get("slug")
    if not slug or not words:
        return
    path = root / "queue" / slug / "episode.json"
    if not path.exists():
        return
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if entry.get("thumbnail_words") == list(words):
        return
    entry["thumbnail_words"] = list(words)
    path.write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    log.info("recorded this episode's thumbnail words: %s", words)


def _clean(raw, title, avoid=()):
    """Keep a model's brief only where it obeys the rules; patch the rest."""
    fb = fallback_brief(title, avoid)
    event = (raw.get("event") or "").strip()
    words = [str(w).strip().upper() for w in (raw.get("words") or []) if str(w).strip()]
    words = [w for w in words
             if len(w) <= MAX_WORD_CHARS and len(w.split()) <= 2
             and _acceptable(w, avoid)][:MAX_LINES]
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
    # A model that answered only with banned or already-used lines has said
    # nothing usable; the title's own words are specific by construction.
    return {"event": event if 4 <= len(event.split()) <= 30 else fb["event"],
            "words": words or fb["words"],
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
    avoid = used_words(exclude_slug=episode.get("slug"))
    out = None
    if use_llm:
        from core import llm
        try:
            prompt = (f'Episode title: "{title}"\n'
                      f'Hook: "{episode.get("hook", "")}"\n\n')
            if avoid:
                prompt += AVOID_HEADER + ", ".join(sorted(avoid)) + "\n\n"
            out = _clean(llm.complete_json(prompt + "Write the thumbnail brief.",
                                           system=SYSTEM, max_tokens=700,
                                           temperature=0.6), title, avoid)
        except Exception as e:                                   # noqa: BLE001
            log.warning("no thumbnail brief from the model (%s); deriving it from "
                        "the title", e)
    if out is None:
        out = fallback_brief(title, avoid)
    # thumbnail_lines in the queue entry is a human override and outranks any model.
    override = [str(w).strip().upper() for w in episode.get("thumbnail_lines") or []
                if str(w).strip()]
    if override:
        out["words"] = (override[:MAX_LINES]
                        if all(len(w) <= MAX_WORD_CHARS for w in override)
                        else _pack(" ".join(override).split()))
        out["words_source"] = "queue entry"
    out["topic"] = title
    log.info("thumbnail brief (%s): words=%s, comparison=%s, %d line(s) avoided",
             out["source"], out["words"], bool(out["comparison"]), len(avoid))
    remember(episode, out["words"])
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
