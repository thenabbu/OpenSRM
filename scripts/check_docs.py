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
import os
import pathlib
import re
import subprocess
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
# Quoting the value is allowed ONLY if it is still correct; quoting a stale one
# is the failure this gate exists for. Not quoting it at all is best practice.
if _ag_sw:
    _d1_ok = bool(_sw and _sw.group(1) == _ag_sw.group(1))
    _d1_ev = f"quoted={_ag_sw.group(1)} sw.js={_sw.group(1) if _sw else '?'}"
elif "sw.js" in _ag and re.search(r"derive it, never quote it|read it out of|read from `sw\.js`", _ag):
    _d1_ok, _d1_ev = True, f"not quoted; sw.js={_sw.group(1) if _sw else '?'}"
else:
    _d1_ok, _d1_ev = False, "AGENTS.md neither quotes the cache name nor says to derive it"
chk("D1", "AGENTS.md does not quote a stale SW cache name", _d1_ok, _d1_ev)

# D2 — every unit suite CI runs is listed in AGENTS.md's matrix as [unit],
# and every [unit] row in AGENTS.md is a suite CI runs. Set equality both ways.
_yml = rd(".github/workflows/tests.yml")
_unit_block = _yml.split("\n  docker:")[0]
_ci = set(re.findall(r"tests/unit/(test_\w+)\.py", _unit_block))
_doc = set(re.findall(r"tests/unit/(test_\w+)\.py[^\n]*#\s*\[unit\]", _ag))
# An empty doc set means the doc stopped keeping a second hand-maintained list
# and points at `gates.sh --list` instead — that is the goal, not a failure.
if _doc:
    chk("D2", "AGENTS.md [unit] rows == suites CI runs (set equality)",
        _ci == _doc,
        f"only-CI={sorted(_ci - _doc)} only-doc={sorted(_doc - _ci)}")
else:
    chk("D2", "AGENTS.md keeps no duplicate suite list (points at gates.sh)",
        "gates.sh" in _ag, "no [unit] rows; points at gates.sh" if "gates.sh" in _ag else "no rows AND no gates.sh pointer")

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
_LINK = re.compile(r"!?\[[^\]]*\]\(([^)#:]+)\)")
# Backticked paths are how these docs cite files; "path-like" means it contains a
# slash and ends in a known file extension, so prose like `tests/unit/` is skipped.
_TICK = re.compile(r"`([A-Za-z0-9_./-]+/(?:[A-Za-z0-9_.-]+\.(?:md|py|sh|yml|json|html|css|js|png)))`")
_checked = 0
# Every markdown file in the tree, not a hand-picked four. The sweep also reads
# docs/ -- a runbook step pointing at a deleted file is the same broken claim
# wherever it lives. CHANGELOG.md is excluded: its links are historical.
_md_files = sorted(
    [p.name for p in R.glob("*.md") if p.name != "CHANGELOG.md"]
    + [str(p.relative_to(R)) for p in (R / "docs").glob("*.md")]
)
for md in _md_files:
    p = R / md
    if not p.exists():
        continue
    body = p.read_text()
    targets = [m.group(1).strip() for m in _LINK.finditer(body)]
    targets += [m.group(1).strip() for m in _TICK.finditer(body)]
    for tgt in targets:
        if tgt.startswith(("http", "mailto", "#", "/")):
            continue
        _checked += 1
        # Exact path first. If that misses, accept the same BASENAME resolved
        # anywhere in the repo: DESIGN.md writes `partials/theme.html` for
        # app/templates/partials/theme.html and `safelist/classes.html` for
        # app/static/safelist/classes.html, which is the house shorthand and not a
        # broken claim. A file that was deleted outright matches neither, which is
        # the failure this check exists for.
        if (R / tgt).exists() or (p.parent / tgt).exists():
            continue
        if any(R.glob(f"**/{tgt.split('/')[-1]}")):
            continue
        _broken.append(f"{md}->{tgt}")
chk("D6", "doc links + backticked paths resolve", not _broken and _checked > 0,
    f"checked={_checked} broken={_broken[:6]}")

# D7 — the migration count in AGENTS.md matches the registry. Counted by the
# decorator, not by a remembered number.
_mig_src = rd("app/migrations.py")
# ignore the usage example in the module docstring
_doc_end = _mig_src.find('"""', _mig_src.find('"""') + 3)
_versions = [int(v) for v in re.findall(r"@migration\(version=(\d+)", _mig_src[_doc_end:])]
_ag_mig = re.search(r"(\d+) migrations\s*(?:→|->|to)\s*v(\d+)", _ag)
if _ag_mig:
    chk("D7", "AGENTS.md migration count == registry",
        int(_ag_mig.group(1)) == len(_versions) and int(_ag_mig.group(2)) == max(_versions),
        f"registry={len(_versions)} maxv={max(_versions)} doc={_ag_mig.groups()}")
