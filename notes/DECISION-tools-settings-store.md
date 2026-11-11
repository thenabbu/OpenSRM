# Decision: Dexie stores for `tools` and `settings`

**Status:** decided — **no store for either panel.**
**Date:** 2026-11-11 · **Task:** P8.3

## The gap being decided

`web/src/db/db.ts` defines `RECORD_SCHEMA` with six panels (`attendance`, `marks`,
`timetable`, `fees`, `campus`, `academics`). `tools` and `settings` are absent, so
`readPanel`/`writePanel` have no table for them and neither panel can ever serve
from cache.

Verified before deciding:

```
$ grep -nE "tools|settings" web/src/db/db.ts
(no output — exit 1)
```

## Why they were excluded — `web/src/data/props.ts:161-174`

`hasIslandProjection`'s docblock lists every absent island with its own reason.
Current text, lines 161-174:

```
161: /** Island names that HAVE a projection, and therefore a cache path.
162:  *
163:  *  Absent, each for a different reason:
164:  *   - `sync-age` renders a clock from props, no store.
165:  *   - `settings` has no endpoint at all — identity data is server-rendered only,
166:  *     so it can never be cached offline.
167:  *   - `dashboard` composes several panels rather than one `/api` feed.
168:  *   - `tools` has an endpoint but no store, and is DELIBERATELY left that way:
169:  *     the rows are a link registry gated server-side by SCOPE_FEATURES + the
170:  *     cold scope blob, so caching them caches a permission map that can only go
171:  *     stale, never self-correct offline — while the browser already gives an
172:  *     uncached link the same reach. Both gaps are argued in full, with the
173:  *     version(2) shape a future store must take, in
174:  *     `notes/DECISION-tools-settings-store.md` (P8.3). */
```

| line | island | stated reason |
|------|--------|---------------|
| 164 | `sync-age` | renders a clock from props, no store |
| **165-166** | **`settings`** | **"has no endpoint at all — identity data is server-rendered only, so it can never be cached offline"** |
| 167 | `dashboard` | composes several panels rather than one `/api` feed |
| **168-174** | **`tools`** | **"has an endpoint but no store, and is DELIBERATELY left that way: … a permission map that can only go stale, never self-correct offline"** |

That comment was itself *rewritten by this task* (commit recorded below), so it is
the conclusion, not the premise. The **original** text at 168-171, which is what
this decision had to argue from, read: *"`tools` has no Dexie store in
`RECORD_SCHEMA`, so there is nowhere to write what /api/tools/island returns.
Adding the store is a schema migration, not a projection."*

Note the asymmetry in the original, and it is the whole decision: `settings` is
excluded because there is *nothing to fetch*. `tools` was excluded only because
the store did not exist yet — the endpoint is real and live
(`app/blueprints/panels.py:134`, `GET /api/tools/island`). So `tools` is a
genuine open question that must be argued on its merits rather than inherited
from that comment. The sections below are that argument.

## `settings` — no store. Nothing to cache.

Re-confirmed live, not taken from the comment:

```
$ grep -rn "api/settings" app/blueprints/ app/app.py
(no output)
```

The routes that do exist are not a data feed:

- `GET /settings` (the page) and `GET /shell/settings` — the shell skeleton.
- `POST /api/push/settings` — a **write** of a notification preference, not a read
  of student data.

`settings/contract.ts:5-8` says the payload is the personal-details block, already
filtered and formatted server-side. The rest of the page — push toggles, logout,
delete-data — is static markup plus `push.js`. Caching a snapshot of a page whose
actionable controls are local toggles and a logout button would be worse than
having none: an offline settings page that *looks* live while its toggles silently
fail to persist is a trap. A store here would need a version(2) migration and a
projection to buy back a page the student opens precisely when they are online.

**Out of scope, permanently:** the panel has no feed to fall back to.

## `tools` — no store. The payload is a gate result, not student data.

This is the closer call, so it gets the real argument.

`tools_island.py:3-6` and `tools/contract.ts:3-5` both describe the payload the same
way: a **link registry**, not user data. The rows are app-owned URLs. What varies
per student is *which* of them appear, and `_tools_entries`
(`app/views/timetable.py:97-122`) computes that from two server-side gates:

1. `SCOPE_FEATURES` — which slugs the deployment enables (config, not per-record).
2. a non-empty answer in the cold `scope_json` blob for that op.

