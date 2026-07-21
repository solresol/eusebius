#!/bin/sh
# Sync canonical Eusebius comic assets to the configured private S3 backup.

set -eu

: "${EUSEBIUS_COMIC_S3_URI:?Set EUSEBIUS_COMIC_S3_URI to the private backup URI}"

comic_root="${EUSEBIUS_COMIC_ROOT:-/home/eusebius/eusebius-comic}"
destination="${EUSEBIUS_COMIC_S3_URI%/}/"

if [ ! -d "$comic_root" ]; then
    echo "Comic asset root does not exist: $comic_root" >&2
    exit 1
fi

aws s3 sync "$comic_root/" "$destination" --only-show-errors
echo "Eusebius comic S3 sync complete: $comic_root -> $destination"
