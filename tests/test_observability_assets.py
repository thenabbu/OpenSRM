"""Guard rails for ops/observability/ — the assets CI would otherwise only
discover are broken when someone deploys them.

Asserts, over the compose file, scrape config, alert rules, and dashboard:
  * every opensrm_ series referenced actually exists in app/ (no invented
    metric makes it into a panel or an alert rule),
  * no metric label is netid/user/ip (PII never enters a label),
  * container images are pinned by tag AND digest (no floating images),
  * no secret-looking literals in the tree (gitleaks stays clean),
  * the dashboard JSON parses, has unique panel ids and a stable uid.

Runner style: plain script, check(name, fn), self-contained (no server,
no network, no docker). CI: tests.yml unit job.
"""
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPS = os.path.join(REPO, "ops", "observability")

FAILS = []
TOTAL = [0]


def check(name, fn):
    TOTAL[0] += 1
    try:
        fn()
        print(f"  ok  {name}")
    except AssertionError as e:
        FAILS.append(name)
        print(f"FAIL  {name}: {e}")
    except Exception as e:
        FAILS.append(name)
        print(f"FAIL  {name}: raised {type(e).__name__}: {e}")


def rd(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


def ops_rd(rel):
    with open(os.path.join(OPS, rel), encoding="utf-8") as f:
        return f.read()


def app_source():
    """Every .py under app/ concatenated — the source of truth for metric names."""
    out = []
    for root, _dirs, files in os.walk(os.path.join(REPO, "app")):
        for f in files:
            if f.endswith(".py"):
                with open(os.path.join(root, f), encoding="utf-8") as fh:
                    out.append(fh.read())
    return "\n".join(out)


def strip_suffixes(name):
    """Histogram exposition adds _bucket/_sum/_count; the app registers the base."""
    for sfx in ("_bucket", "_sum", "_count"):
        if name.endswith(sfx):
            return name[: -len(sfx)]
    return name


def referenced_series(text):
    return set(re.findall(r"opensrm_[a-z0-9_]+", text))


# ── 1. every referenced series exists in app/ ─────────────────────────────
def t_series_exist():
    src = app_source()
    assets = {
        "compose": ops_rd("docker-compose.yml"),
        "scrape config": ops_rd("prometheus/prometheus.yml"),
        "alert rules": ops_rd("prometheus/rules/opensrm.yml"),
        "dashboard": ops_rd("grafana/dashboards/opensrm.json"),
    }
    for where, text in assets.items():
        missing = sorted({m for m in referenced_series(text)
                          if strip_suffixes(m) not in src})
        assert not missing, f"{where} references series absent from app/: {missing}"


# ── 2. no PII label names anywhere in the observability assets ────────────
def t_no_pii_labels():
    banned = ("netid", "user", "ip")
    # match label positions: by (…), {label=…}, legendFormat {{label}}
    label_pos = re.compile(
        r"by\s*\(([^)]*)\)"                       # aggregation group-by
        r"|\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*[=~!]"  # selector {label=
        r"|\{\{\.?([a-zA-Z_][a-zA-Z0-9_]*)\}\}",   # legend/description template
    )
    for rel in ("prometheus/rules/opensrm.yml", "prometheus/prometheus.yml"):
        text = ops_rd(rel)
        for m in label_pos.finditer(text):
            groups = [g for g in m.groups() if g]
            for g in groups:
                for lab in re.split(r"\s*,\s*", g.strip()):
                    name = lab.split("=")[0].strip().strip('"').lower()
                    assert name not in banned, f"{rel}: PII label {name!r} in {m.group(0)!r}"
    dash = json.loads(ops_rd("grafana/dashboards/opensrm.json"))
    exprs = [t["expr"] for p in dash["panels"] for t in p.get("targets", [])]
    for e in exprs:
        for m in label_pos.finditer(e):
            for g in [g for g in m.groups() if g]:
                for lab in re.split(r"\s*,\s*", g.strip()):
                    name = lab.split("=")[0].strip().strip('"').lower()
                    assert name not in banned, f"dashboard expr PII label {name!r}: {e!r}"


# ── 3. images pinned by tag AND digest ────────────────────────────────────
def t_images_pinned():
    compose = ops_rd("docker-compose.yml")
    images = re.findall(r"^\s*image:\s*(\S+)\s*$", compose, re.M)
    assert images, "no image: lines found in the compose file"
    for img in images:
        assert re.fullmatch(r"[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}", img), \
            f"image not pinned by tag+digest: {img}"
    # the pinned digests must be resolvable strings, not placeholders
    assert not any("sha256:<" in i or "DIGEST" in i for i in images), \
        "placeholder digest in compose"


# ── 4. no secret-looking literals ─────────────────────────────────────────
def t_no_secret_literals():
    # files gitleaks would scan: everything under ops/ that is text
    pat = re.compile(
        r"(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9+/=_-]{16,}")
    allow = re.compile(r"(password|token|secret)")  # var/file references, no value
    for root, dirs, files in os.walk(OPS):
        # secrets/ (600-mode, container-uid owned) and the scratch proof
        # configs are deploy-host artifacts — gitignored and unreadable to
        # this process; the tracked-by-git check below is their guard.
        dirs[:] = [d for d in dirs if d not in ("secrets", "proof")]
        for f in files:
            path = os.path.join(root, f)
            with open(path, encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, 1):
                    m = pat.search(line)
                    if not m:
                        continue
                    tail = line[m.end() - 16:].lower()
                    # a real value would not be a documented file/env reference
                    assert allow.search(tail) and ("file" in line.lower()
                                                   or "__FILE" in line
                                                   or "secrets/" in line
                                                   or "${" in line), \
                        f"{os.path.relpath(path, REPO)}:{i} looks like a literal secret: {line.strip()[:80]!r}"
    # the ntfy topic URL must not be committed anywhere in the tree
    topic = re.compile(r"ntfy\.sh/[A-Za-z0-9_-]{6,}")
    for rel in ("ops/observability/docker-compose.yml",
                "ops/observability/alertmanager/alertmanager.yml",
                "ops/observability/prometheus/prometheus.yml"):
        m = topic.search(rd(rel))
        assert not m, f"ntfy topic committed in {rel}: {m.group(0)!r}" if m else ""


# ── 4b. secret/proof artifacts must not be tracked by git ─────────────────
def t_secrets_not_tracked():
    import subprocess
    out = subprocess.run(["git", "ls-files", "ops/"], cwd=REPO,
                         capture_output=True, text=True).stdout.splitlines()
    leaked = [f for f in out if "secrets/" in f or "proof-override" in f or "/proof/" in f]
    assert not leaked, f"deploy-host artifacts committed: {leaked}"


# ── 5. dashboard JSON: valid, unique panel ids, stable uid, read-only ─────
def t_dashboard_valid():
    dash = json.loads(ops_rd("grafana/dashboards/opensrm.json"))
    assert dash["uid"] == "opensrm-observability", f"unstable uid: {dash['uid']}"
    assert dash.get("editable") is False, "dashboard must not be editable"
    ids = [p["id"] for p in dash["panels"]]
    assert len(ids) == len(set(ids)), f"duplicate panel ids: {ids}"
    assert all(isinstance(i, int) for i in ids), f"non-integer panel ids: {ids}"
    assert 1 <= len(dash["panels"]) <= 10, \
        f"panel budget is ~10, found {len(dash['panels'])}"
    for p in dash["panels"]:
        for t in p.get("targets", []):
            assert re.search(r"opensrm_[a-z0-9_]+|\bup\{", t["expr"]), \
                f"panel {p['id']} expr references no opensrm_/up series: {t['expr']!r}"


# ── 6. provisioning: read-only + allowUiUpdates false ─────────────────────
def t_provisioning_readonly():
    prov = ops_rd("grafana/provisioning/dashboards/opensrm.yml")
    assert "allowUiUpdates: false" in prov, "dashboards must be provisioned read-only"
    assert "disableDeletion: true" in prov, "provisioned dashboard must not be deletable"
    ds = ops_rd("grafana/provisioning/datasources/prometheus.yml")
    assert "editable: false" in ds, "datasource must not be editable in the UI"


# ── 7. compose hardening: loopback binds, limits, non-root, no-new-privs ──
def t_compose_hardening():
    compose = ops_rd("docker-compose.yml")
    ports = re.findall(r'^\s*-\s*"([^"]+)"\s*$', compose, re.M)
    pub = [p for p in ports if ":" in p and not p.startswith("./")]
    assert pub, "no published ports found"
    for p in pub:
        assert p.startswith("127.0.0.1:"), f"port not loopback-only: {p}"
    for flag in ("cap_drop", "no-new-privileges", "mem_limit", "pids_limit"):
        assert flag in compose, f"compose missing hardening flag: {flag}"
    # retention: 30d wall clock AND a size cap
    assert "--storage.tsdb.retention.time=30d" in compose, "30d retention missing"
    assert "--storage.tsdb.retention.size=" in compose, "retention size cap missing"
    # lifecycle API off
    # kingpin negation: "--no-web.enable-lifecycle" (v3 rejects "=false");
    # default is off (403 on POST /-/reload) but pinned explicit anyway
    assert "--no-web.enable-lifecycle" in compose, "lifecycle API must be off"
    # grafana: sign-up/anonymous/analytics/update checks off
    for gf in ("GF_USERS_ALLOW_SIGN_UP=false", "GF_AUTH_ANONYMOUS_ENABLED=false",
               "GF_ANALYTICS_REPORTING_ENABLED=false",
               "GF_ANALYTICS_CHECK_FOR_UPDATES=false"):
        assert gf in compose, f"grafana hardening missing: {gf}"
    # admin password from a mounted secret, not an env literal
    assert "GF_SECURITY_ADMIN_PASSWORD__FILE=" in compose, \
        "admin password must come from a secret file"
    assert not re.search(r"GF_SECURITY_ADMIN_PASSWORD=[^$\{]", compose), \
        "admin password literal in compose"


# ── 8. scrape config: secret via file, real target, right header ──────────
def t_scrape_config():
    cfg = ops_rd("prometheus/prometheus.yml")
    assert 'job_name: opensrm' in cfg, "scrape job opensrm missing"
    assert "http_headers:" in cfg, "custom header block missing"
    assert "X-Metrics-Token" in cfg, "X-Metrics-Token header missing"
    assert re.search(r"files:\s*\n\s*-\s*/etc/prometheus/secrets/metrics_token", cfg), \
        "token must be read from a mounted secret file, not inline"
    # no inline token value anywhere in the header block
    hdr = cfg[cfg.index("http_headers:"):]
    assert not re.search(r"values:\s*\[", hdr), "inline header value found"
    # target: the app's real published address (gateway IP for containers)
    assert re.search(r'targets:\s*\[\s*"172\.31\.0\.1:8083"\s*\]', cfg), \
        "scrape target must be 172.31.0.1:8083 (the app's gateway bind)"


# ── 9. alertmanager: ntfy URL from a file, no topic in config ─────────────
def t_alertmanager_ntfy():
    am = ops_rd("alertmanager/alertmanager.yml")
    assert "url_file:" in am, "ntfy URL must come from url_file (secret), not url:"
    assert not re.search(r"^\s*url:\s*http", am, re.M), "inline webhook url literal"
    assert "webhook_configs:" in am, "webhook receiver missing"


for name, fn in [
    ("every opensrm_ series in compose/scrape/rules/dashboard exists in app/", t_series_exist),
    ("no netid/user/ip label in any observability asset", t_no_pii_labels),
    ("images pinned by tag and digest", t_images_pinned),
    ("no secret-looking literals, no committed ntfy topic", t_no_secret_literals),
    ("secrets/ + proof artifacts not tracked by git", t_secrets_not_tracked),
    ("dashboard JSON valid, unique ids, ~10 panel budget, stable uid", t_dashboard_valid),
    ("provisioning read-only (allowUiUpdates false, no deletion)", t_provisioning_readonly),
    ("compose hardening: loopback, limits, caps, retention, grafana flags", t_compose_hardening),
    ("scrape config: secret file, real target, correct header", t_scrape_config),
    ("alertmanager: ntfy url_file, no inline url/topic", t_alertmanager_ntfy),
]:
    check(name, fn)

print(f"\n{TOTAL[0] - len(FAILS)}/{TOTAL[0]} passed")
if FAILS:
    print("FAILED:", ", ".join(FAILS))
    sys.exit(1)
print("ok  observability assets suite")
