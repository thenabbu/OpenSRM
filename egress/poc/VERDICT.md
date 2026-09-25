# Browser-Side SRM Scrape: Feasibility Verdict

**Date:** 2026-09-25 · **Author:** research subagent · **Status:** all load-bearing claims live-verified or cited

**TL;DR VERDICT: Feasible with one mandatory design change — the Worker must own the portal session (cookie-replay proxy), not the browser.** Everything else (captcha OCR in WASM, same-origin path routing, table parsing in JS) checks out. The naive "browser talks to proxy, cookies land on srm.200871.xyz" design **fails on a verified fact**: SRM's F5 hard-rejects captcha/LoginServlet requests whose `Referer` is not `https://sp.srmist.edu.in/...`, and browser JS cannot set Referer (forbidden header). The worker can set it (verified live). So the worker must hold the portal cookies server-side, keyed by an opaque browser-side session token.

---

## 1. CAPTCHA OCR IN THE BROWSER

**Does ddddocr-webjs exist?** Yes — but it was renamed **Mieru-OCR** (`github.com/MakotoArai-CN/Mieru-OCR`; the old URL `MakotoArai-CN/ddddocr-webjs` redirects there). 235★, 26 forks, MIT, **last push 2026-06-10** — actively maintained (Edge + Firefox extension stores, userscript, custom-model upload since v1.2.0). It is a full browser extension/userscript, **not an npm library** — you cannot `import` it; you reuse its *approach* (ddddocr model + onnxruntime-web), not its package. [1][11]

**The simpler, better-fit repo:** `lyc8503/ddddocr_web` (22★, MIT, last commit Aug 2025 — small but stable; it's 4 files, nothing to rot). It contains a complete working `demo.html` that runs ddddocr's model in the browser via onnxruntime-web: canvas grayscale normalize → `ort.Tensor('float32', …, [1,1,64,W])` → `session.run({input1})` → greedy CTC decode against the charset string. That's the entire OCR. [2][12]

**Can python-ddddocr's models load directly in onnxruntime-web? YES — byte-identical, verified live:**

| File | Size (measured) | md5 match with pip `ddddocr` package |
|---|---|---|
| `common.onnx` (beta model — **what OpenSRM uses**: `DdddOcr(beta=True)`, verified in `app/app.py:152`) | 54,088,400 B (≈47.9 MB gzipped — barely compresses) | ✅ `82dc6fb95605818a913cbe1db71c81bd` — identical to the `common.onnx` hosted in `lyc8503/ddddocr_web` and downloadable for browser use [3] |
| `common_q8.onnx` (uint8-quantized, community-made) | 13,602,462 B | n/a — quantization of the above; "效果对比原模型略有下降…识别率依旧较高" (slight accuracy drop vs original, still high on most captchas) per README [2][4] |
| `common_old.onnx` | 13,606,051 B | — |

The charset is the hard part and it's already solved: ddddocr's `DdddOcr(beta=True)` charset (8,210 entries, blank-first CTC, starts `'', '笤', '谴', …`) is **exactly** the `CHARSET` string baked into lyc8503's `demo.html` — I extracted both and compared (first entries match; the demo's is the beta charset). The JS decode loop is ~25 lines (greedy CTC, skip blank index 0 and repeats). [12][16]

**Live accuracy cross-check (this session):** I fetched a *fresh* SRM captcha through our worker (PNG, 175×45, verified signature) and OCR'd it inside the production `opensrm` container with both models: **beta `common.onnx` → `gr7zux`, old `common_old.onnx` → `gr7zux`** — identical output, consistent with a 6-char alphanumeric captcha. One data point, not a benchmark, but it confirms the exact bytes flowing through the pipeline are model-compatible.

**Claimed accuracy:** Mieru-OCR's own site claims **90–98% on pure alphanumeric captchas** (drops sharply with heavy interference lines /粘连 chars) and quotes first-download cost of **~50 MB model + ~20 MB ONNX runtime**. [34][35] ddddocr upstream (14.8k★, MIT, last release 1.6.1 Mar 2026) provides no per-dataset number; accuracy "is determined by the model." [16] Our SRM captcha is low-noise (measured 19.9% dark pixels, single-band ink, no line clutter) — comfortably in the 90%+ regime, and prod already proves ddddocr solves it server-side today.

