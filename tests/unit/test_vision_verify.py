#!/usr/bin/env python3
"""A provider outage must never be reported as a UI regression (W8.6a).

Drives the REAL `scripts/vision_verify.py` against a stub provider through
`VISION_API_BASE` - the seam CI leaves unset, so nothing about the classification
is mocked here. Three states, three outcomes:

  every pair 503     -> UNREACHABLE rows, exit 3, no mismatch anywhere
  one pair 503       -> that pair UNREACHABLE, exit 0, the rest judged MATCH
  every page broken  -> DIFF rows, exit 1, "REAL UI REGRESSION" in the summary

Before the split all three shapes exited 1 with one shared count, so every red
e2e run on the branch had to be re-diagnosed by hand to find out which one it
was. Reasoning and the decision: notes/DECISION-w8.6a-vision-unreachable.md
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "scripts", "vision_verify.py")
ROUTES = ["dashboard", "attendance"]
VIEWPORTS = ["390x844", "1440x900"]

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % name)
    else:
        FAIL += 1
        print("  FAIL %s %s" % (name, detail))


class Stub(BaseHTTPRequestHandler):
    """mode: ok | broken | all503 | one503 (one pair = the 3-model ladder)."""

    mode = "ok"
    seen = 0

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        Stub.seen += 1
        if Stub.mode == "all503" or (Stub.mode == "one503" and Stub.seen <= 3):
            self._send(503, {"error": {"code": 503, "message": "high demand"}})
            return
        broken = Stub.mode == "broken"
        verdict = {"broken": broken,
                   "broken_class": "b" if broken else None,
                   "defects": ["content clipped at the card edge"] if broken else [],
                   "confidence": "high"}
        self._send(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(verdict)}]}}]})

    def log_message(self, *a):
        pass


def run(mode):
    from PIL import Image

    Stub.mode, Stub.seen = mode, 0
    tmp = tempfile.mkdtemp(prefix="vision-%s-" % mode)
    cap = os.path.join(tmp, "cap")
    os.makedirs(os.path.join(cap, "screens"))
    gold = os.path.join(tmp, "golden")
    os.makedirs(gold)
    with open(os.path.join(gold, "routes.json"), "w", encoding="utf-8") as fh:
        json.dump({"tab_ids": ROUTES}, fh)
    for route in ROUTES:
        for vp in VIEWPORTS:
            Image.new("RGB", (8, 8), "white").save(
                os.path.join(cap, "screens", "%s-%s.png" % (route, vp)))

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = dict(os.environ,
               GEMINI_API_KEY="stub",
               VISION_API_BASE="http://127.0.0.1:%d/v1beta/models/" % srv.server_address[1],
               GITHUB_STEP_SUMMARY=os.path.join(tmp, "summary.md"))
    env.pop("GOOGLE_API_KEY", None)          # the key in /opt/data/.env must not leak in
    out = os.path.join(tmp, "vision")
    try:
        proc = subprocess.run(
            [sys.executable, SCRIPT, "--capture-dir", cap, "--golden", gold, "--out", out],
            capture_output=True, text=True, env=env, timeout=180)
    finally:
        srv.shutdown()
    with open(os.path.join(out, "index.json"), encoding="utf-8") as fh:
        index = json.load(fh)
    # The job-summary line is the reporting half of the fix; an old tree without
    # it leaves no summary file and the checks below say so.
    summary = ""
    if os.path.exists(env["GITHUB_STEP_SUMMARY"]):
        with open(env["GITHUB_STEP_SUMMARY"], encoding="utf-8") as fh:
            summary = fh.read()
    return proc, index, summary


def main():
    total = len(ROUTES) * len(VIEWPORTS)

    proc, index, summary = run("all503")
    print("all503: rc=%s" % proc.returncode)
    check("outage: exit 3 (nothing was verified)", proc.returncode == 3, proc.returncode)
    check("outage: every pair UNREACHABLE, none failed",
          (index.get("unreachable"), index.get("failed")) == (total, 0),
          (index.get("unreachable"), index.get("failed")))
    check("outage: no DIFF/FAIL row",
          not [p for p in index.get("pairs_detail", []) if p["verdict"] in ("DIFF", "FAIL")])
    check("outage: summary line says UNREACHABLE", "UNREACHABLE" in summary, summary[:160])
    check("outage: summary names the provider error", "HTTP 503" in summary, summary[:160])
    check("outage: never claimed as a regression", "REAL UI REGRESSION" not in proc.stdout,
          proc.stdout[-200:])

    proc, index, summary = run("one503")
    print("one503: rc=%s" % proc.returncode)
    check("one pair down: exit 0 (the rest were judged)", proc.returncode == 0, proc.returncode)
    check("one pair down: 1 UNREACHABLE + rest MATCH",
          (index.get("unreachable"), index.get("matched")) == (1, total - 1),
          (index.get("unreachable"), index.get("matched")))
    check("one pair down: summary states both counts",
          "UNREACHABLE" in summary and "MATCH" in summary, summary[:200])

    proc, index, summary = run("broken")
    print("broken: rc=%s" % proc.returncode)
    check("broken page: exit 1 (a real gate)", proc.returncode == 1, proc.returncode)
    check("broken page: every pair failed, none unreachable",
          (index.get("failed"), index.get("unreachable")) == (total, 0),
          (index.get("failed"), index.get("unreachable")))
    check("broken page: summary says REAL UI REGRESSION", "REAL UI REGRESSION" in summary,
          summary[:160])
    check("broken page: not reported as an outage", "UNREACHABLE" not in summary,
          summary[:160])

    print("\ntest_vision_verify: %d passed, %d failed" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
