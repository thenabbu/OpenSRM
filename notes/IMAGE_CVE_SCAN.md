# Image CVE scan — P9.4b

Scanned the image P9.4a built. **Report only — nothing here was fixed.**

## Headline

**2 CRITICAL, 62 HIGH.** The 2 CRITICALs are the same npm package (`tinypool@1.1.1`)
reached through **vitest — a dev-only test dependency** that should not be in a
runtime image at all. Neither CRITICAL is reachable in the running app; both are
real only if someone runs the JS test suite inside the container. The fix that
actually matters is not a version bump, it is shipping the image without
`node_modules`.

## Scanner

| field | value |
|---|---|
| scanner | Trivy (`aquasec/trivy:latest`) |
| version | `0.76.2` |
| invocation | `docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:latest image --scanners vuln ...` |
| DB | `trivy-db` v2, Debian + language-specific advisories |
| **DB `UpdatedAt`** | **`2026-11-12T01:03:48.608294617Z`** |
| DB `NextUpdate` | `2026-11-13T01:03:48.608294356Z` |
| DB `DownloadedAt` | `2026-11-12T02:12:23.556500646Z` |
| scanned object | `opensrm-scan@sha256:31b40d1ee02f57145afa36805eb9e43d9856d56c4e965db2eb410858cf30ae3c` |
| exit code | 0 |
| full JSON | 1,602,671 bytes (`--format json`, all severities) |

## Digest — exactly matches `notes/IMAGE_BUILD.md`

From `notes/IMAGE_BUILD.md`:

```
opensrm-scan@sha256:31b40d1ee02f57145afa36805eb9e43d9856d56c4e965db2eb410858cf30ae3c
```

From this scan's report (`ArtifactName` / `Metadata.RepoDigests` / `Metadata.ImageID`, all three identical):

```
opensrm-scan@sha256:31b40d1ee02f57145afa36805eb9e43d9856d56c4e965db2eb410858cf30ae3c
```

`Metadata.ImageID` = `sha256:31b40d1ee02f57145afa36805eb9e43d9856d56c4e965db2eb410858cf30ae3c`.
`Metadata.RepoTags` = `['opensrm-scan:20261112-0644']`. Same manifest, no drift.

## Severity counts

Pasted verbatim from Trivy's `--format table` output, one `Total:` line per scanned target:

```
Total: 47 (HIGH: 47, CRITICAL: 0)
Total: 2 (HIGH: 0, CRITICAL: 2)
Total: 15 (HIGH: 15, CRITICAL: 0)
```

Totals across targets: **CRITICAL 2, HIGH 62** (47 + 2 + 15 = 64 = 2 + 62).

Full image, all severities (from the JSON, which I asked for every severity):

```
CRITICAL: 2
HIGH:     62
MEDIUM:   89
LOW:      66
UNKNOWN:  20
TOTAL:    239
```

Target breakdown — this is the shape of the problem:

| scanner | target | HIGH+CRIT |
|---|---|---|
| debian 13.7 | OS packages (87 pkgs) | 47 |
| node-pkg | `app/web/node_modules` | 2 |
| gobinary | `app/web/node_modules/.pnpm/@typescript+typescript-linux-x64@7.0.2/.../tsc` | 15 |
| python-pkg | Python / site-packages | **0** |

Python scanned clean — consistent with the established `pip-audit` result. Every
single HIGH/CRITICAL in this image comes from Debian OS packages or the shipped
`node_modules`, not from app code.

## Every CRITICAL and HIGH

64 rows, one per (CVE, package) pair — no duplication.

