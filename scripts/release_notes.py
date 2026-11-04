#!/usr/bin/env python3
"""Release notes from git history: the body GitHub Releases publishes.

One input (a commit range), one output (markdown). The app no longer carries a
release-notes feed; this script is the only producer of user-visible changelog
text, so `CHANGELOG.md` and every GitHub Release body are the same rendering of
the same commits — they cannot drift.

Grouping is by conventional prefix, because this repo commits that way:

  feat / perf / fix  -> "What changed"   (a student can see or feel it)
  refactor / ci / test / docs / build / style -> "Internal"
  chore(deps) / chore(release) -> dropped (noise: bumps and version commits)
  revert -> "What changed (reverted)" — surfaced, never silently dropped

`chore(release): vX.Y.Z` is the release commit itself; it is excluded because
the version is the Release's own title, not a change inside it.

Usage:
  python3 scripts/release_notes.py --from v2.9.0 --to HEAD
  python3 scripts/release_notes.py --from v2.9.0 --to HEAD --title "v2.10.0"

Exit 0 always for a readable range; exit 2 when the range is unreadable so CI
fails instead of publishing an empty Release.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

#: prefix -> section. First match wins; unlisted prefixes land in Internal.
SECTIONS = {
    "feat": "What changed",
    "fix": "What changed",
    "perf": "What changed",
    "revert": "What changed",
    "refactor": "Internal",
    "ci": "Internal",
    "test": "Internal",
    "tests": "Internal",
    "docs": "Internal",
    "build": "Internal",
    "style": "Internal",
    "chore": "Internal",
}
ORDER = ["What changed", "Internal"]
SUBJECT_RE = re.compile(r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?:\s*(?P<rest>.+)$")
# Untyped subjects are the load-bearing risk: this repo has plenty of bare
# subjects ("rotatable password-encryption key (...)", "SQLite writers fail
# with ..."). Sending them all to "What changed" publishes internals to users,
# so an untyped subject is only visible when it reads like a user outcome.
INTERNAL_HINTS = re.compile(
    r"(?:^|[^a-z])(?:test|tests|dut|ci|gate|gates|lint|ruff|mypy|refactor|rename|"
    r"extract|move|split|bump|pin|pinned|lock|workflow|screenshot|doc|docs|comment|"
    r"dead.code|cleanup|tidy|internal|probe|script|matrix|runner|tmp|debug|"
    r"assert|fixture|mock|coverage|guard|bypass|header|middleware|schema|migration|"
    r"baseline|capture|shots|benchmark|phase|checkpoint|harness|stub|dummy|placeholder)",
    re.I)


def classify(subject: str) -> tuple[str, str] | None:
    """(section, rendered bullet) for one commit subject, or None to drop it."""
    m = SUBJECT_RE.match(subject.strip())
    if not m:
        # Bare subject: visible only when it does not read like tooling work.
        text = subject.strip()
        return ("Internal", text) if INTERNAL_HINTS.search(text) else ("What changed", text)
    kind = m.group("type").lower()
    scope = (m.group("scope") or "").strip()
    rest = m.group("rest").strip()
    # Version bumps and dependency chores are not changes anyone reads about.
    if kind == "chore" and scope in ("release", "deps"):
        return None
    # The release workflow appends to CHANGELOG.md by committing; that commit
    # lands inside the NEXT release's range and must never publish as an entry.
    if kind == "docs" and scope == "changelog":
        return None
    # An unknown prefix is not a conventional type — it is a bare subject that
    # happens to contain a colon ("scope: fetch the real dues ..."). Judge it by
    # its text rather than letting the Internal default swallow a user-facing fix.
    if kind not in SECTIONS:
        text = f"{kind}: {rest}" if not scope else f"{kind}({scope}): {rest}"
        return ("Internal", text) if INTERNAL_HINTS.search(text) else ("What changed", text)
    section = SECTIONS.get(kind, "Internal")
    # A typed feat/fix can still be pure plumbing ("fix(edge): key the guard on
    # X-Forwarded-Host"). Only a subject that reads like a user outcome AND is
    # not tooling-flavoured belongs in the user-facing section.
    if section == "What changed" and INTERNAL_HINTS.search(f"{scope} {rest}"):
        section = "Internal"
    # Only scope-ify prefixes whose scope names a subsystem (feat(scope), fix(scope));
    # chore/test/docs scopes ("ci", "tests", "docs") read as duplicated labels.
    bullet = f"**{scope}**: {rest}" if scope and kind in ("feat", "fix", "perf") else rest
    if m.group("bang"):
        bullet += " *(breaking)*"
    return section, bullet.rstrip(".")


def notes(from_ref: str, to_ref: str, title: str = "", cwd: str = ".") -> str:
    """Render the markdown body for `from_ref..to_ref`. Raises on a bad range."""
    out = subprocess.run(
        ["git", "log", "--no-merges", "--reverse", "--format=%s", f"{from_ref}..{to_ref}"],
        cwd=cwd, capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"bad range {from_ref}..{to_ref}")
    buckets: dict[str, list[str]] = {s: [] for s in ORDER}
    for subject in out.stdout.splitlines():
        got = classify(subject)
        if got is None:
            continue
        section, bullet = got
        if bullet and bullet not in buckets[section]:
            buckets[section].append(bullet)
    lines = []
    if title:
        lines += [f"## {title}", ""]
    wrote = False
    for section in ORDER:
        if not buckets[section]:
            continue
        wrote = True
        lines += [f"### {section}", ""]
        lines += [f"- {b}" for b in buckets[section]]
        lines.append("")
    if not wrote:
        lines += ["_Internal-only release: no user-visible change._", ""]
    return "\n".join(lines).rstrip() + "\n"


def demo() -> None:
    """Self-check: the classifier is the whole logic, so pin its edges."""
    assert classify("feat(sync): refresh stale data") == ("What changed", "**sync**: refresh stale data")
    assert classify("fix: read the payload shape") == ("What changed", "read the payload shape")
    assert classify("feat(auth)!: drop legacy login") == ("What changed", "**auth**: drop legacy login *(breaking)*")
    assert classify("chore(release): v2.10.0") is None, "version bumps are not changes"
    assert classify("chore(deps): bump playwright") is None, "dep bumps are not changes"
    assert classify("refactor(app): extract tables") == ("Internal", "extract tables")
    assert classify("Merge pull request #1 from x")[0] == "What changed"
    assert classify("docs: fix typo") == ("Internal", "fix typo")
    assert classify("chore(ci): bump runner") == ("Internal", "bump runner")
    # the workflow's own CHANGELOG commit must never publish
    assert classify("docs(changelog): v2.10.1") is None
    # unknown prefix = bare subject, judged by text (a real user-facing fix)
    assert classify("scope: fetch the real dues, fix the fees tab (#150)")[0] == "What changed"
    # bare subjects: tooling reads internal, an outcome reads visible
    assert classify("dut_official_tt wrote screenshots to a dev-host-only path")[0] == "Internal"
    assert classify("delete my data — POST /api/account/delete erases every row")[0] == "What changed"
    # typed feat/fix whose body is plumbing still reads internal
    assert classify("fix(edge): key the origin bypass guard on X-Forwarded-Host")[0] == "Internal"
    assert classify("feat(sync): refresh stale portal data on dashboard load")[0] == "What changed"
    print("release_notes: demo OK")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render release notes from a git range.")
    ap.add_argument("--from", dest="src", help="previous tag (e.g. v2.9.5)")
    ap.add_argument("--to", dest="dst", default="HEAD")
    ap.add_argument("--title", default="", help="markdown heading, usually the version")
    ap.add_argument("--out", default="-", help="write to this file instead of stdout")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args(argv)
    if a.demo:
        demo()
        return 0
    if not a.src:
        ap.error("--from is required unless --demo is given")
    try:
        body = notes(a.src, a.dst, a.title)
    except RuntimeError as e:
        print(f"release_notes: {e}", file=sys.stderr)
        return 2
    if a.out == "-":
        sys.stdout.write(body)
    else:
        with open(a.out, "w") as f:
            f.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
