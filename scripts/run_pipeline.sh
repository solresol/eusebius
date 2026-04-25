#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

mkdir -p logs

: "${EUSEBIUS_DATABASE_URL:=postgresql:///eusebius}"

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if ! git pull --ff-only >> logs/git_pull.log 2>&1; then
    date -u +"%Y-%m-%dT%H:%M:%SZ git pull failed; continuing with existing checkout" >> logs/git_pull.log
  fi
fi

uv run python scripts/import_first1k.py \
  --database-url "$EUSEBIUS_DATABASE_URL" \
  >> logs/import_first1k.log 2>&1

uv run python scripts/generate_site.py \
  --database-url "$EUSEBIUS_DATABASE_URL" \
  --output-dir eusebius_site \
  >> logs/generate_site.log 2>&1

rsync -az --delete eusebius_site/ \
  eusebius@merah:/var/www/vhosts/eusebius.symmachus.org/htdocs/ \
  >> logs/deploy.log 2>&1

date -u +"%Y-%m-%dT%H:%M:%SZ pipeline complete" >> logs/pipeline.log
