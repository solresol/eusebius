# Production database configuration

Verified on Raksasa, 30 October 2026. The production database is **`eusebius`
on PostgreSQL 18, port `5433`**, using the `eusebius` database role and OS
service account. PostgreSQL 16/5432 is retained as pre-cutover recovery data.

```text
postgresql:///eusebius?host=/var/run/postgresql&port=5433
```

Authentication uses the existing local Unix-socket peer rule. No password is
needed. Neither `/home/eusebius/.pgpass` nor `.pg_service.conf` was present at
inspection; no credentials, authentication rules or privileges were changed.

## Configuration locations and precedence

The deployed checkout is `/home/eusebius/eusebius`, from
`git@github.com:solresol/eusebius`. Database configuration is:

1. Explicit `--database-url` on a Python command, when supplied.
2. `EUSEBIUS_DATABASE_URL` in the process environment. The production service
   account's crontab sets it to the explicit URI above. Inspect/manage it with
   `sudo crontab -u eusebius -l` / `sudo crontab -u eusebius -e`; the managed
   spool file is `/var/spool/cron/crontabs/eusebius`.
3. The same explicit URI is the fallback in `scripts/import_first1k.py`,
   `translate_passages.py`, `score_comic_candidates.py`, `plan_comic_panels.py`,
   `generate_site.py`, `run_pipeline.sh` and `run_translation_batch.sh`.

The shell wrappers pass the selected URI as `--database-url` to their children.
Use an explicit different URI for disposable tests. Do not run import,
translation or planning commands merely to test connectivity: they can write
production data and translation/planning can call the paid API.

## Production consumers and schedules

Raksasa's timezone is `Australia/Sydney`. Existing schedules are retained:

| Local time | Command | Database use |
|---|---|---|
| Daily 03:05 | `git pull --ff-only` | None; refreshes deployed source |
| Daily 03:15 | `scripts/generate_site.py`, then rsync | Reads PostgreSQL; publishes static files |
| Monday 03:45 | `scripts/run_pipeline.sh` | Fetches/imports TEI, scores comic candidates, builds/publishes |
| Daily 04:15 | `scripts/run_translation_batch.sh` | Existing capped cleanup, scoring and panel planning; builds/publishes |
| Daily 05:30 | `scripts/sync_comic_assets.sh` | No PostgreSQL access; outgoing S3 asset backup |

The 04:15 job retains cleanup mode, passage limit 100 and the existing planner
limit/budgets. API-key loading remains outside Git at
`/home/eusebius/.openai.eusebius.key`. This migration did not run an extra paid
batch or change model choices, budgets, cron times or S3 settings.

## Current data and publication architecture

The verified deployed workflow is local to Raksasa: First1KGreek TEI import →
PostgreSQL → analysis/translation/comic planning → `eusebius_site/` → rsync to
`eusebius@merah:/var/www/vhosts/eusebius.symmachus.org/htdocs/`.

Merah serves the resulting static site. Canonical comic images/derivatives
remain under `/home/eusebius/eusebius-comic/` on Raksasa. The S3 script uses
`aws s3 sync` from that directory to the configured `EUSEBIUS_COMIC_S3_URI`;
it is an outgoing backup, not an incoming cloud-results importer. A separate
cloud/S3 workflow transition is being investigated; this database migration
does not implement it or change other workers' schedules, claims or results.

## Verification, backups and rollback

An independent source backup was restored and verified before cutover. A fresh
consistent source dump and a separately restored destination backup are saved
root-private under:

`/var/backups/postgresql/eusebius-cutover-20261030T071500Z/`

All nine tables, schema/object ownership/ACLs and seven sequence states matched.
The ordinary service role read the fresh destination successfully. A fixed-clock
site comparison produced identical hashes for all 284 files, without API calls
or publication. See [migration evidence](documentation/postgresql-18-cutover.json).

The old PG18 candidate is preserved as
`eusebius_stale_20261014_preserved_20261030`. PG16/5432 `eusebius` remains intact.
Before destination writes, rollback can use the original cron URI and source
revision. After new PG18 writes, reconcile translations, plans, assets, run
records and sequences before routing back; an old recovery copy is not current.
No cluster restart, role/password, listener/HBA or business-schema change was
required. Machine-wide PG18 backup activation was not used.

Scheduled acceptance remains pending: observe the next normal site publication
at **30 October 16:15 UTC** and cleanup/planning run at **17:15 UTC** (31 October
03:15/04:15 Sydney). Do not run a duplicate paid batch to finish acceptance.
