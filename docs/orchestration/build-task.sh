#!/usr/bin/env bash
# Usage: docs/orchestration/build-task.sh <task-id>
# Assembles docs/orchestration/tasks/<id>.md = src/<id>.md + src/_common.md (self-contained prompt).
set -euo pipefail
cd "$(dirname "$0")/tasks"
cat "src/$1.md" src/_common.md > "$1.md"
echo "wrote docs/orchestration/tasks/$1.md"
