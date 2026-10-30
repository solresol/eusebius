# Eusebius cloud comic exchange

Status, 2026-10-30: this is an implemented, opt-in handoff for **rendering existing
queued comic panels**. It has not been deployed, added to a saved Codex Cloud
environment, or scheduled. No production S3 objects, credentials, database or
cron configuration were changed to develop it. The PG16-to-PG18 migration is
separate; its [configuration and acceptance evidence](../DATABASE_CONFIG.md)
now records PG18 routing with scheduled acceptance pending. This branch is
rebased onto that source change; use its final explicit connection configuration.

Current production is the local import/translation/planning/site pipeline and
outbound S3 asset backup. This increment moves image production into a cloud
worker; source import, translation and panel planning still originate on
Raksasa. Cloud translation/correction import and replacements are deliberately
outside this protocol version. Existing accepted and rejected art is retained.

## Ownership and data flow

```text
Raksasa PostgreSQL + accepted originals/derivatives
  -> immutable S3 corpus snapshot and checksummed reference art
  -> single leased Codex Cloud worker, no production DB connection
  -> immutable reviewed result bundle, conditionally checkpointed in S3
  -> Raksasa validates and imports into PostgreSQL + local comic storage
  -> existing generate_site.py and publication to Merah
```

Unlike Pausanias's mutable SQLite exchange, Eusebius keeps content in immutable
JSON snapshots and uses a small JSON control object for the same conditional
write/lease mechanism. JSON is a file format here; the new PostgreSQL receipt
and file tables use typed relational columns, with no new JSON/JSONB columns.
No cloud command imports the PostgreSQL adapter or connects to the database.

`EUSEBIUS_EXCHANGE_S3_URI` must name an explicitly approved **dedicated prefix**
inside a private bucket. There is no bucket default. Never point it at the old
`EUSEBIUS_COMIC_S3_URI` backup location, Pausanias's exchange, or a real catalogue
for testing. The old backup helper remains an independent outbound backup.
All keys live below `<prefix>/exchange/v1/`:

- `state.json`: version, generation, snapshot pointer, lease and pending results.
- `snapshots/<sha256>`: exact Greek, rough English, plan-linked and latest
  translations, source provenance, plans, panel prompts/exclusions/captions,
  ordered backlog, and asset baseline.
- `references/<sha256>`: verified existing accepted originals and derivatives.
- `results/<result-id>/manifest.json` and `files/<sha256>`: full result bundle.

Every object creation uses `If-None-Match: *`. Existing immutable keys permit
only byte-identical retries. Every state change uses the original downloaded
ETag with `If-Match`; conflicts terminate the session. Never upload state with
`aws s3 cp`, fetch a new ETag to retry an old state, or clear another owner's
lease. Leases last six hours for cloud production and one hour for server sync.
Renew before expiry. Expired owners cannot renew, record, release or acknowledge.

The cloud claim fixes the earliest eligible panel in numeric book/chapter/
paragraph order, then plan and panel order. Eligibility requires a queued panel,
a nonempty prompt, an active planned/rendering plan, and no generated or staged
accepted asset.
One claim can checkpoint one panel, and pending results block further production
until Raksasa imports them. A completed result survives `abort` or lease expiry.
After an uncertain network response, inspect state first; never assume failure
means the conditional write did not execute. Orphan immutable objects are safe
to retain; no automatic deletion is performed.

## Cloud worker runbook

The saved environment must include `solresol/eusebius`, Python 3.11+, `uv`,
the approved S3 identity/prefix and appropriate image-generation/GitHub access.
Setup is `uv sync --locked --python 3.11`. No PostgreSQL URL, SSH credentials or
production database access is needed. Adding Eusebius to the saved
`classical-texts` configuration and approving access is still required.

Run from the repository root. Use the configured AWS SDK identity normally;
do not copy credentials from another project or print secrets.

```sh
uv run python -m scripts.comic_exchange begin
uv run python -m scripts.comic_exchange hydrate
uv run python -m scripts.comic_exchange next
```

