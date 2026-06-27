#!/usr/bin/env bash
set -euo pipefail

for letter in {D..Z}; do
  if [[ "$letter" == "M" || "$letter" == "V" ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Skipping Spotify enrichment for artists: ${letter}*"
    continue
  fi

  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting Spotify enrichment for artists: ${letter}*"

  uv run musicseed --verbose enrich \
    --resume \
    --batch-size 100 \
    --concurrency 20 \
    --source spotify \
    --artist "${letter}*"

  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Finished Spotify enrichment for artists: ${letter}*"
done

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Completed Spotify enrichment for C* through Z*, excluding M* and V*"
