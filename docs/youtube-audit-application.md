# Заявка на аудит YouTube API — текст для подання

Форма: **YouTube API Services - Audit and Quota Extension Form**
(шукається як "youtube api audit form"; подається від імені проєкту Google Cloud
`whatif-channel`).

Подаєш сам. Нижче — відповіді на поля форми. Англійською, бо форма англомовна.

---

## Основні поля

**Project ID:** `whatif-channel` *(підстав реальний ID з Cloud Console — він під
назвою проєкту, зазвичай із цифрами на кінці)*

**API Client Name:** Hypothetica Uploader

**Channel URL:** *(посилання на канал Hypothetica)*

---

## How does your API Client use YouTube API Services?

> Hypothetica is a single YouTube channel publishing long-form educational
> science videos that explore hypothetical scenarios using real physics - for
> example, what would actually happen if the Moon's orbit decayed.
>
> The API Client is a private automation pipeline that publishes to this one
> channel and no other. It is not a product, it has no users other than the
> channel owner, and it offers no interface to third parties.
>
> It uses exactly three operations:
> - `videos.insert` to upload the finished video file
> - `thumbnails.set` to attach the thumbnail
> - `captions.insert` to attach the English subtitle track
>
> It also reads `channels.list` once at setup to confirm it is authenticated
> against the correct channel.
>
> Each upload sets the title, description, tags, category (Science &
> Technology), language (English), the "not made for kids" flag, and the
> synthetic-media disclosure where the video contains AI-generated imagery or a
> synthetic narration voice.

## How many users do you expect?

> One. The channel owner. The client authenticates once with a refresh token and
> uploads only to the owner's own channel. There is no sign-in flow for anybody
> else and no plan to add one.

## What is your expected daily quota usage?

> Five uploads per week, scheduled Monday, Tuesday, Thursday, Friday and
> Saturday. One upload costs 1,600 units, so a publishing day costs roughly
> 1,700 units including the thumbnail and caption calls. That is well inside the
> default 10,000 unit allocation.
>
> We are not requesting additional quota. We are requesting the audit so that
> uploaded videos are not permanently locked to private, which is the current
> behaviour for unaudited projects.

## Does your API Client make content publicly available?

> It publishes to one public YouTube channel owned by the applicant. It does not
> expose YouTube data, metadata or video content anywhere else - no website, no
> app, no feed, no third-party surface.

## Do you use YouTube data for machine learning or AI training?

> No. No YouTube data is stored, analysed or used for training of any kind. The
> client writes to YouTube and does not read from it beyond confirming the
> channel identity at setup.

## Describe your content and how AI is used

> Scripts are written with AI assistance and then fact-checked against named
> sources - NASA fact sheets, peer-reviewed papers and university material - with
> every numerical claim recorded with its source before recording. Where the
> underlying science is genuinely contested, the video says so rather than
> presenting one side as settled.
>
> Narration uses a synthetic voice (Kokoro, Apache-2.0). It does not imitate any
> real person and is not a clone of any individual's voice.
>
> Imagery comes from three sources: public-domain NASA and ESA archive
> photography with per-frame credit records; images generated with
> FLUX.1-schnell (Apache-2.0); and diagrams drawn programmatically by the
> pipeline. Generated frames are reviewed automatically before publication and
> rejected if they contain artefacts.
>
> Videos that contain AI-generated imagery or synthetic narration are uploaded
> with the synthetic-media disclosure set, and the description states plainly
> that parts of the video were produced with AI tools.
>
> Music is licensed for commercial use and attributed in every description
> (Kevin MacLeod, CC BY 4.0). Every video ships with a credits record and a
> sources record from which the description is generated, so the attribution
> cannot drift from what is actually in the video.

## Will your client be used by others / distributed?

> No. The code is in a public repository so the pipeline is auditable, but it
> carries no credentials and is configured for this one channel. Nobody else
> runs it.

---

## Перед поданням перевір

1. Канал Hypothetica має аватар, банер, опис і щонайменше кілька
   опублікованих відео. Порожній канал — найчастіша причина відмови.
2. У Cloud Console заповнений OAuth consent screen і статус **In production**.
3. Пошта підтримки у consent screen робоча — відповідь приходить саме туди.
4. Опис застосунку у формі й у consent screen не суперечать один одному.

Розгляд зазвичай займає кілька тижнів. До відповіді конвеєр працює як зараз:
пакет у артефакт, публікація руками через Studio.