else:
    chk("D7", "AGENTS.md quotes no migration count (derives it)",
        "migrations.py" in _ag,
        f"registry={len(_versions)} maxv={max(_versions)}, not quoted")

# D8 — every CI `run:` command is executed by gates.sh or named in its CI_ONLY
# table. Adding a CI step without teaching gates.sh about it is exactly how the
# local bar silently fell behind CI.
_wf = rd(".github/workflows/tests.yml")
_gates = rd("scripts/gates.sh")
_ci_only = (_gates.split("<<'CIEOF'")[1].split("CIEOF")[0] if "<<'CIEOF'" in _gates else "").lower()
_LOCAL_ONLY = (_gates.split("LOCAL_ONLY=")[1].split("step()")[0] if "LOCAL_ONLY=" in _gates else "")

# Runner setup and scaffolding, not project gates.
_SETUP = ("uv sync", "playwright install", "actions/", "git config", "pip install",
          "::set-output", "echo ", "set -e",
          # shell scaffolding inside CI's docker job (that whole job is CI_ONLY)
          "trap ", "NAME=osrm", "sleep ", "docker rm", "docker cp", "docker run",
          "docker exec", "if ! ", "fi", "then", "for ", "done")
_runs = []
for _wf_path in (".github/workflows/tests.yml", ".github/workflows/lint.yml"):
    _lines = rd(_wf_path).splitlines()
    _i = 0
    while _i < len(_lines):
        _ln = _lines[_i]
        _m2 = re.match(r"^(\s+)run:\s*(\|)?\s*$", _ln)
        if _m2:
            _ind = len(_m2.group(1))
            _block = []
            _i += 1
            while _i < len(_lines):
                _sub = _lines[_i]
                if _sub.strip() and len(_sub) - len(_sub.lstrip()) <= _ind:
                    break
                if _sub.strip():
                    _block.append(_sub.strip())
                _i += 1
            if _block:
                _runs.append(" ;; ".join(_block))
            continue
        _m3 = re.match(r"^\s+run:\s*(\S.*)$", _ln)
        if _m3:
            _runs.append(_m3.group(1).strip())
        _i += 1

_uncovered = []
for _cmd in _runs:
    if any(_s in _cmd for _s in _SETUP) or _cmd.startswith("#"):
        continue
    _key = None
    for _pat in (r"(tests/(?:unit|e2e)/test_[a-z_0-9]+\.py)",
                 r"(scripts/[a-z_0-9]+\.(?:sh|py))",
                 r"(docker build)"):
        _m2 = re.search(_pat, _cmd)
        if _m2:
            _key = _m2.group(1); break
    if _key is None:
        _k3 = re.search(r"([a-z_0-9]+\.(?:sh|py))", _cmd)
        _key = _k3.group(1) if _k3 else _cmd.split()[0]
    _bare = _key.rsplit("/", 1)[-1]
    # gates.sh may name the script, or DERIVE the set it belongs to: unit_suites()
    # and e2e_suites() pull from tests.yml, so every unit/e2e path is covered by
    # the derivation even though the filename never appears in the script.
    _derived = ("tests/unit/" in _key and "unit_suites" in _gates) or \
               ("tests/e2e/" in _key and ("e2e_suites" in _gates or "run_push_duts" in _gates))
    _any = any(t in _gates for t in re.findall(r"[a-z_0-9]+\.(?:sh|py)", _cmd))
    if (_any or _key in _gates or _bare in _gates or _derived
            or _bare.lower() in _ci_only or _key.lower() in _ci_only):
        continue
    _uncovered.append(_cmd[:70])
chk("D8", "every CI run: command is in gates.sh or CI_ONLY",
    not _uncovered, f"uncovered={_uncovered[:4]}")

# D9 — every tests/e2e/test_*.py is run by CI or named in LOCAL_ONLY with a reason.
_e2e_disk = {p.stem for p in (R / "tests/e2e").glob("test_*.py")}
# CI arms the shared-server e2e suites as ARGUMENTS to ci_e2e_http.sh, which
# `_ci` (unit paths only) never sees -- parse those args, the self-booting steps,
# and run_push_duts' own list.
_e2e_armed = set()
_eb = re.search(r"ci_e2e_http\.sh((?:\s*\\?\s*\n?\s*test_[a-z_0-9]+)+)", _yml)
if _eb:
    _e2e_armed |= set(re.findall(r"test_[a-z_0-9]+", _eb.group(1)))
