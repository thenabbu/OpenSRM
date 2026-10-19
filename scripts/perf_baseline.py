#!/usr/bin/env python3
"""OpenSRM frontend performance baseline — smoothness campaign, Phase 0.

Measures the seeded dashboard under fixed CPU + network throttling so every
later phase has real numbers to compare against. Run from the worktree root:

  PLAYWRIGHT_BROWSERS_PATH=/opt/data/cache/scratch/pw-browsers \\
  .venv/bin/python scripts/perf_baseline.py --out docs/perf/baseline.md

Harness reuse (the prompt's "do not build a second harness"):
  - seeds via tests._seed.seed_rich() — the shared rich dataset
  - boots gunicorn from the running interpreter's bin dir (test_dash_fit pattern)
  - guard: tests._seed.require_own_server() — kills phantom verdicts

Honesty rules baked in:
  - /api/refresh is INTERCEPTED with {"ok": true, "cached": false} — the
    portal is never contacted; what is measured is the CLIENT's reaction to
    a successful non-cached sync (navigation / scroll / focus survival).
  - every number in the generated markdown is measured in that run.
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# ── Throttle profile (fixed — later phases must reuse these exact values) ──
CPU_RATE = 6  # Emulation.setCPUThrottlingRate
# Chrome DevTools "Slow 4G" (the preset renamed from Fast 3G): 1.62 Mbps
# down / 750 Kbps up / 150 ms RTT. CDP wants bytes/s + ms.
NET_SLOW_4G = {
    "offline": False,
    "latency": 150,
    "downloadThroughput": int(1_620_000 / 8),
    "uploadThroughput": int(750_000 / 8),
}
CPU_NOTE = "CPU throttle 6x (Emulation.setCPUThrottlingRate)"
NET_NOTE = "Slow 4G: 1.62 Mbps down / 750 Kbps up / 150 ms RTT (Network.emulateNetworkConditions)"

VIEWPORTS = [(390, 844), (1024, 768), (1366, 768), (1920, 1080)]
TABS = ["dashboard", "attendance", "timetable", "marks", "settings"]
MODALS = ["fb-modal", "delete-account-modal", "add-subject-modal"]
METRIC_VP = (1366, 768)  # laptop viewport for the throttled metric run
DATA = "/tmp/osrm-perf-baseline"

INIT_JS = r"""
window.__lt = [];
try {
  new PerformanceObserver(function (l) {
    l.getEntries().forEach(function (e) { window.__lt.push(Math.round(e.duration)); });
  }).observe({ type: 'longtask', buffered: true });
} catch (e) {}
window.__lcp = 0;
try {
  new PerformanceObserver(function (l) {
    var es = l.getEntries();
    if (es.length) window.__lcp = es[es.length - 1].startTime;
  }).observe({ type: 'largest-contentful-paint', buffered: true });
} catch (e) {}
"""

PAINT_JS = """() => {
  var paints = {};
  performance.getEntriesByType('paint').forEach(function (e) {
    paints[e.name] = Math.round(e.startTime);
  });
  var nav = performance.getEntriesByType('navigation')[0] || {};
  var rt = performance.getEntriesByType('resource');
  var rtBytes = nav.transferSize || 0;
  rt.forEach(function (r) { rtBytes += r.transferSize || 0; });
  return {
    fp: paints['first-paint'] || null,
    fcp: paints['first-contentful-paint'] || null,
    lcp: Math.round(window.__lcp || 0),
    ttfb: Math.round(nav.responseStart || 0),
    dcl: Math.round(nav.domContentLoadedEventEnd || 0),
    loadEvt: Math.round(nav.loadEventEnd || 0),
    rt_requests: rt.length + 1,
    rt_bytes: rtBytes
  };
}"""

ACTIVE_JS = """() => {
  var vis = [...document.querySelectorAll('[data-tabpanel]')]
    .filter(function (p) { return p.style.display !== 'none'; });
  return vis.map(function (p) { return p.id; }).join(',');
}"""

ANIM_JS = """() => {
  var anims = document.getAnimations();
  var run = anims.filter(function (a) { return a.playState === 'running'; });
  var infinite = run.filter(function (a) {
    try { return a.effect.getComputedTiming().iterations === Infinity; }
    catch (e) { return false; }
  });
  return {total: anims.length, running: run.length, infinite: infinite.length};
}"""


class NetMeter:
    """CDP Network events -> per-request byte rows (wire bytes incl headers)."""

    def __init__(self, cdp):
        self.rows = {}
        cdp.on("Network.responseReceived", self._resp)
        cdp.on("Network.loadingFinished", self._fin)

    def _resp(self, p):
        r = p["response"]
        self.rows[p["requestId"]] = {
            "url": r["url"], "status": r["status"],
            "type": p.get("type", "?"), "bytes": 0,
        }

    def _fin(self, p):
        row = self.rows.get(p["requestId"])
        if row is not None:
            row["bytes"] += int(p.get("encodedDataLength", 0))

    def reset(self):
        self.rows = {}

    def read(self):
        return list(self.rows.values())


def is_third_party(url):
    if not url.startswith(("http://", "https://")):
        return False  # data:/blob: URLs are inline, not a network party
    return not (url.startswith("http://127.0.0.1") or url.startswith("http://localhost"))


def summarize(rows):
    third = [r for r in rows if is_third_party(r["url"])]
    top = sorted(rows, key=lambda r: -r["bytes"])[:8]
    return {
        "n": len(rows),
        "bytes": sum(r["bytes"] for r in rows),
        "third": [{"url": r["url"], "bytes": r["bytes"], "status": r["status"]}
                  for r in sorted(third, key=lambda r: -r["bytes"])],
        "top": [{"url": r["url"], "bytes": r["bytes"]} for r in top],
    }


def kb(n):
    return f"{n / 1024:.1f} KB"


def boot_server():
    """Fresh DATA_DIR + rich seed + own gunicorn (test_dash_fit pattern)."""
    os.environ["DATA_DIR"] = DATA
    shutil.rmtree(DATA, ignore_errors=True)
    import tests._seed as seed_mod
    seed_mod.seed_rich()
    token = seed_mod.mint_token()
    gunicorn = os.environ.get("GUNICORN") or os.path.join(
        os.path.dirname(sys.executable), "gunicorn")
    if not os.path.isfile(gunicorn):
        raise SystemExit(f"FAIL[guard]: missing {gunicorn} "
                         "(run this script with the repo .venv's python)")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = subprocess.Popen(
        [gunicorn, "-w", "1", "--threads", "4", "-b", f"127.0.0.1:{port}",
         "app.app:app"], cwd=str(REPO),
        env={**os.environ, "PYTHONPATH": str(REPO)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", port), 0.5).close()
            break
        except OSError:
            time.sleep(0.5)
    else:
        raise SystemExit("FAIL[guard]: own server never came up")
    seed_mod.require_own_server(f"http://127.0.0.1:{port}")
    return srv, f"http://127.0.0.1:{port}", token


def add_auth(ctx, base, token):
    ctx.add_cookies([{"name": "srm_session", "value": token, "url": base}])


def measure_nav(page, meter, goto_fn, label, settle_ms=900):
    """Run one navigation under throttle; return paint + byte metrics."""
    meter.reset()
    t0 = time.time()
    goto_fn()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(settle_ms)  # LCP finalize + runtime CSS compile
    wall_ms = int((time.time() - t0) * 1000)
    m = page.evaluate(PAINT_JS)
    m["wall_ms"] = wall_ms
    m["cdp"] = summarize(meter.read())
    m["label"] = label
    return m


def run_metrics(browser, base, token, meter_factory):
    """Throttled run: cold, warm, 10 tab switches, animations.

    The context blocks service workers on purpose: a SW-mediated response is
    invisible to a page-level CDP session (its bytes land on the worker's
    target), which made warm transfers read ~1.5 KB while resource timing
    said 86 KB. Blocking SW makes warm = pure HTTP-cache behaviour with
    fully visible wire bytes; the SW's own cache behaviour is verified
    separately (Phase 3 done-check, DevTools Network panel)."""
    ctx = browser.new_context(viewport={"width": METRIC_VP[0],
                                        "height": METRIC_VP[1]},
                              service_workers="block")
    add_auth(ctx, base, token)
    page = ctx.new_page()
    page.add_init_script(INIT_JS)
    cdp = ctx.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": CPU_RATE})
    cdp.send("Network.emulateNetworkConditions", NET_SLOW_4G)
    meter = meter_factory(cdp)

    out = {}
    print("[metrics] cold load (throttled, SW blocked) ...")
    out["cold"] = measure_nav(page, meter,
                              lambda: page.goto(base + "/", wait_until="load"),
                              "cold")
    print(f"  fcp={out['cold']['fcp']}ms lcp={out['cold']['lcp']}ms "
          f"wall={out['cold']['wall_ms']}ms bytes={out['cold']['cdp']['bytes']}")

    print("[metrics] warm reload (throttled, SW blocked) ...")
    out["warm"] = measure_nav(page, meter,
                              lambda: page.reload(wait_until="load"),
                              "warm")
    print(f"  fcp={out['warm']['fcp']}ms lcp={out['warm']['lcp']}ms "
          f"wall={out['warm']['wall_ms']}ms bytes={out['warm']['cdp']['bytes']}")

    out["animations"] = page.evaluate(ANIM_JS)
    print(f"[metrics] running animations on dashboard: {out['animations']}")

    # 10 tab switches: attendance->timetable->marks->settings->dashboard x2
    print("[metrics] 10 tab switches (throttled) ...")
    page.evaluate("window.__lt = []")
    order = ["attendance", "timetable", "marks", "settings", "dashboard"] * 2
    switch_ms = []
    for name in order:
        t0 = time.time()
        page.locator(f'[data-tab="{name}"]:visible').first.click()
        page.wait_for_timeout(150)
        switch_ms.append(int((time.time() - t0) * 1000))
    long_tasks = page.evaluate("window.__lt.slice()")
    out["switches"] = {"n": len(order), "long_tasks_ms": long_tasks,
                       "click_wall_ms": switch_ms}
    print(f"  long tasks >50ms: {long_tasks or 'none'}")
    ctx.close()
    return out


def run_sync_probe(browser, base, token):
    """Sync survival probe on a MOBILE viewport (mobile is where pages
    scroll — desktop attendance fits 768px, scrollY stays 0 there).

    Sets scroll + focus + a JS sentinel, then fires an intercepted
    successful sync (no portal). Navigation is detected by polling the
    sentinel with Execution-context-destroyed tolerance: expect_navigation
    missed real reloads in practice, while the sentinel flips either way."""
    from playwright.sync_api import Error as PWError
    # no is_mobile: with device_scale_factor=2 Chromium scaled the layout
    # viewport to 449px under is_mobile and Playwright's tap point landed
    # outside the dock (hit intercepted by main content). Touch realism is
    # not what this probe measures; scroll/focus survival is.
    ctx = browser.new_context(viewport={"width": 390, "height": 844},
                              has_touch=True, service_workers="block")
    add_auth(ctx, base, token)
    page = ctx.new_page()
    cdp = ctx.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": CPU_RATE})
    cdp.send("Network.emulateNetworkConditions", NET_SLOW_4G)
    print("[metrics] sync probe (mobile 390x844, intercepted /api/refresh, "
          "no portal) ...")
    page.goto(base + "/", wait_until="networkidle")
    page.wait_for_timeout(600)
    # focus the visible dock's dashboard button — same end state as a tap
    # (switchTab calls btn.focus()); avoids a hit-test dispatch entirely
    page.evaluate("""() => {
      var b = [...document.querySelectorAll('[data-tab="dashboard"]')]
        .filter(function (x) { return x.offsetParent !== null; })[0];
      if (b) b.focus();
    }""")
    page.wait_for_timeout(150)
    page.evaluate("window.scrollTo(0, 400)")
    page.wait_for_timeout(200)
    before = page.evaluate("""() => {
      window.__alive = 1;
      return {
        scroll: window.scrollY,
        focus: document.activeElement && (document.activeElement.dataset.tab
                || document.activeElement.id || document.activeElement.tagName),
        hash: location.hash,
        docSH: document.documentElement.scrollHeight,
        docCH: document.documentElement.clientHeight
      };
    }""")
    if before["scroll"] == 0:
        print(f"  WARN: mobile doc not scrollable "
              f"(sh={before['docSH']} ch={before['docCH']}) — scroll "
              "survival not measurable on this seed")
    ctx.route("**/api/refresh", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body='{"ok": true, "cached": false}'))
    navigated = False
    t0 = time.time()
    page.locator('[data-refresh]:visible').first.click()
    while time.time() - t0 < 8:
        try:
            if not page.evaluate("window.__alive !== undefined"):
                navigated = True
                break
        except PWError:
            navigated = True   # execution context destroyed = navigation
            break
        page.wait_for_timeout(100)
    if navigated:
        try:
            page.wait_for_load_state("load", timeout=10000)
        except PWError:
            pass
    else:
        page.wait_for_timeout(1500)  # no navigation: let a soft refresh finish
    after = page.evaluate("""() => ({
      scroll: window.scrollY,
      focus: document.activeElement && (document.activeElement.dataset.tab
              || document.activeElement.id || document.activeElement.tagName),
      hash: location.hash,
      alive: window.__alive !== undefined,
      navType: (performance.getEntriesByType('navigation')[0] || {}).type || '?'
    })""")
    print(f"  navigated={navigated} scroll {before['scroll']}->{after['scroll']} "
          f"focus {before['focus']}->{after['focus']} alive={after['alive']} "
          f"navType={after['navType']}")
    ctx.close()
    return {"navigated": navigated, "before": before, "after": after}


def run_shots(browser, base, token, shots_dir):
    """Unthrottled captures: login + 5 tabs + 3 modals, at every viewport.
    Entry-state (clean) shots first; modals are opened LAST so no overlay
    leaks into a tab shot."""
    shots_dir.mkdir(parents=True, exist_ok=True)
    names = []
    for w, h in VIEWPORTS:
        vp = f"{w}x{h}"
        print(f"[shots] {vp} ...")
        # login (no cookie)
        ctx = browser.new_context(viewport={"width": w, "height": h},
                                  device_scale_factor=2,
                                  is_mobile=(w < 600), has_touch=(w < 600))
        pg = ctx.new_page()
        pg.goto(base + "/login", wait_until="networkidle")
        pg.wait_for_timeout(400)
        assert "OpenSRM" in pg.title(), pg.title()
        f = shots_dir / f"baseline-{vp}-login.png"
        pg.screenshot(path=str(f))
        names.append(f.name)
        ctx.close()
        # authenticated: dashboard entry shot FIRST, then tabs, then modals
        ctx = browser.new_context(viewport={"width": w, "height": h},
                                  device_scale_factor=2,
                                  is_mobile=(w < 600), has_touch=(w < 600))
        add_auth(ctx, base, token)
        pg = ctx.new_page()
        pg.goto(base + "/", wait_until="networkidle")
        pg.wait_for_timeout(500)
        assert "zz9999" in pg.title(), pg.title()
        f = shots_dir / f"baseline-{vp}-dashboard.png"
        pg.screenshot(path=str(f))
        names.append(f.name)
        for tab in TABS[1:]:
            # hash-only nav does not switch tabs (dash.js restores on load):
            # always goto + reload before shooting a specific tab
            pg.goto(base + "/#" + tab, wait_until="load")
            pg.reload(wait_until="networkidle")
            pg.wait_for_timeout(400)
            active = pg.evaluate(ACTIVE_JS)
            assert active == f"tab-{tab}", f"expected tab-{tab}, got {active!r}"
            f = shots_dir / f"baseline-{vp}-{tab}.png"
            pg.screenshot(path=str(f))
            names.append(f.name)
        # modals last (clean entry states already captured above)
        pg.goto(base + "/", wait_until="load")
        pg.reload(wait_until="networkidle")
        pg.wait_for_timeout(400)
        for mid in MODALS:
            shown = pg.evaluate(
                "id => { var d = document.getElementById(id);"
                "if (d) { d.showModal(); return true; } return false; }", mid)
            if not shown:
                print(f"  WARN: {mid} not present (skipped)")
                continue
            pg.wait_for_timeout(300)
            short = {"fb-modal": "modal-fb",
                     "delete-account-modal": "modal-delete",
                     "add-subject-modal": "modal-addsubject"}[mid]
            f = shots_dir / f"baseline-{vp}-{short}.png"
            pg.screenshot(path=str(f))
            names.append(f.name)
            pg.evaluate(
                "id => { var d = document.getElementById(id);"
                "if (d) d.close(); }", mid)
            pg.wait_for_timeout(150)
        ctx.close()
    return names


def render_md(res, sha, branch, browser_ver, shot_names, shots_dir):
    c, w = res["cold"], res["warm"]
    sw = res["switches"]
    sy = res["sync"]
    an = res["animations"]
    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
    L = []
    L.append("# OpenSRM frontend perf baseline")
    L.append("")
    L.append(f"Measured {now} on branch `{branch}` @ `{sha}` — Chromium "
             f"{browser_ver}. Throttle: {CPU_NOTE}; {NET_NOTE}.")
    L.append("Generated by `scripts/perf_baseline.py` (seeded local instance, "
             "shared rich dataset `tests._seed.seed_rich`, no portal contact).")
    L.append("Metrics run with service workers BLOCKED: SW-mediated "
             "responses are invisible to a page-level CDP session, so warm "
             "bytes here are true HTTP-cache wire bytes; the SW's own cache "
             "behaviour is checked separately with the DevTools Network "
             "panel. The sync probe runs on mobile 390x844 (mobile is where "
             "the document scrolls).")
    L.append("Re-run: `PLAYWRIGHT_BROWSERS_PATH=/opt/data/cache/scratch/pw-browsers "
             ".venv/bin/python scripts/perf_baseline.py --out <file>`.")
    L.append("")
    L.append("## Load (1366x768, throttled)")
    L.append("")
    L.append("| metric | cold | warm |")
    L.append("|---|---|---|")
    for k, label in [("fp", "first-paint (ms)"), ("fcp", "first-contentful-paint (ms)"),
                     ("lcp", "LCP (ms)"), ("ttfb", "TTFB (ms)"),
                     ("dcl", "DOMContentLoaded (ms)"), ("loadEvt", "load event (ms)"),
                     ("wall_ms", "wall clock to networkidle (ms)")]:
        L.append(f"| {label} | {c.get(k)} | {w.get(k)} |")
    L.append(f"| requests (resource timing) | {c['rt_requests']} | {w['rt_requests']} |")
    L.append(f"| transferred bytes (CDP wire) | {c['cdp']['bytes']} "
             f"({kb(c['cdp']['bytes'])}) | {w['cdp']['bytes']} ({kb(w['cdp']['bytes'])}) |")
    L.append(f"| same-origin bytes (resource timing) | {c['rt_bytes']} "
             f"({kb(c['rt_bytes'])}) | {w['rt_bytes']} ({kb(w['rt_bytes'])}) |")
    L.append("")
    L.append("## Third-party requests (cold)")
    L.append("")
    if c["cdp"]["third"]:
        for t in c["cdp"]["third"]:
            L.append(f"- {t['url']} — {t['bytes']} bytes (HTTP {t['status']})")
    else:
        L.append("- none")
    L.append("")
    L.append("## Top requests by bytes (cold)")
    L.append("")
    for t in c["cdp"]["top"]:
        L.append(f"- {t['bytes']:>8} B  {t['url']}")
    L.append("")
    L.append(f"## Tab switches ({sw['n']} switches, 6x CPU)")
    L.append("")
    if sw["long_tasks_ms"]:
        L.append(f"Long tasks (>50 ms): {sw['long_tasks_ms']} — total "
                 f"{sum(sw['long_tasks_ms'])} ms")
    else:
        L.append("Long tasks (>50 ms): none")
    L.append(f"Per-click wall time: {sw['click_wall_ms']}")
    L.append("")
    L.append("## Sync probe (intercepted `/api/refresh` -> `{ok:true, cached:false}`)")
    L.append("")
    L.append(f"- navigation occurred: **{sy['navigated']}** "
             f"(nav entry type after: `{sy['after']['navType']}`; sentinel "
             f"`window.__alive` survives: {sy['after']['alive']})")
    L.append(f"- doc at probe: scrollHeight {sy['before'].get('docSH')} / "
             f"clientHeight {sy['before'].get('docCH')} (mobile 390x844)")
    L.append(f"- scroll position: {sy['before']['scroll']} -> {sy['after']['scroll']}")
    L.append(f"- focused element: `{sy['before']['focus']}` -> `{sy['after']['focus']}`")
    L.append(f"- page JS state survived (`window.__alive`): {sy['after']['alive']}")
    L.append(f"- hash: `{sy['before']['hash']}` -> `{sy['after']['hash']}`")
    L.append("")
    L.append("## Running animations (dashboard tab, after warm load)")
    L.append("")
    L.append(f"- total {an['total']}, running {an['running']}, "
             f"infinite {an['infinite']}")
    L.append("")
    L.append("## Screenshots (before-captures, main code)")
    L.append("")
    L.append(f"{len(shot_names)} shots in `{shots_dir}/`: login + dashboard + "
             "5 tabs + 3 modals at 390x844, 1024x768, 1366x768, 1920x1080 "
             "(device_scale_factor 2).")
    for n in sorted(shot_names):
        L.append(f"- {n}")
    L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/perf/baseline.md",
                    help="markdown report path (default docs/perf/baseline.md)")
    ap.add_argument("--shots-dir", default="docs/screenshots/perf-baseline")
    ap.add_argument("--skip-shots", action="store_true")
    args = ap.parse_args()

    srv, base, token = boot_server()
    print(f"[boot] server at {base}, DATA_DIR={DATA}")
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=[
                "--font-render-hinting=none", "--force-color-profile=srgb"])
            browser_ver = browser.version
            res = run_metrics(browser, base, token,
                              lambda cdp: NetMeter(cdp))
            res["sync"] = run_sync_probe(browser, base, token)
            shot_names = []
            shots_dir = REPO / args.shots_dir
            if not args.skip_shots:
                shot_names = run_shots(browser, base, token, shots_dir)
            browser.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except subprocess.TimeoutExpired:
            srv.kill()
    sha = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    branch = subprocess.run(["git", "-C", str(REPO), "--no-pager", "branch",
                             "--show-current"],
                            capture_output=True, text=True).stdout.strip()
    md = render_md(res, sha, branch, browser_ver, shot_names,
                   args.shots_dir)
    out_path = REPO / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md)
    print(f"\n[done] wrote {out_path}")
    print(md)


if __name__ == "__main__":
    main()
