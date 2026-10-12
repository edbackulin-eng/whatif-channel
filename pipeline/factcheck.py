"""Fact checking: primary verification by the author, Gemini as a second opinion.

The earlier design had this backwards. It sent every claim to Gemini and treated
the answer as authoritative, which failed twice over:

  - Gemini was wrong. Asked about the Moon's mass it "corrected" 73 billion
    billion tonnes to "73.5 million billion tonnes", an error of three orders of
    magnitude. A checker that invents corrections is worse than no checker.
  - The free tier allows 20 requests per DAY per model. One video's worth of
    batched checking consumed the entire daily quota, which no pipeline running
    a video a day can live with.

So now:
  1. The author verifies each claim against a real, named source and records the
     URL. That is the authority.
  2. Gemini sees the finished claim list ONCE, in a single batched request, and
     may only FLAG items as doubtful. It never rewrites anything.
  3. Every change is written to factcheck-log.md as before / after / source.
  4. Where the author and Gemini disagree, the text stands and the disagreement
     is surfaced for a human.

Cost: exactly one Gemini request per video.
"""
import json
from datetime import date
from pathlib import Path

from core import llm
from core.logger import get_logger

log = get_logger("factcheck")

SYSTEM = """You are a second reader checking a science video's claim list.

You do NOT rewrite anything. For each claim, say only whether you consider it
sound as written, given the source cited beside it.

Flag a claim only when you have a specific, concrete reason: a wrong order of
magnitude, a figure that contradicts the cited source, a causal claim the source
does not support, or a statement presented as settled when it is contested.

Do not flag a claim for being a simplification, for rounding, or for omitting
caveats a general audience does not need. Most claims should come back sound.

Reply with valid JSON only."""

PROMPT = """Review this claim list. For each, return:
{{"id":<int>,"status":"sound|doubt","reason":"<one sentence, only when status is doubt>"}}

Return {{"results":[...]}}.

Claims:
{claims}"""


def load_claims(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def second_opinion(claims, model=None):
    """One batched request. Gemini may flag; it may not edit.

    `model` lets the caller pick a different quota bucket; the free tier counts
    requests per day PER MODEL, so the bulk model is a usable spare when the
    main one is spent.
    """
    listing = "\n".join(
        f"{i}. CLAIM: {c['text']}\n   AS USED: {c['as_written']}\n   SOURCE: {c['source']}"
        for i, c in enumerate(claims))
    try:
        data = llm.complete_json(
            PROMPT.format(claims=listing), system=SYSTEM,
            max_tokens=8192, temperature=0.0, model=model)
    except Exception as e:
        log.error("second opinion unavailable: %s", e)
        return {i: {"status": "unreviewed", "reason": str(e)[:120]}
                for i in range(len(claims))}
    out = {}
    for r in data.get("results", []):
        out[r.get("id")] = {"status": (r.get("status") or "sound").lower(),
                            "reason": r.get("reason", "") or ""}
    flagged = sum(1 for v in out.values() if v["status"] == "doubt")
    log.info("second opinion: %d claims, %d flagged", len(out), flagged)
    return out


def merge(claims, opinions):
    for i, c in enumerate(claims):
        o = opinions.get(i, {"status": "unreviewed", "reason": ""})
        c["second_opinion"] = o["status"]
        c["second_opinion_reason"] = o["reason"]
        # The author's verification stands. A disagreement is surfaced, not applied.
        c["needs_human"] = o["status"] == "doubt"
    return claims


def write_sources(claims, path):
    payload = {
        "generated": date.today().isoformat(),
        "method": ("Primary verification by the author against named sources. "
                   "Gemini used once as a second reader, flagging only."),
        "claims_checked": len(claims),
        "flagged_for_human": sum(1 for c in claims if c.get("needs_human")),
        "claims": claims,
    }
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                          encoding="utf-8")
    log.info("wrote %d claims to %s", len(claims), Path(path).name)
    return payload


def write_log(changes, claims, path):
    """factcheck-log.md: what changed, what it became, and on whose authority."""
    lines = [
        "# Fact-check log",
        "",
        f"Video: What If the Moon Fell to Earth?  |  {date.today().isoformat()}",
        "",
        "Primary verification: the author, against the sources named below.",
        "Gemini: one batched pass, second reader, flags only - it changes nothing.",
        "",
        f"## Changes applied ({len(changes)})",
        "",
    ]
    for i, ch in enumerate(changes, 1):
        lines += [
            f"### {i}. {ch['what']}",
            "",
            f"- **Was:** {ch['before']}",
            f"- **Now:** {ch['after']}",
            f"- **Why:** {ch['why']}",
            f"- **Source:** {ch['source']}",
            "",
        ]
    flagged = [c for c in claims if c.get("needs_human")]
    lines += [f"## Flagged by the second reader, left unchanged ({len(flagged)})", ""]
    if not flagged:
        lines.append("None.")
    for c in flagged:
        lines += [
            f"- **{c['text']}**",
            f"  - As written: {c['as_written']}",
            f"  - Author's source: {c['source']}",
            f"  - Gemini's objection: {c['second_opinion_reason']}",
            "  - **Left as written.** Resolve by hand if you disagree.",
            "",
        ]
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    log.info("wrote %s", Path(path).name)
