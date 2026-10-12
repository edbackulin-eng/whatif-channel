"""Subtitles via faster-whisper, transcribed from our own narration.

Transcribing rather than reusing the script sounds wasteful, but it is the only
way to get timings that match what the voice actually did: Kokoro's pace varies
per sentence by design, so script order alone cannot place the cues.
"""
import re
from pathlib import Path

from core.logger import get_logger

log = get_logger("subtitles")

MODEL_SIZE = "small"        # int8 on CPU; `base` is faster and noticeably worse
MAX_CHARS = 84              # two lines of ~42, the readable limit


def _format_ts(seconds):
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _wrap(text):
    """Break one cue into at most two balanced lines."""
    text = text.strip()
    if len(text) <= MAX_CHARS // 2:
        return text
    words, lines, current = text.split(), [], ""
    for w in words:
        if current and len(current) + 1 + len(w) > MAX_CHARS // 2:
            lines.append(current)
            current = w
        else:
            current = f"{current} {w}".strip()
    if current:
        lines.append(current)
    return "\n".join(lines[:2]) if len(lines) <= 2 else "\n".join(
        [" ".join(lines[:-1]), lines[-1]])


# Whisper mangles domain vocabulary it has no context for: "Roche limit" came
# back as "Raj Limit", which is the single most important term in this video.
# These are repaired against the script rather than left in the shipped .srt.
TERM_FIXES = [
    (r"\bRaj Limit\b", "Roche limit"),
    (r"\bRoach limit\b", "Roche limit"),
    (r"\bRoshi limit\b", "Roche limit"),
    (r"\bFarsal\b", "Fossil"),
    (r"\bRemove the break\b", "Remove the brake"),
]


def _repair(text):
    for pattern, replacement in TERM_FIXES:
        text = re.sub(pattern, replacement, text, flags=re.I)
    return text


def transcribe(audio_path, srt_path, language="en"):
    from faster_whisper import WhisperModel

    log.info("loading faster-whisper %s (int8 cpu)", MODEL_SIZE)
    model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        str(audio_path), language=language, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300})

    cues, n = [], 0
    for seg in segments:
        body = _wrap(_repair(seg.text))
        if not body:
            continue
        n += 1
        cues.append(f"{n}\n{_format_ts(seg.start)} --> {_format_ts(seg.end)}\n{body}\n")
        if n % 40 == 0:
            log.info("  %d cues, %.1f min transcribed", n, seg.end / 60)

    Path(srt_path).write_text("\n".join(cues), encoding="utf-8")
    log.info("wrote %d cues to %s", n, Path(srt_path).name)
    return n
