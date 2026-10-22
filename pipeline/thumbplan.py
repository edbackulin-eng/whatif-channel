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
each other; otherwise null.

Also return where the PERSON in the foreground is when it happens to them:
 "setting":"earth" or "space",
 "place":"street" | "coast" | "rooftop" | "home" | "field"
"space" ONLY when the story itself takes place in space - a black hole passing
through the solar system, a trip to another planet, life on a space station.
Everything experienced from the ground is "earth", even when the cause is up
in the sky: two moons, a vanished Jupiter, failing satellites, a shifted orbit
are all seen by an ordinary person on Earth. "place" is the real location on
Earth that suits the event best (a coast for oceans and melting ice, a street
for collapsing cities, a rooftop for something in the sky); ignored for space."""

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


# Stories that happen in space rather than to someone standing on Earth. Only
# these get a spacesuit; checked as substrings of the title.
SPACE_STORIES = ("black hole", "solar system", "another planet", "on mars",
                 "on venus", "on the moon", "every planet", "space station",
                 "in space", "lost in space", "neptune", "astronaut")
# The real place an Earth-bound story most naturally happens to someone.
PLACE_HINTS = (
    (("ocean", "pacific", "sea level", "antarctica", "ice", "melted", "tsunami",
      "flood"), "coast"),
    (("moon", "jupiter", "satellite", "sky", "orbit", "sun", "star", "aurora",
      "magnetic"), "rooftop"),
    (("photosynthesis", "forest", "crops"), "field"),
    (("internet", "power", "electricity"), "home"),
)


def setting_for(title):
    """("earth" | "space", place) from the title alone."""
    low = (title or "").lower()
    if any(k in low for k in SPACE_STORIES):
        return "space", "street"
    for keys, place in PLACE_HINTS:
        if any(k in low for k in keys):
            return "earth", place
    return "earth", "street"


def fallback_brief(title, avoid=()):
    """A brief from the title alone, for when no model answers."""
    core = _core(title)
    setting, place = setting_for(title)
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
            "setting": setting, "place": place, "source": "title"}


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
    setting = str(raw.get("setting") or "").lower()
    # The model may say "space" for anything with the sky in it. The rule is
    # that a spacesuit belongs only to a story that happens in space, so an
    # Earth-bound subject overrules it: two moons are watched from a rooftop.
    if setting not in ("earth", "space") or (setting == "space" and _earth_bound(title)):
        setting = fb["setting"]
    place = str(raw.get("place") or "").lower()
    if place not in style_places():
        place = fb["place"]
    # A model that answered only with banned or already-used lines has said
    # nothing usable; the title's own words are specific by construction.
    return {"event": event if 4 <= len(event.split()) <= 30 else fb["event"],
            "words": words or fb["words"],
            "setting": setting, "place": place,
            # "model", not "gemini": core/llm.py falls back to Groq, and on the
            # first real run Gemini answered 503 and Groq wrote all four briefs.
            # A field that names the wrong provider is worse than a vague one.
            "comparison": comparison, "source": "model"}


# Subjects that happen to people standing on Earth, whatever the model thinks.
EARTH_STORIES = ("gravity", "volcano", "erupt", "ocean", "pacific", "ice",
                 "antarctica", "melted", "moons", "spun", "spinning", "internet",
                 "photosynthesis", "atmosphere", "magnetic", "satellite", "orbit",
                 "jupiter", "sun went out")


def _earth_bound(title):
    low = (title or "").lower()
    return (any(k in low for k in EARTH_STORIES)
            and not any(k in low for k in SPACE_STORIES))


def style_places():
    from core import style
    return tuple(style.CAST_PLACES)


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


RESTATE_SYSTEM = """You are rewriting the EVENT description for a YouTube
thumbnail because the pictures it produced did not show the episode's subject.
A vision model looked at them and said what was wrong.

Rewrite it blunter and more literal. Name the object, say what shape and colour
it is, and make it the single unmistakable thing in the frame. Drop metaphor,
drop mood words, drop anything the first description was vague about. A viewer
who knows the subject must be able to name it from the picture alone.

