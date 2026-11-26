#!/usr/bin/env bash
# wt.sh — worktree lifecycle without the two traps that eat sessions:
#   * the canonical checkout may be on another agent's branch (never work there)
#   * scratch prunes between turns, so a vanished worktree is NOT a lost branch
#
# Usage:
#   bash scripts/wt.sh new <slug>        # branch feat/<slug> off origin/main, prints the path
#   bash scripts/wt.sh resume <slug>     # re-attach a pruned worktree to its existing local branch
#   bash scripts/wt.sh detach <card-id>  # DETACHED worktree at origin/feat/preact-migration (mission workers, L4)
#   bash scripts/wt.sh list              # worktrees + MERGED-BUT-ALIVE branches
#   bash scripts/wt.sh rm <slug>         # remove worktree + delete its local branch
set -u
REPO=${REPO:-/opt/data/opensrm-repo}
SCRATCH=${SCRATCH:-/opt/data/cache/scratch}
SLUG=${2:-}
path_for() { echo "$SCRATCH/$1/wt"; }

# ---------------------------------------------------------------------------
# Per-worktree git config. EVERY setting here is written into THIS worktree's
# config.worktree file via extensions.worktreeConfig, so it cannot leak to the
# canonical checkout or to another agent's worktree -- the whole reason not to
# use `git config --global` or the shared repo config.
harden_worktree() {
  local wt=$1
  local gitdir hk
  gitdir=$(git -C "$wt" rev-parse --absolute-git-dir)
  hk="$gitdir/hooks"

  # MEASURED: a hook dropped in the per-worktree ADMIN dir is never executed --
  # `git rev-parse --git-path hooks` resolves to the SHARED .git/hooks for every
  # worktree. The only per-worktree hook mechanism is core.hooksPath, and for
  # that to stay per-worktree it must live in config.worktree, which requires
  # extensions.worktreeConfig=true in the SHARED config. So:
  #   * the opt-in flag is shared (harmless: it enables per-worktree config,
  #     it does not set anything);
  #   * core.hooksPath is written with `config --worktree`, which lands in
  #     .git/worktrees/<name>/config.worktree and is invisible to every other
  #     worktree and to the canonical checkout.
  git -C "$wt" config extensions.worktreeConfig true
  mkdir -p "$hk"
  git -C "$wt" config --worktree core.hooksPath "$hk"

  cat > "$hk/pre-commit" <<'HOOK'
#!/usr/bin/env bash
# Installed by scripts/wt.sh; reached only through this worktree's core.hooksPath.
top=$(git rev-parse --show-toplevel 2>/dev/null || true)
if [ "$top" = "/opt/data/opensrm-repo" ]; then
  echo "REFUSED: committing in the canonical checkout ($top)." >&2
  echo "         Create a worktree: bash scripts/wt.sh new <slug>" >&2
  exit 1
fi
if git diff --cached --name-only | grep -qE '(^|/)\.env$|credentials|_rsa$'; then
  echo "REFUSED: a secret-looking path is staged. Unstage it before committing." >&2
  exit 1
fi
HOOK
  chmod +x "$hk/pre-commit"

  # Commit email: per-worktree too, same config file.
  git -C "$wt" config --worktree user.email "128571614+thenabbu@users.noreply.github.com"
  printf '%s' "$hk" > "$wt/.hookdir"
}


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
    harden_worktree "$wt"
    echo "$wt"
    ;;
  detach)
    # L4: mission workers get DETACHED worktrees at origin/feat/preact-migration.
    # No branch is created or deleted. Integrate with:
    #   git pull --rebase origin feat/preact-migration
    #   git push origin HEAD:feat/preact-migration      # fast-forward only
    [ -z "$SLUG" ] && { echo "usage: $0 detach <card-id>" >&2; exit 2; }
    wt=$(path_for "$SLUG")
    git -C "$REPO" fetch origin --prune -q
    if [ -e "$wt/.git" ]; then echo "$wt"; exit 0; fi
    mkdir -p "$(dirname "$wt")"
    git -C "$REPO" worktree add --detach "$wt" origin/feat/preact-migration >/dev/null 2>&1 \
      || { echo "failed: worktree add --detach $wt origin/feat/preact-migration" >&2; exit 1; }
    harden_worktree "$wt"
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
