#!/usr/bin/env bash
# Usage: docs/orchestration/append-metrics.sh <task-id>   (task id == worktree dir name)
# Appends harness metrics from the worker's opencode session to docs/orchestration/reports/<id>.md
set -euo pipefail
cd "$(dirname "$0")/../.."
id="$(docs/orchestration/session-for.sh "$1")"
m="$(docs/orchestration/session-metrics.sh "$id")"
python3 - "$1" "$m" <<'PY'
import json,sys
t,m=sys.argv[1],json.loads(sys.argv[2])
open(f"docs/orchestration/reports/{t}.md","a").write(f"""
## Harness metrics (added by master from `opencode session export`, session {m['session']})
- Model: {m['model']}; wall {m['wall_minutes']} min
- Tokens: input {m['tokens_in']:,} (uncached) / output {m['tokens_out']:,} / reasoning {m['tokens_reasoning']:,} / cache read {m['cache_read']:,} / cache write {m['cache_write']:,}
- Cost: US${m['cost_usd']} (harness-reported)
""")
print(m)
PY
