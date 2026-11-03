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
        stat_calc="lastNotNull", calcs=("mean", "max", "lastNotNull")):
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
            # instant=True means "evaluate once, now". Setting range=True
            # alongside it makes Grafana pull the whole window, and a series
            # left over from a previous container build then renders as a
            # SECOND value in the tile (observed: Process RSS showing both
            # 109MiB and 98MiB). A stat tile wants one number: instant only.
            t["instant"] = True
            t["range"] = False
        ts_targets.append(t)
    opts = {"legend": {"displayMode": "table" if kind != "stat" else "list",
                       "placement": legend, "calcs": list(calcs)},
            "tooltip": {"mode": "multi", "sort": "desc"}}
    if kind in ("stat", "gauge"):
        opts = {"reduceOptions": {"calcs": [stat_calc], "fields": "", "values": False},
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
    [('up{job="opensrm"}', "up")], kind="stat", w=4, h=4,
    thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 1}])
add("Push tick age", "Seconds since the every-minute tick last succeeded. >300s means the Hermes "
    "cron job is dead, disabled, or the host is gone.",
    # guarded: the gauge is 0 until the very first tick, and time()-0 renders
    # as ~56 YEARS of "age" on a fresh deploy (observed live). The `and`
    # yields no series at all when the tick has never run, so the tile shows
    # "No data" instead of a nonsense number.
    [("(time() - opensrm_push_tick_last_success_timestamp_seconds) "
      "and (opensrm_push_tick_last_success_timestamp_seconds > 0)", "age")],
    kind="stat", w=4, h=4, unit="s",
    thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 120},
                {"color": "red", "value": 300}])
add("Portal cooldown", "Seconds the portal budget is still locked out. Non-zero means syncs are being "
    "refused for everyone right now.", [("opensrm_portal_cooldown_seconds", "cooldown")],
    kind="stat", w=4, h=4, unit="s",
    thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}])
add("Process RSS", "Resident memory. A number that only climbs across days is a leak; the container "
    "limit is the ceiling to watch.",
    [("opensrm_process_rss_bytes", "rss")], kind="stat", w=4, h=4,
    unit="bytes", thresholds=[{"color": "green", "value": None},
                              {"color": "orange", "value": 400 * 1024 * 1024}])
add("Threads", "Gunicorn runs --threads 8; a number pinned at the ceiling means requests are queuing.",
    [("opensrm_process_threads", "threads")], kind="stat", w=4, h=4)
add("DB size", "srm.db on disk. Growth is fine, a step change means a retention path stopped pruning.",
    [("opensrm_db_size_bytes", "db")], kind="stat", w=4, h=4, unit="bytes")

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
    w=12, h=8, kind="stat")

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
# ══════════════════════════════════════════════════════════════════
# 6. Users and usage — who comes, when, and what they read
# ══════════════════════════════════════════════════════════════════
row("Users and usage", "Who is actually using the app, when they show up, and which tabs they read. "
    "Users are shown as a short hash (u + sha256[:10]) — never the netid.")
add("Active users (5m)", "Distinct users who did anything in the last 5 minutes. The live read on "
    "\"is anyone using this right now\".",
    [('count(count by (uid) (rate(opensrm_active_users_total{uid!="anonymous"}[5m])))', "active")],
    kind="stat", w=4, h=4)
add("Users today", "Distinct users active since midnight. Compare against the user-row count in the "
    "Database row: a gap means accounts exist that nobody logs into.",
    [('count(count by (uid) (increase(opensrm_active_users_total{uid!="anonymous"}[24h])))', "today")],
    kind="stat", w=4, h=4)
add("Requests per user per hour", "Load per person. One series per user (hashed), so a single heavy "
    "client stands out from the crowd.",
    [('topk(8, sum by (uid) (rate(opensrm_events_total{uid!="anonymous"}[1h]) * 3600))', "{{uid}}")],
    w=8, h=8)
add("Activity by hour of day (IST)", "When students actually open the app. This is the curve that "
    "decides when a sync or a push is worth running, and when the box sits idle.",
    [('sum(rate(opensrm_events_total[1h])) * 3600', "events/hour")],
    w=12, h=9)
add("Events by type (1h)", "What people do: page views, successful syncs, cached syncs, logins, "
    "tab switches, feedback fills. A shift in the mix is a behaviour change, not a bug.",
    [('sum by (event) (increase(opensrm_events_total[1h]))', "{{event}}")],
    w=12, h=9)
add("Top tabs (24h)", "Which tab people actually read after the dashboard. Tabs switch client-side, "
    "so this is the only place that is measurable at all.",
    [('topk(9, sum by (target) (increase(opensrm_events_total{event="tab_view"}[24h])))', "{{target}}")],
    w=12, h=8)
