#!/usr/bin/env bash
set -euo pipefail

# Run from the musicseed repository root. Pass the sibling website checkout
# when it is not located at ../website.
website_root="${1:-../website}"
app_tokens="web/src/app/tokens.css"
website_tokens="$website_root/assets/tokens.css"

if [[ ! -f "$app_tokens" ]]; then
  echo "Missing $app_tokens" >&2
  exit 1
fi
if [[ ! -f "$website_tokens" ]]; then
  echo "Missing $website_tokens" >&2
  exit 1
fi

tokens=(
  --ms-canvas
  --ms-surface
  --ms-surface-raised
  --ms-text
  --ms-text-muted
  --ms-text-subtle
  --ms-accent
  --ms-accent-secondary
  --ms-accent-gradient
  --ms-accent-foreground
  --ms-border
  --ms-border-strong
  --ms-focus
  --ms-radius-control
  --ms-radius-panel
  --ms-radius-pill
  --ms-font-sans
  --ms-font-mono
)

for token in "${tokens[@]}"; do
  if ! rg -q -- "${token}:" "$app_tokens"; then
    echo "Missing $token in $app_tokens" >&2
    exit 1
  fi
  if ! rg -q -- "${token}:" "$website_tokens"; then
    echo "Missing $token in $website_tokens" >&2
    exit 1
  fi
done

echo "Shared MusicSeed token vocabulary is present in both surfaces."
