# eusebius

Digital humanities and explainable NLP tools for Eusebius of Caesarea.

The current baseline imports Eusebius' *Historia Ecclesiastica* from
OpenGreekAndLatin First1KGreek TEI into PostgreSQL on `raksasa`, generates a
small static site, and deploys it to `merah`. The default import/site pipeline
does not call OpenAI.

# Tooling

All the programs use Python. Lots of digital humanities folks run into
trouble with environments and dependencies, so I've made sure
everything works nicely with `uv`. Download `uv` from here:
https://github.com/astral-sh/uv (it's one command, so it's quick, and
it won't disrupt any other installation you might have).

The first time you run a `uv` command it will output something like this:

```
Using CPython 3.11.6 interpreter at: /Users/gregb/anaconda3/bin/python3.11
Creating virtual environment at: .venv
```



# Data Loading

PostgreSQL is the canonical store:

```bash
createdb eusebius
uv run python scripts/import_first1k.py
```

To run a smoke test:

```bash
uv run python scripts/import_first1k.py --limit-books 1
```

The First1K English file is retained as a rough comparison source only. It has
OCR and alignment problems, so the public site prefers translations stored in
`ai_translation_runs` and labels the First1K English as rough reference text.

# English Cleanup and Translation

To clean up the rough First1K English against the Greek:

```bash
uv run python scripts/translate_passages.py --mode cleanup --limit 100
```

Cleanup mode uses `gpt-5.4-mini` by default. It is only for minor OCR,
spacing, punctuation, and alignment repairs to the supplied English, with the
Greek used as a guardrail. The default daily token budget is 500,000 tokens.

For a fresh translation from Greek:

```bash
uv run python scripts/translate_passages.py --mode translate --limit 3
```

Translation mode uses `gpt-5.5` by default and has a 10,000-token daily budget.
Runs are stored in PostgreSQL with model, prompt version, token counts, status,
and error messages.

For cron use on `raksasa`, run:

```bash
./scripts/run_translation_batch.sh
```

That script defaults to cleanup mode, processes up to
`EUSEBIUS_TRANSLATION_LIMIT` passages, regenerates the site, and deploys the
static output. It requires `OPENAI_API_KEY` or a readable
`~/.openai.eusebius.key` for the `eusebius` service user.

# Comic Candidate Scoring

To populate the first documentary-comic backlog table without using model
tokens:

```bash
uv run python scripts/score_comic_candidates.py
```

The scorer uses deterministic, explainable features from the passage English
and stores qualifying rows in `comic_candidates`. It does not create plans or
image prompts; those remain a later, source-grounded planning step.

To let the text model turn at most one candidate into a stored panel backlog:

```bash
uv run python scripts/plan_comic_panels.py --limit 1
```

The planner reads the highest-scored unplanned candidate, asks for structured
JSON, stores accepted plans in `comic_plans`, and inserts queued prompts in
`comic_panels`. It does not render images. Panel prompts may include short
readable labels or captions when they make the comic understandable, but should
avoid long text blocks and invented dialogue.

# Daily

The scheduled pipeline is intentionally cheap:

```bash
./cronscript.sh
```

This fetches First1KGreek TEI, imports it into PostgreSQL, regenerates the
static site, and deploys to `eusebius@merah:/var/www/vhosts/eusebius.symmachus.org/htdocs/`.

# Static Site

To generate without deploying:

```bash
uv run python scripts/generate_site.py
```

The output is written to `eusebius_site/`.
The passage browser writes lightweight book and section index pages; full
passage text is only loaded on a single section page.

Planned site work now includes a comic-book viewer, PNG web derivatives under
`comic/`, a daily comic-book PDF, and clean weekly Greek/English side-by-side
pages.
