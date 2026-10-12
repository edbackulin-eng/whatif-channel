"""Write an episode script, via Claude where possible.

Provider order is set in config.json (`script_source`). Claude is the default
because the channel's voice was developed with it; Gemini and Groq exist so a
bad day at Anthropic costs a slightly weaker script rather than a missed upload.

Claude runs headless through the CLI (`claude -p`), authenticated with a token
from `claude setup-token`, so it draws on the existing subscription instead of
metered API credit.
"""
import json
import os
import re
import subprocess
from pathlib import Path

from core import llm
from core.logger import get_logger
from core.text import word_count

log = get_logger("scriptwriter")

PROVIDERS = ("claude", "gemini", "groq")
MIN_WORDS, MAX_WORDS = 2800, 3800
CLAUDE_TIMEOUT_S = 900

SYSTEM = """You write narration for a YouTube channel that explores scientific
"what if" scenarios. The narrator is calm, precise and conversational.

Hard rules:
- Second person where it helps, present tense, short sentences, plain words.
- No markdown, no headings, no bullets, no stage directions, no parentheses.
  A speech synthesiser reads this aloud, so write continuous prose only.
- Every number must be real and checkable. Never invent a figure. If you are
  unsure of a value, describe the magnitude in words instead.
- State the premise as impossible if it is impossible, early and plainly, then
  explore the consequences with the physics left switched on.
- Where the science is genuinely contested, say so rather than picking the
  dramatic version.
- No "In conclusion", no "Remember that", no "It is important to".
- Write only the narration. No title, no preamble, no sign-off."""

OUTLINE = """Write the full narration for a video titled "{title}".

Structure:
- A hook in the first 30 seconds that puts the viewer inside the scenario.
- Then a timeline of consequences: seconds, minutes, hours, days, years.
- Real science with concrete numbers throughout.
- A genuinely surprising turn near the end - something most viewers will not
  have seen coming.
- Close with a question that invites comments.

Every 60 to 90 seconds, plant a reason to keep watching.

Length: {min_words} to {max_words} words. This is a hard requirement.
Then, after the narration, output a line containing only:
===CLAIMS===
followed by a JSON array. One object per factual claim you made, each with:
  {"text": "<the claim in plain words>",
   "as_written": "<the phrase as it appears in the narration>",
   "source": "<the specific organisation, mission, dataset or publication that
               establishes it>"}

List every number you used. If you could not source a figure, you should not
have used it - remove it from the narration rather than listing it unsourced."""

CLAIMS_MARKER = "===CLAIMS==="


def _claude_available():
    try:
        r = subprocess.run(["claude", "--version"], capture_output=True,
                           text=True, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


def _write_with_claude(title):
    """Headless Claude. Uses CLAUDE_CODE_OAUTH_TOKEN when present (CI)."""
    env = dict(os.environ)
    prompt = (SYSTEM + "\n\n" +
              OUTLINE.format(title=title, min_words=MIN_WORDS, max_words=MAX_WORDS))
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True, text=True, timeout=CLAUDE_TIMEOUT_S, env=env,
        encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"claude -p failed: "
                           f"{(result.stderr or result.stdout)[:300]}")
    text = (result.stdout or "").strip()
    if not text:
        raise RuntimeError("claude -p returned nothing")
    return text


def _write_with_gemini(title):
    return llm.complete(
        OUTLINE.format(title=title, min_words=MIN_WORDS, max_words=MAX_WORDS),
        system=SYSTEM, max_tokens=16000, temperature=0.85)


def _write_with_groq(title):
    return llm._call_groq(
        OUTLINE.format(title=title, min_words=MIN_WORDS, max_words=MAX_WORDS),
        SYSTEM, 16000, 0.85, False)


WRITERS = {"claude": _write_with_claude,
           "gemini": _write_with_gemini,
           "groq": _write_with_groq}


def split_claims(raw):
    """Separate the narration from the claims block the writer appends.

    Primary verification is the writer's job - it names a source for every
    figure as it goes. Gemini only reads the finished list afterwards and flags
    what looks wrong; it never edits. A writer that returns no claims block is
    not an error, it just means the episode ships with nothing pre-sourced.
    """
    if CLAIMS_MARKER not in raw:
        return raw, []
    body, _, tail = raw.partition(CLAIMS_MARKER)
    start, end = tail.find("["), tail.rfind("]")
    if start == -1 or end <= start:
        return body, []
    try:
        claims = json.loads(tail[start:end + 1])
    except json.JSONDecodeError as e:
        log.warning("claims block was not valid JSON: %s", e)
        return body, []
    cleaned = [c for c in claims
               if isinstance(c, dict) and c.get("text") and c.get("source")]
    log.info("writer supplied %d sourced claims", len(cleaned))
    return body, cleaned


def clean_script(text):
    """Strip anything a narrator should not read aloud."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    lines = []
    for line in text.splitlines():
        s = line.strip()
        # A bare upper-case line is a section marker, useful in the file and
        # never spoken; keep it, the narrator strips it later.
        s = re.sub(r"^#{1,6}\s*", "", s)
        s = re.sub(r"^\s*[-*•]\s+", "", s)
        lines.append(s)
    text = "\n".join(lines)
    text = re.sub(r"\*+([^*\n]*?)\*+", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def write(title, order=None):
    """Try each provider in turn. Returns (text, provider_used)."""
    order = order or PROVIDERS
    errors = []
    for name in order:
        if name not in WRITERS:
            log.warning("unknown script provider %r, skipping", name)
            continue
        if name == "claude" and not _claude_available():
            errors.append("claude: CLI not available or not authenticated")
            log.warning("claude unavailable, falling through")
            continue
        try:
            raw = WRITERS[name](title)
            body, claims = split_claims(raw)
            text = clean_script(body)
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {e}")
            log.warning("%s failed: %s", name, e)
            continue
        words = word_count(text)
        if words < MIN_WORDS * 0.8:
            errors.append(f"{name}: only {words} words")
            log.warning("%s returned %d words, below the floor", name, words)
            continue
        log.info("script written by %s: %d words, %d sourced claims",
                 name, words, len(claims))
        return text, name, claims
    raise RuntimeError("no script provider succeeded:\n  " + "\n  ".join(errors))


def provider_order(cfg):
    wanted = (cfg.get("script_source") or "auto").lower()
    if wanted in ("auto", "", None):
        return PROVIDERS
    if wanted not in PROVIDERS:
        raise ValueError(f"unknown script_source {wanted!r}")
    # The named provider first, the others still available behind it.
    return (wanted, *[p for p in PROVIDERS if p != wanted])
