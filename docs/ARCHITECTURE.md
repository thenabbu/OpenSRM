# Architecture

How OpenSRM is put together: the server, the client, the data path, and the
rules that keep it from leaking data between students. Read this before you
change the client. `DESIGN.md` governs how it looks; this file governs how it
works.

**Contents:** 1 Shape · 2 Server · 3 Client · 4 Data contracts · 5 The store ·
6 Offline · 7 Privacy rules · 8 The CSS cascade rule · 9 Where things live

---

## 1. Shape

One Flask application serves nine logged-in pages, and a Preact bundle
hydrates panels inside them. The page arrives complete from the server; the
client adds behaviour on top. This is a multi-page app (MPA) with islands, not
a single-page app.

```
browser ──► Cloudflare edge ──► gunicorn ──► Flask routes ──► parsers ──► SQLite
   │                                            │
   └── Preact islands hydrate <div data-island> ┘
```

What that buys, in order:

- **Every page works with JavaScript off.** The server renders the rows, the
  numbers and the forms. The island is an enhancement, never the source of a
  value.
- **No client-side router.** Each navigation is a real request. Back and
  forward, deep links and a hard reload behave the way the browser already
  does.
- **One shared bundle.** Nine panels, one entry module, emitted with
  content-hashed names under `app/static/dist/`. Panels load as separate
  chunks only when their island mounts.

## 2. Server

| Layer | What it is |
|---|---|
| WSGI server | gunicorn, `-w 1 --threads 8 -t 120 --worker-class gthread` (`Dockerfile`) |
| App | Flask 3.1, blueprints under `app/blueprints/` |
| Templates | Jinja, one `partials/theme.html` shared by every page |
| Upstreams | the SRM student portal (HTML scraping) and the SCOPE backend (SOAP) |
| Store | SQLite at `srm.db` on a volume |

**gunicorn runs exactly one worker, and that is deliberate.** The portal
scraper keeps process-local singletons behind `_pw_lock`, and the sync routes
assume a single worker (audit F1). Raising `-w` breaks those assumptions
silently, so treat `-w 1` as a correctness requirement, not a tuning knob.
Concurrency comes from the eight threads.

**Two upstreams, neither optional.** Each is the only source for part of the
UI, so the dashboard is built to survive either one being down. See the
README's two-sources table; the parser layer in `app/` is where that split
lives.

**The `/shell/<panel>` routes belong to this layer.** They are the
privacy-critical server output — see §7.

## 3. Client

`web/` is a TypeScript + Preact project built by Vite. Three dependencies do
the work: **Preact** (rendering), **Zod** (validating server data at the
boundary) and **Dexie** (IndexedDB access).

```
web/src/
  main.ts          entry: mounts islands, wiring for the non-island behaviours
  islands/         the island contract and schemas
  panels/          one directory per island: Component + contract + tests
  data/            behaviour modules (refresh, outbox, sync-age, toasts, …)
  contracts/       Zod schemas for every panel API payload
  db/              db.ts — the ONE module allowed to touch IndexedDB
  session/         offline session bootstrap, shell warming
  sw-template.js   the service worker source (Workbox injectManifest)
```

**Islands.** A server template renders
`<div data-island="attendance" data-props="#island-attendance">`, plus an inert
`<script type="application/json" id="island-attendance">` block holding that
panel's props. `main.ts` finds every `[data-island]`, parses the props through
the island's Zod schema, lazily imports the component and renders it **into**
the existing container. The server's markup stays; Preact takes over the
subtree.

The ten islands are `sync-age`, `dashboard`, `attendance`, `marks`, `campus`,
`academics`, `fees`, `timetable`, `tools` and `settings`. Adding one is a
registry line in `main.ts` plus a directory under `panels/`.

**Mount rules that matter when you touch an island:**

1. One props contract per island, in Zod, in that island's `contract.ts`.
2. The props are validated before the first render. An invalid payload logs a
   warning and renders nothing — it never half-renders.
3. A failed mount must leave the server-rendered page readable.

**No-JS paths stay server-side.** `/marks/tag`, login, logout, delete-account
and every other write that must survive a dead bundle are plain form POSTs, not
island handlers.

**The build outputs one bundle and one worker.** `pnpm build` in `web/` runs
`tsc --noEmit`, compiles the design tokens, runs `vite build` into
`app/static/dist/`, then runs `web/workbox-config.js`, which bundles
`sw-template.js`, injects the precache manifest and writes
`app/static/sw.js`. Both outputs are committed: CI fails if either is stale.

## 4. Data contracts

The panel APIs (`/api/attendance`, `/api/marks`, `/api/dashboard`,
`/api/campus`, `/api/academics`, `/api/fees`, `/api/timetable`, `/api/tools`,
… and their `/island` variants) answer with one envelope
(`web/src/contracts/envelope.ts`, server side `app/blueprints/panels.py`):

```json
{ "ok": true,  "data": { … } }
{ "ok": false, "error": "human-readable reason" }
```

Both branches are **closed** objects — `.strict()` in Zod. An unknown
top-level key is a contract change and fails the parse rather than riding
through. Consequences you must respect when you change either side:

- **A parser failure is not a throw.** `makeParser` returns
  `{ok:false, reason}` and the caller decides what the student sees. A
  contract drift therefore shows a visible error, never empty rows.
- **Parse before use.** No panel reads a response field that its Zod schema
  did not accept.
- **Fixtures pin the shape.** `web/src/contracts/fixtures/*.json` are the
  agreed payloads; a contract test compares them against the schemas.

The schemas are the boundary. Server-side field renames are breaking changes
even when the TypeScript still compiles.

## 5. The store

Two stores, and they are not interchangeable:

| Store | Lives | Holds | Source of truth for |
|---|---|---|---|
| SQLite `srm.db` | server, on a volume | everything synced from both upstreams | other devices, the shell, SSR |
| IndexedDB (Dexie) | the browser | that panel's props, keyed by netid | offline reads on this device |

**`web/src/db/db.ts` is the one module allowed to touch IndexedDB.** Nothing
else may open a database. Everything goes through it, because the version
history below only works if there is exactly one opener.

- **Migrations are append-only.** Editing a migration that already shipped is
  invisible to Dexie — the schema silently stays what it was. Add a new entry.
- **Rows are keyed by netid** (`sessionGroupKey`). A different student on the
  same device misses the key and gets nothing, which is the point.
- **Writes degrade, they do not throw.** When storage is full or refused,
  `db.ts` returns `false` and the caller falls back to network-only.
- **A failed Dexie row and the live repaint can never disagree** — the refresh
  path writes the row and repaints from the same parse.

## 6. Offline

An installed PWA is expected to open with the server unreachable. Three pieces
make that work, and all three are required:

1. **The precache.** The service worker precaches `dist/assets/*` and the
   manifest. These are content-hashed, so cache-first is safe.
2. **The shells.** `warmShells()` (`web/src/session/shell.ts`) fetches
   `/shell/<panel>` for each panel and stores them in the `opensrm-shell`
   cache. A shell is the panel's real markup with every personal value blanked
   server-side.
3. **The ladder.** A navigation is network-first. When the network fails, the
   worker serves `/shell/<panel>`, then `/shell/dashboard`, then `/shell/`,
   then a generic 503 page. Rendered pages are never cached, so the ladder
   cannot serve one.

**Navigation preload is a trap here.** If the server is dead, the preload
promise *rejects*; an uncaught rejection escapes the route handler, the
offline handler never runs, and the navigation dies with `net::ERR_FAILED`.
The worker treats a failed preload as "no preload" and falls through. Do not
remove that guard.

**Cache naming.** `workbox-config.js` hashes the injected manifest *and* the
bytes on disk into `CACHE_NAME`. Revision-only hashing is blind to a bundle
that changed shape in place. `CACHE_NAME` is a single-quoted literal because
three gates regex it out of the built file — keep it that way.

## 7. Privacy rules

The app holds one student's data on a device that may be shared. Four rules
follow, and every one of them is enforced somewhere you can point at:

1. **A rendered page is never cached.** `sw-template.js` registers the HTML
   route with `cacheWillUpdate: async () => null`, so no HTML response is ever
   written. This is the leak fixed in audit run-1 #12.
2. **The shell carries no personal data.** `app/blueprints/shell.py` blanks
   values in the **view model** — `presentation()` never receives the rows, so
   there is no page that ever contained PII to scrub. A regex pass over
   rendered HTML is the fragile version of this and would silently miss the
   day someone adds a field. `_assert_no_pii` runs as a belt: anything
   netid-shaped left in the response refuses to be served.
3. **Personal rows may live on the device, keyed by netid.** That is what
   makes offline work. They are in IndexedDB, never in the HTTP cache, and a
   second student's netid misses the key.
4. **`/logout` wipes everything.** It deletes every cache this origin wrote —
   `CACHE_NAME`, `workbox-precache*` and `opensrm-shell` — and unsubscribes
   this device's push subscription. An allow-list of caches to keep is a bug:
   the shells are what let the next student load a panel offline. The only
   caches that survive are ones this origin did not write.

**The banner rule.** The offline banner and the stale-row styling are UI
decorations over correct data; they must never be the only signal that data is
old. A caption or a colour that disappears with JavaScript off is not a
privacy or correctness control.

## 8. The CSS cascade rule

**Tokens only, and the cascade decides — not `!important`.**

1. Every colour is a daisyUI/Tailwind token class or a CSS variable. No hex,
   no `rgb()`, no `oklch()`, no palette class (`bg-gray-800`). See
   `DESIGN.md` §0.
2. **A daisyUI component wins inside itself.** Measured on this build:
   `text-base-content` does **not** override `.badge-info`'s colour, even with
   `!important`. To restyle component text, use another variant of that
   component or a hand-rolled span. Never reach for a utility override
   against a component's own rules — it is unreliable, not merely ugly.
3. **Specificity is not the tool.** Prefer the right token or the right
   component variant over a more specific selector. A selector that needed
   `!important` to win is a design-system decision that has not been made yet.
4. Tailwind + daisyUI are compiled ahead of time into `app/static/app.css`,
   committed, and CI fails if it is stale against the templates. No runtime
   CDN, no inline `<script>`, no web fonts. After touching `app/static/dist/`
   or the worker, rebuild from `web/` — `CACHE_NAME` is stamped from the
   bundle hash, never edited by hand (§6).

## 9. Where things live

| You want to change | Go to |
|---|---|
| A page's markup | `app/templates/` (shared chrome in `partials/theme.html`) |
| A route or a panel API | `app/blueprints/` |
| Panel behaviour | `web/src/panels/<name>/` and `web/src/data/` |
| A payload shape | `web/src/contracts/` (and its fixture) plus the server blueprint |
| Anything touching IndexedDB | `web/src/db/db.ts`, and nowhere else |
| Offline behaviour | `web/src/sw-template.js`, `web/src/session/shell.ts` |
| The shell scrub list | `app/blueprints/shell.py` |
| Colours, type, spacing | `DESIGN.md`, then `app/static/app.css` |
| This diagram | `scripts/build_arch_diagram.py` → `docs/architecture.html` |

The architecture diagram is **generated**. Edit `scripts/build_arch_diagram.py`
(the `NODES` table), never `docs/architecture.html`:

```bash
python3 scripts/build_arch_diagram.py docs/architecture.html
```

Turning the client layer off is documented in `docs/ROLLBACK.md`.
