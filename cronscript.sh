#!/bin/sh

set -eu

cd "$(dirname "$0")"

exec ./scripts/run_pipeline.sh
