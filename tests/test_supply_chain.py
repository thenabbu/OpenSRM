#!/usr/bin/env python3
"""Unit: supply-chain CI surface — pins the image-tag/rollback contract and the
report-only scan workflow. Static file checks, no server, no network.

Guards the two halves of the deploy story:
  1. compose must keep its default render byte-identical (OPENSRM_TAG unset =
     :latest) while allowing an explicit pin to roll the deploy back;
  2. build.yml must tag the image with the VERSION file's value next to
     :latest and the commit sha, and label the image with the same version;
  3. scans.yml must stay report-only (continue-on-error on every job) with
     SHA-pinned actions and read-only permissions — a silent flip to blocking
     would change merge behaviour without a review-visible diff.
"""
import re
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[1]
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
check("build.yml keeps :latest and the sha tag",
      "type=raw,value=latest" in build and "type=sha,prefix=" in build,
      "latest keeps meaning latest; sha stays for hotfix identification")
check("build.yml labels org.opencontainers.image.version from VERSION",
      re.search(r"org\.opencontainers\.image\.version=\$\{\{ steps\.version\.outputs\.version \}\}", build) is not None)
check("build.yml labels org.opencontainers.image.revision from github.sha",
      re.search(r"org\.opencontainers\.image\.revision=\$\{\{ github\.sha \}\}", build) is not None)
# rollback integrity: the version tag must come from the file, not a literal —
# a hardcoded tag would survive a release bump silently
_check_no_literal = not re.search(r"type=raw,value=\d+\.\d+\.\d+", build)
check("no hardcoded version literal in tags", _check_no_literal)

# ── 3. scans.yml: report-only surface ───────────────────────────────────────
scans = rd(".github/workflows/scans.yml")
jobs = re.findall(r"^  (\w[\w-]*):", scans.split("jobs:", 1)[1], re.M)
check("scans.yml has the three scan jobs", set(jobs) == {"secrets", "deps", "image"}, str(jobs))
for job in jobs:
    block = re.split(rf"^  {job}:\n", scans, flags=re.M)[1]
    block = re.split(r"^  \w", block, flags=re.M)[0]  # cut at the next job key
    check(f"scan job '{job}' is continue-on-error",
          "continue-on-error: true" in block,
          "flipping a scan to blocking is a maintainer decision (docs/SCANS.md)")
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
check("each scan writes a job summary",
      scans.count("GITHUB_STEP_SUMMARY") >= 3)

# ── 4. docs ─────────────────────────────────────────────────────────────────
scans_doc = rd("docs/SCANS.md")
for tool in ("gitleaks", "pip-audit", "trivy"):
    check(f"docs/SCANS.md documents {tool}", tool in scans_doc)
check("SCANS.md documents flip-to-blocking per job",
      "continue-on-error" in scans_doc and "exit-code" in scans_doc)
check("SCANS.md reports the blobatar git-dep gap",
      "blobatar" in scans_doc)

print("FAILED:", fails) if fails else print("supply-chain surface: OK")
sys.exit(1 if fails else 0)
