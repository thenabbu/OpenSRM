#!/usr/bin/env bash
# wt.sh — worktree lifecycle without the two traps that eat sessions:
#   * the canonical checkout may be on another agent's branch (never work there)
#   * scratch prunes between turns, so a vanished worktree is NOT a lost branch
#
# Usage:
#   bash scripts/wt.sh new <slug>        # branch feat/<slug> off origin/main, prints the path
#   bash scripts/wt.sh resume <slug>     # re-attach a pruned worktree to its existing local branch
#   bash scripts/wt.sh list              # worktrees + MERGED-BUT-ALIVE branches
#   bash scripts/wt.sh rm <slug>         # remove worktree + delete its local branch
set -u
REPO=${REPO:-/opt/data/opensrm-repo}
SCRATCH=${SCRATCH:-/opt/data/cache/scratch}
SLUG=${2:-}
path_for() { echo "$SCRATCH/$1/wt"; }

case "${1:-list}" in
  new|resume)
    [ -z "$SLUG" ] && { echo "usage: $0 new|resume <slug>" >&2; exit 2; }
    wt=$(path_for "$SLUG")
    git -C "$REPO" fetch origin --prune -q
    if [ -d "$wt/.git" ] || [ -f "$wt/.git" ]; then echo "$wt"; exit 0; fi
    mkdir -p "$(dirname "$wt")"
    if git -C "$REPO" show-ref --verify --quiet "refs/heads/feat/$SLUG"; then
      # branch survives a pruned worktree; only uncommitted edits die
      git -C "$REPO" worktree add "$wt" "feat/$SLUG" >/dev/null 2>&1
    else
      git -C "$REPO" worktree add -b "feat/$SLUG" "$wt" origin/main >/dev/null 2>&1
    fi
    [ -d "$wt" ] || { echo "failed to create $wt" >&2; exit 1; }
    echo "$wt"
    ;;
  rm)
    [ -z "$SLUG" ] && { echo "usage: $0 rm <slug>" >&2; exit 2; }
    wt=$(path_for "$SLUG")
    # cwd out first: a removed-but-current cwd kills every later call silently
    cd / || exit 1
    open=$(ls -l /proc/[0-9]*/cwd 2>/dev/null | grep -F "$wt" | grep -vc 'proc/self')
    [ "${open:-0}" -gt 0 ] && { echo "REFUSING: $open process(es) still in $wt" >&2; exit 1; }
    dirty=$(git -C "$wt" status --porcelain 2>/dev/null | head -3)
    [ -n "$dirty" ] && { echo "REFUSING: uncommitted work in $wt (push it first):" >&2; echo "$dirty" >&2; exit 1; }
    git -C "$REPO" worktree remove "$wt" 2>/dev/null
    git -C "$REPO" branch -D "feat/$SLUG" 2>/dev/null | tail -1
    echo "removed feat/$SLUG"
    ;;
  list)
    echo "=== worktrees ==="; git -C "$REPO" worktree list
    echo; echo "=== MERGED-BUT-ALIVE (delete these; they are the base an agent picks by mistake) ==="
    found=0
    # both the canonical checkout's branch and the caller's own branch are in progress
    cur=$(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
    here=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
    while read -r b; do
      # main is the destination, and the branch you are standing on is not "alive" —
      # it is work in progress
      [ "$b" = "main" ] && continue
      [ "$b" = "$cur" ] && continue
      [ "$b" = "$here" ] && continue
      if git -C "$REPO" merge-base --is-ancestor "$b" origin/main 2>/dev/null; then
        echo "  $b"; found=1
      fi
    done < <(git -C "$REPO" for-each-ref --format='%(refname:short)' refs/heads)
    [ "$found" = 0 ] && echo "  none"
    ;;
  *) echo "usage: $0 new|resume|list|rm [slug]" >&2; exit 2;;
esac
