# Supply-chain scans (report-only)

`.github/workflows/scans.yml` runs three read-only scans on every PR to `main`
and every push to `main`. **All three are `continue-on-error: true`** — a
finding lands in the job summary and as a PR annotation, never as a red check.
This is deliberate: scans land green-first so a baseline can be observed, and
the maintainer flips the ones worth gating on (see below).

| Job | Tool | Scope | What a finding looks like |
|-----|------|-------|---------------------------|
| `secrets` | [gitleaks](https://github.com/gitleaks/gitleaks) (via gitleaks-action v2) | full git history (not just the diff) | a leaked token/key in any commit |
| `deps` | [pip-audit](https://github.com/pypa/pip-audit) | the locked python dependency set (`uv export --frozen --no-dev`) | a CVE with a fix in the PyPI advisory DB |
| `image` | [trivy](https://github.com/aquasecurity/trivy) (via trivy-action) | the locally built Docker image, **HIGH/CRITICAL with a fix available** | an OS/package CVE in the runtime image |

## What each scan deliberately does NOT cover

- `deps` drops the one `git+` line in the export (`blobatar`). pip cannot
  resolve a git URL for hash verification, and the dependency is
  **commit-pinned** (`rev = 7fb1eed2…` in `pyproject.toml` + `uv.lock`,
  enforced by `tests/verify76.py` M22), so it is not a moving target: any
  change to what it resolves to shows up as a lock diff in review. This is a
  known supply-chain gap — a git dependency is only as trustworthy as the repo
  that hosts it — and it is reported here rather than "fixed", because the
  alternatives (vendoring the package, or hosting a wheel) are structural
  decisions for the maintainer.
- `image` uses `--ignore-unfixed`: CVEs with no available fix are listed by
  the tool but do not fire the summary; flip that flag off to see them.
- `secrets` covers history, not *live* credential hygiene (rotation is the
  response to a finding there; the scan only tells you one exists).

## Flipping a scan to blocking

Each job is one `continue-on-error: true` line away from gating the merge:

1. **`secrets`** — delete the `continue-on-error: true` line. gitleaks then
   fails the check on any leak, and the branch protection "Scans / gitleaks"
   entry (add it under Settings → Branches → Require status checks) blocks the
   merge. Also set a `GITLEAKS_LICENSE` secret if you enable organization-wide
   scanning mode; for plain public-repo scanning the `GITHUB_TOKEN` is enough.
2. **`deps`** — delete `continue-on-error: true` AND change the audit step to
   `--format markdown --strict` (or just remove the `|| true` on the first
   invocation). pip-audit exits non-zero on any vulnerability found.
3. **`image`** — delete `continue-on-error: true` AND set `exit-code: 1` in the
   trivy step. The step already filters to HIGH/CRITICAL with
   `ignore-unfixed: true`, so blocking means: any *fixable* HIGH/CRITICAL CVE
   in the shipped image blocks the merge.

Each of the three then needs its check name added to the repo's required
status checks to actually block a merge.
