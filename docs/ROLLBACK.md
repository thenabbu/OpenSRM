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

The unit suite pins both directions on EVERY panel route (not just
`/attendance`): `tests/unit/test_rollback_flag.py` boots the app once with the
flag on and once off, renders all nine routes in each, and asserts the two
HTML bodies are the same page except for the module tag. Default is on, off
drops exactly the module tag and keeps the rows — and neither direction can
quietly lose a section.

## Roll back a release

The flag above turns the client layer off inside one build. Rolling back the
**build** is a different job: pin the previous release image and recreate the
container.

`docker-compose.yml` reads the image from `${OPENSRM_TAG:-latest}`, and
`/docker/opensrm/.env` sets it. Version tags are immutable: `build.yml`
publishes `:VERSION` and `:latest` only when `VERSION` moves, and `:<sha>` on
every commit, so a previous release stays pullable.

The last release on the v2 line is **`2.12.1`**, and that is what the box runs
today (`OPENSRM_TAG=2.12.1`, `/app/VERSION` = `2.12.1`). Everything the Preact
branch builds is `3.0.0`, so a rollback from a `3.0.0` deploy lands on
`2.12.1`. Verified 2026-11-19: `2.12.1`, `2.12.0` and `2.11.0` all pull from
`ghcr.io` with no login.

Use the deployer, not hand-edited commands. It snapshots the database first,
pins the tag, verifies the new image, and reverts to the previous tag by itself
if the new one is unhealthy:

```bash
# on the box, from a checkout of this repo
bash scripts/deploy_gated.sh 2.12.1
DEPLOY_DRY_RUN=1 bash scripts/deploy_gated.sh 2.12.1   # rehearse; changes nothing
```

It verifies in three places: the container's own health status, public
`/healthz` returning 200, and an in-container request to `/login`. The 8 October
failure was `/login` green while every authenticated page returned 500, so the
render check is the one that catches it.

To do it by hand, change the tag and recreate:

```bash
cd /docker/opensrm
cp .env .env.bak-$(date +%F-%H%M)
sed -i 's|^OPENSRM_TAG=.*|OPENSRM_TAG=2.12.1|' .env
docker compose pull opensrm
docker compose up -d opensrm
docker exec opensrm cat /app/VERSION                                       # -> 2.12.1
curl -sS -o /dev/null -w '%{http_code}\n' https://srm.200871.xyz/healthz    # -> 200
```

**The image reverts; the database schema does not.** A release that ran a
migration has already changed `srm.db`, so the older image runs against the
newer schema. Take the snapshot before you touch the tag — that is exactly why
`deploy_gated.sh` does it first.