add("Tab switch rate", "Tab switches per minute. A sustained high rate on one tab is a sign people "
    "are hunting for something the page is not giving them.",
    [('sum by (target) (rate(opensrm_events_total{event="tab_view"}[15m]) * 60)', "{{target}}")],
    w=12, h=8)
add("Logged-out traffic", "Events with no user attached: prefetches, bots, expired sessions. A jump "
    "here with real users flat means something is scanning the site.",
    [('sum(rate(opensrm_events_total{uid="anonymous"}[1h])) * 3600', "anonymous/hour")],
    w=12, h=8)
add("Sync outcomes per user (1h)", "Who is syncing and how it went. A single user going all-error is "
    "their credentials; everyone erroring is the portal.",
    [('topk(8, sum by (uid) (increase(opensrm_events_total{event=~"sync_ok|sync_fail|sync_cached"}[1h])))', "{{uid}}")],
    w=12, h=8)

# ══════════════════════════════════════════════════════════════════
# 7. Sync cost attribution — where the seconds actually go
# ══════════════════════════════════════════════════════════════════
row("Sync cost by data source", "One sync has three costs: the SRM portal (JSP pages over HTTP), the "
    "SCOPE SOAP backend, and writing the result to SQLite. This row answers \"which one is slow today\".")
add("Time per phase p50", "Median wall time of each phase. Portal should dominate; SCOPE should be "
    "small and steady; persist should be milliseconds.",
    [('histogram_quantile(0.50, sum by (le, phase) (rate(opensrm_sync_phase_duration_seconds_bucket[1h])))', "{{phase}} p50")],
    w=12, h=8, unit="s")
add("Time per phase p95", "The tail. A p95 far above the p50 means a minority of syncs are dragging — "
    "usually the portal throttling, not our code.",
    [('histogram_quantile(0.95, sum by (le, phase) (rate(opensrm_sync_phase_duration_seconds_bucket[1h])))', "{{phase}} p95")],
    w=12, h=8, unit="s")
add("Share of sync time by phase", "The same data as a proportion: what fraction of a user's wait is "
    "the portal, SCOPE, and disk. This is the number to quote when arguing about where to optimise.",
    [('sum by (phase) (rate(opensrm_sync_phase_duration_seconds_sum[1h])) / clamp_min(sum(rate(opensrm_sync_phase_duration_seconds_sum[1h])), 0.0001)', "{{phase}}")],
    w=12, h=8, unit="percentunit")
add("SCOPE ops per sync", "How many SOAP ops a SCOPE run touched: 0 (everything fresh), 1-3, or 4+. "
    "High counts mean the cached SCOPE data keeps going stale.",
    [('sum by (bucket) (increase(opensrm_sync_phase_ops_total{phase="scope"}[24h]))', "{{bucket}}")],
    w=12, h=8)

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

# ══════════════════════════════════════════════════════════════════
# 8. WHO USES IT — the product questions, in plain words
# ══════════════════════════════════════════════════════════════════
# This row exists because every panel above answers "is the server healthy".
# None of them answered "is anyone using this and what do they do here", which
# is what actually decides what to build next. Titles are written as the
# question being asked, and descriptions say what a number MEANS rather than
# naming the metric — a dashboard nobody can read is a dashboard nobody opens.
row("Who uses it",
    "New vs returning vs total people, how long a visit lasts, and what they touch. "
    "Read this row left-to-right: how many came, did they stay, what did they do. "
    "Per-person labels are a short hash (u + sha256[:10]) — never a netid.")

add("New people today", "First-time users: accounts whose very first activity was in the last 24h. "
    "This is the growth number — a steady 0 with total flat means nobody new is arriving.",
    [("opensrm_users_new_24h", "new (24h)"), ("opensrm_users_new_7d", "new (7d)")],
    kind="stat", w=6, h=4, stat_calc="lastNotNull", unit="short")
add("Came back today", "Used the app in the last 24h, but are NOT first-timers. New + returning = "
    "everyone active today, so if the two do not add up to the active number something is misclassified.",
    [("opensrm_users_returning_24h", "returning (24h)")],
    kind="stat", w=6, h=4, stat_calc="lastNotNull")
add("Total accounts", "Every account in the database. Compare with 'Synced at least once': the gap is "
    "people who signed up and never finished a first sync — the most expensive kind of dropout.",
    [("opensrm_users_total", "accounts"), ("opensrm_users_synced_total", "synced at least once")],
    kind="stat", w=6, h=4, stat_calc="lastNotNull")