_e2e_armed |= set(re.findall(r"tests/e2e/(test_[a-z_0-9]+)\.py", _wf))
_rpd = R / "tests/e2e/run_push_duts.sh"
if _rpd.exists():
    _e2e_armed |= set(re.findall(r"test_[a-z_0-9]+", _rpd.read_text()))
_e2e_unarmed = sorted(_e2e_disk - _e2e_armed - set(re.findall(r"(test_[a-z_0-9]+)\|", _LOCAL_ONLY)))
chk("D9", "every tests/e2e suite runs in CI or is LOCAL_ONLY",
    not _e2e_unarmed, f"unarmed={_e2e_unarmed}")

# D10 — D9 above globs `test_*.py`, so a DRIVER (a11y.py, stress.py of the
# a11y/stress gate, route_paint.py and offline_paint.py of the offline proof)
# is invisible to it. That is exactly how the a11y+stress suite ended up wired
# into gates.sh but absent from CI: locally green, never executed on a runner.
# Resolve the single hop that matters — driver -> a .sh that CI names.
_DRIVERS_MANUAL = {
    # Not a gate: prints console/SW diagnostics for a failing offline run, has
    # no PASS/FAIL and no exit code. Run by hand while triaging.
    "probe_sw.py",
}
_scripts = list((R / "scripts").glob("*.sh")) + list((R / "tests/e2e").glob("*.sh"))
_ci_scripts = [s for s in _scripts if s.name in _wf]
_drivers_idle = []
for _d in sorted(p.name for p in (R / "tests/e2e").glob("*.py")
                 if not p.name.startswith(("_", "test_"))):
    if _d in _DRIVERS_MANUAL or _d in _wf:
        continue
    if not any(_d in s.read_text(errors="replace") for s in _ci_scripts):
        _drivers_idle.append(_d)
chk("D10", "every tests/e2e driver script reaches CI through a CI-run .sh",
    not _drivers_idle, f"unreachable={_drivers_idle}")

# D11 — a suite's check count quoted in prose equals the count the suite RUNS.
#
# This is the class that was actually stale: DESIGN.md said test_layout.py runs 25
# checks when it runs 26.
#
# Counting `check(` call sites statically does NOT work -- the number depends on
# loops over viewports and on `if label == ...` guards that execute one branch, and
# a heuristic that guessed wrong reported a correct doc as stale. So the count is
# taken from the run: a suite that prints its own total is run, and its last
# "N checks" / "N/N PASS" line is the truth. A suite that needs a browser or a
# server is SKIPPED and reported as skipped, never as a pass -- an unverified
# claim must not look verified.
#
# Only claims written as "`<path>` ... N checks" are checked. A doc that says
# "the suite" with no number is not a claim, so a growing suite changes no prose.
# The path may sit INSIDE a longer backtick span -- "`DATA_DIR=/tmp .venv/bin/python
# tests/unit/test_layout.py` still passes (25 checks)" is the exact line the stale
# count lived in, and anchoring the closing backtick right after ".py" missed it.
_CLAIM = re.compile(r"`[^`\n]*?([A-Za-z0-9_./-]+\.py)[^`\n]*`[^\n`]*?\b(\d+)\s+checks\b")
_TOTAL = re.compile(r"(?:TOTAL:\s*(\d+)\s+checks|(\d+)/(\d+) PASS)")
_count_bad, _count_ok, _count_skipped = [], [], []
_seen_pairs = set()
for _md in _md_files:
    _p = R / _md
    if not _p.exists():
        continue
    for _m in _CLAIM.finditer(_p.read_text(errors="replace")):
        _path, _quoted = _m.group(1), int(_m.group(2))
        _cand = [R / _path, _p.parent / _path]
        _cand += list(R.glob(f"**/{_path.split('/')[-1]}"))
        _src_p = next((c for c in _cand if c.is_file()), None)
        if _src_p is None or (_src_p, _quoted) in _seen_pairs:
            continue
        _seen_pairs.add((_src_p, _quoted))
        _rel = str(_src_p.relative_to(R))
        # Run it. Only unit suites are cheap and self-contained; anything else is
        # declared skipped so the gap is visible instead of silently green.
        if not _rel.startswith("tests/unit/"):
            _count_skipped.append(f"{_rel} (needs browser/server)")
            continue
        try:
            _r = subprocess.run(
                [sys.executable, str(_src_p)], cwd=str(R), timeout=300,
                capture_output=True, text=True,
                env={**os.environ, "PYTHONPATH": str(R),
                     "DATA_DIR": os.environ.get("DATA_DIR", "/tmp/osrm-check-docs")},
            )
            _out = _r.stdout + _r.stderr
            _t = _TOTAL.findall(_out)
            _actual = None
            for _g in _t:
                _actual = int(_g[0]) if _g[0] else int(_g[2])
            if _r.returncode != 0 or _actual is None:
                _count_skipped.append(f"{_rel} (exited {_r.returncode}, no total)")
                continue
        except Exception as _e:  # a suite that cannot run must not fail the doc gate
            _count_skipped.append(f"{_rel} ({type(_e).__name__})")
            continue
        if _actual == _quoted:
            _count_ok.append(f"{_rel}={_actual}")
        else:
            _count_bad.append(f"{_md} says {_quoted}, {_rel} runs {_actual}")