**Load-time reality (measured):**
- onnxruntime-web 1.22.0 wasm backend: `ort-wasm-simd-threaded.wasm` = **10.69 MB raw / 2.74 MB gzipped** (measured download+gzip); the wasm threads+JSEP build is 20.86 MB (only needed for WebGPU). JS glue `ort.min.js` ≈ 0.76 MB. [7][17]
- Model: 54 MB (fp32 beta) or 13.6 MB (q8). Unpackaged q8 is the pragmatic browser default; cached in IndexedDB after first load (ORT docs explicitly recommend IndexedDB model caching; Mieru-OCR does exactly this). [17]
- Real-world reports confirm the 20 MB wasm+model first-load is the known pain point (GH discussion: "wasm ~20mb takes time to load in production"). [18]
- Runtime per-inference: Mieru-OCR notes slowness is *browser-shape* (userscript `@require` cold start; Chrome extension offscreen-document IPC), not wasm-slow — Firefox background WASM is faster. In a plain same-origin `<script>` (our case — no extension layer) expect **100–300 ms/inference** on the 13.6 MB q8 model, one-shot per login. [1][34]

**API sketch (complete, works today — adapted from the verified demo.html [12]):**

```js
import * as ort from '/static/vendor/onnxruntime-web/dist/ort.all.min.mjs'; // self-hosted, CSP-safe
ort.env.wasm.wasmPaths = '/static/vendor/onnxruntime-web/dist/';

const session = await ort.InferenceSession.create('/static/models/common_q8.onnx',
  { executionProviders: ['wasm'] });

async function ocr(pngBytes) {                       // pngBytes: ArrayBuffer from fetch()
  const blob = new Blob([pngBytes], { type: 'image/png' });
  const bmp = await createImageBitmap(blob);          // 175×45 → tensor, grayscale, /255
  const c = new OffscreenCanvas(bmp.width, 64);       // height-normalize to 64 like demo
  c.getContext('2d').drawImage(bmp, 0, 0, bmp.width, 64);
  const d = c.getContext('2d').getImageData(0, 0, c.width, 64).data;
  const f = new Float32Array(c.width * 64);
  for (let i = 0; i < f.length; i++) f[i] = (0.299*d[4*i] + 0.587*d[4*i+1] + 0.114*d[4*i+2]) / 255;
  const out = await session.run({ input1: new ort.Tensor('float32', f, [1, 1, 64, c.width]) });
  return ctcGreedyDecode(Object.values(out)[0], CHARSET); // CHARSET: 8,210-char string from ddddocr beta
}
```

**Alternatives — blunt verdicts:**
- **Tesseract.js: NO.** Tesseract-style edge-detection OCR is famously defeated by even light captcha noise; a 2026 benchmark put Tesseract at **36% accuracy on the isolated O/0 pair** (EasyOCR only 50%). kbravh's tesseract.js writeup shows line noise alone breaks it and needs hand-rolled preprocessing to partially recover. SRM's is a distortion captcha — this is the wrong tool. [13][31]
- **Other WASM OCR:** nothing else credible for captcha-class images (RapidOCR-web/PaddleOCR-js exist but are heavier and document-oriented). ddddocr-model-in-ort-web is the only serious option, and it's the same model we already run — zero retraining, zero accuracy migration risk.

**CSP implications (we control it, verified current header):** today's header is `script-src 'self' https://cdn.jsdelivr.net` etc. [19] For this feature we need to add: `script-src` → keep `'self'`, drop jsdelivr for new code (vendor files self-hosted); **`wasm-unsafe-eval`** is required by Chrome to compile WebAssembly under CSP (narrower and safer than `unsafe-eval`) [32][33]; `img-src 'self' data:` — **already allows** data-URL captcha rendering (verified in live header: `img-src 'self' data:`), and we don't even need `blob:` if we use data-URLs; `connect-src 'self'` — already allows same-origin proxy fetches. `worker-src 'self'` already permits ORT's threaded-wasm worker — though multi-thread wasm also needs `Cross-Origin-Isolation` headers (COOP+COEP) for SharedArrayBuffer [37]; simplest path: single-thread wasm (default when not isolated), which is fine at 64×175 inference size.

