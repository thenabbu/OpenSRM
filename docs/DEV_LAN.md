# Dev build over the LAN (laptop + phone)

A disposable container running the current build, reachable from your laptop and
phone on the same Wi-Fi. Built for hands-on testing, not for users.

## Start it

```bash
cd /opt/data/opensrm-repo
PORT=8095 bash scripts/dev-lan.sh start
```

`PORT` is required in practice: **8080 is taken by qbittorrent** on the lab, so a
default start fails with `address already in use`.

Output:
```
seeded devuser
started  http://localhost:8095  ·  http://192.168.29.7:8095
login    devuser / devpass123
```

## Open it

| Device | URL | Notes |
|---|---|---|
| **Laptop** | `http://localhost:8095` | Full PWA: service worker, install prompt, offline |
| **Phone** | `http://192.168.29.7:8095` | App works; **no service worker** (see below) |

Login is **`devuser` / `devpass123`**. It is seeded into the DB, not a real SRM
account — `/api/login` is a live portal scrape, so there is no local-password
path to log in through.

## What works, and what 404s

Verified against the running container:

| Route | Status |
|---|---|
| `/` `/attendance` `/timetable` `/marks` `/settings` | **200** |
| `/campus` `/academics` `/fees` `/tools` | **404 — expected** |

The 404s are not a bug. `app/views/campus.py:181` returns `{"show": bool(cards)}`
and `app/blueprints/shell.py:81-82` aborts 404 for any panel the student has no
data for. Those four panels need real `scope_json` payloads, and the image does
not ship `tests/_scope_fixture.py`, so a seeded dev user genuinely has no data
for them.

**If you need those four routes for testing**, run the app from source instead of
the container (`DATA_DIR=... .venv/bin/python -m gunicorn app.app:app`) and call
`tests/_scope_fixture.inject(DATA_DIR)` first. That is the same path the e2e
suite uses.

## The phone limitation — read this

**Service workers require a secure context.** `http://192.168.29.7:8095` is not
one, so on the phone:

- ✗ no offline mode
- ✗ no "Add to Home Screen" install prompt
- ✗ no cache warm-up
- ✓ everything else — all pages, all islands, all interaction

`http://localhost` **is** treated as secure, which is why the laptop gets the
full PWA and the phone does not. Same build, different browser rule.

**To test the service worker on Android**, forward the port over USB:

```bash
adb reverse tcp:8095 tcp:8095
# then open http://localhost:8095 on the phone
```

That makes the phone see `localhost`, which *is* secure, so the service worker
registers and offline/install work. iOS cannot do this — it needs real HTTPS,
which means a certificate the phone trusts.

## Other commands

```bash
bash scripts/dev-lan.sh status   # running? + both URLs + / status code
bash scripts/dev-lan.sh url      # just the LAN URL
bash scripts/dev-lan.sh stop     # remove the container, keep the data dir
```

State lives in `.dev-lan-data/` (git-ignored). Delete it for a clean slate.

## Overrides

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8080` | Host port — **set this**, 8080 is occupied |
| `IMAGE` | `opensrm-scan:20261112-1406` | Image to run |
| `DATA` | `./.dev-lan-data` | Bind-mounted data dir |
| `DEV_NETID` | `devuser` | Seeded login name |
| `DEV_PASSWORD` | `devpass123` | Seeded login password |

The LAN IP is detected from the default route at runtime — never hardcoded, so
this keeps working if the lab's address changes.