An active owner, a missing export, no eligible panel, or a pending import exits
with status 3: stop without generating art. Conditional conflicts/expired
sessions exit 4: stop using that session. A successful `begin` saves the
immutable corpus locally under `.comic-exchange/snapshot-<sha>.json` and prints
the selected panel. `hydrate` verifies reference images into
`.comic-exchange/references/<sha256>`; the snapshot maps them to panel and role.
Read the exact exported Greek, plan translation, latest translation and rough
reference; never silently rewrite any of them or invent a different panel.

Before generating, read `documentation/render_issues.md` and
`documentation/translation_and_comic_pipeline.md`, plus the selected plan and
its stored negative prompt. Preserve the accepted documentary-comic palette,
costume, architecture, source-grounded captions and visual continuity. In
particular, first-century Jerusalem must not acquire the Dome of the Rock,
Islamic shrines, minarets or later buildings. Inspect accepted neighbouring art
at full size, then review the new original and WebP at full and display size.
Check historical/source grounding, anatomy, legibility, composition, captions,
exclusions and consistency. A written review is required but is **not** an
automated art-quality certification. Failed art must not be checkpointed.

Use Codex image generation only when separately authorized by the production
automation; this code never calls an image API. Preserve the original PNG,
optimized single-frame WebP, exact generation prompts, every renderer/plan and
component asset, and an honest review. Keep binary work under ignored
`comic_work/`; commit/push scoped text sources normally. Record the full source
commit SHA. It is provenance supplied by the worker, not a remote signature or
proof that GitHub contains that commit; source bytes are independently archived
and checksummed in the bundle.

```sh
uv run python -m scripts.comic_exchange record-result \
  --source-commit <full-40-character-commit-sha> --model <actual-image-model> \
  --file original=comic_work/original.png --file web=comic_work/web.webp \
  --file prompt=comic_sources/prompt.txt --file review=comic_sources/review.md \
  --file source=comic_sources/render.py
uv run python -m scripts.comic_exchange finish
```

Repeat `--file source=...` and `--file component=...` for **every** supporting
source, additional prompt and component, including any source-text snapshot used
by the renderer. Exactly one original, derivative, review and primary generation
prompt are required; that exact prompt's hash populates `prompt_sha256`.
Up to 40 files/256 MiB total, 64 MiB per file, raster size at most
40 million pixels. All objects are read back and verified before checkpointing.
Use `renew` before expiry for a long run. Use `abort` on a failed run while still
owning the claim. It releases ownership and preserves completed checkpoints.
Keep a failed or expired local session as evidence; after inspecting remote
status and confirming expiry, archive it before beginning a fresh claim.

Report the panel/reference, review, source commit/push, result ID, readback and
claim-release outcome. Upload does not mean PostgreSQL import or publication.

## Raksasa runbook

After approval and completion of the database migration, configure an explicit
`EUSEBIUS_DATABASE_URL` from the final deployment configuration, the dedicated
S3 prefix/identity and the existing comic root. Do not assume port 5432 or 5433.
Run a bounded sync manually before connecting it to cron:

```sh
uv run python -m scripts.comic_exchange sync \
  --comic-root /home/eusebius/eusebius-comic --limit 4
```

Only `sync` bootstraps an empty approved prefix and applies
`scripts/comic_exchange.sql`. It imports at most 1–32 results per invocation
(default 4), verifies all manifests/images/files before DB write locks, then
takes a transaction lock and briefly blocks writes to relevant source tables.
It compares the complete exported unit and current earliest eligible unit.
Changed text, translation, source metadata, prompt, caption, plan, status or
existing generated asset causes a durable rejection, preserving accepted art.

Acceptance first archives files only under
`comic_root/exchange/<result-id>/<sha256>`, inserts a **staged**
`comic_image_assets` row with no public path, and commits a receipt plus all file
metadata in one PostgreSQL transaction. The panel remains queued. This phase
never writes `web/<plan>/<panel>.webp`: rollback leaves only result-addressed
archives and cannot obstruct a later different valid result. Existing canonical
files are checked without replacing or reserving them.

