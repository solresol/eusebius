# Eusebius Translation and Documentary Comic Pipeline

Date: 2026-04-25

## Model Defaults

Use the best available model for the translation and planning work, but keep
the model names configurable rather than hard-coded:

- `EUSEBIUS_TEXT_MODEL=gpt-5.5`
- `EUSEBIUS_TEXT_MODEL_HIGH=gpt-5.5`
- `EUSEBIUS_IMAGE_MODEL=gpt-image-2`

Use the text model for daily translation and comic planning. If a cheaper
model is later good enough for simple passages, make that an explicit
configuration change rather than lowering quality silently.

## Daily Translation

Goal: create our own English translation from the Greek for fun, while keeping
cost bounded.

Default policy:

- Process 3-5 passages per day.
- Translate from `passages.greek_text`; use the First1K aligned English only as
  an internal comparison/reference field, not as the published translation.
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
- captions that are short enough to add locally after image generation;
- no reliance on the image model rendering long Greek or English text;
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
  web/<plan_id>/<panel_number>.webp
  manifests/<plan_id>.json
```

Repository storage:

- Store prompts, metadata, scripts, and generated site pages in Git.
- Do not store bulk images in Git.
- Publish optimized WebP/JPEG derivatives into `eusebius_site/comic/`.

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
  - update PostgreSQL asset metadata;
  - sync to S3 only when `EUSEBIUS_COMIC_S3_URI` is configured.

The image automation should not invent new panels. It should only consume
queued `comic_panels` rows.

The repo should therefore contain the queue, prompts, storage helpers, and
metadata update scripts, but not a programmatic image-generation API client.
