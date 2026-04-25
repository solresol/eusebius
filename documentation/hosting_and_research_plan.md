# Eusebius Hosting Audit and Research Plan

Date: 2026-04-25

## Decisions

- Canonical storage is PostgreSQL on `raksasa`, not SQLite.
- `merah` is static publication only.
- There is no Stephanos-style human review workflow and no CGI surface planned.
- Routine jobs must be parsimonious with OpenAI tokens. The default pipeline uses zero OpenAI calls.
- The first corpus is Eusebius, `Historia Ecclesiastica`, from OpenGreekAndLatin First1KGreek TEI.

## Source

Use the First1KGreek TEI files for Eusebius, `Historia Ecclesiastica`:

- Greek: `tlg2018.tlg002.1st1K-grc1.xml`
- English alignment file: `tlg2018.tlg002.1st1K-eng1.xml`
- Work CTS URN: `urn:cts:greekLit:tlg2018.tlg002`
- Greek edition URN: `urn:cts:greekLit:tlg2018.tlg002.1st1K-grc1`
- Repository path: `OpenGreekAndLatin/First1KGreek/data/tlg2018/tlg002`

This is better than the current local placeholder because it is structured TEI, reproducible, and small enough to import cheaply. The current `description_of_greece.txt` is not usable Eusebius content and should be treated as obsolete.

## Hosting Audit

### Local checkout

- Repository: `/Users/gregb/Documents/devel/eusebius`
- Branch: `main`
- Current commit before this pass: `a4347b4`
- Working tree note: `AGENTS.md` is untracked in the local checkout.
- Added pipeline files:
  - `scripts/init_db.sql`
  - `scripts/import_first1k.py`
  - `scripts/generate_site.py`
  - `scripts/run_pipeline.sh`
- Updated `cronscript.sh` to delegate to the new pipeline.

### `eusebius@raksasa`

- SSH works via the existing local host alias `eusebius`.
- Home: `/home/eusebius`
- Checkout: `/home/eusebius/eusebius`
- PostgreSQL was present, but the `eusebius` role did not exist.
- Created PostgreSQL role/database:
  - role: `eusebius`
  - database: `eusebius`
  - verified service-user access with `psql -d eusebius`.
- `uv` works for the service user.
- The remote checkout was stale and locally modified before this pass. It should now be treated as infrastructure state until the repo changes are committed and pulled cleanly.

### `eusebius@merah`

- Direct SSH initially failed from the workstation.
- Fixed by adding the local `~/.ssh/id_rsa.pub` key to `/home/eusebius/.ssh/authorized_keys` through the working `gregb@merah` admin login.
- Direct SSH now works:
  - host: `merah.cassia.ifost.org.au`
  - user: `eusebius`
- Existing vhost:
  - `/var/www/vhosts/eusebius.symmachus.org`
  - `/var/www/vhosts/eusebius.symmachus.org/htdocs`
- `htdocs` is writable by `eusebius`.
- `/etc/httpd.conf` has a static-only vhost, which is the right shape for this project.

## Operating Model

The site follows the `merah` personal research pattern, but with PostgreSQL as the only canonical database:

1. `raksasa` fetches TEI source files.
2. `raksasa` imports structured passages into PostgreSQL.
3. `raksasa` generates a static site from PostgreSQL.
4. `raksasa` deploys static files to `merah:/var/www/vhosts/eusebius.symmachus.org/htdocs/`.
5. No CGI, SQLite edge database, or human review sync exists.

OpenAI usage is opt-in only. Any future LLM task should have an explicit low cap, such as 5-10 passages per run, and should write prompt/model/token provenance to PostgreSQL.

## Current Pipeline

The first pipeline is deliberately small:

- `scripts/import_first1k.py`
  - fetches Greek and English First1KGreek TEI;
  - caches raw XML under `data/raw/`;
  - creates PostgreSQL tables from `scripts/init_db.sql`;
  - imports book/chapter/paragraph passages;
  - stores source URL, CTS URN, SHA-256, byte size, and fetch timestamp.
- `scripts/generate_site.py`
  - reads PostgreSQL;
  - writes a static status site;
  - publishes corpus counts, book-level counts, top Greek terms, sample passages, and the research agenda;
  - does not call OpenAI.
- `scripts/run_pipeline.sh`
  - attempts `git pull --ff-only` and logs any pull failure without blocking the no-OpenAI rebuild;
  - runs import;
  - runs site generation;
  - deploys by `rsync --delete` to `merah`.

Installed `eusebius@raksasa` cron jobs:

- `15 3 * * *`: daily no-OpenAI static-site rebuild from PostgreSQL and deploy.
- `45 3 * * 1`: weekly no-OpenAI source refresh/import, site rebuild, and deploy.

Logs are written under `/home/eusebius/eusebius/logs/`.

## Research Agenda

These are meant to stay explainable: start with transparent features, networks, distances, and source labels before any black-box model.

1. Transport-weighted place network: do nearby coastal cities co-occur differently from inland places, and does sea access predict narrative centrality?
2. Apostolic succession as graph compression: how much of the narrative is explained by bishop-to-bishop succession chains, and where does Eusebius break that chain for polemic or crisis?
3. Persecution geography: are persecution episodes clustered by province, imperial center, or communication corridor?
4. Authority-source switching: when Eusebius moves between scripture, Josephus, letters, archives, and named historians, does the local vocabulary or certainty marking change?
5. Citation distance: do quoted authorities appear near the places and people they discuss, or does Eusebius use geographically remote authorities for particular arguments?
6. Imperial proximity: do mentions of emperors correlate with Rome, Nicomedia, Antioch, and other administrative centers, and does that change across books?
7. Heresy and network periphery: are heresiarchs and disputed teachers structurally peripheral in the co-occurrence graph, or are they central bridges between orthodox figures?
8. Martyrdom narrative signatures: can martyrdom passages be separated by transparent lexical and entity features without using a black-box classifier?
9. Chronological density: which books compress the most years per passage, and which slow down into document-heavy narrative?
10. Epistolary infrastructure: do letters and decrees link different regions than narrative prose does, suggesting a documentary communication network?
11. Classical versus biblical geography: are biblical places, Greek cities, and Roman administrative centers used in different argumentative contexts?

## Next Work Items

1. Commit and push the PostgreSQL/static-pipeline changes.
2. Replace or remove the obsolete Pausanias-derived scripts once the PostgreSQL importer/site generator are stable.
3. Add a no-OpenAI place extraction pass:
   - start from ToposText tagged-place counts as a comparison target;
   - add Wikidata/Pleiades lookups only for high-confidence city/place strings;
   - store transport features such as coastal/inland and approximate sea/land path proxies.
4. Add source/citation formula extraction with regular expressions before using LLMs.
5. If OpenAI is later useful, run only capped batch jobs and record token counts by run.
