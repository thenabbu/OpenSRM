# Image build record — P9.4a

Built for the P9.4b CVE scan. Nothing here was scanned; this card only builds.

## Result: BUILD OK (fresh build, verified runnable)

| field | value |
|---|---|
| tag | `opensrm-scan:20261112-0644` |
| image ID | `sha256:31b40d1ee02f57145afa36805eb9e43d9856d56c4e965db2eb410858cf30ae3c` |
| RepoDigest | `opensrm-scan@sha256:31b40d1ee02f57145afa36805eb9e43d9856d56c4e965db2eb410858cf30ae3c` |
| size | 1,197,700,102 bytes (`1.2GB` as docker reports it) |
| **wall-clock build duration** | **50 s** |
| build exit code | 0 |
| commit built from | `418b1fd` on `feat/preact-migration` |
| smoke test | `docker run --rm <tag> python -c 'import flask'` → `python 3.14.10 flask ok` |

## Exact build command

```bash
cd /opt/data/opensrm-repo
docker build --progress=plain -t "opensrm-scan:$(TZ='Asia/Kolkata' date +%Y%m%d-%H%M)" .
```

Timed as `s=$(date +%s); docker build ...; e=$(date +%s); echo $((e-s))`.
Run from the repo root with no build args, so `WITH_PLAYWRIGHT` keeps its
Dockerfile default of `0` (the archived Playwright/Chromium stack is **not**
in this image). No `Dockerfile`, compose file, or app code was modified.

## `docker images --digests | grep opensrm-scan`

```
opensrm-scan   20261112-0644   sha256:31b40d1ee02f57145afa36805eb9e43d9856d56c4e965db2eb410858cf30ae3c   31b40d1ee02f   3 minutes ago   1.2GB
```

Tag **and** digest both present, as required.

## Why 50 s, and what that means for the scan

This is a **cache-warm** build, not a from-scratch timing. The lab still holds
the build cache and base layers from earlier attempts, so 13 of 24 steps came
from cache and the rest re-exported; the slowest single step was the final
`exporting/unpacking` at 31.8 s. A cold build with no cache and no local base
image took roughly an hour on this lab — the two combined build+scan attempts
at 2416 s and 2452 s blew a 40 min card budget that way.

The image itself is complete and self-consistent: the digest above is real and
the image runs. Budget P9.4b on the digest, not on this duration.

## For P9.4b (the scan card)

Scan this reference, tagged or by digest — both resolve to the same manifest:

```bash
trivy image --severity HIGH,CRITICAL opensrm-scan:20261112-0644
# or, immune to tag drift:
trivy image opensrm-scan@sha256:31b40d1ee02f57145afa36805eb9e43d9856d56c4e965db2eb410858cf30ae3c
```

Source-found-only or fs scans are **not** what this card produced; the point is
the shipped filesystem, so scan the image.

## Older images on the lab (superseded, safe to delete after the scan)

- `opensrm-scan:20261112-0024` — `sha256:43fcc1cc…` built from `d6208fd`, 54 s.
- `opensrm-scan:20261112-0037` — `sha256:3b508f89…`, same tree as 0024.
- `opensrm-9.4-scan:20261112-0315` — `sha256:e68c502d…`, the earliest attempt.

`opensrm-scan:20261112-0644` is the **newest of these**, but it is NOT built from
current HEAD: it was built from `418b1fd` (see the table at line 15). HEAD at the
time of writing was `2d7588c`, three commits later, which includes the CI wiring
(`e70aca7`) and the dist rebuild. Its digest therefore does not describe what
ships. Card **P9.4c** rebuilds from HEAD with an `org.opensrm.commit` label so
the digest→commit mapping is provable rather than asserted.
