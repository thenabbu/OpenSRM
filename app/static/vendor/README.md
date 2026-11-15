Vendored library: idiomorph
===========================

- Package: idiomorph (https://github.com/bigsnubs/idiomorph)
- Version: 0.8.0 (npm tarball idiomorph-0.8.0.tgz)
- File: dist/idiomorph.min.js, copied byte-for-byte, unmodified
- sha256 of the vendored file:
    4cbd535caf7663a51eda9bce6595371c384fc430d54b8d414e29a61167f19f96
- License: IDIOMORPH-LICENSE next to this file (sha256 of the upstream
  LICENSE as shipped in the tarball:
    d3d2456f76414f2456104660ebd65aff1c04cd7966b942bdabd63f3cdb316a38)
- Why vendored: in-place DOM morphing for the soft-refresh flow
  (DESIGN.md 10.16 rule 3 — no full-page reloads for data updates).
  Same-origin, no CDN, version- and checksum-pinned.

To upgrade: download the new tarball from registry.npmjs.org, copy
dist/idiomorph.min.js here, update this file's version + sha256, bump
CACHE_NAME in ../sw.js (static file changed).

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
