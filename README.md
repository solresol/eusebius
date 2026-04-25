# eusebius

Digital humanities and explainable NLP tools for Eusebius of Caesarea.

The current baseline imports Eusebius' *Historia Ecclesiastica* from
OpenGreekAndLatin First1KGreek TEI into PostgreSQL on `raksasa`, generates a
small static site, and deploys it to `merah`. The default pipeline does not call
OpenAI.

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
