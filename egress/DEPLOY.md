# srm-egress Worker — deploy & ops notes

Live at `https://srm-egress.200871.xyz/srmiststudentportal/*` (zone route `srm-egress.200871.xyz/*` + proxied A record).
Script name is random per deploy: read from CF API or infra notes; token-gated, so name guessability is not load-bearing.

## Deploy (curl only, no wrangler)
Token: CF API token in `/docker/.env` on lab (`CF_FULL_TOKEN`, line 20 — value ends before the `#` comment).
```bash
ACC=6861cc3276134b677ad93f92561fa95c
WNAME=<script name>
PROXY_TOKEN=<client token>
curl -X PUT "https://api.cloudflare.com/client/v4/accounts/$ACC/workers/scripts/$WNAME" \
  -H "Authorization: Bearer $CF_TOKEN" \
  -F 'metadata=@metadata.json;type=application/json' \
  -F 'worker.js=@worker.js;type=application/javascript+module'
```
metadata.json MUST include the PROXY_TOKEN binding inline (`bindings:[{type:secret_text,...}]`) or `keep_bindings:["secret_text"]` —
a bare re-upload resets the binding set and env.PROXY_TOKEN goes undefined (cost us ~1h to find).

## Gotchas (all verified live, Sep 24 2026)
- workers.dev 404: per-script subdomain enablement is OFF by default via raw API — `POST .../scripts/$WNAME/subdomain {"enabled":true}` (we did, works too now).
- POST /workers/domains and POST .../secrets don't exist — custom-domain attach is **PUT**, secrets update is **PUT**. Using POST returns 10405 "Method not allowed for this authentication scheme".
- Zone route + proxied A record (198.51.100.10 placeholder) works identically to Workers Custom Domains for our use.
- F5 issues its TS persistence cookie to CF egress IPs (observed both ways; intermittent absence earlier was not reproducible).
- SRM does NOT validate Origin (Worker can't send it — forbidden header). Referer must be `https://sp.srmist.edu.in/...` exactly.
- Captcha flow via worker works (full login SUCCESS through worker, Sep 24 2026): GET page → fetch page's own `data-src` captcha with `X-Domain-Proof: btoa(nonce:hostname)` → OCR (ddddocr on lab) → POST LoginServlet. Do NOT fetch a fresh SCaptchaServlet URL — desyncs session.
- Login page through worker returns 16245b vs 15306b direct — extra bytes are CF-challenge injection on our worker host; harmless (login worked).
- Keep 2-3 min gaps between live login tests; F5/others rate-limit aggressively (~1 attempt / 2-3 min is safe).
