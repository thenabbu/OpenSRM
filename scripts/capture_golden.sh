#!/usr/bin/env bash
# Regenerate the committed golden captures (see tests/golden/README.md).
#   bash scripts/capture_golden.sh [OUT_DIR] [PORT] [REPO]
# Default OUT_DIR is tests/golden; any other dir is safe to diff against it.
# REPO selects the checkout/worktree to capture (default: this script's repo),
# so an old SHA can be baselined from a detached worktree.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3
exec "$PY" scripts/capture_golden.py --out "${1:-tests/golden}" --port "${2:-18185}" \
  ${3:+--repo "$3"} ${OPENSRM_PY:+--python "$OPENSRM_PY"}
