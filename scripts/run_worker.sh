#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."

set -a
source .env
set +a

exec /Users/kknaks/.local/bin/uv run open-kknaks worker run \
  --broker "$REDIS_URL" \
  --namespace "$REDIS_NAMESPACE" \
  --work-dir "$WORK_DIR" \
  --queues default \
  --concurrency 2
