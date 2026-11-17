#!/usr/bin/env bash
# Usage: docs/orchestration/session-metrics.sh <opencode-session-id>
# Prints model, cost (harness-reported USD), tokens and wall time from `opencode session export`.
set -euo pipefail
tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
opencode session export "$1" > "$tmp" 2>/dev/null
python3 - "$tmp" <<'PY'
import json,sys
d=json.load(open(sys.argv[1])); i=d["info"]; t=i["tokens"]; tm=i["time"]
print(json.dumps({
 "session": i["id"], "model": i["model"]["providerID"]+"/"+i["model"]["id"],
 "cost_usd": round(i["cost"],4), "tokens_in": t["input"], "tokens_out": t["output"],
 "tokens_reasoning": t["reasoning"], "cache_read": t["cache"]["read"], "cache_write": t["cache"]["write"],
 "wall_minutes": round((tm["updated"]-tm["created"])/60000,1)}))
PY
