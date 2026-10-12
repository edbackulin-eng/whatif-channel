"""Title, description, tags and chapter markers for the upload package.

Everything here is assembled locally from material the pipeline already has, so
the description's sources and music credits can never drift from what is actually
in the video.
"""
import json
from pathlib import Path

from core.logger import get_logger

log = get_logger("seo")

TITLE_LIMIT = 60
DESC_LIMIT = 5000
TAG_CHARS_LIMIT = 460        # YouTube counts the whole tag list, ~500 with commas


def _timestamp(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def build_chapters(sections):
    """`sections` is [(start_seconds, label)]. YouTube needs the first at 0:00."""
    lines = []
    for i, (start, label) in enumerate(sections):
        ts = _timestamp(0 if i == 0 else start)
        lines.append(f"{ts} {label}")
    return "\n".join(lines)


def build_description(hook, chapters, credit_block, music_credits, sources_note):
    """First two lines carry the key phrase; everything else follows."""
    parts = [
        hook.strip(),
        "",
        "CHAPTERS",
        chapters,
        "",
        "IMAGERY",
        credit_block.strip(),
        "",
        "MUSIC",
        music_credits.strip(),
        "",
        "SOURCES",
        sources_note.strip(),
        "",
        "This video explores a hypothetical scenario. The physics around it is real;",
        "the premise is not. Parts of this video were produced with AI tools.",
    ]
    desc = "\n".join(parts)
    if len(desc) > DESC_LIMIT:
        desc = desc[:DESC_LIMIT - 3] + "..."
    return desc


def build_tags(base, extra=()):
    tags, total = [], 0
    for t in [*base, *extra]:
        if total + len(t) + 1 > TAG_CHARS_LIMIT:
            break
        tags.append(t)
        total += len(t) + 1
    return tags


def write_metadata(path, title, description, tags, hashtags, extra=None):
    if len(title) > TITLE_LIMIT:
        log.warning("title is %d chars, over the %d limit", len(title), TITLE_LIMIT)
    body = [
        f"TITLE ({len(title)}/{TITLE_LIMIT} chars)",
        title,
        "",
        f"DESCRIPTION ({len(description)} chars)",
        description,
        "",
        f"TAGS ({len(tags)})",
        ", ".join(tags),
        "",
        "HASHTAGS",
        " ".join(hashtags),
        "",
        "UPLOAD SETTINGS",
        "categoryId: 28 (Science & Technology)",
        "defaultLanguage: en",
        "defaultAudioLanguage: en",
        "privacyStatus: private",
        "containsSyntheticMedia: true   # AI-generated imagery and synthetic voice",
        "madeForKids: false",
    ]
    if extra:
        body += ["", json.dumps(extra, indent=2)]
    Path(path).write_text("\n".join(body), encoding="utf-8")
    log.info("wrote %s", Path(path).name)


def sources_note(sources_json_path, max_lines=14):
    """A short human-readable digest of what the fact-check verified."""
    data = json.loads(Path(sources_json_path).read_text(encoding="utf-8"))
    seen, lines = set(), []
    for claim in data.get("claims", []):
        src = (claim.get("source") or "").strip()
        if not src or src.lower() in ("none", "n/a") or src in seen:
            continue
        seen.add(src)
        lines.append(f"- {src}")
        if len(lines) >= max_lines:
            break
    total = data.get("claims_checked", data.get("checked", 0))
    flagged = data.get("flagged_for_human", 0)
    header = (f"{total} factual claims were verified against the sources below "
              f"before recording.")
    if flagged:
        header += f" {flagged} remain under review."
    return "\n".join([header, *lines])
