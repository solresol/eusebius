# IMPROVEMENTS.md

*Analysis date: 2026-07-11*

Eusebius is a digital-humanities pipeline around Eusebius of Caesarea's
*Historia Ecclesiastica*: it imports First1KGreek TEI into PostgreSQL on
`raksasa`, runs AI cleanup/translation batches, scores and plans comic panels,
generates a static site, and rsyncs it to `merah`. The repo is in good shape —
already on `uv` (pyproject.toml + uv.lock), has tests, a CLAUDE.md, and a
working cron pipeline — but the comic-publishing half described in TODO.md is
largely unbuilt, and the daily pipeline silently omits the translation and
comic steps it documents.

## Bugs & Fixes

- **`scripts/run_pipeline.sh` doesn't run the whole documented flow.** It runs
  import → score → generate_site → deploy, but never invokes
  `translate_passages.py` or `plan_comic_panels.py`. Either wire
  `scripts/run_translation_batch.sh` and panel planning/rendering into
  `cronscript.sh`/`run_pipeline.sh` (with the documented token budgets:
  500k/day for `gpt-5.6-luna` cleanup, 10k/day for `gpt-5.5` translation), or
  document that they run under separate cron entries. Right now the "daily"
  pipeline and the docs disagree.
- **Pipeline steps swallow failures invisibly.** Every step redirects to a
  per-step log under `logs/`; a failed import aborts the run (`set -eu`) but
  nothing notifies anyone. Add a failure trap that writes a clear line to
  `logs/pipeline.log` (or emails/pings) so a broken import doesn't just stall
  the site silently while the last "pipeline complete" line stays stale.
- **`rsync --delete` after a partially-empty generate.** If
  `generate_site.py` ever produces a truncated `eusebius_site/` (e.g. empty DB
  after a failed import in a fresh checkout), `--delete` will wipe the live
  site. Add a sanity check (minimum file count / presence of `index.html`)
  before deploying.

## Unfinished work (from TODO.md)

All four TODO.md areas are open — prioritize in this order:

1. **Comic viewer on the static site** (`generate_site.py`): panels grouped by
   plan with image, title, caption, passage ref, source translation. This is
   the visible payoff of `plan_comic_panels.py` output.
2. **PNG derivatives instead of WebP** in the public `comic/` tree.
3. **Daily comic-book PDF** rendered from current panels and published.
4. **Translation review step in automation** with runs recorded in
   `ai_translation_runs` (model, prompt version, token counts, notes) — never
   overwriting prior runs — plus weekly Greek/English side-by-side pages.

## Improvements

- `scripts/generate_site.py` (562 lines) hand-builds HTML with string
  concatenation across ~15 render functions. Consider extracting a tiny
  template layer (even f-string templates in one module) before adding the
  comic viewer, or the file will double in size and drift.
- `plan_comic_panels.py` and `score_comic_candidates.py` share
  passage-selection logic with `translate_passages.py`; factor common DB
  fetch/budget-tracking helpers into a `scripts/common.py` (or make `scripts/`
  a package) to avoid three copies of connection/budget code.
- Add `--dry-run` to `translate_passages.py` so budget/candidate selection can
  be inspected without spending tokens.

## Testing

- Tests exist for four scripts but **`generate_site.py` has none**, despite
  being the most churned file (per recent commits: book/section split,
  cleanup/translate mode separation, nonnumeric chapter labels). Add tests for
  `numeric_label_sort_key`, `book_sort_key`, `section_page_name`, and
  `render_translation_block` — all pure functions, cheap to cover.
- Add a CI workflow (GitHub Actions: `uv sync && uv run pytest`) — the repo
  has a GitHub remote and PR history but apparently no CI.

## Documentation

- `pyproject.toml` still says `description = "Add your description here"`.
- README documents `uv run python scripts/...`; per owner preference this
  should be `uv run scripts/import_first1k.py` etc. (drop the redundant
  `python`). Update CLAUDE.md's build commands to match.
- `documentation/translation_and_comic_pipeline.md` should be reconciled with
  what `run_pipeline.sh` actually executes (see first bug above).

## Security

- Good: OpenAI key lives at `~/.openai.eusebius.key`, not in the repo; no
  committed secrets spotted. DB URL defaults to local socket
  (`postgresql:///eusebius`).
- The rsync deploy trusts `merah`'s host key implicitly; pin it in the
  service user's `known_hosts` on `raksasa` rather than relying on first-use
  acceptance.

## Housekeeping / Quick Wins

- `scripts/__pycache__/` and `tests/__pycache__/` exist on disk; commit
  85296a3 added a bytecode ignore — verify `.gitignore` actually exists and
  covers `__pycache__/`, `logs/`, and `eusebius_site/` (there is no
  `.gitignore` visible at repo root in a plain `ls`; confirm it's committed).
- Trim unused heavyweight dependencies: `matplotlib`, `networkx`, `numpy`,
  `pandas`, `scikit-learn` are declared but none of the five current scripts
  obviously need all of them post-Pausanias-pivot. `uv remove` the unused
  ones to speed cold `uv run` on raksasa.
- Fill in the pyproject description and add `tqdm` if CLAUDE.md's dependency
  list is accurate (it's listed there but absent from pyproject).