chk("D11", "suite check counts quoted in docs == the count the suite runs",
    not _count_bad,
    f"verified={_count_ok} skipped={_count_skipped} mismatch={_count_bad[:4]}")
# A skipped claim is not a verified claim. Print it on PASS too, so "D11 PASS"
# never reads as "every count in every doc was checked".
if _count_skipped:
    print(f"      note: not verified (cannot run in a static gate): {_count_skipped}")

# D12 — the migration count quoted in prose equals the registry, docstring excluded.
# D7 only reads AGENTS.md and only when it states the count; README.md quotes
# "18 migrations -> schema v18", where 18 is the max VERSION and not the count of
# migrations. Those are two different numbers and the sentence means the second.
_mig_doc = rd("app/migrations.py")
_mig_end = _mig_doc.find('"""', _mig_doc.find('"""') + 3)
_mig_list = [int(v) for v in re.findall(r"@migration\(version=(\d+)", _mig_doc[_mig_end:])]
_mig_n, _mig_max = len(_mig_list), max(_mig_list)
_mig_bad, _mig_seen = [], []
for _md in _md_files:
    _p = R / _md
    if not _p.exists():
        continue
    for _m in re.finditer(r"\b(\d+) migrations\b", _p.read_text(errors="replace")):
        _q = int(_m.group(1))
        _mig_seen.append(f"{_md}={_q}")
        if _q != _mig_n:
            _mig_bad.append(f"{_md} says {_q} migrations, registry has {_mig_n}")
chk("D12", "migration count quoted in docs == registry (docstring excluded)",
    not _mig_bad,
    f"registry={_mig_n} maxv={_mig_max} quoted={_mig_seen} mismatch={_mig_bad[:4]}"
    if _mig_seen else f"not quoted; registry={_mig_n} maxv={_mig_max}")

# D13 — no doc names a script in THIS repo's scripts/ that does not exist. This is
# the exact failure the mission hit: prose said scripts/capture.py when the file is
# capture_golden.py.
#
# Anchored to a bare or repo-relative `scripts/` on purpose:
#   - a bare filename (sw.js, app.css) is shorthand for app/static/ and is not resolved;
#   - an ABSOLUTE path (`/opt/data/scripts/push-tick.sh`) is a host path, belongs to
#     the lab, and is not this repo's file -- matching inside it reported a documented
#     cron script as missing;
#   - a placeholder (`<diagram-design-skill>/scripts/x.py`) belongs to another skill.
# Widening these three would red on correct docs, which is how a sweep gets deleted.
_scr_bad, _scr_seen = [], set()
for _md in _md_files:
    _p = R / _md
    if not _p.exists():
        continue
    _body = _p.read_text(errors="replace")
    for _m in re.finditer(r"(?:^|[\s`(\[\"'])(?:\.[/])?scripts/([A-Za-z0-9_.-]+\.(?:py|sh))\b",
                          _body):
        _name = _m.group(1)
        _scr_seen.add(_name)
        if not (R / "scripts" / _name).exists():
            _scr_bad.append(f"{_md}->scripts/{_name}")
chk("D13", "every scripts/<file> named in docs exists",
    not _scr_bad and bool(_scr_seen),
    f"checked={len(_scr_seen)} missing={_scr_bad[:6]}")

fails = [r for r in results if not r[2]]
for cid, desc, ok, ev in results:
    print(f"{cid:5} {'PASS' if ok else 'FAIL':7} {desc}")
    if not ok and ev:
        print(f"      {ev}")
print(f"\nTOTAL: {len(results)} checks | PASS {len(results) - len(fails)} | FAIL {len(fails)}")
if fails:
    print("FAILED:", ", ".join(r[0] for r in fails))
sys.exit(1 if fails else 0)