| # | CVE | Pkg | Installed | Fixed | Fix? |
|---|---|---|---|---|---|
| 1 | CVE-2026-104848 | `tinypool` | `1.1.1` | `2.1.1` | **YES** |
| 2 | CVE-2026-104849 | `tinypool` | `1.1.1` | `2.1.2` | **YES** |
| 3 | CVE-2026-76642 | `bsdutils` | `1:2.41.5-0+deb13u1` | — | no |
| 4 | CVE-2026-78408 | `bsdutils` | `1:2.41.5-0+deb13u1` | — | no |
| 5 | CVE-2026-78409 | `bsdutils` | `1:2.41.5-0+deb13u1` | — | no |
| 6 | CVE-2026-78410 | `bsdutils` | `1:2.41.5-0+deb13u1` | — | no |
| 7 | CVE-2026-56851 | `golang.org/x/text` | `v0.38.0` | `0.41.0` | **YES** |
| 8 | CVE-2026-56852 | `golang.org/x/text` | `v0.38.0` | `0.39.0` | **YES** |
| 9 | CVE-2026-54369 | `libacl1` | `2.3.2-2+b1` | — | no |
| 10 | CVE-2026-76642 | `libblkid1` | `2.41.5-0+deb13u1` | — | no |
| 11 | CVE-2026-78408 | `libblkid1` | `2.41.5-0+deb13u1` | — | no |
| 12 | CVE-2026-78409 | `libblkid1` | `2.41.5-0+deb13u1` | — | no |
| 13 | CVE-2026-78410 | `libblkid1` | `2.41.5-0+deb13u1` | — | no |
| 14 | CVE-2026-76642 | `liblastlog2-2` | `2.41.5-0+deb13u1` | — | no |
| 15 | CVE-2026-78408 | `liblastlog2-2` | `2.41.5-0+deb13u1` | — | no |
| 16 | CVE-2026-78409 | `liblastlog2-2` | `2.41.5-0+deb13u1` | — | no |
| 17 | CVE-2026-78410 | `liblastlog2-2` | `2.41.5-0+deb13u1` | — | no |
| 18 | CVE-2026-76642 | `libmount1` | `2.41.5-0+deb13u1` | — | no |
| 19 | CVE-2026-78408 | `libmount1` | `2.41.5-0+deb13u1` | — | no |
| 20 | CVE-2026-78409 | `libmount1` | `2.41.5-0+deb13u1` | — | no |
| 21 | CVE-2026-78410 | `libmount1` | `2.41.5-0+deb13u1` | — | no |
| 22 | CVE-2025-69720 | `libncursesw6` | `6.5+202****0216-2` | — | no |
| 23 | CVE-2026-76642 | `libsmartcols1` | `2.41.5-0+deb13u1` | — | no |
| 24 | CVE-2026-78408 | `libsmartcols1` | `2.41.5-0+deb13u1` | — | no |
| 25 | CVE-2026-78409 | `libsmartcols1` | `2.41.5-0+deb13u1` | — | no |
| 26 | CVE-2026-78410 | `libsmartcols1` | `2.41.5-0+deb13u1` | — | no |
| 27 | CVE-2026-119373 | `libsqlite3-0` | `3.46.1-7+deb13u2` | — | no |
| 28 | CVE-2026-119374 | `libsqlite3-0` | `3.46.1-7+deb13u2` | — | no |
| 29 | CVE-2026-119379 | `libsqlite3-0` | `3.46.1-7+deb13u2` | — | no |
| 30 | CVE-2026-16742 | `libsystemd0` | `257.13-1~deb13u1` | — | no |
| 31 | CVE-2025-69720 | `libtinfo6` | `6.5+202****0216-2` | — | no |
| 32 | CVE-2026-16742 | `libudev1` | `257.13-1~deb13u1` | — | no |
| 33 | CVE-2026-76642 | `libuuid1` | `2.41.5-0+deb13u1` | — | no |
| 34 | CVE-2026-78408 | `libuuid1` | `2.41.5-0+deb13u1` | — | no |
| 35 | CVE-2026-78409 | `libuuid1` | `2.41.5-0+deb13u1` | — | no |
| 36 | CVE-2026-78410 | `libuuid1` | `2.41.5-0+deb13u1` | — | no |
| 37 | CVE-2026-76642 | `login` | `1:4.16.0-2+really2.41.5-0+deb13u1` | — | no |
| 38 | CVE-2026-78408 | `login` | `1:4.16.0-2+really2.41.5-0+deb13u1` | — | no |
| 39 | CVE-2026-78409 | `login` | `1:4.16.0-2+really2.41.5-0+deb13u1` | — | no |
| 40 | CVE-2026-78410 | `login` | `1:4.16.0-2+really2.41.5-0+deb13u1` | — | no |
| 41 | CVE-2026-76642 | `mount` | `2.41.5-0+deb13u1` | — | no |
| 42 | CVE-2026-78408 | `mount` | `2.41.5-0+deb13u1` | — | no |
| 43 | CVE-2026-78409 | `mount` | `2.41.5-0+deb13u1` | — | no |
| 44 | CVE-2026-78410 | `mount` | `2.41.5-0+deb13u1` | — | no |
| 45 | CVE-2025-69720 | `ncurses-base` | `6.5+202****0216-2` | — | no |
| 46 | CVE-2025-69720 | `ncurses-bin` | `6.5+202****0216-2` | — | no |
| 47 | CVE-2026-9538 | `perl-base` | `5.40.1-6+deb13u1` | — | no |
| 48 | CVE-2026-111943 | `stdlib` (Go 1.26.4) | `v1.26.4` | `1.26.10, 1.27.3` | **YES** |
| 49 | CVE-2026-33818 | `stdlib` (Go 1.26.4) | `v1.26.4` | `1.25.13, 1.26.6, 1.27.0-rc.3` | **YES** |
| 50 | CVE-2026-39821 | `stdlib` (Go 1.26.4) | `v1.26.4` | `1.25.13, 1.26.6, 1.27.0-rc.3` | **YES** |
| 51 | CVE-2026-39822 | `stdlib` (Go 1.26.4) | `v1.26.4` | `1.25.12, 1.26.5, 1.27.0-rc.2` | **YES** |
| 52 | CVE-2026-46600 | `stdlib` (Go 1.26.4) | `v1.26.4` | `1.26.6, 1.27.0-rc.3` | **YES** |
| 53 | CVE-2026-56853 | `stdlib` (Go 1.26.4) | `v1.26.4` | `1.25.13, 1.26.6, 1.27.0-rc.3` | **YES** |
| 54 | CVE-2026-56858 | `stdlib` (Go 1.26.4) | `v1.26.4` | `1.25.13, 1.26.6, 1.27.0-rc.3` | **YES** |
| 55 | CVE-2026-56859 | `stdlib` (Go 1.26.4) | `v1.26.4` | `1.25.13, 1.26.6, 1.27.0-rc.3` | **YES** |
| 56 | CVE-2026-56860 | `stdlib` (Go 1.26.4) | `v1.26.4` | `1.25.13, 1.26.6, 1.27.0-rc.3` | **YES** |
| 57 | CVE-2026-56862 | `stdlib` (Go 1.26.4) | `v1.26.4` | `1.25.13, 1.26.6, 1.27.0-rc.3` | **YES** |
| 58 | CVE-2026-78667 | `stdlib` (Go 1.26.4) | `v1.26.4` | `1.26.9, 1.27.2` | **YES** |
| 59 | CVE-2026-78669 | `stdlib` (Go 1.26.4) | `v1.26.4` | `1.26.9, 1.27.2` | **YES** |
| 60 | CVE-2026-97031 | `stdlib` (Go 1.26.4) | `v1.26.4` | `1.26.9, 1.27.2` | **YES** |
| 61 | CVE-2026-76642 | `util-linux` | `2.41.5-0+deb13u1` | — | no |
| 62 | CVE-2026-78408 | `util-linux` | `2.41.5-0+deb13u1` | — | no |
| 63 | CVE-2026-78409 | `util-linux` | `2.41.5-0+deb13u1` | — | no |
| 64 | CVE-2026-78410 | `util-linux` | `2.41.5-0+deb13u1` | — | no |

