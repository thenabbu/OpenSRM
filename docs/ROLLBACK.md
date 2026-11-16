# Turning the Preact front end off

`PREACT_ISLANDS` is a boot flag that stops the Preact islands from hydrating.

**Read this first: W5.4 changed what the flag means.** Until W5.4 the legacy
scripts were still in the tree and `PREACT_ISLANDS=0` fell back to them. They
are deleted now (`dash.js`, `timetable.js`, `pull.js`, `drag-drop-touch.js`), so
the flag no longer switches to a second client implementation — it switches the
client layer OFF.

- **Default: on.** `PREACT_ISLANDS` unset, empty, or `1/true/yes/on` → the island
  module is emitted and hydrates as normal. This is the shipping configuration.
- **Off** (`PREACT_ISLANDS=0`, `false`, `no`, `off`) → the one island module tag
  in `app/templates/partials/theme.html` is not rendered. The server-rendered
  panels are the whole app: every route renders, every row and number is there,
  links work, forms still POST (the no-JS paths: `/marks/tag`, login, logout,
  delete-account).

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

Everything is still there and still correct — same routes, same
server-rendered rows, same data. What stops is every client enhancement, because
the code that provided them now lives only in the bundle:

- the sync caption no longer re-ages itself (the server's first paint stands);
- `[data-refresh]`, click-to-copy, the attendance graph/table toggle, the
  offline banner, the item beacon, the feedback/delete dialogs and the marks tag
  save are unwired — the page is read-only apart from plain form POSTs;
- the timetable editor and pull-to-refresh are unavailable;
- the service worker is not registered on app routes (login.js still registers
  it on `/login`), so an installed PWA falls back to the network.

No 500, no blank page: this is a deliberately degraded, fully server-rendered
mode, useful for isolating a bundle regression. It is not a supported
end-user configuration.

## Confirm

With `PREACT_ISLANDS=0` on a running instance:

```bash
curl -s -b "srm_session=$TOKEN" http://127.0.0.1:8000/attendance | grep -c 'type="module"'   # -> 0
curl -s -b "srm_session=$TOKEN" http://127.0.0.1:8000/attendance | grep -c 'class="att-subj"'   # -> row count > 0
```

The unit suite pins both directions: `tests/unit/test_rollback_flag.py`
(default is on, off drops exactly the module tag and keeps the rows).
