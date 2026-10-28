# Agent-workflow guards: version allocation and migration collisions

Symptom: parallel agent sessions on separate branches repeatedly collide on
release numbers and migration numbers. Both agents answer "what's the next
number?" correctly from their own base, both pick the same N, and the
collision is invisible until merge or boot.

## Root causes

1. **Numbers are chosen on branches, not allocated on main.** A feature branch
   reading `VERSION` from its own stale base cannot see a sibling that already
   took the number.
2. **`pr_preflight.sh`'s version-race check was blind.** It used
   `git log --all -S"$CUR" -- VERSION`. `-S` matches commits that *changed* the
   string, so it flags the branch's own bump and never sees a sibling that
   merely *inherited* the number. Reproduced in a scratch repo: two refs both
   at `2.5.0` yielded a FAIL naming the current branch while the real
   colliding sibling was never listed.
3. **`migration()` had no duplicate guard.** `_registry.append` accepted any
   version, so two `@migration(version=N)` decorators coexisted silently.
4. **A duplicate migration half-applies before it crashes.** `migrate_db()`
   calls `fn(conn)` *before* inserting into `schema_version` (whose `version`
   is the PRIMARY KEY). With two decorators at the same N, both DDL bodies
   execute and commit, only one records, then boot dies on
   `UNIQUE constraint failed: schema_version.version`. The schema is left
   *ahead* of its own version table, so a renumbered re-run cannot replay
   cleanly.

## Fixes

- `app/migrations.py`: duplicate versions are rejected **at registration**,
  raising `ValueError` with both descriptions and zero DDL executed. The
  check runs in the decorator, so it fires at import, before any connection.
- `scripts/pr_preflight.sh`: version-race compares `VERSION` **per ref** via
  `git for-each-ref --format='%(refname:short) %(symref)'`, skipping symbolic
  refs (the `origin -> origin/main` alias), `main`/`origin/main`, and the
  current branch. Two controls: a unique version passes, a clean repo passes.
- `scripts/alloc_number.sh`: prints main's VERSION, every VERSION in flight
  across live refs, and the next free migration number — so allocation is a
  remote read rather than a local guess.
- `tests/unit/test_audit_findings.py` `C1c`: static gate pinning the guard.
  Red-tested — removing the guard message turns `C1c` FAIL.
- `AGENTS.md`: corrected two stale numbers (`16 migrations → v17` was really
  17 → v18; `72/72` static gates was really 73/73).

## Verification

- Fresh-DB boot: `db.schema version=18 — all migrations complete`, 17 rows in
  `schema_version`, no duplicates.
- Duplicate probe: two decorators at version 99 → `ValueError` at import,
  **zero tables created**.
- `pr_preflight.sh` version-race: collision → FAIL naming the sibling;
  unique version and clean repo → PASS (both controls run).
- `uvx ruff check app/` clean, `uv lock --check` clean,
  `test_audit_findings` 73/73.

## Standing rule

A feature branch never edits `VERSION` / `pyproject.toml` / `uv.lock`. The
trio moves once on main in a `chore(release)` commit. Migrations allocate
their `version=N` at merge time on main via `scripts/alloc_number.sh` — if two
branches pick the same N anyway, registration now fails loudly and free of
side effects instead of half-applying a schema.