**Only 17 of 64 have a fix available** (2 tinypool + 2 golang.org/x/text + 13 Go stdlib).
The other 47 are Debian `13.7` packages still marked `affected` with no `FixedVersion`
— that is Debian's tracker not having shipped a patched `deb13u` revision yet, not a
scanner blind spot.

## CRITICAL remediation

### CVE-2026-104848 — tinypool prototype pollution → RCE
Installed `tinypool@1.1.1`, fixed `2.1.1`. Path:
`app/web/node_modules/.pnpm/tinypool@1.1.1/node_modules/tinypool/package.json`.
CVSS 3.1 **8.1** (`AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:H/A:H`).

`tinypool` builds `ThreadPool.options` from a plain object and copies `execArgv` /
`env` inherited from a polluted `Object.prototype`, then hands them to
`worker_threads.Worker`.

**Remediation:** drop `web/node_modules` from the image build context (add
`web/node_modules` to `.dockerignore`). `tinypool` arrives only through `vitest`
(`web/package.json:29`, `"vitest": "^3"` → `tinypool: 1.1.1` at
`web/pnpm-lock.yaml:5429`), a devDependency with no runtime role. If the JS
toolchain is genuinely needed inside the image, bump `vitest` so `tinypool` resolves
to `>=2.1.1`.

