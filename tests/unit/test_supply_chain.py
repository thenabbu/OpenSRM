#!/usr/bin/env python3
"""Unit: supply-chain CI surface — pins the image-tag/rollback contract and the
blocking scan workflow. Static file checks, no server, no network.

Guards the two halves of the deploy story:
  1. compose must keep its default render byte-identical (OPENSRM_TAG unset =
     :latest) while allowing an explicit pin to roll the deploy back;
  2. build.yml must tag the image with the VERSION file's value next to
     :latest and the commit sha, and label the image with the same version;
  3. scans.yml must keep all four scans BLOCKING (gitleaks, pip-audit,
     pnpm audit, trivy) with SHA-pinned actions and read-only permissions — a
     silent drop back to report-only would change merge behaviour without a
     review-visible diff, and the accepted-finding allowlist must stay an
     explicit list of named advisories rather than a severity floor.
"""
import re
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[2]
fails = []

def check(name, cond, extra=""):
    if cond:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} {extra}")
        fails.append(name)

def rd(p):
    return (R / p).read_text()

# ── 1. compose: pin-able image, byte-identical default ──────────────────────
compose = rd("docker-compose.yml")
check("compose image line is OPENSRM_TAG-interpolated",
      re.search(r"^    image: ghcr\.io/thenabbu/opensrm:\$\{OPENSRM_TAG:-latest\}$",
                 compose, re.M) is not None)
check("compose rollback doc names the project env file",
      "/docker/opensrm/.env" in compose and "docker compose pull" in compose)
# the interpolating form must still render :latest when the var is unset —
# that equivalence is asserted by the string itself: ${VAR:-latest} is the
# compose-documented "unset -> latest" operator, so pinning the literal here
# is the contract; the rendered-config proof lives in the PR body.
check("compose default stays :latest (the :- operator)",
      ":-latest" in compose)
# test_logging_telemetry's passthrough assertions must survive (regression
# guard against a compose rewrite dropping the env lines it checks)
check("compose LOG_LEVEL default INFO still present",
      "LOG_LEVEL=${LOG_LEVEL:-INFO}" in compose)
check("compose NTFY_ALERT_URL passthrough still present",
      "NTFY_ALERT_URL=${NTFY_ALERT_URL:-}" in compose)

# ── 2. build.yml: VERSION tag + OCI labels ──────────────────────────────────
build = rd(".github/workflows/build.yml")
check("build.yml reads VERSION from the file",
      re.search(r"cat VERSION", build) is not None,
      "the image tag must derive from the VERSION file (single source of truth)")
check("build.yml tags raw VERSION value",
      re.search(r"type=raw,value=\$\{\{ steps\.version\.outputs\.version \}\}", build) is not None)
check("build.yml publishes :latest and :<VERSION> and no sha tag",
      "type=raw,value=latest" in build and "type=sha" not in build,
      "a sha tag makes GHCR name the package version after the commit "
      "(page read 'a9c2598' instead of '2.12.0')")
check(":VERSION is emitted last (GHCR names a version by a tag it carries)",
      build.index("type=raw,value=latest")
      < build.index("type=raw,value=${{ steps.version.outputs.version }}"),
      "tag order decides the name a human reads in the package list")
# The gate and the tag list live in one `meta` job now: two build legs and a
# merge must not each resolve them, or they can disagree about which push is a
# release. The legs therefore read them as needs.meta.*.
check("build.yml labels org.opencontainers.image.version from VERSION",
      re.search(r"org\.opencontainers\.image\.version=\$\{\{ needs\.meta\.outputs\.version \}\}", build) is not None)
check("build.yml labels org.opencontainers.image.revision from github.sha",
      re.search(r"org\.opencontainers\.image\.revision=\$\{\{ github\.sha \}\}", build) is not None)
