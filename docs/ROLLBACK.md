# Turning the Preact front end off

`PREACT_ISLANDS` is a boot flag that stops the Preact islands from hydrating.
It is a **mitigation**: nothing is deleted, the legacy path was never removed.

- **Default: on.** `PREACT_ISLANDS` unset, empty, or `1/true/yes/on` → the island
  module is emitted and hydrates as normal.
- **Off** (`PREACT_ISLANDS=0`, `false`, `no`, or `off`) → the one island module
  tag in `app/templates/partials/theme.html` is not rendered. The
  server-rendered panels are the whole app, and `app/static/dash.js` keeps
  doing the client work it always did.

## Flip it

Boot-time only (it is read once in `AppConfig.from_env()`), so it needs a
container restart, not a redeploy:

```bash
# /docker/opensrm/.env  (or the compose environment)
PREACT_ISLANDS=0

docker compose -f /docker/opensrm/docker-compose.yml up -d opensrm
```

To put it back, delete the line (or set `PREACT_ISLANDS=1`) and restart.

## What changes for the user

Everything is still there — same routes, same server-rendered rows, same
`dash.js` behaviour (auto-sync, tabs, graphs). What stops is the Preact-side
upgrade: island-owned captions, the offline IndexedDB store and the
service-worker freshness logic do not mount, so an already-installed PWA falls
back to the legacy fetch-on-load behaviour. No 500, no blank page.

## Confirm

With `PREACT_ISLANDS=0` on a running instance:

```bash
curl -s -b "srm_session=$TOKEN" http://127.0.0.1:8000/attendance | grep -c 'type="module"'   # -> 0
curl -s -b "srm_session=$TOKEN" http://127.0.0.1:8000/attendance | grep -c 'class="att-subj"'   # -> row count > 0
```

The unit suite pins both directions: `tests/unit/test_rollback_flag.py`
(default is on, off drops exactly the module tag and keeps the rows).
