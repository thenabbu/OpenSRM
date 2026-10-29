#!/usr/bin/env python3
"""Generate the OpenSRM Grafana dashboard JSON from a compact table.

Why a generator: the dashboard is ~45 panels across 6 subsystem rows, and
hand-editing that JSON drifts panel ids, gridPos collisions and refIds. One
row per subsystem here, one call to `add()` per panel, and the output is
deterministic — so `python3 scripts/build_dashboard.py --check` in CI can
prove the committed JSON matches this file.

Usage:
    python3 scripts/build_dashboard.py            # write the JSON
    python3 scripts/build_dashboard.py --check    # exit 1 if stale
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "ops/observability/grafana/dashboards/opensrm.json"
DS = {"type": "prometheus", "uid": "prometheus"}

W = 24  # Grafana grid width

panels = []
_pid = [0]
# layout cursor, shared by row() and add():
#   _line   — y of the line of panels currently being filled
#   _used   — grid columns consumed on that line
#   _line_h — tallest panel on that line (where the next line starts)
_line = [0]
_used = [0]
_line_h = [0]


def _nid():
    _pid[0] += 1
    return _pid[0]


def row(title, desc=""):
    """A collapsible subsection. Rows let the operator collapse everything
    that is not currently in question instead of scrolling past it.

    Closes the current line: the row sits below every panel written so far.
    """
    _line[0] += _line_h[0]
    _used[0] = 0
    _line_h[0] = 0
    panels.append({
        "id": _nid(), "type": "row", "title": title, "description": desc,
        "collapsed": False, "gridPos": {"h": 1, "w": W, "x": 0, "y": _line[0]},
        "panels": [],
    })
    _line[0] += 1


def add(title, desc, targets, kind="timeseries", w=12, h=8, unit="short",
        legend="bottom", stack=False, thresholds=None, instant=False,
        span=10, calcs=("mean", "max", "lastNotNull")):
    """One panel in the current row, flowing left-to-right and wrapping.

    Layout cursor: `_line` is the y of the current line of panels, `_used`
    the x consumed on it, `_line_h` the tallest panel on it so far. A panel
    that does not fit wraps to a new line, and the new line starts below the
    tallest panel of the line just finished.
    """
    if _used[0] + w > W:                      # wrap to a fresh line
        _line[0] += _line_h[0]
        _used[0] = 0
        _line_h[0] = 0
    y = _line[0]
    used = _used[0]
    _used[0] += w
    _line_h[0] = max(_line_h[0], h)
    custom = {"drawStyle": "line", "lineWidth": 1, "fillOpacity": 8,
              "showPoints": "never"}
    if stack:
        custom.update({"drawStyle": "bars", "fillOpacity": 60, "stacking": {"mode": "normal"}})
    defaults = {"unit": unit, "custom": custom}
    if thresholds:
        defaults["thresholds"] = {"mode": "absolute", "steps": thresholds}
        defaults["color"] = {"mode": "thresholds"}
    ts_targets = []
    for i, (expr, leg) in enumerate(targets):
        t = {"expr": expr, "legendFormat": leg, "refId": chr(65 + i), "datasource": DS}
        if instant or kind in ("stat", "table"):
            t["instant"] = True
            t["range"] = not instant
        ts_targets.append(t)
    opts = {"legend": {"displayMode": "table" if kind != "stat" else "list",
                       "placement": legend, "calcs": list(calcs)},
            "tooltip": {"mode": "multi", "sort": "desc"}}
    if kind in ("stat", "gauge"):
        opts = {"reduceOptions": {"calcs": [span], "fields": "", "values": False},
                "orientation": "auto", "textMode": "auto",
                "colorMode": "background" if kind == "stat" else "value",
                "graphMode": "none"}
    p = {"id": _nid(), "type": kind, "title": title, "description": desc,
         "gridPos": {"h": h, "w": w, "x": used, "y": y},
         "datasource": DS, "fieldConfig": {"defaults": defaults, "overrides": []},
         "options": opts, "targets": ts_targets}
    panels.append(p)


# ══════════════════════════════════════════════════════════════════
# 1. Liveness — the questions you ask when something is wrong
# ══════════════════════════════════════════════════════════════════
row("Liveness", "Is the app answering, is the scheduler ticking, how big is the process.")
add("Scrape up", "1 = Prometheus reached /internal/metrics. 0 means the app is down OR the "
    "metrics token no longer matches METRICS_SECRET — check the secret file before assuming a crash.",
    [('up{job="opensrm"}', "up")], kind="stat", w=4, h=4, span=1,
    thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 1}])
add("Push tick age", "Seconds since the every-minute tick last succeeded. >300s means the Hermes "
    "cron job is dead, disabled, or the host is gone.",
    [("time() - opensrm_push_tick_last_success_timestamp_seconds", "age")],
    kind="stat", w=4, h=4, span=1, unit="s",
    thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 120},
                {"color": "red", "value": 300}])
add("Portal cooldown", "Seconds the portal budget is still locked out. Non-zero means syncs are being "
    "refused for everyone right now.", [("opensrm_portal_cooldown_seconds", "cooldown")],
    kind="stat", w=4, h=4, span=1, unit="s",
    thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}])
add("Process RSS", "Resident memory. A number that only climbs across days is a leak; the container "
    "limit is the ceiling to watch.",
    [("opensrm_process_rss_bytes", "rss")], kind="stat", w=4, h=4, span=1,
    unit="bytes", thresholds=[{"color": "green", "value": None},
                              {"color": "orange", "value": 400 * 1024 * 1024}])
add("Threads", "Gunicorn runs --threads 8; a number pinned at the ceiling means requests are queuing.",
    [("opensrm_process_threads", "threads")], kind="stat", w=4, h=4, span=1)
add("DB size", "srm.db on disk. Growth is fine, a step change means a retention path stopped pruning.",
    [("opensrm_db_size_bytes", "db")], kind="stat", w=4, h=4, span=1, unit="bytes")

# ══════════════════════════════════════════════════════════════════
# 2. HTTP — every request the app serves
# ══════════════════════════════════════════════════════════════════
row("HTTP requests", "Every request, by matched route. This is the view that answers "
    "\"what is the app actually being asked to do\".")
add("Requests per minute by status class",
    "Throughput split by 2xx/3xx/4xx/5xx. A 5xx bump here is the fastest signal that a deploy broke something.",
    [('sum by (status_class) (rate(opensrm_http_requests_total[5m]) * 60)', "{{status_class}}")],
    w=12, h=8, stack=True)
add("Latency p50 / p95 / p99 across all routes",
    "Server-side request duration. The sync-bearing routes (/api/refresh, /api/login) legitimately run "
    "seconds; a jump on a static route is the interesting case.",
    [
        ('histogram_quantile(0.50, sum by (le) (rate(opensrm_http_request_duration_seconds_bucket[1h])))', "p50"),
        ('histogram_quantile(0.95, sum by (le) (rate(opensrm_http_request_duration_seconds_bucket[1h])))', "p95"),
        ('histogram_quantile(0.99, sum by (le) (rate(opensrm_http_request_duration_seconds_bucket[1h])))', "p99"),
    ], w=12, h=8, unit="s")
add("Top routes by request rate",
    "Which routes carry the traffic. Cardinality is bounded by the route table, so this cannot explode.",
    [('topk(10, sum by (route) (rate(opensrm_http_requests_total{route!="<unmatched>"}[5m]) * 60))', "{{route}}")],
    w=12, h=9)
add("Top routes by p95 latency",
    "The slowest routes over the window. Expect the sync paths here; anything else is a regression.",
    [('topk(10, histogram_quantile(0.95, sum by (le, route) (rate(opensrm_http_request_duration_seconds_bucket[1h]))))', "{{route}}")],
    w=12, h=9, unit="s")
add("Errors by route (5xx only)",
    "Only 5xx. 4xx is dominated by bad logins and bot 404s and would drown the signal.",
    [('topk(10, sum by (route) (rate(opensrm_http_requests_total{status_class="5xx"}[1h]) * 3600))', "{{route}}")],
    w=12, h=8)
add("Unmatched requests (24h)",
    "Requests for paths no route handles — scanners, stale bookmarks, or a frontend calling a removed API. "
    "A sudden jump usually means a deploy removed a route that clients still call.",
    [('sum(increase(opensrm_http_requests_total{route="<unmatched>"}[24h]))', "unmatched")],
    w=12, h=8, kind="stat", span=1)

# ══════════════════════════════════════════════════════════════════
# 3. Portal sync — the core business flow
# ══════════════════════════════════════════════════════════════════
row("Portal syncs", "The scrape pipeline: outcomes, error taxonomy, duration, and the "
    "drift signals that mean the portal changed its markup.")
add("Syncs per minute by pipeline and outcome",
    "ok vs error per pipeline (http / playwright). Playwright is archived behind a flag, so it should be flat zero.",
    [('sum by (pipeline, result) (rate(opensrm_sync_total[5m]) * 60)', "{{pipeline}}/{{result}}")],
    w=12, h=8, stack=True)
add("Error classes (1h)",
    "The typed error vocabulary: bad_credentials, rate_limited, portal_cooldown, busy, portal_down, "
    "markup_changed, internal, auth, captcha, other. One class dominating names the cause.",
    [('sum by (error) (increase(opensrm_sync_total{result="error"}[1h]))', "{{error}}")],
    w=12, h=8)
add("Sync duration p50 / p95",
    "End-to-end sync time. The pipeline deadline is 150s; p95 approaching it means users are timing out.",
    [
        ('histogram_quantile(0.50, sum by (le) (rate(opensrm_sync_duration_seconds_bucket[1h])))', "p50"),
        ('histogram_quantile(0.95, sum by (le) (rate(opensrm_sync_duration_seconds_bucket[1h])))', "p95"),
    ], w=12, h=8, unit="s")
add("Cache hits vs joined vs real syncs (1h)",
    "How much work single-flight and caching is saving. cached/joined should dwarf real syncs; if they do not, "
    "every user is paying full scrape cost.",
    [("sum(increase(opensrm_sync_cached_total[1h]))", "cached"),
     ("sum(increase(opensrm_sync_joined_total[1h]))", "joined"),
     ('sum(increase(opensrm_sync_total{result="ok"}[1h]))', "real")], w=12, h=8)
add("Parse-empty by page (24h) — portal drift",
    "A page parsed to zero records. Alive-empty is legitimate for seasonal pages (exams outside their "
    "window); a page that is normally populated going empty is the earliest markup-drift signal.",
    [('sum by (page) (increase(opensrm_parse_empty_total[24h]))', "{{page}}")], w=12, h=8)
add("Scrape-lock rejections",
    "A second scrape for the same user while one is in flight. Sustained rejections mean users are "
    "double-tapping refresh or a client is retrying too aggressively.",
    [('sum by (op) (rate(opensrm_scrape_lock_rejections_total[1h]) * 60)', "{{op}}")], w=12, h=8)
add("Captcha attempts per login",
    "Average OCR attempts to clear the login captcha. A rising average means the captcha images are "
    "getting harder or the OCR model is degrading.",
    [("rate(opensrm_captcha_attempts_per_login_sum[1h]) / clamp_min(rate(opensrm_captcha_attempts_per_login_count[1h]), 0.0005)", "avg attempts")],
    w=12, h=8)
add("Preflight fates (1h)",
    "The captcha pre-warm pipeline: ready / consumed / wasted / busy / failed. A high 'wasted' share means "
    "we are pre-warming sessions nobody uses; 'failed' means the pre-warm is not landing.",
    [("sum by (outcome) (increase(opensrm_preflight_total[1h]))", "{{outcome}}")], w=12, h=8)

# ══════════════════════════════════════════════════════════════════
# 4. SCOPE backend — the second data source
# ══════════════════════════════════════════════════════════════════
row("SCOPE SOAP backend", "The SRMIST-SCOPE SOAP API: per-operation call rate, outcomes and latency. "
    "Faults here never affect the portal pipeline, but they surface as empty tabs.")
add("Calls per minute by operation",
    "Which SOAP ops drive traffic. A single op jumping is usually a page retry loop.",
    [('sum by (op) (rate(opensrm_scope_calls_total[5m]) * 60)', "{{op}}")], w=12, h=8)
add("Outcome split (1h)",
    "ok / http_error / transport_error. transport_error means the SOAP host was unreachable or timed out; "
    "http_error means it answered with a fault.",
    [('sum by (outcome) (increase(opensrm_scope_calls_total[1h]))', "{{outcome}}")], w=12, h=8)
add("Latency p50 / p95 by operation",
    "SOAP round-trip time. The client timeout is 15s; anything near it is about to start failing.",
    [
        ('histogram_quantile(0.50, sum by (le, op) (rate(opensrm_scope_call_duration_seconds_bucket[1h])))', "p50 {{op}}"),
        ('histogram_quantile(0.95, sum by (le, op) (rate(opensrm_scope_call_duration_seconds_bucket[1h])))', "p95 {{op}}"),
    ], w=12, h=9, unit="s")
add("Fault rate by operation",
    "Share of calls that were not ok. A single op at a high fault rate points at a contract change on that op.",
    [('sum by (op) (rate(opensrm_scope_calls_total{outcome!="ok"}[1h])) / clamp_min(sum by (op) (rate(opensrm_scope_calls_total[1h])), 0.0001)', "{{op}}")],
    w=12, h=9, unit="percentunit")

# ══════════════════════════════════════════════════════════════════
# 5. Push notifications
# ══════════════════════════════════════════════════════════════════
row("Push notifications", "Delivery attempts against the browser push services. Dead subscriptions "
    "accumulate here before any user complains.")
add("Delivery outcomes (1h)",
    "ok / retryable / dead / deadline / error. 'dead' is a 404/410 — the subscription is gone and gets "
    "deleted. 'deadline' means the tick ran out of time and deferred the send.",
    [("sum by (outcome) (increase(opensrm_push_send_total[1h]))", "{{outcome}}")], w=12, h=8)
add("Send latency p50 / p95",
    "Time inside pywebpush. The per-send timeout is 5s, so p95 near 5 means the push services are hanging.",
    [
        ('histogram_quantile(0.50, sum by (le) (rate(opensrm_push_send_duration_seconds_bucket[1h])))', "p50"),
        ('histogram_quantile(0.95, sum by (le) (rate(opensrm_push_send_duration_seconds_bucket[1h])))', "p95"),
    ], w=12, h=8, unit="s")
add("Delivery success rate",
    "ok / all attempts. A drop here with a flat request rate means the push services changed behaviour.",
    [('sum(rate(opensrm_push_send_total{outcome="ok"}[1h])) / clamp_min(sum(rate(opensrm_push_send_total[1h])), 0.0001)', "success rate")],
    w=12, h=8, unit="percentunit")
add("Push tick throughput (1h)",
    "Ticks that completed ok vs errored. One per minute is expected; a gap shows up as fewer 'ok' bars.",
    [('sum by (outcome) (increase(opensrm_push_tick_total[1h]))', "{{outcome}}")], w=12, h=8)

# ══════════════════════════════════════════════════════════════════
# 6. Database and data growth
# ══════════════════════════════════════════════════════════════════
row("Database", "SQLite health: statement latency by verb, file/WAL size, and the tables whose "
    "growth means adoption — or a broken retention path.")
add("Query rate by verb",
    "Statements per minute split by leading verb. A SELECT rate that climbs without traffic is an N+1 "
    "or a polling loop.",
    [('sum by (verb) (rate(opensrm_db_queries_total[5m]) * 60)', "{{verb}}")], w=12, h=8)
add("Query latency p50 / p95 / p99",
    "Statement time. Reads should sit in single-digit ms; a rising p95 on writes means lock contention.",
    [
        ('histogram_quantile(0.50, sum by (le) (rate(opensrm_db_query_duration_seconds_bucket[1h])))', "p50"),
        ('histogram_quantile(0.95, sum by (le) (rate(opensrm_db_query_duration_seconds_bucket[1h])))', "p95"),
        ('histogram_quantile(0.99, sum by (le) (rate(opensrm_db_query_duration_seconds_bucket[1h])))', "p99"),
    ], w=12, h=8, unit="s")
add("DB and WAL size",
    "The main file vs the WAL. A WAL that only grows means checkpoints are not completing — reads get "
    "slower and the disk fills.",
    [("opensrm_db_size_bytes", "db"), ("opensrm_db_wal_bytes", "wal")], w=12, h=8, unit="bytes")
add("Row counts",
    "users = adoption. push_subscriptions growing without users = dead devices accumulating. "
    "push_sent_log and usage_events are retention-managed: growth there means pruning broke.",
    [("opensrm_rows_users", "users"),
     ("opensrm_rows_push_subscriptions", "subscriptions"),
     ("opensrm_rows_push_sent_log", "sent_log"),
     ("opensrm_rows_usage_events", "usage_events")], w=12, h=9)

dashboard = {
    "uid": "opensrm",
    "title": "OpenSRM",
    "description": "Everything OpenSRM measures, grouped by subsystem. Panels are generated from "
                   "scripts/build_dashboard.py — edit that file, not this JSON.",
    "tags": ["opensrm", "observability"],
    "timezone": "browser",
    "schemaVersion": 39,
    "version": 2,
    "editable": False,
    "graphTooltip": 1,
    "time": {"from": "now-6h", "to": "now"},
    "refresh": "30s",
    "panels": panels,
    "links": [],
}

text = json.dumps(dashboard, indent=2, sort_keys=False) + "\n"
if "--check" in sys.argv:
    current = OUT.read_text() if OUT.exists() else ""
    if current != text:
        print(f"STALE: {OUT} does not match scripts/build_dashboard.py")
        sys.exit(1)
    print("dashboard JSON is current")
    sys.exit(0)

OUT.write_text(text)
print(f"wrote {OUT} — {len(panels)} panels, {sum(1 for p in panels if p['type']=='row')} rows")
