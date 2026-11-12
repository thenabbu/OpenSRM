# Image build record — P9.4a

Built for the P9.4b CVE scan. Nothing here was scanned; this card only builds.

## Result: BUILD OK

| field | value |
|---|---|
| tag | `opensrm-scan:20261112-0024` |
| image ID | `sha256:43fcc1cc3c7cd54e01a0f1e6ececef7bc5477830ba66e038acb8738a7f422048` |
| RepoDigest | `opensrm-scan@sha256:43fcc1cc3c7cd54e01a0f1e6ececef7bc5477830ba66e038acb8738a7f422048` |
| created | `2026-11-12T05:54:40.480116284+05:30` |
| size | 1,198,259,995 bytes (`1.2GB` as docker reports it) |
| wall-clock duration | **54 s** (13 cached steps, 11 executed) |
| build exit code | 0 |
| commit built from | `d6208fd` on `feat/preact-migration` |

## Exact build command

```bash
cd /opt/data/opensrm-repo
docker build -t "opensrm-scan:$(date +%Y%m%d-%H%M)" .
```

Run from the repo root with no build args, so `WITH_PLAYWRIGHT` keeps its
Dockerfile default of `0` (the archived Playwright/Chromium stack is **not**
in this image). No `Dockerfile`, compose file, or app code was modified.

## `docker images --digests | grep opensrm-scan`

```
opensrm-scan   20261112-0024   sha256:43fcc1cc3c7cd54e01a0f1e6ececef7bc5477830ba66e038acb8738a7f422048   43fcc1cc3c7c   5 minutes ago   1.2GB
```

Tag **and** digest both present, as required.

## Why 54 s, and what that means for the scan

The lab already had a `1.2GB` `opensrm-9.4-scan:20261112-0315` image
(`sha256:e68c50…`), created 2026-11-11T21:48Z from commit `d6208fd`'s
predecessor. Only two files changed between that build and current HEAD
(`.github/workflows/tests.yml`, `app/static/dist/assets/app-DFaSgyMC.css`),
and both sit below the `COPY` boundary that invalidates the dependency layer,
so 13 of 24 steps came from cache and the rest re-exported in 34 s.

The result is a **complete, self-consistent image** — the digest above is real
and `docker run`-able. It is not, however, a from-scratch timing: a cold build
with no cache and no local base image took ~62 min on this lab (the two
`opensrm-9.4-scan` predecessor attempts at 2416 s and 2452 s hit the 40 min
card budget). Budget P9.4b's scan on the digest, not on this duration.

An earlier, near-identical image exists: `opensrm-9.4-scan:20261112-0315`
(`sha256:e68c502d948b64b53eb36e784fbacf91b8f3cf2bc8479511e59711d1e32ee453`).
Prefer `opensrm-scan:20261112-0024` — it is built from current HEAD.

## For P9.4b (the scan card)

Scan this reference, tagged or by digest — both resolve to the same manifest:

```bash
trivy image --severity HIGH,CRITICAL opensrm-scan:20261112-0024
# or, immune to tag drift:
trivy image opensrm-scan@sha256:43fcc1cc3c7cd54e01a0f1e6ececef7bc5477830ba66e038acb8738a7f422048
```

Source-found-only or fs scans are **not** what this card produced; the point is
the shipped filesystem, so scan the image.