add("Active now / today / this week", "Distinct people, three windows. The 24h and 7d numbers are read "
    "from the event table so they survive a redeploy; 'active now' is the live 5-minute view.",
    [("count(count by (uid) (rate(opensrm_active_users_total{uid!=\"anonymous\"}[5m])))", "now (5m)"),
     ("opensrm_users_active_24h", "today"),
     ("opensrm_users_active_7d", "this week")],
    kind="stat", w=6, h=4, stat_calc="lastNotNull")

add("People active, hour by hour (IST)", "How many distinct people were active each hour. The shape of "
    "this curve decides when to run a sync, a push, or a deploy without annoying anyone.",
    [("count(count by (uid) (rate(opensrm_active_users_total[1h])))", "people active")],
    w=12, h=8)
add("What people did, by activity type", "Every event the app records, split by type. sync_ok is someone "
    "getting fresh data; sync_cached is them getting it free from the last sync; tab_view and item_view "
    "are reading; login_ok is a new session.",
    [("sum by (event) (increase(opensrm_events_total[1h]))", "{{event}}")],
    w=12, h=8)

add("How long one visit lasts", "From someone's first click to their last, with a 30-minute idle gap ending "
    "a visit. p50 is the typical sitting; compare p95 — a long tail means people keep the app open, which "
    "is good, provided the page is not slow.",
    [("histogram_quantile(0.50, sum by (le) (rate(opensrm_user_session_span_seconds_bucket[6h])))", "p50"),
     ("histogram_quantile(0.90, sum by (le) (rate(opensrm_user_session_span_seconds_bucket[6h])))", "p90"),
     ("histogram_quantile(0.99, sum by (le) (rate(opensrm_user_session_span_seconds_bucket[6h])))", "p99")],
    w=12, h=8, unit="s")
add("Which tabs people actually read", "Tab switches per hour. Tabs are a client-side switch, so this is "
    "the only evidence that a tab is used at all — a tab that never appears here is dead weight in the navbar.",
    [("topk(9, sum by (target) (increase(opensrm_events_total{event=\"tab_view\"}[1h])))", "{{target}}")],
    w=12, h=8)
add("What inside a tab people touch", "Clicks on the real controls: expanding a marks component, opening a "
    "semester, hitting refresh. A control that never fires is either undiscoverable or unwanted — both are "
    "answers, and both are worth knowing before building more like it.",
    [("topk(12, sum by (item) (increase(opensrm_item_views_total[24h])))", "{{item}}")],
    w=12, h=9)
add("Reading vs syncing, per person", "Events per person per hour, top 8. One person far above the rest is "
    "usually a stuck client reloading, not enthusiasm.",
    [("topk(8, sum by (uid) (rate(opensrm_events_total{uid!=\"anonymous\"}[1h]) * 3600))", "{{uid}}")],
    w=12, h=8)

# ── Waiting: what a person actually feels ────────────────────────────────
row("How long people wait",
    "Two completely different waiting experiences live behind the word 'sync'. A first login fetches "
    "everything cold and is slow by nature; a refresh by someone already signed in should be near-instant "
    "(it is usually answered from the last sync). This row keeps them apart on purpose.")

add("First login wait", "How long a fresh login takes, end to end, including the browser-driven portal fetch. "
    "This is the first impression — if p95 here is above about 30s, people are giving up before they see "
    "their data.",
    [("histogram_quantile(0.50, sum by (le) (rate(opensrm_login_duration_seconds_bucket[6h])))", "p50"),
     ("histogram_quantile(0.95, sum by (le) (rate(opensrm_login_duration_seconds_bucket[6h])))", "p95")],
    w=12, h=8, unit="s")
add("Refresh wait, split by how it was answered", "cache = answered from the last sync (should be "
    "milliseconds). joined = waited on a sync already running for the same account. synced = a real "
    "round trip. If 'cache' is not the fastest line, caching is not working.",
    [("histogram_quantile(0.50, sum by (le, kind) (rate(opensrm_refresh_duration_seconds_bucket[6h])))",
      "{{kind}} p50")],
    w=12, h=8, unit="s")
add("Refreshes answered from cache vs real syncs", "The share of refresh requests that cost the portal "
    "nothing. Higher is better for both speed and the portal's rate limit — a drop here means the cache "
    "window is being missed by real traffic patterns.",
    [("sum by (kind) (increase(opensrm_refresh_duration_seconds_count[1h]))", "{{kind}}")],
    w=12, h=8)

