#!/usr/bin/env bash
set -euo pipefail

# Run from the musicseed repository root. Pass the sibling website checkout
# when it is not located at ../website.
website_root="${1:-../website}"

check_contains() {
  local file="$1"
  local pattern="$2"
  local description="$3"

  if [[ ! -f "$file" ]]; then
    echo "Missing $file ($description)" >&2
    exit 1
  fi
  if ! rg -q -- "$pattern" "$file"; then
    echo "Missing $description in $file" >&2
    exit 1
  fi
}

"$(dirname "$0")/check_design_tokens.sh" "$website_root"

check_contains "web/src/app/globals.css" "\\.app-header" "product app shell"
check_contains "web/src/app/globals.css" "\\.page-header" "product page hierarchy"
check_contains "web/src/app/globals.css" "\\.btn" "product controls"
check_contains "web/src/app/globals.css" "\\.panel" "product surfaces"
check_contains "web/tailwind.config.ts" "--ms-radius-panel" "product radius mapping"

check_contains "$website_root/index.html" "assets/tokens.css" "website token stylesheet"
check_contains "$website_root/assets/styles.css" "\\.btn" "website controls"
check_contains "$website_root/assets/styles.css" "\\.card" "website surfaces"
check_contains "$website_root/assets/styles.css" "focus-visible" "website keyboard focus treatment"

echo "MusicSeed web UI parity checks passed."
