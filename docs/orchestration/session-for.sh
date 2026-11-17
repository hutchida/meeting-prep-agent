#!/usr/bin/env bash
# Usage: docs/orchestration/session-for.sh <worktree-dir-name>  -> prints the newest opencode session id whose directory ends with that name
set -euo pipefail
tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
for id in $(opencode session list 2>/dev/null | cut -f1); do
  opencode session export "$id" > "$tmp" 2>/dev/null || continue
  python3 - "$tmp" "$1" <<'PY' && { echo "$id"; exit 0; } || true
import json,sys
d=json.load(open(sys.argv[1])); loc=d["info"].get("location",{}).get("directory","")
sys.exit(0 if loc.rstrip("/").endswith("/"+sys.argv[2]) else 1)
PY
done
