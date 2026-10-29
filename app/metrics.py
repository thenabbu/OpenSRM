"""In-process observability: thread-safe counters, timers and gauges.

`GET /internal/metrics` renders this as Prometheus text (secret-header auth,
same contract as /internal/push/tick — see app.app).

ponytail: three dicts behind ONE lock. Gunicorn runs a single gthread worker
for this app, so process-local IS the whole picture; a multi-worker deploy
would need an aggregating store (StatsD / Pushgateway) — that is the upgrade
path, not an abstraction shipped now.
"""
import threading

_lock = threading.Lock()
_counters = {}   # (name, ((label, value), ...)) -> int
_hists = {}      # (name, labels) -> {"buckets": [...], "sum": float, "count": int}
_gauges = {}     # name -> callable() -> float

# duration buckets (seconds): syncs run ~2s warm .. 150s (pipeline deadline)
DURATION_BUCKETS = (1, 2, 5, 10, 20, 30, 60, 90, 120, 150)
# captcha attempts per login: 0 (rejected before any submit) .. 5
ATTEMPT_BUCKETS = (0, 1, 2, 3, 4, 5)

_BUCKET_SETS = {
    "opensrm_sync_duration_seconds": DURATION_BUCKETS,
    "opensrm_captcha_attempts_per_login": ATTEMPT_BUCKETS,
    # HTTP request latency: healthchecks land <10ms, dashboard renders 10-300ms,
    # a sync-backed refresh runs 2-150s. One bucket set spans all three so a
    # single histogram answers "how slow is anything" without label-splitting
    # the bucket layout.
    "opensrm_http_request_duration_seconds": (0.005, 0.01, 0.025, 0.05, 0.1,
                                              0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 150),
    # scope SOAP round trips: warm 150-400ms, cold 1-3s, timeout 15s
    "opensrm_scope_call_duration_seconds": (0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 15, 30),
    # portal page fetches: each is one HTTP GET through the egress proxy
    "opensrm_portal_fetch_duration_seconds": (0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60),
    # sqlite statements: a healthy read is <1ms, a busy write can hit seconds
    "opensrm_db_query_duration_seconds": (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.5, 1, 5),
    # push delivery: the push service either answers fast or times out at 5s
    "opensrm_push_send_duration_seconds": (0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10),
}


def _key(name, labels):
    return (name, tuple(sorted(labels.items())))


def inc(name, **labels):
    """Counter +1 (thread-safe)."""
    k = _key(name, labels)
    with _lock:
        _counters[k] = _counters.get(k, 0) + 1


def get(name, **labels):
    """Current counter value (0 when never incremented)."""
    with _lock:
        return _counters.get(_key(name, labels), 0)


def observe(name, value, **labels):
    """Record one value into a histogram bucket set (thread-safe)."""
    buckets = _BUCKET_SETS.get(name, DURATION_BUCKETS)
    v = float(value)
    k = _key(name, labels)
    with _lock:
        h = _hists.get(k)
        if h is None:
            h = _hists[k] = {"buckets": [0] * len(buckets), "sum": 0.0, "count": 0}
        h["sum"] += v
        h["count"] += 1
        for i, le in enumerate(buckets):
            if v <= le:
                h["buckets"][i] += 1


def hist_count(name, **labels):
    """Observations recorded for one histogram series."""
    with _lock:
        h = _hists.get(_key(name, labels))
        return h["count"] if h else 0


def gauge(name, fn):
    """Register a render-time gauge provider. Keep fn cheap and re-entrant-free
    (it runs without the lock held, but must not assume ordering)."""
    with _lock:
        _gauges[name] = fn


def reset():
    """Drop every series (tests only)."""
    with _lock:
        _counters.clear()
        _hists.clear()


def _esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\"').replace("\n", "\\n")


def _labels(labels, extra=None):
    parts = [f'{k}="{_esc(v)}"' for k, v in labels]
    if extra is not None:
        parts.append(f'le="{_esc(extra)}"')
    return "{" + ",".join(parts) + "}" if parts else ""


def render():
    """Prometheus text exposition (v0.0.4): counters, histograms, gauges."""
    lines, seen_types = [], set()
    with _lock:
        counters = sorted(_counters.items())
        hist_groups = {}
        for (name, labels), h in _hists.items():
            hist_groups.setdefault(name, []).append((labels, h))
        gauges = list(_gauges.items())

    def _typed(name, kind):
        if name not in seen_types:
            seen_types.add(name)
            lines.append(f"# TYPE {name} {kind}")

    for (name, labels), val in counters:
        _typed(name, "counter")
        lines.append(f"{name}{_labels(labels)} {val}")
    for name in sorted(hist_groups):
        _typed(name, "histogram")
        bucket_set = _BUCKET_SETS.get(name, DURATION_BUCKETS)
        for labels, h in sorted(hist_groups[name]):
            for le, n in zip(bucket_set, h["buckets"]):
                lines.append(f"{name}_bucket{_labels(labels, le)} {n}")
            lines.append(f"{name}_bucket{_labels(labels, '+Inf')} {h['count']}")
            lines.append(f"{name}_sum{_labels(labels)} {h['sum']}")
            lines.append(f"{name}_count{_labels(labels)} {h['count']}")
    for name, fn in gauges:
        _typed(name, "gauge")
        try:
            v = float(fn())
        except Exception:
            v = 0.0
        lines.append(f"{name} {v}")
    return "\n".join(lines) + ("\n" if lines else "")