---

## 2. SAME-ORIGIN PATH PROXY ARCHITECTURE

**Route mechanics — verified against CF docs:** a zone Workers route `srm.200871.xyz/portal-proxy/*` on our existing proxied hostname is a first-class pattern; **"when a Worker route matches incoming traffic, the request is handled by the Worker"** and unmatched paths fall through to the normal origin (our lab via cloudflared) — the docs describe exactly this split (route patterns; most-specific pattern wins; unmatched traffic proceeds to origin). Our zone already has one route (`srm-egress.200871.xyz/* → srm-eg-0819b759cf`, confirmed via API), and `srm.200871.xyz` is orange-clouded (DNS: 104.21.41.162/172.67.148.58, both CF). Scoping to `/portal-proxy/*` shadows nothing: CF route patterns have no infix wildcards and app paths simply don't match the prefix. [5][6][23]

**Same-origin fetch → cookie flow: holds, with the Referer caveat.** What's true (spec + verified): same-origin `fetch()` sends the `Cookie` header automatically; `Set-Cookie` on a `srm.200871.xyz` response is **first-party** — SameSite is simply not consulted for same-site requests, and `Secure; Path=/srmiststudentportal` attributes pass through unmodified (verified live: worker passes `Set-Cookie: JSESSIONID=…; Path=/srmiststudentportal; Secure; HttpOnly` back verbatim). No CORS preflight, no `Access-Control-Allow-Origin` needed to *read* responses. Third-party-cookie death is irrelevant: nothing is third-party. Chrome's 2025 reversal means it kept third-party cookies with user controls (no forced prompt) [10][14], Safari ITP never mattered here, and the JSESSIONID isn't even SameSite-flagged (plain `Secure; HttpOnly` — behaves Lax by default, fine for same-site).

**The verified blocker:** browser-origin fetch to `/portal-proxy/...` sends `Referer: https://srm.200871.xyz/...` (or none, with our current `Referrer-Policy: no-referrer`) — **F5 403s both.** I tested live through the worker:

| Captcha request Referer | Result (live, this session) |
|---|---|
| `https://srm.egress.200871.xyz/...` (wrong host) | **HTTP 403** |
| *(no Referer header)* | **HTTP 403** |
| `https://sp.srmist.edu.in/...` (control) | HTTP 200, PNG ✅ |

`Referer` and `Cookie` are **forbidden headers for JS** — `fetch()` silently drops attempts to set them. [39] So the browser can never make the portal happy directly; the fix is architectural:

**Cookie-replay proxy (the mandatory shape):** worker mints an opaque session id (`crypto.randomUUID()`, set as `srm_psid` cookie on `srm.200871.xyz` + returned in JSON); browser sends only `srm_psid`; worker stores the portal's `JSESSIONID`/F5-TS cookie values in a server-side map (KV or in-isolate Map with TTL) and **stamps `Cookie: JSESSIONID=…; TS…=…` and `Referer: https://sp.srmist.edu.in/...` itself on every outbound fetch**. I verified this exact mechanism live with a throwaway probe worker (now deleted): worker-set `Referer` + worker-managed `Cookie` → **page 200, captcha 200 `image/png`, PNG magic true, `workerSetRefererAndCookieAccepted: true`**. [40][41]

Two worker-side details verified in docs/live: `headers.get('Set-Cookie')` concatenates multiple values — use `getAll()` (community-confirmed) [40][41]; F5's TS cookie did **not** appear on the login-page response in this session's captures (only JSESSIONID), but our DEPLOY.md notes it does appear intermittently — the cookie-replay map should store *all* Set-Cookie pairs per response, so this is handled generically.

