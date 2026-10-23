# Privacy — what OpenSRM stores, and what "Delete my data" erases

Plain language, verified against the live schema (every table and column
listed below comes from `app/migrations.py`'s registry, applied at startup).
Two rules shape everything here:

- **This app never changes anything on the SRM portal.** It reads your data
  from the portal to show you dashboards. Deleting your data here tells the
  portal nothing — your SRM account, password and records at SRM are
  untouched, always.
- **Shared data stays shared.** Timetables are per class, not per student.
  Erasing your account never damages what your classmates see.

## What is stored

| Table | What it holds |
|---|---|
| `users` | Your account: your NetID, your portal password (encrypted at rest — the server needs it to log in for you), and cached copies of everything the dashboard shows: attendance, marks, timetable references, personal details, exam schedule, subject→teacher map. |
| `cookies` | Your login sessions *here* (this app, not the portal). Since v1.22.1 each token is stored only as a SHA-256 digest, so a copied database cannot be replayed as a live session. |
| `portal_sessions` | The server's cached SRM portal session (its cookies, encrypted at rest) so syncing doesn't log in again every time. |
| `push_subscriptions`, `push_sent_log`, `push_events` | Notification setup: one row per registered device, the log of reminders sent, and delivery receipts. |
| `usage_events` | Anonymous daily usage counts (which feature, which day). Your NetID sits in the `user` column. Default retention is 365 days (`USAGE_EVENTS_RETENTION_DAYS`), pruned automatically. |
| `timetable_groups`, `timetable_slots`, `timetable_subjects` | The shared class timetable — no student identity in it. |
| `timetable_edit_log` | Who edited the shared timetable, when, and what changed (`editor_netid` = your NetID, `editor_name` = your name). |
| `component_tags` | Class-wide exam-component confirmations (IE-1/IE-2). The key is class-scoped; `confirmed_by` records which student confirmed it. An incomplete profile falls back to a per-student `net:<netid>|…` key. |
| `schema_version` | Migration bookkeeping — no identity. |

Operational note: server logs (`opensrm.log`) contain request lines that
mention a NetID (login, sync, deletions). Logs rotate daily and keep 14
days; they are operational data, not a profile, and are not rewritten when
an account is deleted.

## What "Delete my data" erases

`POST /api/account/delete` (Settings → **Delete my data** → confirm), in one
transaction:

- your `users` row — the whole account and every cached copy of your data;
- **every** session cookie for your NetID (all devices, digest or legacy row);
- your cached portal session row (`portal_sessions`);
- your push devices, their sent-reminder rows, and your receipts;
- your `usage_events` rows;
- your timetable edit-history entries (the shared timetable itself stays);
- your per-student `component_tags` rows; on shared rows your `confirmed_by`
  attribution is detached — the class-wide confirmation itself stays;
- the session cookie in your browser (you land on `/login`).

It is rate-limited (3 attempts per hour per account), requires you to be
logged in, and leaves one `opensrm.auth` log line with the per-table counts.
The schema is scanned on every test run: if a future migration adds any new
column that can hold a NetID, `tests/unit/test_account_delete.py` fails until the
deleter covers it.

## What it never touches

- **The SRM portal** — nothing is deleted on SRM's servers; your portal
  account and password there are unaffected (next login here simply creates
  a fresh account).
- Shared timetables, subjects, and class-wide exam-tag confirmations.
- Any other student's account or data (verified by a control account in the
  test suite).
- Other students' edit history — only *your* entries are removed.