# The labels block only proves the EXPRESSION is in the workflow. Without this
# step a mislabelled push is green and a deploy cannot say which code runs: the
# artifact is read back and compared to the commit that built it. Keyed on the
# pushed digest, never on :latest, which answers for whatever moved it last.
check("build.yml verifies the pushed image's revision label against this commit",
      re.search(r"docker inspect -f '\{\{index \.Config\.Labels "
                r"\"org\.opencontainers\.image\.revision\"\}\}' \"\$img\"", build) is not None
      and 'steps.build.outputs.digest' in build
      and '[ "$got" = "${{ github.sha }}" ]' in build,
      "label expression present but never checked against the built artifact")
check("the revision check keys on the digest, not the mutable :latest tag",
      'steps.build.outputs.digest' in build and re.search(r"opensrm:latest", build) is None)
# rollback integrity: the version tag must come from the file, not a literal —
# a hardcoded tag would survive a release bump silently
_check_no_literal = not re.search(r"type=raw,value=\d+\.\d+\.\d+", build)
check("no hardcoded version literal in tags", _check_no_literal)
# :VERSION and :latest may only move on a real VERSION bump; re-pushing them on
# every main commit makes the version tag a moving target and destroys the
# rollback point it exists for.
check("version/latest tags are gated on a real VERSION change",
      "released == 'true'" in build,
      "tags must be enable=<VERSION moved>, or :2.11.0 drifts with every commit")
# Multi-arch pushes each leg by DIGEST and `merge` names the tag, so "publishes
# nothing" is expressed differently: an unreleased commit falls back to a
# cache-only build, and the only tag-writing job is skipped outright.
check("an unreleased commit publishes nothing",
      "mode=type=cacheonly" in build
      and "if: needs.meta.outputs.released == 'true'" in build,
      "otherwise every docs commit mints an untagged package version")
# The gate was DEAD for weeks and printed 'moved' on every push: checkout was
# depth-1, so the baseline commit did not exist and the comparison fell through
# to the always-released branch. It then broke the OTHER way: comparing
# HEAD~1:VERSION still skipped a real release when a bump commit is followed by
# another push to main, because the second push's baseline already carries the
# new version. Measured on v2.12.1 - a Release exists, :2.12.1 returns 404,
# :2.12.0 returns 200. Asking the registry is idempotent and repairs a cancelled
# publish, so that is what this pins.
check("VERSION gate asks the registry instead of diffing history",
      "imagetools inspect" in build and "HEAD~1:VERSION" not in build,
      "a history diff misses a bump that is followed by another push to main")
# Provenance + SBOM make the artifact's origin and contents verifiable at
# deploy time instead of trusting a mutable tag.
check("build records provenance", "provenance: mode=max" in build)
check("build records an SBOM", "sbom: true" in build)

# Multi-arch is the reason this file changed: the package was amd64-only, so the
# arm64 oclab VPS could not pull ANY published tag and had to build from source
# on 2 vCPUs. Pin the pairing (platform <-> native runner) and the merge, or a
# later edit can quietly drop one leg and reintroduce the original failure.
check("build.yml builds both architectures on native runners",
      "linux/amd64" in build and "ubuntu-latest" in build
      and "linux/arm64" in build and "ubuntu-24.04-arm" in build,
      "an amd64-only package cannot be pulled on the arm64 VPS")
check("build.yml merges the legs into one manifest list",
      "push-by-digest=true" in build and "imagetools create" in build,
      "two digests, one tag - or the package is single-arch again")
check("the merge job fails when an architecture is missing",
      build.count("missing from") >= 2,
      "a green merge only proves the API accepted it; read the manifest")

# ── 3. scans.yml: report-only surface ───────────────────────────────────────
scans = rd(".github/workflows/scans.yml")
jobs = re.findall(r"^  (\w[\w-]*):", scans.split("jobs:", 1)[1], re.M)
check("scans.yml has the four scan jobs",
      set(jobs) == {"secrets", "deps", "web-deps", "image"}, str(jobs))