# ── The two data sources, separately ─────────────────────────────────────
row("Where the sync time goes",
    "The portal (JSP pages over HTTP) and SCOPE (SOAP) are separate upstreams with separate failure modes. "
    "Keeping them apart is what makes 'the sync is slow' answerable — it is nearly always ONE of them.")

add("Portal vs SCOPE vs disk", "Median seconds each part of a sync costs. Portal should dominate; persist "
    "(writing to SQLite) should be milliseconds. A persist line climbing means the disk is the problem, "
    "not the network.",
    [("histogram_quantile(0.50, sum by (le, phase) (rate(opensrm_sync_phase_duration_seconds_bucket[6h])))",
      "{{phase}} p50")],
    w=12, h=8, unit="s")
add("Share of the wait, by source", "The same thing as a proportion: what fraction of a person's wait is the "
    "portal, SCOPE, and disk. Quote this number, not the total, when arguing about where to optimise.",
    [("sum by (phase) (rate(opensrm_sync_phase_duration_seconds_sum[6h])) "
      "/ clamp_min(sum(rate(opensrm_sync_phase_duration_seconds_sum[6h])), 0.0001)", "{{phase}}")],
    w=12, h=8, unit="percentunit")
add("SCOPE: which operation is slow", "Every SOAP operation by median cost. Five ops dominate a run "
    "(personal details, subjects, hourwise attendance, credit status, exam details) while the rest are "
    "sub-second — a new name appearing high on this list is upstream drift worth reacting to.",
    [("topk(10, histogram_quantile(0.50, sum by (le, op) "
      "(rate(opensrm_scope_op_duration_seconds_bucket[6h]))))", "{{op}} p50")],
    w=12, h=9, unit="s")
add("SCOPE: operation outcomes", "ok vs error per operation. Errors clustered on ONE op is that endpoint "
    "misbehaving; errors across all of them is the session or the network.",
    [("sum by (op, outcome) (increase(opensrm_scope_op_total[6h]))", "{{op}} {{outcome}}")],
    w=12, h=9)

# ── Storage and freshness ────────────────────────────────────────────────
row("Storage and freshness",
    "How much room the data takes, how big one person's footprint is, and how stale the freshest data in "
    "the system is. A frozen timestamp here explains every 'nothing is updating' report before you read a log.")

add("How much space one person takes", "The distribution of per-account storage (attendance, marks, subjects, "
    "SCOPE blobs and photo together). A synced student sits around 50-80KB today; an account far to the "
    "right is one whose SCOPE blob is bloated, and the 4MB bucket should stay empty.",
    [("opensrm_user_db_bytes_bucket", "{{le}}")],
    w=12, h=8, unit="bytes")
add("Time since anything changed", "Seconds since the freshest data in the whole system. If sync age climbs "
    "past a day while the app looks healthy, nobody is syncing — that is the difference between a quiet "
    "product and a broken one.",
    [("opensrm_last_sync_age_seconds", "since last sync"),
     ("opensrm_last_usage_event_age_seconds", "since last recorded event")],
    w=12, h=8, unit="s")
add("Database size and rows", "Main file, WAL, and the account count together. Usage events are "
    "retention-managed (365d): growth there faster than adoption means pruning stopped.",
    [("opensrm_db_size_bytes", "db file"), ("opensrm_db_wal_bytes", "wal"),
     ("opensrm_rows_usage_events", "usage_events rows")],
    w=12, h=8)

# ── Errors, per person ───────────────────────────────────────────────────
row("Errors people hit",
    "Who is failing and on what. Broken down by the route rule (never the raw path — a path carries a "
    "netid) and by event type, so one person's broken login can be told apart from everyone's.")

add("Failed logins and syncs per person", "Error events per person per hour. One name going up alone is that "
    "account's credentials; every name going up together is the portal or the network.",
    [("topk(8, sum by (uid) (rate(opensrm_events_total{event=~\"login_fail|sync_fail|feedback_fill_fail\"}[1h]) * 3600))",
      "{{uid}}")],
    w=12, h=8)
add("Errors by route", "HTTP 5xx per route rule. The route name is the rule pattern (/api/login), never the "
    "URL, so this cannot leak who hit it.",
    [("topk(8, sum by (route) (rate(opensrm_http_requests_total{status=~\"5..\"}[1h]) * 3600))", "{{route}}")],
    w=12, h=8)
add("Slow requests by route", "p95 latency per route. Sync routes legitimately run seconds; a static page in "
    "this list is a real problem.",
    [("topk(8, histogram_quantile(0.95, sum by (le, route) (rate(opensrm_http_request_duration_seconds_bucket[1h]))))",
      "{{route}}")],
    w=12, h=8, unit="s")

dashboard = {
    "uid": "opensrm-observability",
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
