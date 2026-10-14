# 2026-10-14 — `/api/refresh` subjects wipe (R1): regression pin, preserve visibility, prod impact

Follow-up to the2026-10-09 code review (`2026-10-09-pr25-32-review.md` §3),
opened by a re-check request whose described defect state turned out to match
the **pre-fix** code, not current main. This record pins the behaviour with a
regression test, makes preserves visible in the logs, and answers "did this
ever bite prod" with snapshot evidence.

## Symptom

A hot-only `POST /api/refresh` whose marks-page parse failed returned
`subjects={}` (`subject_map` comes from `parse_marks`) and wrote it straight
over `users.subjects_json` — blanking stored subjects on exactly the failure
that preserved `marks_json`. Pre-fix refresh code (`e8c8867^`, ≤ v1.15.x):

```python
# api_refresh UPDATE tuple, 5th value — unconditional, no preserve
marks_json, json.dumps(res.get("subjects", {})), exams_json, faculty_json, netid))
```

while `api_login` preserved inline
(`if not res.get("subjects") and existing["subjects_json"]: subjects_json = ...`).
Two hand-copies of the preserve contract; one drifted.

## Root cause

Duplicated merge logic between the two write routes (review finding §3). The
literal appeared twice on `e8c8867^` (`git show e8c8867^:app/app.py | grep -c`
= 2) and zero times on current main.

## Fix

- **Write path**: shipped 2026-10-09 in `e8c8867` — both routes now share
  `_merge_fetch_result()`; released in v1.16.0 (tagged 2026-10-11); prod runs
  1.20.0. The re-check request's VERIFY-against-main on 2026-10-14 confirmed
  `api_refresh` UPDATE value #5 is the merged `subjects_json`.
- **Still missing on 2026-10-14, added here**:
  1. No test pinned refresh subjects preservation (the suite covered marks and
     attendance only) — `tests/test_fault_handling.py::t_refresh_preserves_subjects`
     (stored non-empty subjects, stubbed fetch `subjects={}`, minted cookie,
     assert unchanged).
  2. No log line when a preserve kept stored data — the original drift was
     silent. `_merge_fetch_result()` now emits one INFO line per sync when any
     column was kept: `preserve kept stored data netid=… columns=…`
     (`opensrm.auth`; columns = the users columns kept, comma-joined).

## Verification

- Red (data guard): UPDATE tuple reverted to the pre-fix literal →
  `FAIL refresh preserves stored subjects on empty fetch (B6/R1):
  empty-subjects refresh must NOT overwrite stored subjects_json (R1 wipe): got {}`
  (10/11), restore → green.
- Red (visibility): preserve log line removed →
  `FAIL … preserve must log netid+columns to opensrm.auth, got: []` (11/12),
  restore → green.
- Green stack (fresh runs,2026-10-14): `test_fault_handling` 12/12 ·
  `verify76` 72/72 · `test_relogin_save` 9/9 · `test_sessions` 6/6 ·
  `test_feedback` 71/71 · `test_official_tt` 53/53 · `test_exams` 69/69 ·
  `test_logging_telemetry` 10/10 · `ruff check app/` + `uv lock --check` clean.
  No `app/static` / `app/templates` / `sw.js` change → browser DUTs not in scope.

## Prod impact (read-only, aggregates only)

Method: daily snapshots `srm.2026MMDD.snapshot.db.gz` plus predeploy snapshots
(`predeploy-*.gz`,2026-09-28/29) and the live `/app/data/srm.db`, all opened
`mode=ro`, gunzipped to throwaway temp copies; `subjects_json` classified
empty iff NULL / `''` / `'{}'`. No values or netids leave the host.

| range | DB states | accounts non-empty→empty (consecutive) | net first→last non-empty→empty |
|---|---|---|---|
| 2026-09-28 → 2026-10-14 (incl. live) | 9 | 0 in every pair | 0 |

Accounts grew8→9 and non-empty-subjects7→8 over the window (one new account,
no losses). Durable log (`opensrm.log*`, retained from 2026-10-08): 126
successful refreshes (44/13/5/15/18/22/9 per day) — consistent with zero
observed loss. Limits: logs before 2026-10-08 are rotated away, snapshots
before 2026-09-28 don't exist, and the v1.16.0 deploy time isn't recorded in
the log, so pre-fix per-day exposure is an upper bound, not an attribution.

## Standing rule

Every route that writes `users` data columns goes through the one merge
contract `_merge_fetch_result()` — no route may write fetch-derived values
into `subjects_json` / `marks_json` / `personal_details_json` /
`attendance_json` / `exam_schedule_json` / `faculty_map_json` directly. A new
preserve path must route through the merge and therefore emits the
`preserve kept stored data` line automatically; pin new preserve behaviour in
`tests/test_fault_handling.py`.

## Deliberately left unfixed

- Merging the login upsert and refresh UPDATE persistence code — out of scope
  (tracked as A8).
- No version bump with this record: test + logging + docs only, no
  user-visible change (CONTRIBUTING: docs/tests-only changes get no bump).