for job in jobs:
    block = re.split(rf"^  {job}:\n", scans, flags=re.M)[1]
    block = re.split(r"^  \w", block, flags=re.M)[0]  # cut at the next job key
    # Blocking since 2026-11-05: the baseline was clean, so a finding is now a
    # red check instead of a summary line nobody reads. Re-introducing
    # `continue-on-error` on a scan is a maintainer decision and must be
    # deliberate, which is exactly what this pin makes it.
    check(f"scan job '{job}' blocks the merge (no continue-on-error)",
          "continue-on-error: true" not in block,
          "a scan that cannot fail the run is not a gate (docs/SCANS.md)")
check("scans default permissions read-only",
      re.search(r"^permissions:\n  contents: read$", scans, re.M) is not None)
uses = re.findall(r"uses: (\S+)@([0-9a-f]{40})", scans)
check("every scan action is SHA-pinned", len(uses) >= 4 and all(len(s) == 40 for _, s in uses),
      str([u for u in uses]))
check("gitleaks scans full history (fetch-depth: 0)",
      "fetch-depth: 0" in scans)
check("pip-audit audits the frozen export minus git+ lines",
      "uv export --frozen --no-dev" in scans and "grep -v 'git+'" in scans)
check("trivy filters HIGH,CRITICAL with a fix available",
      "severity: HIGH,CRITICAL" in scans and "ignore-unfixed: true" in scans)
check("trivy fails the job on a fixable CVE (exit-code 1)",
      "exit-code: 1" in scans)
check("pip-audit raises on findings (its exit code is swallowed)",
      "raise SystemExit" in scans)
check("each scan writes a job summary",
      scans.count("GITHUB_STEP_SUMMARY") >= 3)
# uvx resolves the newest release on every run; the lockfile pins it.
check("scans run pip-audit from the locked dev group", "uv run --locked pip-audit" in scans)
check("no uvx in CI or gates.sh (unpinned resolution)",
      "uvx ruff" not in scans and "uvx ruff" not in rd(".github/workflows/lint.yml")
      and "uvx ruff" not in rd("scripts/gates.sh"))

# ── 3b. the web-deps job: audits the lockfile, blocks on a new HIGH/CRITICAL ──
_web = re.split(r"^  web-deps:\n", scans, flags=re.M)[1].split("\n  image:")[0]
check("pnpm audit reads web/pnpm-lock.yaml and never installs",
      "pnpm -C web audit --json" in _web and "pnpm install" not in _web,
      "an install step would run a dependency's postinstall on the runner")
check("pnpm audit fails the job on an unaccepted HIGH/CRITICAL",
      "unaccepted HIGH/CRITICAL" in _web and "sys.exit" in _web,
      "pip-audit's lesson: the tool's own exit code is swallowed by `|| true`")
check("pnpm audit fails when the report is missing",
      "the audit did not run" in _web,
      "an unreachable registry must not read as a clean audit")
check("pnpm audit's accepted set is an explicit GHSA allowlist",
      "ACCEPTED" in _web and "GHSA-fc5q-39xc-vjpf" in _web,
      "acceptance is one named advisory, not a severity floor")
check("pnpm audit runs the same Node pin as the web job",
      "node-version: '22'" in _web and "pnpm@9.15.9" in _web)

# ── 4. docs ─────────────────────────────────────────────────────────────────
scans_doc = rd("docs/SCANS.md")
for tool in ("gitleaks", "pip-audit", "pnpm audit", "trivy"):
    check(f"docs/SCANS.md documents {tool}", tool in scans_doc)
# The doc said "report-only" for weeks while all four jobs blocked, and the pin
# that was supposed to catch it asserted the STALE section instead (it required
# "continue-on-error", which the workflow no longer contains). Pin the claim a
# reader actually acts on.
check("SCANS.md says the scans block, and carries no report-only claim",
      "block the merge" in scans_doc and "report-only" not in scans_doc.lower())
check("SCANS.md records the accepted picomatch advisory",
      "GHSA-fc5q-39xc-vjpf" in scans_doc)
check("SCANS.md reports the blobatar git-dep gap",
      "blobatar" in scans_doc)

print("FAILED:", fails) if fails else print("supply-chain surface: OK")
sys.exit(1 if fails else 0)
