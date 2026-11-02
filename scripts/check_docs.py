#!/usr/bin/env python3
"""Doc-consistency gate: the repo's own docs must not contradict the repo.

Every check here corresponds to a claim that went stale at least once
(AGENTS.md said SW cache v37 while sw.js said v40; the unit matrix was
25% duplicates of itself; a suite sat on disk that CI never ran).

Each check prints PASS/FAIL with the derived value, so a failure tells you
what the true value is. Derive, never hardcode: the doc is compared against
the CODE, not against a literal in this file.

Run: .venv/bin/python scripts/check_docs.py
Exit: 0 all pass, 1 any fail.
"""
import pathlib
import re
import sys

R = pathlib.Path(__file__).resolve().parents[1]


def rd(p):
    return (R / p).read_text()


results = []


def chk(cid, desc, ok, ev=""):
    results.append((cid, desc, bool(ok), ev))


# D1 — AGENTS.md's SW cache name equals the one in sw.js.
# The doc quotes a literal; the code derives it. Anything else is a stale quote.
_sw = re.search(r"CACHE_NAME\s*=\s*['\"]([^'\"]+)['\"]", rd("app/static/sw.js"))
_ag = rd("AGENTS.md")
_ag_sw = re.search(r"current value (opensrm-v\d+)", _ag)
chk("D1", "AGENTS.md SW cache name == sw.js CACHE_NAME",
    _sw and _ag_sw and _sw.group(1) == _ag_sw.group(1),
    f"sw.js={_sw.group(1) if _sw else '?'} AGENTS.md={_ag_sw.group(1) if _ag_sw else '?'}")

# D2 — every unit suite CI runs is listed in AGENTS.md's matrix as [unit],
# and every [unit] row in AGENTS.md is a suite CI runs. Set equality both ways.
_yml = rd(".github/workflows/tests.yml")
_unit_block = _yml.split("\n  docker:")[0]
_ci = set(re.findall(r"tests/unit/(test_\w+)\.py", _unit_block))
_doc = set(re.findall(r"tests/unit/(test_\w+)\.py[^\n]*#\s*\[unit\]", _ag))
chk("D2", "AGENTS.md [unit] rows == suites CI runs (set equality)",
    _ci == _doc,
    f"only-CI={sorted(_ci - _doc)} only-doc={sorted(_doc - _ci)}")

# D3 — no unit suite sits on disk unrun by CI. A suite nobody runs is a
# gate that was never armed, which reads as coverage and is not.
_disk = {p.stem for p in (R / "tests/unit").glob("test_*.py")}
chk("D3", "every tests/unit/test_*.py is run by tests.yml",
    _disk <= _ci,
    f"unrun={sorted(_disk - _ci)}")

# D4 — no suite is listed in AGENTS.md twice under [unit] (the matrix was
# 45 rows for 42 suites; duplicates hide a missing entry).
_rows = re.findall(r"tests/unit/(test_\w+)\.py[^\n]*#\s*\[unit\]", _ag)
_dupes = sorted({r for r in _rows if _rows.count(r) > 1})
chk("D4", "AGENTS.md lists each [unit] suite once", not _dupes, f"dupes={_dupes}")

# D5 — VERSION == pyproject == uv.lock (the trio). Already pinned by
# test_audit_findings M23; restated here because AGENTS.md states the rule
# and a doc gate should fail on the same input.
_ver = rd("VERSION").strip()
_py = re.search(r'^version\s*=\s*"([^"]+)"', rd("pyproject.toml"), re.M)
_uv = re.search(r'^name = "opensrm"\nversion = "([^"]+)"', rd("uv.lock"), re.M)
chk("D5", "VERSION == pyproject.toml == uv.lock",
    _py and _uv and _ver == _py.group(1) == _uv.group(1),
    f"VERSION={_ver} pyproject={_py.group(1) if _py else '?'} uv.lock={_uv.group(1) if _uv else '?'}")

# D6 — every relative link/image in the markdown docs resolves on disk.
# A doc pointing at a deleted file is a claim to a reader that the thing exists.
_broken = []
for md in ["AGENTS.md", "README.md", "CONTRIBUTING.md", "SECURITY.md"]:
    p = R / md
    if not p.exists():
        continue
    for m in re.finditer(r"!?\[[^\]]*\]\(([^)#:]+)\)", p.read_text()):
        tgt = m.group(1).strip()
        if tgt.startswith(("http", "mailto", "#")):
            continue
        if not (R / tgt).exists() and not (p.parent / tgt).exists():
            _broken.append(f"{md}->{tgt}")
chk("D6", "markdown doc links resolve", not _broken, f"broken={_broken[:6]}")

# D7 — the migration count in AGENTS.md matches the registry. Counted by the
# decorator, not by a remembered number.
_mig_src = rd("app/migrations.py")
# ignore the usage example in the module docstring
_doc_end = _mig_src.find('"""', _mig_src.find('"""') + 3)
_versions = [int(v) for v in re.findall(r"@migration\(version=(\d+)", _mig_src[_doc_end:])]
_ag_mig = re.search(r"versioned schema \((\d+) migrations → v(\d+)\)", _ag)
chk("D7", "AGENTS.md migration count == registry",
    _ag_mig and int(_ag_mig.group(1)) == len(_versions) and int(_ag_mig.group(2)) == max(_versions),
    f"registry={len(_versions)} maxv={max(_versions)} doc={_ag_mig.groups() if _ag_mig else '?'}")

fails = [r for r in results if not r[2]]
for cid, desc, ok, ev in results:
    print(f"{cid:5} {'PASS' if ok else 'FAIL':7} {desc}")
    if not ok and ev:
        print(f"      {ev}")
print(f"\nTOTAL: {len(results)} checks | PASS {len(results) - len(fails)} | FAIL {len(fails)}")
if fails:
    print("FAILED:", ", ".join(r[0] for r in fails))
sys.exit(1 if fails else 0)