Return JSON only: {"event":"<one visual phrase, 8-20 words>"}"""

# What the first description of each subject failed to make literal. Used when
# no model answers, and appended to whatever one does: it is the specific detail
# the judge kept missing, not a general instruction.
LITERAL = (
    ("black hole", "a perfectly black circle at the centre with a thin blazing "
                   "orange ring of matter around it and stars smeared around its edge"),
    ("two moons", "two separate round moons in the same sky, both clearly visible, "
                  "one larger and one smaller"),
    ("moons", "two separate round moons in the same sky, both clearly visible"),
    ("antarctica", "a white ice cliff breaking apart into turquoise meltwater, "
                   "icebergs tipping into the sea"),
    ("gravity", "a street of buildings folded and flattened downward, roofs "
                "collapsed into themselves, concrete dust blasting sideways"),
    ("jupiter", "a vast banded orange and cream gas giant with a red oval storm, "
                "filling most of the sky"),
    ("satellite", "hundreds of broken metal satellites and panels tumbling in low "
                  "orbit above the curve of the earth"),
    ("ocean", "a bare ocean floor of cracked mud with ships lying on their sides, "
              "no water anywhere"),
    ("sun", "a black disc where the sun was, in a dim sky over a city under thick "
            "blue ice"),
    ("atmosphere", "a city under an utterly black star-filled sky with no blue in "
                   "it at all"),
    ("magnetic field", "curtains of green and red aurora over the whole sky, the "
                       "air visibly streaming away into space"),
    ("volcano", "a single enormous volcano throwing a column of orange lava and "
                "black ash straight upward"),
    ("photosynthesis", "a forest of bare grey dead trees with not one green leaf"),
)


def restate(brief_, notes=(), use_llm=True):
    """A blunter event description, after the judge said the pictures were not
    the episode's subject.

    One rewrite, never a loop: another description is a GPU kernel, and a second
    one that still misses costs more than shipping the best picture there is.
    """
    topic = brief_.get("topic") or ""
    literal = next((text for key, text in LITERAL if key in topic.lower()), "")
    out = dict(brief_)
    out["event_first_pass"] = brief_.get("event", "")
    event = None
    if use_llm:
        from core import llm
        try:
            prompt = (f'Episode title: "{topic}"\n'
                      f'The description that failed: "{brief_.get("event", "")}"\n'
                      f'What the vision model said was wrong: '
                      f'{"; ".join(n for n in notes if n) or "it was not the subject"}\n\n'
                      "Rewrite the event description.")
            answer = llm.complete_json(prompt, system=RESTATE_SYSTEM, max_tokens=300,
                                       temperature=0.4)
            candidate = str(answer.get("event") or "").strip()
            if 4 <= len(candidate.split()) <= 36:
                event = candidate
        except Exception as e:                                   # noqa: BLE001
            log.warning("could not restate the event (%s); using the literal "
                        "description", e)
    if not event:
        event = literal or brief_.get("event", "")
    if literal and literal not in event:
        event = f"{event}, {literal}"
    out["event"] = f"{event}, the single unmistakable subject of the picture"
    out["source"] = f"{brief_.get('source', '?')}+restated"
    log.info("restated event: %s", out["event"][:120])
    return out


# --- who is in the picture ---------------------------------------------------------
#
# A feed of five thumbnails with the same screaming man in the same helmet looks
# like one video uploaded five times, and that was where the first published
# batch was heading: three of four were men in spacesuits, two of them in front
# of things happening on Earth. So the person is cast, not fixed. Each thumbnail
# records who it used, in its queue entry next to the words, and the next is
# cast against that record:
#
#   - the gender alternates with the thumbnail before it in the feed;
#   - no one of the same type - gender, age band, appearance - as anyone on the
#     last five thumbnails, or on the next one when a thumbnail is replaced out
#     of order;
#   - not the same camera angle twice in a row.
#
# All the candidates for one thumbnail share a gender, so the rule holds
# whichever of them the judge picks.

CAST_WINDOW = 5
ROOT = Path(__file__).resolve().parent.parent


def _entries(root=None):
    out = []
    for path in sorted(Path(root or ROOT).joinpath("queue").glob("*/episode.json")):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        entry.setdefault("slug", path.parent.name)
        out.append(entry)
    return sorted(out, key=lambda e: e.get("position") or 0)


def neighbours(episode, planned=(), root=None, window=CAST_WINDOW):
    """(previous person, next person, everyone in the window) around this episode.

    Recorded people come from the queue; `planned` adds episodes cast earlier in
    the same run, which have a gender and candidate types but no winner yet.
    """
    pos = (episode or {}).get("position")
    if pos is None:
        return None, None, []
    slug = episode.get("slug")
    planned_slugs = {p.get("slug") for p in planned}
    known = [(e.get("position") or 0, e["thumbnail_person"]) for e in _entries(root)
             if e.get("thumbnail_person") and e.get("slug") != slug
             and e.get("slug") not in planned_slugs]
    known += [(p["position"], p) for p in planned if p.get("slug") != slug]
    before = sorted([k for k in known if k[0] < pos], key=lambda k: -k[0])
    after = sorted([k for k in known if k[0] > pos], key=lambda k: k[0])
    previous = before[0][1] if before else None
    following = after[0][1] if after else None
    near = [k[1] for k in before[:window]] + [k[1] for k in after[:1]]
    return previous, following, near


def _types_of(person):
    """Every type a person entry stands for: one for a recorded winner, all the
    candidates' for an episode planned earlier in this run."""
    from core import style
    if person.get("types"):
        return {tuple(t) for t in person["types"]}
    return {style.person_type(person)}