Only **after that receipt commits**, a separate publication transaction verifies
the accepted receipt/asset association and promotes the fsynced derivative into
the existing `web/<plan>/<panel>.webp` convention. It then atomically marks the
asset generated, sets its public path and marks the panel rendered. The existing
site query excludes staged assets, so a site build before or during promotion
sees the previous committed catalogue; after commit it sees the complete file.
An interrupted promotion may leave a canonical file belonging to a durable
accepted receipt, while its staged row remains invisible. Retrying that same
pending result repairs missing files and finalizes publication idempotently.
The accepted receipt reserves the panel; it cannot be replaced with a different
result after this point. A conflicting unrelated file or accepted asset is
preserved and stops reconciliation for investigation.

The importer checks its lease before each database commit. It exports fresh
authoritative content, then updates the snapshot pointer and acknowledges the
processed results together in **one conditional S3 state write**, after durable
acceptance and publication. A crash during export therefore cannot leave an
idle worker reading an acknowledged but obsolete queue. Lost acknowledgements
deduplicate by result ID and reconcile publication before retrying. Database
uniqueness prevents two accepted exchange results for a panel. A lost claim
cannot clear its successor's ownership.

The importer then releases its lease. Failures leave the owner to expire; they never force-unlock
an uncertain state. Inspect errors, state and PostgreSQL receipts before retry.
Corrupt/missing artifacts stop import without acknowledgement. Repair the
underlying object/file or investigate manually; do not delete originals or
edit a pending envelope just to make the queue advance.

After cutover, place sync immediately before the existing site build. Exit 3
means an active cloud owner: continue building the previously accepted site.
All other sync errors must fail visibly through cron mail/logging. Site
generation and rsync to Merah remain Raksasa's work. No schedules are wired by
this change. Keep the old S3 backup separate and preserve its existing files.

## Cutover checklist and outstanding setup

1. Finish the independent PostgreSQL migration, verify its backup/restore and
   final DSN, then reconcile/rebase any overlapping source changes. Do not edit
   the migration's production checkout/configuration from this task.
2. Review and merge the handoff branch separately. The new SQL is additive;
   confirm DB backups include the receipt and file tables before first sync.
3. Approve a private, dedicated S3 exchange prefix and correctly scoped cloud
   worker/server identities. Verify conditional PutObject support and access in
   an isolated test prefix. No bucket, grants, tokens, network rules or saved
   cloud configuration were created by this implementation.
4. Inventory existing originals and web derivatives against PostgreSQL. Resolve
   missing files or checksum mismatches before seeding; do not relabel old art
   as newly reviewed or replace it. Confirm disk space and the object-size bounds.
5. Add Eusebius to the saved cloud configuration, with locked dependencies and
   the approved S3/image-generation/GitHub access. Verify the actual observed
   environment readiness; having source code does not mean production is running.
6. Manually seed/export, test a synthetic result in isolation, and rehearse a
   failed acknowledgement/retry. Then approve one real reviewed panel end to
   end: claim, upload, import, local site build, publication and public bytes.
7. Only after explicit schedule-cutover authorization, update the Raksasa job
   and cloud automation. Preserve the established image budget (one panel/day
   or three/week), review pauses and no-repeat rules. Disable the competing
   direct-to-DB image worker before enabling the cloud one. Keep import,
   translation and planning on Raksasa in this version.
8. Rollback by pausing the cloud schedule and optional sync step. Keep existing
   site generation running against accepted PostgreSQL assets. Retain receipts,
   immutable S3 results and originals for audit/recovery; do not drop the tables.

## Verification

Offline protocol and existing regression tests (no credentials or generation):

```sh
uv run --locked python -m unittest discover -s tests -v
```

Disposable PostgreSQL integration tests additionally need
`EUSEBIUS_EXCHANGE_TEST_DSN`. They create/drop unique `test_exchange_<uuid>`
schemas only in that explicitly supplied disposable database; they never read
`EUSEBIUS_DATABASE_URL`. CI runs them on PostgreSQL 16 and 18. They exercise
numeric ordering, stale source/translation/plan and existing-art rejection,
site publication, corrupt assets, local collisions, rollback followed by a
different valid result, interrupted promotion, concurrent site visibility,
replay and lost acknowledgements. S3 uses an atomic-precondition fake in tests; a live isolated
S3 smoke test remains a deployment prerequisite, not a claimed success.