So a cached row set is a **stale permission map**. Three concrete ways that is
worse than not caching:

- **It over-advertises.** A feature disabled after the cache was written still
  shows a row. The student taps a destination that now 404s — and the comment at
  `tools_island.py:6` notes the route already 404s when the list is empty, so this
  is the *designed* failure mode for an empty list, reintroduced by the cache.
- **It under-advertises.** A sync that populated a new op leaves the offline Tools
  tab hiding a working destination the student is paying for.
- **It buys nothing the browser doesn't already give.** Every row is an `<a href>`
  (label + hint + tab). Offline, a cached link is still just a link to a URL that
  the service worker either has cached or does not. The cache does not make the
  destination reachable; it only makes the shortcut visible. The actual offline
  value is already delivered by the individual panel stores.

Against that, the cost is a **new store + a `version(2)` upgrade + a parser + a
projection**: `RECORD_SCHEMA` entry, `RECORD_SCHEMA` is also the `Panel` type so
`load.ts`'s `parsePanel` and `ENDPOINT` maps must both grow a `tools` arm, and
`props.ts`'s `PROJECT` map gains an identity projection. That is a migration
touching the one module that owns IndexedDB, to cache the *availability of other
panels* — which is derived from server config the client cannot re-derive, so it
can only ever be wrong, never self-correcting offline.

**Out of scope for now.** The endpoint stays live and the Tools tab keeps painting
from the server. Not a permanent no like `settings`: if Tools ever carries content
a student reads (not just links), it earns a store — and then the version(2)
upgrade below is the required shape.

## Requirement for any future store on this table

Recorded so the constraint is not rediscovered the hard way. `db.ts:14-25`
already mandates it ("NEVER wipe on upgrade"); restating it because the cheapest
wrong move here is a fresh `version(2).stores({...})` that re-declares the v1
stores and wipes them.

```ts
this.version(2).stores({
  // Every v1 store re-declared — omitting one DROPS it, and those rows are
  // real cached student data. Add the new table alongside; delete nothing.
  attendance: '[netid+groupKey], netid, fetchedAt',
  marks:      '[netid+groupKey], netid, fetchedAt',
  timetable:  '[netid+groupKey], netid, fetchedAt',
  fees:    'netid, fetchedAt',
  campus:  'netid, fetchedAt',
  academics: 'netid, fetchedAt',
  tools:   'netid',          // ← the only addition
  meta:    'netid',
});
```

`SCHEMA_VERSION` bumps with it. A test must open a v1 database, write a row,
then open at v2 and assert the row is still there — a migration with no such test
is a migration nobody has run.

## Consequence

Six of nine islands have a cache path. `tools` and `settings` are the two without,
and both are now documented here rather than left as an unexplained hole in
`hasIslandProjection`. The comment at `props.ts:161-174` is updated to point here.

## How this was verified (not taken from the prior draft)

| claim | command | result |
|-------|---------|--------|
| no store in `db.ts` | `grep -nE "tools\|settings" web/src/db/db.ts` | no output, exit 1 |
| no settings feed | `grep -rn "api/settings" app/blueprints/ app/app.py` | no output, exit 1 |
| settings routes are page + shell | `grep -rn "shell/settings" app/blueprints/` | `shell.py:163`, plus the `/settings` page at `dashboard.py:25` |
| push settings is a write | `grep -rn "api/push/settings" app/` | `push.py:19` — `methods=["POST"]` only |
| tools endpoint is live | `grep -rn "api/tools/island" app/` | `panels.py:134` |
| tools rows are gated server-side | `sed -n '97,122p' app/views/timetable.py` | `_tools_entries` requires `SCOPE_FEATURES` **and** a truthy `blob[op]["data"]` |
| tools route 404s on empty | `tools_island.py:6` + `panels.py:103-106` | `_panel(..., "no tools available")` |
| settings payload = identity block | `sed -n '1,10p' web/src/panels/settings/contract.ts` | "the only data is the personal details collapse … filtered and formatted server-side" |

Commits: `27731b2` (this note) · `props.ts` docblock updated in the same task to
cite it. "Argument 1" of the prior timed-out run drafted the note but left it
quoting the *pre-decision* `props.ts` text; that quote and the line refs were
corrected here against the tree.