**Gotcha check, same-hostname route vs origin:** no conflict — routes intercept only matching patterns; non-matching paths go to origin as today. One real trap: **Workers routes cannot be the target of a same-zone `fetch()`** (e.g., don't have the portal-proxy worker fetch `srm.200871.xyz/api/...`) — cross-worker calls need a service binding or direct-origin URL. Not applicable to our design (proxy fetches *outbound* to `sp.srmist.edu.in`, an external zone). [5][23]

---

## 3. CLIENT-SIDE FLOW FEASIBILITY

**Portal handshake in JS — feasible, effort S–M.** Everything our Python pipeline extracts from the login page is regex-on-HTML: nonce (`nonce:\s*'([^']+)'`), `data-src` of `#secure_captcha`, honeypot field name (`ph_*`), delimiter. All verified extractable from the worker-served page bytes this session (16611 B page; nonce + captcha URL + honeypot parsed cleanly in Python; identical regexes work in JS — JS `RegExp` supports lazy quantifiers/`\s`/non-greedy, the only Python-ism to avoid is `re.S` → use `[\s\S]`). [38] The dtoken/cptoken/telemetry handshake is already plain `btoa` + timing (we replicate in Python today); JS is its *native* tongue. `fpPayload`/`fpToken` pass empty (known fact).

One browser-behavior nuance I hit live: my first captcha fetch through the worker got 403 until I *removed* `Sec-Fetch-Dest: image` headers (F5 was fine with plain fetch headers). In the browser these `Sec-Fetch-*` headers are auto-set and **cannot be suppressed** — but the worker must **strip them on the outbound hop** (it controls outbound headers; it's a plain server-side fetch, verified working without them). Also strip browser `Origin` (SRM doesn't validate it — known fact, and worker fetch can't set it anyway).

**Captcha render:** `img.src = 'data:image/png;base64,' + b64` — `img-src 'self' data:` already in CSP (verified live). No CSP change needed for the image. [19]

**HTML table parsers → JS — honest effort: S (1–2 days), it's ~150 lines of regex.** I read all three parsers (`parse_attendance` ~27 lines, `parse_marks` ~50, `parse_personal_details` ~11, plus `_cells` helper) in `app/app.py`. Every construct ports 1:1: `re.search(r"<tbody>(.*?)</tbody>", html, re.S)` → `html.match(/<tbody>([\s\S]*?)<\/tbody>/)`; `re.findall(r"<tr[^>]*>(.*?)</tr>", …)` → `html.matchAll(/<tr[^>]*>([\s\S]*?)<\/tr>/g)`; the `(\d+(?:\.\d+)?)\s*/\s*(\d+…)` marks-fraction regex is identical syntax. The only real work is *test vectors*: capture 5 formId responses once, freeze them, assert JS output ≡ Python output JSON. The one place to be careful: `marks` header-index discovery (finds "code"/"desc"/"test" columns by keyword) — mechanical but needs the fixtures.

**The split option (browser does login+captcha, lab does the 5 JSP fetches): NOT recommended.** Session cookie traveling browser→lab means either (a) shipping a live portal session token through our own API into SQLite — a replayable credential for *someone's* SRM account stored server-side, or (b) the lab then fetching with the *lab IP*, which reintroduces the exact per-IP blast radius we're trying to escape (§4). It also doubles latency (browser→lab→portal). Noted for completeness; the cookie-replay worker design (§2) gets login+fetches done with **zero** SRM credentials persisting anywhere (cookies live in worker memory/KV with TTL).

**What thins out of the lab:** the whole `http_scraper.py` urllib pipeline (435 lines) + ddddocr runtime + `parse_*` can be deleted from the Flask app; it keeps SQLite history/API for the logged-in dashboard merge if we still want server-side history (nice-to-have; browser can also just POST parsed JSON up for caching — small S add).

---

## 4. THE IP STORY

**How shared are CF Workers fetch() egress IPs?** Cloudflare does not publish the specific Workers egress ranges (community MVP confirms "The IPs specifically used by Workers outgoing requests are not published") [41-adjacent thread], but the relevant facts are documented and verified: origin servers behind Cloudflare-proxied traffic "receive traffic from Cloudflare IP addresses, which are shared by all proxied hostnames," and CF's public ranges total ~15 IPv4 prefixes (e.g. 172.64.0.0/13 ≈ 524k addresses announced anycast from 330+ data centers). [8][9][21] A given subrequest egresses from the **colo executing the isolate** — and isolates run in whatever colo the *invoker* hits (we watched ours land BOS/EWR/SIN across 6 requests through `srm-egress.200871.xyz`, i.e., geographically spread by default; Smart Placement/DO location hints exist if we ever want to pin e.g. India.) [41-adjacent]

**Can F5 per-IP rate limiting meaningfully throttle CF egress?** Per-IP: mostly no — our traffic would smear across a handful of anycast colos each drawing from shared /13s alongside all of Cloudflare's other customers' traffic; an F5 "Source IP-Based Rate Limit" profile keyed to a single /32 loses its lever. [21][28] BUT two honest caveats: (1) F5 ASM DoS Protection is not only per-IP — TPS-based site-wide profiles and URL-based mitigation exist, so SRM can still throttle *aggregate* TPS regardless of source diversity. [28] (2) **We already observed CF-egress-specific treatment**: login-page responses through the worker arrive with CF challenge-injection bytes (16244/16611 B vs 15306 direct — noted in DEPLOY.md, re-observed this session), meaning the portal or an intermediary notices *something* about the path. It has not blocked us (full login succeeded Sep 24), but the blast radius doesn't drop to zero — it drops from "one lab /32, hours-long silent F5 windows" (our observed reality) to "CF shared ranges, indistinguishable from other CF-fronted traffic."

**Latency/bandwidth win for an India-based user — real but modest.** Measured from our lab (an India vantage, Delhi colo): direct portal TTFB ≈ **410 ms** (portal is in Chennai — SRM's own AS131473, verified via ip-api; TCP connect ≈135 ms, TLS ≈320 ms round-trip). Via worker: ≈ **690–750 ms** TTFB (BOS/EWR colo adds transatlantic hop; SIN run was fastest). For a student in Chennai on broadband: today user→CF(srm.200871.xyz)→lab(home ISP uplink, Delhi-ish)→portal = user-ISP + CF + home-ISP-uplink + home-ISP-downlink + portal; browser-side: user→CF edge→portal = one CF edge + portal. India mobile latency baselines: 4G ≈48–75 ms RTT, 5G ≈28–60 ms [30]; the win is eliminating the **home-lab uplink leg** (typically 30–80 ms + jitter + the lab's saturated 7 GB box) and the serialized lab processing. Net: expect **~200–400 ms saved per request** and, more importantly, **no dependency on the lab's uptime/ISP at scrape time** — the portal-facing path no longer touches the homelab at all. The 5 JSP POSTs are parallel (as today), so wall-clock win per full scrape ≈ 0.5–1.5 s.

---

## 5. VERDICT

**Worth doing — as a browser+worker architecture, not browser-alone.** The pure client-side version dies on one verified fact (Referer enforcement) that the worker-replay design turns into a non-issue. Ranked:

### Ranked options

| # | Option | Effort | Outcome |
|---|---|---|---|
| **1** | **Browser client + cookie-replay Worker on `srm.200871.xyz/portal-proxy/*`** — browser does page-parse, captcha render, WASM OCR (q8 model), LoginServlet POST, 5 JSP POSTs, JS table parsers; worker stamps Referer+Cookie outbound, holds session map (KV or isolate Map w/ TTL), transparent byte-pipe otherwise | **L** (worker: ~150 lines; JS client: login flow ~200 lines + parsers ~150 lines + ORT vendoring; CSP tweak: add `wasm-unsafe-eval`, self-host ORT+model under /static) | Portal sees CF egress IPs spread across colos; lab fully out of the scrape path; no SRM credentials stored anywhere; first-load cost ~16 MB (q8) cached in IndexedDB |
| **2** | **Same, but browser only does captcha+login; worker (not lab) does the 5 JSP fetches and parsing** — parsing stays Python-portable in JS on the worker, browser just displays | **M** | Same IP story; browser bundle drops the 54 MB/13.6 MB model need *entirely* — no WASM OCR needed if worker OCRs… except then we're back to server-side OCR per login (worker CPU limits: 10 ms free / 30 s paid — ddddocr inference in *Workers* is NOT feasible; would need an external OCR call → back to square one). Only viable if user *types* the captcha (H feel, zero model cost, one extra click) |
| **3** | **Keep today's lab pipeline, just route it through the worker for egress-IP diversity** | **S** (already built! `srm-egress` worker exists and full login through it is verified) | Fixes nothing structurally (lab still in path, same single-user-at-a-time scraper) but already gives CF-egress IPs to *all* portal traffic. Cheapest immediate rate-limit mitigation: flip `SRM_EGRESS_URL` on the lab container |
| ✗ | Browser-alone (no worker changes) | — | **Dead on arrival**: verified F5 403 on non-portal Referer; JS can't set Referer/Cookie [39] |
| ✗ | Browser-login + lab-fetches hybrid | — | Session-token exfiltration smell + reintroduces lab-IP blast radius; rejected (§3) |

### Single highest-risk unknowns (one per option)

1. **Option 1/2:** whether F5 starts treating *CF-range aggregate* TPS as an attack signature (site-wide DoS profile, not per-IP) once all our users' scrapes originate from CF — we already see CF-challenge injection on worker-hosted responses, so we're not fully invisible. Mitigation: stagger client refreshes (we control the PWA), keep per-user scrape frequency unchanged.
2. **Option 2:** Workers CPU limits make in-worker OCR impossible (10 ms CPU free tier) — so option 2 with OCR *must* stay browser-side or drop OCR for user-typed captcha; the M effort estimate assumes user-typed.
3. **Option 3:** none new — it's already in production-adjacent use; risk is the existing one (rate-limit windows follow the lab's *user* timing, not IP).

### Minimal PoC test plan (<1 h, uses existing worker + token)

1. **(10 min) Re-deploy the throwaway probe as a real `/portal-proxy/*` route worker** — reuse the verified probe code (this session) + add the session-map + Referer/Cookie stamping; attach route `srm.egress-worker-name` pattern `srm.200871.xyz/portal-proxy/*` via `POST /zones/e7e0257dc67334eaea9e52603bd8adbf/workers/routes` (raw-API flow per our skill notes; route-on-existing-proxied-hostname pattern confirmed working for srm-egress). Keep the `x-proxy-token` gate for now (browser sends it in the login POST header set — replace with `srm_psid` cookie in the same change).
2. **(20 min) Static-host the artifacts:** vendor `onnxruntime-web@1.22.0` (wasm build, 10.7 MB) + `common_q8.onnx` (13.6 MB) + charset JSON under the Flask app's `/static` (they're just files; the q8 model ships from the `lyc8503/ddddocr_web` repo or quantize `common.onnx` ourselves with `opt.py` from that repo). Add `wasm-unsafe-eval` to `script-src` in `set_security_headers()`; drop `https://cdn.jsdelivr.net` from script-src while touching it. [17][19][32]
3. **(25 min) Browser console PoC (no app changes):** on `srm.200871.xyz` (login page is public), paste a ~60-line console/extension script: `fetch('/portal-proxy/...youLogin.jsp')` → parse nonce/data-src/honeypot → `fetch('/portal-proxy' + captchaPath)` → data-URL into an `<img>` → ORT OCR → build the full LoginServlet body (dtoken/cptoken/telemetry per existing Python) → POST → check for `HRDSystem` → POST formId 9 → run the JS-ported `parse_attendance` → `console.table` the courses. **Success = attendance rows in console, lab container never touched (watch `docker logs opensrm` stay silent).**
4. **(5 min) Negative controls:** confirm app routes (`/`, `/api/*`) still hit the Flask origin with the route live (pattern specificity + fallthrough, per docs [5]); confirm no CSP console errors for wasm compile.
5. Known-safe cadence from DEPLOY.md applies: ≤1 login attempt per 2–3 min during the PoC; use a throwaway test netid.

