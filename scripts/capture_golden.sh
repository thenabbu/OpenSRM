#!/usr/bin/env bash
# Regenerate the committed golden captures (see tests/golden/v3/README.md).
#   bash scripts/capture_golden.sh [OUT_DIR] [PORT] [REPO]
# Default OUT_DIR is tests/golden/v3, the baseline CI checks; v2 is frozen and
# only ever an explicit target.
# REPO selects the checkout/worktree to capture (default: this script's repo),
# so an old SHA can be baselined from a detached worktree.
set -euo pipefail
cd "$(dirname "$0")/.."
# The interpreter that runs THIS script needs playwright; a worktree never has a
# .venv, so the python3 fallback dies on ModuleNotFoundError before capturing
# anything and the drift gate reads as red while having compared nothing.
# OPENSRM_PY selects it (it is also handed to the capture as the server python).
PY=${OPENSRM_PY:-.venv/bin/python}
[ -x "$PY" ] || PY=${OPENSRM_PY:-python3}

# Golden drift gate — see tests/golden/v3/README.md:
#   bash scripts/capture_golden.sh --check [GOLDEN_DIR] [--no-screens]
# Captures this checkout into a throwaway dir and diffs it against the committed
# goldens. Exit 0 = matches, 1 = drift (the differing files are named).
if [ "${1:-}" = "--check" ]; then
  shift
  GOLDEN=tests/golden/v3
  case "${1:-}" in ""|--*) ;; *) GOLDEN=$1; shift ;; esac
  exec "$PY" scripts/capture_golden.py --repo "$PWD" --check "$GOLDEN" --port 18190 "$@" \
    ${OPENSRM_PY:+--python "$OPENSRM_PY"}
fi

exec "$PY" scripts/capture_golden.py --out "${1:-tests/golden/v3}" --port "${2:-18185}" \
  ${3:+--repo "$3"} ${OPENSRM_PY:+--python "$OPENSRM_PY"}