def cast(episode, n=CANDIDATES, planned=(), root=None):
    """n people for this episode's candidates, cast against the recent record."""
    import random
    from core import style
    episode = episode or {}
    previous, following, near = neighbours(episode, planned, root)
    anchor = previous or following
    if anchor and anchor.get("gender") in style.CAST_GENDERS:
        gender = next(g for g in style.CAST_GENDERS if g != anchor["gender"])
    else:
        gender = style.CAST_GENDERS[(episode.get("position") or 0) % 2]
    avoid = set()
    for person in near:
        avoid |= _types_of(person)
    rng = random.Random(episode.get("slug") or "whatif")
    pool = [(age, look) for age in style.CAST_AGES for look in style.CAST_LOOKS
            if (gender, style.age_band(age), look) not in avoid]
    if len(pool) < n:
        # Not enough unused types left: relax to "not the one right next to it".
        nearest = set()
        for person in (previous, following):
            if person:
                nearest |= _types_of(person)
        pool = [(age, look) for age in style.CAST_AGES for look in style.CAST_LOOKS
                if (gender, style.age_band(age), look) not in nearest]
    rng.shuffle(pool)
    # Spread the candidates across looks first and ages second, so the judge is
    # choosing between different people rather than six near-twins.
    picked, looks, ages = [], set(), set()
    for strict in (True, False):
        for age, look in pool:
            if len(picked) == n:
                break
            if (age, look) in picked:
                continue
            if strict and (look in looks or
                           (age in ages and len(ages) < len(style.CAST_AGES))):
                continue
            picked.append((age, look))
            looks.add(look)
            ages.add(age)
    # Both neighbours, not just the one before: a thumbnail replaced out of order
    # sits next to the one after it in the feed just the same.
    taken = {(p or {}).get("angle") for p in (previous, following)}
    angles = [a for a in style.CAST_ANGLES if a not in taken] or list(style.CAST_ANGLES)
    rng.shuffle(angles)
    clothes = list(style.CAST_CLOTHES)
    rng.shuffle(clothes)
    people = []
    for i, (age, look) in enumerate(picked):
        people.append({"gender": gender, "age": age, "look": look,
                       "angle": angles[i % len(angles)],
                       "expression": style.CAST_EXPRESSIONS[i % len(style.CAST_EXPRESSIONS)],
                       "clothes": clothes[i % len(clothes)]})
    log.info("cast: %d %s candidate(s), %d type(s) avoided (previous: %s)", len(people),
             gender, len(avoid), (previous or {}).get("gender", "none on record"))
    return people


def as_planned(episode, people):
    """How an episode cast earlier in this run is seen by the ones after it."""
    from core import style
    return {"slug": episode.get("slug"), "position": episode.get("position") or 0,
            "gender": people[0]["gender"] if people else None,
            "types": [list(style.person_type(p)) for p in people]}


def remember_person(episode, person, root=None):
    """Record who is on this episode's thumbnail, for the next one to avoid."""
    slug = (episode or {}).get("slug")
    if not slug or not person:
        return
    path = Path(root or ROOT) / "queue" / slug / "episode.json"
    if not path.exists():
        return
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    keep = {k: person[k] for k in ("gender", "age", "look", "angle", "setting")
            if k in person}
    if entry.get("thumbnail_person") == keep:
        return
    entry["thumbnail_person"] = keep
    path.write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    log.info("recorded this episode's thumbnail person: %s %s, %s", keep.get("look"),
             keep.get("gender"), keep.get("age"))


def candidates(brief_, people=None, n=CANDIDATES):
    """The FLUX prompts for one episode's thumbnail, as a list of
    {"role": "single"|"left"|"right", "label", "prompt", "person"}.

    One person per candidate, from `people` (see cast()); without it a cast is
    made with no history. A comparison brief spends its budget on both halves,
    alternating, so the split can be assembled from the best face on each side.
    """
    from core import style
    people = list(people or cast({}, n))
    setting = brief_.get("setting") or "earth"
    place = brief_.get("place") or "street"
    comparison = brief_.get("comparison")
    out = []
    if comparison:
        for i in range(max(2, n // 2)):
            for side in ("left", "right"):
                person = people[len(out) % len(people)]
                out.append({"role": side, "label": comparison[side]["label"],
                            "person": {**person, "setting": setting},
                            "prompt": style.thumbnail_prompt(
                                comparison[side]["event"], person, setting, place,
                                centred=True)})
    else:
        for i in range(n):
            person = people[i % len(people)]
            out.append({"role": "single", "label": "",
                        "person": {**person, "setting": setting},
                        "prompt": style.thumbnail_prompt(brief_["event"], person,
                                                         setting, place)})
    return out[:n]