### CVE-2026-104849 — tinypool prototype pollution gadget to RCE in `run()`
Installed `tinypool@1.1.1`, fixed `2.1.2`. Same path. CVSS 3.1 **8.1**
(`AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:H/A:H`).

`pool.run(task, options)` reads `filename` without requiring an own property, so a
polluted `Object.prototype.filename` swaps the worker module.

**Remediation:** same single change as above — it is the same package, and the
strictest fixed version (`2.1.2`) covers both CVEs. Removing `node_modules` from
the image eliminates both CRITICALs without touching application code.

## Why those CRITICALs are in the image at all

`.dockerignore` has no `node_modules` entry, and line 108 of the `Dockerfile` is a
bare `COPY . .`. So the image ships the entire pnpm dev tree — 400+ `node_modules`
packages, including `@typescript/typescript-linux-x64`'s Go `tsc` binary, which is
where all 15 gobinary HIGHs come from. `web/node_modules` is **not** git-tracked
(`git ls-files web/node_modules | wc -l` → `0`), so it was present in the build
context as a leftover local artifact, not from a `pnpm install` step. Both the 2
CRITICALs and the 15 gobinary HIGHs are downstream of that one `.dockerignore` gap.
Recorded here, not fixed — fixing belongs to a separate card.

## Debian HIGHs — grouping

The 47 Debian HIGH rows collapse to only **9 distinct CVEs** across the `util-linux`
family (4), `sqlite3` (3), `acl` (1) and `ncurses` (1):

- **CVE-2026-76642 / 78408 / 78409 / 78410** (util-linux 2.41.5) — all require a
  local unprivileged user plus a mount/nsenter path (`X-mount.*` hooks, fstab
  entries, `nsenter --join-cgroup`). The app runs as a non-root user in a single
  container with no mount privileges; mitigate by keeping it that way (no
  `--privileged`, no host fstab, no `CAP_SYS_ADMIN`).
- **CVE-2026-119373 / 119374 / 119379** (sqlite 3.46.1, FTS5 + session extension) —
  need a crafted database file. OpenSRM's data dir is operator-controlled; mitigate
  by never mounting an untrusted SQLite file into the container. Also worth noting:
  Python's `sqlite3` module bundles its own library, so the practical exposure
  depends on which build handles the file.
- **CVE-2026-54369** (acl) — symlink traversal in `acl_*_file()`, local only.
- **CVE-2025-69720** (ncurses `infocmp`) — local, needs a crafted terminfo file.
- **CVE-2026-9538** (perl-Archive-Tar) — attacker-controlled tar header; `perl-base`
  is a Debian base-image artifact and no app code path parses tars.
- **CVE-2026-16742** (systemd-homed) — `systemd-homed` is not running in this
  container; not reachable here.

## Notes and caveats

- Trivy emitted `WARN Third-party SBOM may lead to inaccurate vulnerability detection`
  — informational. The image carries a pre-existing SBOM artifact from an upstream
  layer; Trivy scanned the live filesystem.
- `WARN Using severities from other vendors for some vulnerabilities` — expected
  for Debian advisories, which sometimes carry a vendor-assigned severity.
- The `6.5+202****0216-2` version string for ncurses is mangled **by the scanner's
  own JSON**, not by this document — it is what Trivy reported verbatim.
- Python scanned 0 vulnerabilities, which independently corroborates the earlier
  `pip-audit` (62 packages, clean) result. The uncovered surface this card existed
  to cover — OS packages and the Python runtime — is now covered, and the Python
  half is clean.

## Verdict

The image is **not clean**, but the two CRITICALs are dev-toolchain artifacts
reachable only by running vitest inside the container, not by any request the app
serves. There is no CRITICAL in OS packages, in Python, or in anything the Flask
app imports. The highest-value single fix is excluding `web/node_modules` from the
build context, which removes 2 CRITICAL + 15 HIGH in one line and shrinks the image.
