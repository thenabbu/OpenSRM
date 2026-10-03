# OpenSRM Incident — end-sem exam card vanished (2026-10-04)

**Status: code fix merged path (PR), prod data restore run separately.**
Symptom reported: "the dashboard no longer shows the endsem exam dates."

## Root cause — two-part

**1. Portal side (external, Oct 1–3 2026):** `ScribeInner.jsp` window `11_2026`
still returns the student's subject table, but the **Date and Session cells are
now empty** (`<td ...></td>`). The dates had been seeded since ~Sep 27 and were
served until Sep 30. Captured live 2026-10-04 02:28 IST with ng2776's cached
session (raw captures: `exam_11_2026.html` 8135B, subjects present, 0 dated
rows; the other three candidate windows return the clean `No subject found`
1603B marker).

**2. App side (the actual bug):** `_merge_exam_results()`'s guard only checked
page *type* — `No subject found` OR `<td` present = clean. A subject table with
**zero parseable dated rows** therefore passed as a clean empty probe →
returned `[]` → both save paths overwrote `users.exam_schedule_json` →
`_exams_view([])` returns `None` → card hidden. The probe destroyed the good
data instead of preserving it.

Evidence the wipe happened Oct 1–3 (daily snapshots, `exam_schedule_json` byte
lengths): ng2776 479 → `[]` at the 2026-10-04 02:20 sync; sg2935 479 → 2;
ag2188 591 → 2; gg9557 477 → 2. na8163 (last synced 09-30) still holds 479 —
the only survivor. Prod log line (all that was visible):
`exam probe netid=ng2776 candidates=[(11, 2026), ...] rows=0` — no per-window
detail, which is why diagnosis needed a raw HTML capture.

## Fix

`_merge_exam_results()` (app/http_scraper.py) — single guard where every sync
path routes:
- window with `No subject found` → clean empty, skipped (as before)
- window whose subject table parses to **0 dated rows** → `blanked=True`
- rows empty **and** any blanked window → `return None` → upstream preserves
  the stored schedule (same contract as transport failure/silent rejection)
- real dated rows anywhere → they win (dedupe/sort as before)
- all windows clean-empty → `[]` still overwrites, so a genuinely released
  schedule still clears when the portal withdraws every window (self-healing:
  the 11/2026 candidate slides out of `exam_candidates()` ~45d after its end,
  leaving only clean-empty windows)

Added `log.debug("exam probe: subject table(s) with no dated rows —
unreliable, preserving stored value")` so the next occurrence is diagnosable
from `docker logs` alone.

## Verification

- `tests/test_exams.py` 27/27 (3 new checks: blanked→None, blanked+clean→None,
  blanked alongside real rows→rows win; BLANK_ROW fixture mirrors the captured
  Oct-4 markup)
- **Real captured portal responses** (the four raw HTML files from the live
  02:28 probe) fed through the fixed `_merge_exam_results` → `None` (assert)
- `tests/test_exams_view.py` ok · `tests/verify76.py` 71/71 · `ruff check
  app/` · `uv lock --check` all green

## Standing rule for future sessions

A portal response that is *structurally valid but content-empty* (subject table
without dated rows) is **unreliable, not empty** — it must never overwrite
stored exam data. When the exam card disappears: capture the raw
`ScribeInner` HTML first (`_exam_post` + session reuse recipe in
`srm-portal-attendance`), never diagnose from `rows=0` alone.

## Related state (not fixed here)

- **Exam Time Table page (formId 126, `transaction/StudentExamTimeTable.jsp`)**:
  real table (Date & Session + Hall No + Seat No columns) but "No subjects
  found" — not yet published server-side; no params/inner JSPs can force it.
  Candidate second source once the exam cell publishes it.
- **Users who never held rows** (av5351, ds4647, an0750 — last synced before
  the feature deployed): nothing to restore; they show no card until the portal
  re-seeds dates. Deliberately not fabricated from other students' schedules.
- **Data restore** for the four wiped users is a live-UPDATE runbook
  (snapshot-first) executed outside this PR — repo code never touches prod DB.
