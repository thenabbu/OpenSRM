# srm-maintenance Worker — deploy & ops notes

Cloudflare Worker on zone route `srm.200871.xyz/*` that catches origin failures
and serves a branded maintenance page. It runs **at the edge, in front of the
tunnel**, so it works even when the whole lab host is powered off — the case
where the edge would otherwise return Error 1033 / HTTP 530.

## Reproduce from scratch

```bash
cd edge/maintenance
./deploy.sh --dry-run   # what would change, touches nothing
./deploy.sh             # DNS + ingress + worker + route + verify
```

`deploy.sh` is idempotent: re-running it changes nothing when the state already
matches. It creates, in order:

1. CNAME `srm-origin.200871.xyz` → `<tunnel>.cfargotunnel.com` (proxied)
2. Tunnel ingress rule for that hostname (cloned from `srm.200871.xyz`, so it
   keeps the `X-Edge-Secret` origin header)
3. Worker `srm-maintenance` (built from `worker.src.js` + `page.html`)
4. Zone route `srm.200871.xyz/*` with **`request_limit_fail_open: true`**

Auth: `$CF_TOKEN`, else the first `CF_FULL_TOKEN` candidate in the lab's
`/docker/.env` that passes `/user/tokens/verify`. No token is stored in this repo.

## Why a second hostname

Routes cannot be the target of a same-zone `fetch()` call, so the Worker cannot
fetch the hostname it is attached to. `srm-origin.200871.xyz` points at the same
tunnel and carries no route, giving the Worker a clean path to the origin.

## Files

| File | Role |
|---|---|
| `worker.src.js` | Worker source. Edit this for logic. |
| `page.html` | The maintenance page. Edit this for copy/markup/styles. |
| `build.sh` | Inlines `page.html` into `worker.js` + runs syntax and self-checks. |
| `worker.js` | **Generated** — never edit. |
| `metadata.json` | Worker upload metadata (ESM entry + compatibility date). |
| `deploy.sh` | End-to-end deploy. |

## Gotchas (all verified live, Nov 2026)

- **`request_limit_fail_open` defaults to false.** On the Free plan the daily
  cap is 100,000 requests and exceeding it serves Error 1027. Fail-closed means
  every visitor sees a Cloudflare error *during an outage* — the exact thing
  this Worker exists to prevent. The flag can only be set when the route is
  **created**; `PATCH` fails with `10405 Method not allowed for this
  authentication scheme`, so `deploy.sh` deletes and recreates the route when
  the flag is wrong.
- **ESM upload needs the multipart form.** A bare `--data-binary` upload fails
  with `10021 Uncaught SyntaxError: Unexpected token 'export'`. Send
  `metadata=@metadata.json` plus `worker.js=@worker.js;type=application/javascript+module`.
- **`530` must be in the dead-code set.** It is the status an offline tunnel
  actually returns (body `error code: 1033`), not 502. Stopping the app
  container proves only the 502 path; stopping `cloudflared` is what a powered-off
  host looks like.
- **Account id ≠ zone id.** Passing the zone tag as the account id gives a
  misleading `10000 Authentication error` rather than a routing error.
- **`CF_FULL_TOKEN` may appear twice** in the lab env file (a dead stub first),
  and the live line can end in a `# comment` that corrupts the Bearer header
  (`6003`/`6111`). `deploy.sh` verifies candidates instead of trusting position.
- **Tunnel ingress PUT replaces the whole list.** Always GET → merge → PUT; never
  rebuild from memory. `deploy.sh` inserts by index and keeps the catch-all last.
- **Verify every sibling hostname after an ingress change.** Expected codes vary
  per app (immich 200, *arr 302, status 301). A pre-existing 502 for a hostname
  whose container is gone is not a regression from this deploy.

## Proving it works

```bash
ssh lab 'docker stop cloudflared'                 # simulates the whole host being off
curl -sI https://srm.200871.xyz/ | grep -i x-opensrm   # expect x-opensrm-maintenance: 1
curl -s  https://srm.200871.xyz/ | grep -o '<title>[^<]*'  # expect "Under maintenance"
ssh lab 'docker start cloudflared'
curl -sI https://srm.200871.xyz/ | grep -i x-opensrm   # back to x-opensrm-edge: pass
```

## Cost

Workers Free: 100,000 requests/day, no overage billing (the cap drops requests,
it does not charge). Observed traffic is roughly 60-100 app events/day; even at
~20 edge requests per page load this stays a few percent of budget. Route is
fail-open, so hitting the cap degrades to the pre-existing direct behaviour
rather than an error page.
