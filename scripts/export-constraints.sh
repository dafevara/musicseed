#!/usr/bin/env bash
# Regenerate the pinned end-user dependency set (constraints.txt) from the
# runtime apps' lockfiles. End-user `scripts/install.sh` installs against this
# so it gets the exact versions CI tested rather than whatever pip resolves
# today. Run this after `uv lock` changes in core/, api/, or cli/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
out="$ROOT/constraints.txt"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

for app in core api cli; do
  (cd "$ROOT/$app" && uv export --no-dev --no-hashes) >> "$tmp"
done

python3 - "$tmp" "$out" <<'PY'
import re
import sys

src, dst = sys.argv[1], sys.argv[2]

def key(ver: str) -> tuple:
    # Turn a version into a sortable tuple, tolerating pre/post suffixes.
    parts = re.split(r"[.+\-]", re.sub(r"[a-zA-Z].*$", "", ver))
    return tuple(int(p) for p in parts if p.isdigit())

pins: dict[str, str] = {}
for line in open(src):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    m = re.match(r"([A-Za-z0-9_.-]+)==([^;\s]+)", line)
    if not m:
        continue
    name, ver = m.group(1), m.group(2)
    if name not in pins or key(ver) > key(pins[name]):
        pins[name] = ver

with open(dst, "w") as f:
    f.write("# Pinned end-user dependency set (core + api + cli), merged from the\n")
    f.write("# lockfiles CI tests against. Regenerate with scripts/export-constraints.sh\n")
    for name in sorted(pins):
        f.write(f"{name}=={pins[name]}\n")
print(f"wrote {dst} ({len(pins)} packages)")
PY
