#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

mkdir -p logs

: "${EUSEBIUS_DATABASE_URL:=postgresql:///eusebius}"
: "${EUSEBIUS_TRANSLATION_MODE:=cleanup}"
: "${EUSEBIUS_TRANSLATION_LIMIT:=100}"

uv run python scripts/translate_passages.py \
  --database-url "$EUSEBIUS_DATABASE_URL" \
  --mode "$EUSEBIUS_TRANSLATION_MODE" \
  --limit "$EUSEBIUS_TRANSLATION_LIMIT" \
  >> logs/translate_passages.log 2>&1

uv run python scripts/generate_site.py \
  --database-url "$EUSEBIUS_DATABASE_URL" \
  --output-dir eusebius_site \
  >> logs/generate_site.log 2>&1

rsync -az --delete eusebius_site/ \
  eusebius@merah:/var/www/vhosts/eusebius.symmachus.org/htdocs/ \
  >> logs/deploy.log 2>&1

date -u +"%Y-%m-%dT%H:%M:%SZ translation batch complete" >> logs/pipeline.log
