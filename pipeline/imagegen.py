"""Image generation, behind a switchable provider.

Three external services now sit on the critical path (Kaggle for GPU, Hugging
Face for weights, Gemini for planning and checking) and each has already failed
at least once during development. The generator is therefore chosen by config
rather than hard-wired, so losing one provider is a one-line change rather than
a rewrite.

Providers, best first:

  kaggle_flux   FLUX.1-schnell on Kaggle's free GPU. Apache-2.0 weights, no
                watermark, full resolution. Needs a Kaggle token and an HF token.
  local_sd      Stable Diffusion 1.5 + LCM on this CPU. CreativeML OpenRAIL-M
                permits commercial use. No external service at all, but slow
                (minutes per frame) and visibly weaker, so it is a floor, not a
                substitute.
  archive_only  No generation. Scenes marked "generated" fall back to archive
                footage and infographic cards. Always available, and the only
                option that depends on nothing.

`pollinations` is deliberately absent: its free tier burns a watermark into the
frame, gates removal behind payment, and caps resolution below 1280x720.
"""
from pathlib import Path

from core.logger import get_logger

log = get_logger("imagegen")

PROVIDERS = ("kaggle_flux", "local_sd", "archive_only")


class ProviderUnavailable(Exception):
    pass


def available(cfg):
    """Which providers could actually run right now, best first."""
    from core import llm
    ready = []
    kaggle_cfg = Path.home() / ".kaggle" / "kaggle.json"
    if kaggle_cfg.exists() and llm.get_key("HF_TOKEN"):
        ready.append("kaggle_flux")
    try:
        import torch  # noqa: F401
        ready.append("local_sd")
    except ImportError:
        pass
    ready.append("archive_only")
    return ready


def choose(cfg):
    """The configured provider, or the best available one when it is set to auto."""
    wanted = (cfg.get("image_source") or "auto").lower()
    options = available(cfg)
    if wanted == "auto":
        picked = options[0]
        log.info("image_source=auto -> %s (available: %s)", picked, ", ".join(options))
        return picked
    if wanted not in PROVIDERS:
        raise ValueError(f"unknown image_source {wanted!r}; expected one of "
                         f"{', '.join(PROVIDERS)} or auto")
    if wanted not in options:
        raise ProviderUnavailable(
            f"image_source is {wanted!r} but it is not usable right now "
            f"(available: {', '.join(options)}). Set image_source to 'auto' to "
            f"fall back automatically.")
    return wanted


def describe(provider):
    return {
        "kaggle_flux": "FLUX.1-schnell on Kaggle free GPU (Apache-2.0)",
        "local_sd": "Stable Diffusion 1.5 + LCM on CPU (OpenRAIL-M)",
        "archive_only": "No generation; archive and infographics only",
    }.get(provider, provider)
