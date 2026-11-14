# OpenSRM golden capture

Deterministic baseline of the app at `feat/preact-migration` HEAD
before the Preact migration landed. Regenerate with `scripts/capture_golden.sh`,
then diff against this dir — `dom/`, `api/`, `routes.json` and `metrics.json`
must be byte-identical; screenshots must be ~0% pixel difference (they were
0/23,259,114 px on the two-run determinism check).

## One command

```
bash scripts/capture_golden.sh /tmp/golden-check
diff -r -x v2 -x v3 tests/golden /tmp/golden-check   # expect: no output (-x: v2/ and v3/ are the separate, revision-pinned baselines)
```

Wipes the target dir, seeds a clean
`DATA_DIR=/tmp/osrm-premig` (`tests/_seed.py` `seed_rich()`, user
`zz9999` only), injects the fabricated scope blob, boots gunicorn on
127.0.0.1 (port 18185 if free, else auto-increment), captures, and
shuts the server down. Read-only on the repo; nothing is committed.
Playwright chromium lives at `/opt/data/cache/scratch/pw-browsers`
(`playwright install chromium` if missing).

## Contents

| path | what |
|---|---|
| `routes.json` | the 9 tab ids, `panels_present` (asserted == 9 in-harness), and each panel's normalized outer HTML |
| `dom/<tab>.html` | post-JS-load DOM of each panel, normalized (see below) |
| `screens/<tab>-{390x844,768x1024,1440x900}.png` | full-page screenshots, 9 tabs x 3 viewports |
| `api/<endpoint>.json` | status, content-type, byte + gzip sizes, and body (or b64 for binary) of every GET endpoint, including static assets and `/login`; `logout.json` captured last |
| `metrics.json` | per page: html bytes, gzip bytes, `<script>` count, JS file list + total bytes; per api endpoint sizes; DOM node counts |

## What is normalized (and why)

Captured output must be identical across runs, so anything that
legitimately varies with wall-clock is normalized at record time:

1. **`?v=<hash>` asset query strings** — `app/app.py asset()` appends
   `?v=sha256(file)[:10]`. Hash is stable for unchanged files, but the
   query string is a deployment detail, not app behaviour; stripped so
   a content-hash change alone doesn't fail the diff. (Regex is
   hex-aware: `\?v=[0-9a-fA-F]+`.)
2. **`data-ts` / `data-full` attributes on the sync line** — the
   dashboard's "last synced" epoch + ISO string. Replaced with
   `data-ts="0"` / `data-full="1970-01-01T00:00:00Z"`.
3. **Relative-time strings** (`just now`, `Ns ago`, `Nm ago`, ...) —
   rendered from wall-clock in `dash.js`; replaced with a fixed
   `x ago` placeholder.
4. **Epoch / ISO timestamps in visible text** — same reason.
5. **`/internal/metrics` values** — Prometheus counters/timers for the
   live process (histogram sums, RSS, sync ages) change every run by
   design; values are zeroed, metric names + labels (the structural
   contract) are kept.
6. **Recorded sizes are computed on the normalized bytes**, not the
   raw wire bytes — raw HTML contains the volatile bits above, so
   raw sizes would wobble by a few bytes between runs.

## What is fixed to keep things stable (not normalized)

- Clean `DATA_DIR` + `seed_rich()` + fabricated scope blob every run:
  the repo's campus fixtures are alive-empty ("No data found")
  envelopes, and `campus_view` hides the tab when every card is empty
  (`show = bool(cards)`), so the harness fabricates minimal rows for
  jobs/resume/library/hostel/transport/notifications.
- `SCOPE_FEATURES` = all 9 feature slugs on the server env.
- Client clock frozen (`page.clock.setFixedTime`), CSS/SVG animations
  paused, `prefers-reduced-motion: reduce`, service workers blocked,
  external (non-127.0.0.1) requests aborted.
- `gzip` recorded with `mtime=0`.

## Panel parity

`routes.json` records `panels_present`; the harness hard-fails
(`panels missing from DOM: [...]`) if fewer than the 9 known tabs are
in the DOM — a capture that silently baselines 5 of 9 is rejected,
not accepted.
