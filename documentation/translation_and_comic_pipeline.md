# Eusebius Translation and Documentary Comic Pipeline

Date: 2026-04-25

## Model Defaults

Use the best available model for the translation and planning work, but keep
the model names configurable rather than hard-coded:

- `EUSEBIUS_TRANSLATION_MODE=cleanup`
- cleanup mode: `gpt-5.4-mini`, 500,000 tokens/day
- translate mode: `gpt-5.5`, 10,000 tokens/day
- `EUSEBIUS_TEXT_MODEL=gpt-5.4`
- `EUSEBIUS_TEXT_MODEL_HIGH=gpt-5.4`
- `EUSEBIUS_IMAGE_MODEL=gpt-image-2`

Use `gpt-5.4-mini` only for English cleanup when the prompt includes both the
Greek and the existing First1K English. It should fix minor OCR, spacing,
punctuation, and alignment problems in the English, not produce a fresh
translation. Use `gpt-5.5` for real translation from Greek, with a much tighter
daily token budget.

## Daily Translation

Goal: first clean the existing English cheaply, then create our own English
translation from the Greek where needed while keeping cost bounded.

Default policy:

- Cleanup mode may process many passages per day, up to 500,000 tokens.
- Real translation mode is capped at 10,000 tokens/day.
- Cleanup mode receives `passages.greek_text` and `passages.english_text`, and
  lightly repairs the English.
- Translation mode translates from `passages.greek_text`; use the First1K
  English only as a rough comparison/reference field. It contains OCR errors
  and can be misaligned around title matter.
- Store every run in `ai_translation_runs` with model, prompt version, token
  counts, status, errors, and completion time.
- Do not overwrite translations silently; a new prompt/model gets a new row.

Prompt stance:

- faithful, readable, paragraph-level English;
- no commentary in the translation field;
- preserve named people, places, works, and quoted-document texture;
- allow a short `notes` field for uncertainty, textual awkwardness, or possible
  documentary-comic value.

## Comic Candidate Flagging

The first flagging pass should be cheap and explainable:

- Score passages from deterministic features:
  - named cities/regions;
  - emperors, bishops, martyrs, letters, decrees, persecutions;
  - visual action words such as travel, prison, fire, crowds, ships, soldiers;
  - documentary structures such as quoted letters or public proclamations.
- Store scores in `comic_candidates`.
- Let a small daily GPT planning job inspect only the top unplanned candidates.

Candidate statuses:

- `candidate`: deterministic score says it may be useful.
- `planned`: GPT has created a comic plan.
- `rejected`: planning judged it too abstract or repetitive.
- `rendering`: panels are queued for images.
- `done`: at least one image asset exists for every queued panel.

## Comic Planning

For each accepted candidate, GPT should produce a compact JSON plan stored in
`comic_plans` and `comic_panels`.

The plan should include:

- short title;
- one-sentence documentary framing;
- 2-6 panels;
- panel-by-panel visual prompts;
- captions that are short enough to display in the viewer and, when useful,
  render directly in the generated artwork;
- short readable labels, captions, map callouts, or title text are allowed when
  they make the panel intelligible;
- no reliance on the image model rendering long Greek or English passages,
  dense paragraphs, or invented dialogue;
- continuity hints for costume, era, palette, page layout, and map/document
  inset style.

For Eusebius, use a documentary-comic visual language:

- manuscript/document panels;
- city maps and route lines;
- bishops and imperial officials;
- courtroom, prison, council, and letter-delivery scenes;
- marginal source notes and timeline strips.

## Image Backlog

`comic_panels` is the canonical backlog. A panel is ready for the Codex image
automation when:

- its status is `queued`;
- it has a complete `panel_prompt`;
- it belongs to a `comic_plan` with status `planned` or `rendering`;
- the project has not exceeded the daily/weekly image budget.

Image generation should be slower than planning:

- default: 1 panel per day or 3 panels per week;
- pause automatically if more than 30 unreviewed generated images exist;
- never regenerate an existing panel unless status is explicitly reset.

## Storage

Canonical non-Git storage on `raksasa`:

```text
/home/eusebius/eusebius-comic/
  originals/<plan_id>/<panel_number>.png
  web/<plan_id>/<panel_number>.png
  pdf/eusebius-comic-YYYY-MM-DD.pdf
  manifests/<plan_id>.json
```

Repository storage:

- Store prompts, metadata, scripts, and generated site pages in Git.
- Do not store bulk images in Git.
- Publish optimized PNG derivatives into `eusebius_site/comic/`.
- Publish a daily generated comic-book PDF into `eusebius_site/comic/`.

PostgreSQL:

- `comic_image_assets.local_path`: canonical `raksasa` original.
- `comic_image_assets.public_path`: deployed site path.
- `comic_image_assets.s3_uri`: backup URI when S3 is configured.
- `comic_image_assets.sha256`: integrity check.
- `comic_image_assets.prompt_sha256`: prompt provenance.
- `comic_image_assets.model`: image model used by the Codex automation, e.g.
  `gpt-image-2`.

S3 backup:

- Use `EUSEBIUS_COMIC_S3_URI` when configured.
- Sync originals, web derivatives, and manifests.
- Do not make S3 public by default.

Suggested command shape:

```bash
aws s3 sync /home/eusebius/eusebius-comic/ "$EUSEBIUS_COMIC_S3_URI"/
```

## Automations

Keep responsibilities separate:

- `raksasa` cron:
  - import source;
  - run small daily translation batches;
  - score candidates;
  - generate comic plans for at most one passage/day.
- Codex automation:
  - render at most one queued comic panel per run using Codex image generation,
    not a repo script that calls the image API directly;
  - save the image to `raksasa`;
  - convert the website derivative to PNG, not WebP;
  - update PostgreSQL asset metadata;
  - copy new PNG derivatives to the public `comic/` tree;
  - rebuild and publish the daily comic-book PDF;
  - check the source translation for the rendered passage and make small,
    source-grounded corrections when a mistranslation or confusing wording is
    evident, recording provenance in `ai_translation_runs`;
  - sync to S3 only when `EUSEBIUS_COMIC_S3_URI` is configured.

The image automation should not invent new panels. It should only consume
queued `comic_panels` rows.

The repo should therefore contain the queue, prompts, storage helpers, and
metadata update scripts, but not a programmatic image-generation API client.

## Website Outputs

The static website should include:

- a comic-book viewer that groups rendered panels by `comic_plan_id`, shows the
  generated image, title, caption, passage reference, and source translation,
  and makes it easy to move through the book in order;
- a current daily PDF export of the comic book;
- clean weekly Greek/English pages with side-by-side passage text, preferring
  reviewed AI translations when available and clearly labelling rough reference
  English when that is all the database has.
