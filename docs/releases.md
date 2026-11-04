# Releases

The app shows no release notes. **GitHub Releases is the changelog**:
<https://github.com/thenabbu/OpenSRM/releases>

## How a release happens

1. Land your change on `main` as normal (feature PR, merge commit).
2. Bump the trio **in one commit** — `VERSION` + `pyproject.toml` + `uv.lock`
   (`uv lock` after the pyproject edit). SemVer: patch = fix, minor = feature,
   major = breaking/user-visible redesign. Docs/tests/dependency-only changes
   take no bump.
3. That's it. `.github/workflows/release.yml` runs on the `main` push and:
   - tags `v<VERSION>` on the merge commit,
   - generates the Release body from the commits since the previous tag
     (`scripts/release_notes.py`),
   - appends the same section to `CHANGELOG.md`.

Nothing is hand-written and nothing is remembered. A version that lands
without a Release is a red workflow, not a silent gap.

## What the generated notes contain

Commits are grouped by their conventional prefix:

- `feat` / `fix` / `perf` / `revert` → **What changed**
- `refactor` / `ci` / `test` / `docs` / `build` / `style` → **Internal**
- `chore(release)` and `chore(deps)` → dropped (a version bump and a dependency
  bump are not changes anyone reads about)

A typed `feat`/`fix` whose subject reads like plumbing ("key the guard on
X-Forwarded-Host") is demoted to **Internal** — a word-list in the script, not a
model, so it is predictable and adjustable.

**Write commit subjects for humans.** The subject is the release note.

## Backfilling a missed release

Tags stop at `v1.27.2`, so everything after it needs catching up:

```bash
scripts/backfill_releases.sh --dry-run   # what it would create
scripts/backfill_releases.sh             # create tags + Releases
```

It walks every commit that touched `VERSION`, keeps the last commit per version,
skips versions already tagged, and publishes oldest-first so each Release's
range is the previous version. Idempotent — existing tags and Releases are left
alone. Non-semver junk (a `VERSION` once committed with merge markers) is
skipped by the `x.y.z` filter.

## Why not in the app

A release-notes feed inside the product meant a hand-edited table shipped with
every deploy, a test forcing the newest entry to equal `VERSION`, and a feed
where "watch the log rotate" sat next to "delete my data". It also published
internal failures as release notes. The changelog belongs where the code and
the commits are. `test_audit_findings` M27 now fails if an in-app feed comes
back, and M27b fails if this pipeline disappears.