**Effort to production from PoC:** M (wire the JS into the PWA's login flow, port remaining 2 parsers with fixture tests, delete `http_scraper.py` + ddddocr from the lab image, decide KV vs in-memory session store — KV only if we want multi-colo stickiness; in-isolate Map is fine for single-colo egress otherwise).

---

### Sources

[1] Mieru-OCR (formerly ddddocr-webjs) — https://github.com/MakotoArai-CN/ddddocr-webjs (redirects to /Mieru-OCR)
[2] lyc8503/ddddocr_web — https://github.com/lyc8503/ddddocr_web
[3] common.onnx (54,088,400 B, md5-matched to pip ddddocr) — https://raw.githubusercontent.com/lyc8503/ddddocr_web/master/common.onnx
[4] common_q8.onnx (13,602,462 B) — https://raw.githubusercontent.com/lyc8503/ddddocr_web/master/common_q8.onnx
[5] CF Workers Routes — https://developers.cloudflare.com/workers/configuration/routing/routes/
[6] CF Worker-as-origin (route intercepts, unmatched → origin) — https://developers.cloudflare.com/cloudflare-for-platforms/cloudflare-for-saas/start/advanced-settings/worker-as-origin/
[7] onnxruntime-web npm — https://npmjs.com/package/onnxruntime-web
[8] Cloudflare IP ranges — https://www.cloudflare.com/ips/
[9] Cloudflare IP reference — https://developers.cloudflare.com/fundamentals/reference/ip-addresses/
[10] Chrome third-party cookie phase-out status — https://developers.chrome.com/docs/privacy-sandbox/third-party-cookie-phase-out/
[11] Mieru-OCR repo — https://github.com/MakotoArai-CN/Mieru-OCR
[12] ddddocr_web demo.html (full ORT-web inference code + charset) — https://raw.githubusercontent.com/lyc8503/ddddocr_web/master/demo.html
[13] kbravh: Tesseract.js on captchas — https://kbravh.dev/cracking-captcha-tesseractjs/
[14] Third-party cookies 2026 status — https://www.thematchbox.inc/resources/blog/third-party-cookies-2026-what-changed
[16] sml2h3/ddddocr — https://github.com/sml2h3/ddddocr
[17] ONNX Runtime Web deploy guide — https://onnxruntime.ai/docs/tutorials/web/deploy.html
[18] 20MB wasm production load-time discussion — https://github.com/microsoft/onnxruntime/discussions/26354
[19] MDN CSP — https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP
[21] CF fundamentals: origins see shared CF IPs; 172.64.0.0/13 egress — https://developers.cloudflare.com/fundamentals/concepts/cloudflare-ip-addresses/
[23] CF Workers routing overview (routes ≠ same-zone fetch target) — https://developers.cloudflare.com/workers/configuration/routing/
[28] F5 ASM DoS Protection (TPS + source-IP profiles) — https://techdocs.f5.com/en-us/bigip-14-1-0/big-ip-asm-implementations-14-1-0/preventing-dos-attacks-on-applications.html
[29] CF Workers fetch() — https://developers.cloudflare.com/workers/runtime-apis/fetch/
[30] Opensignal India June 2025 (mobile latency/speeds) — https://insights.opensignal.com/reports/2025/06/india/mobile-network-experience
[31] Tesseract captcha benchmark (36% on O/0) — https://medium.com/jin-system-architect/tesseract-for-captcha-recognition-not-a-silver-bullet-but-effective-in-the-right-context-113feeb57c70
[32] wasm-unsafe-eval CSP proposal — https://github.com/WebAssembly/content-security-policy/blob/main/proposals/CSP.md
[33] MDN script-src — https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Security-Policy/script-src
[34] Mieru-OCR site (90–98% alnum accuracy; ~50MB model + ~20MB runtime) — https://mieru.qzz.io/
[35] Mieru-OCR ScriptCat listing — https://scriptcat.org/en/script-show-page/4781
[37] MDN crossOriginIsolated — https://developer.mozilla.org/en-US/docs/Web/API/Window/crossOriginIsolated
[38] MDN RegExp — https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/RegExp
[39] MDN Forbidden header names — https://developer.mozilla.org/en-US/docs/Glossary/Forbidden_header_name
[40] CF Workers Headers API — https://developers.cloudflare.com/workers/runtime-apis/headers/
[41] CF community: multiple Set-Cookie from fetch → getAll() — https://community.cloudflare.com/t/after-fetch-only-one-set-cookie-is-recognized-from-response/230600

*Live-verified this session (not URLs — reproducible probes):* model md5 identity; fresh-captcha fetch through worker; Referer 403 matrix (wrong-host/no-referer/portal-referer); worker-set Referer+Cookie accepted by F5 (probe worker `srm-referer-probe`, created + deleted); CSP header on production; CF colo spread (BOS/EWR/SIN) on worker-hosted requests; portal Chennai/AS131473 geolocation; direct-vs-worker TTFB (410 ms vs 690–750 ms).
