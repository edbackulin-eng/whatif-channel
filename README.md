# whatif-channel

An automated pipeline that builds 20-minute science videos for a "What If"
YouTube channel, end to end, on free infrastructure.

Nothing here costs money. The heavy work is split so that the only machine that
has to be powerful is one Kaggle borrows to us for half an hour a day.

## What runs where

| Stage | Where | Why there |
|---|---|---|
| Script | Claude (headless CLI), falling back to Gemini, then Groq | written weekly, ahead of time |
| Fact check | the writer sources its own figures; Gemini reads them once and flags | one request per video |
| Narration | Kokoro ONNX, on the runner | Apache-2.0, no GPU, ~1.1x realtime |
| Subtitles | faster-whisper, on the runner | timings must match the voice, not the script |
| Scene plan | Gemini | decides archive vs generated vs infographic per scene |
| Archive stills | NASA Image and Video Library | public domain, rights-screened |
| Generated frames | FLUX.1-schnell on Kaggle's free GPU | Apache-2.0, ~32s per frame |
| Infographics | Pillow, on the runner | numbers are always right, look never drifts |
| Visual check | Gemini vision, before the render | catches what technical QC cannot see |
| Render | ffmpeg, on the runner | ~1.1x realtime |
| Package | GitHub Actions artifact, 3-day retention | until the YouTube API audit clears |

## Schedule

- **Sunday 05:00 UTC** - `write-scripts.yml` tops the queue up to two weeks.
- **Mon, Tue, Thu, Fri, Sat 06:00 UTC** - `build-video.yml` renders the oldest
  queued script. It calls no language model: the script is already written.

A public repository has its scheduled workflows disabled after 60 days without
a commit. The weekly queue job commits, which is what keeps the schedule alive.

## The queue

`queue/<nnn>-<slug>/` holds a finished script, its sources, and an
`episode.json` with its status. Media never enters the repository.

- Fewer than one week of stock raises a warning on the run.
- An empty queue skips the day and writes to `queue/journal.md`.

## Secrets

| Secret | Needed for | How to get it |
|---|---|---|
| `GEMINI_API_KEY` | planning, checks, vision | aistudio.google.com/apikey |
| `KAGGLE_USERNAME`, `KAGGLE_KEY` | GPU frames | kaggle.com > Settings > API |
| `HF_TOKEN` | FLUX weights (until mirrored) | huggingface.co > Settings > Tokens |
| `CLAUDE_CODE_OAUTH_TOKEN` | scripts | `claude setup-token` |
| `GROQ_API_KEY` | script fallback | console.groq.com/keys |
| `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | direct upload | after the API audit |

Set the repository variable `YOUTUBE_AUDIT_APPROVED` to `true` once Google
approves the project, and builds will upload instead of leaving an artifact.

## Falling back

Every external dependency has a documented plan in
[docs/fallbacks.md](docs/fallbacks.md). The image source is switchable from
`config.json` (`image_source`: `auto`, `kaggle_flux`, `local_sd`,
`archive_only`), and the script writer from `script_source`.

The local stack - ffmpeg, Kokoro, Pillow, faster-whisper - is the real fallback.
It depends on nothing and is already on disk.

## Running one build by hand

```
python -X utf8 automation/fetch_models.py
python -X utf8 automation/build_next.py
```

## Licensing of what it produces

- NASA imagery: public domain, credited, rights-screened for third-party material
- FLUX.1-schnell: Apache-2.0
- Kokoro: Apache-2.0
- Music: Kevin MacLeod, CC BY 4.0, attributed in every description
- Fonts: Anton and Bebas Neue, SIL Open Font License

Every video ships a `credits.json` and a `sources.json`, and the description is
generated from them so the two cannot drift apart.
