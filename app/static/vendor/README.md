Vendored library: axe-core
==========================
File:   axe.min.js
Version: 4.10.2 (from https://unpkg.com/axe-core@4.10.2/axe.min.js)
Size:   553,290 bytes
sha256: b511cd9dec01c76f... (verify with `sha256sum app/static/vendor/axe.min.js`)

Why vendored and not loaded from a CDN: the app's CSP is `script-src 'self'`
(app/app.py:641). A CDN script would be blocked in a real browser, and an
accessibility audit that only works when you disable CSP is testing a different
app than the one users get.

Used by: tests/e2e/a11y.py (plan unit 9.3). Injected via add_script_tag from
this local file, never fetched at runtime by the app itself — it ships in the
repo so the audit runs on the lab with no node install.

To upgrade: download the new version, replace the file, update the version and
sha256 above, re-run `python3 tests/e2e/a11y.py <base> <token>`.
