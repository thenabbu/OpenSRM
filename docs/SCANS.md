# Supply-chain scans

`.github/workflows/scans.yml` runs four read-only scans on every PR to `main`
and every push to `main`. **All four block the merge.** A finding fails the
check and appears in the job summary, so a red `Scans / …` entry always names
the advisory that caused it.

| Job | Tool | Scope | What a finding looks like |
|-----|------|-------|---------------------------|
| `secrets` | [gitleaks](https://github.com/gitleaks/gitleaks) (via gitleaks-action v3) | full git history (not just the diff) | a leaked token or key in any commit |
| `deps` | [pip-audit](https://github.com/pypa/pip-audit) | the locked python dependency set (`uv export --frozen --no-dev`) | any known vulnerability in a pinned python package |
| `web-deps` | [pnpm audit](https://pnpm.io/cli/audit) | `web/pnpm-lock.yaml` — the browser bundle plus its build toolchain | a HIGH/CRITICAL advisory, unless it is in the accepted set |
| `image` | [trivy](https://github.com/aquasecurity/trivy) (via trivy-action) | the locally built Docker image, **HIGH/CRITICAL with a fix available** | an OS or package CVE in the runtime image |

`web-deps` does not run `pnpm install`: the audit reads the lockfile, so no
dependency's postinstall script ever runs on a runner. It uses the same Node 22
and pnpm 9.15.9 pin as the `web` job in `tests.yml`; two pins that disagree
would audit a resolution the build never produces.

## Accepted findings

An accepted finding is listed by its GHSA id in the `ACCEPTED` set inside the
`web-deps` job, with the reason in `notes/DECISION-w8.2-supply-chain.md`.
Acceptance is never a severity floor: a new advisory is red on arrival, and the
job prints a reminder when an accepted id stops being reported so the entry can
be deleted.

Current acceptances:

- `GHSA-fc5q-39xc-vjpf` — picomatch ReDoS. The registry's newest release
  (4.0.7) is itself the vulnerable version, so no upgrade exists. The package is
  reached only by vite's glob matcher while building `web/`; it is not in the
  image and not in the browser bundle.

## What each scan deliberately does NOT cover

- `deps` drops the one `git+` line in the export (`blobatar`). pip cannot
  resolve a git URL for hash verification, and the dependency is
  **commit-pinned** (`rev = 7fb1eed2…` in `pyproject.toml` + `uv.lock`,
  enforced by `tests/unit/test_audit_findings.py` M22), so it is not a moving
  target: any change to what it resolves to shows up as a lock diff in review.
  This is a known supply-chain gap — a git dependency is only as trustworthy as
  the repo that hosts it — and it is reported here rather than "fixed", because
  the alternatives (vendoring the package, or hosting a wheel) are structural
  decisions for the maintainer.
- `image` uses `--ignore-unfixed`: CVEs with no available fix are listed by the
  tool but do not fail the job.
- `secrets` covers history, not *live* credential hygiene (rotation is the
  response to a finding there; the scan only tells you one exists).
- None of the four scans the running deployment. The image's
  `org.opencontainers.image.revision` label ties a running container to the
  commit it was built from (see `notes/IMAGE_BUILD.md`), and that identity is
  what a deploy check reads — not a scan.

## Changing the policy

Loosening a scan (accepted set, `--ignore-unfixed`, `exit-code: 0`, a
`continue-on-error` guard) is a maintainer decision, not a fix. Say why in the
PR body, update `notes/DECISION-*.md`, and update the matching pin in
`tests/unit/test_supply_chain.py` in the same commit — that test exists so the
change is review-visible.
