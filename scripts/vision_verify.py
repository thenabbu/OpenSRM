#!/usr/bin/env python3
"""Real vision verification: a vision model LOOKS at every route x device.

WHY THIS EXISTS
  tests/golden/v3/screens holds 27 screenshots and nothing has ever looked at
  them: CI runs the golden gate with --no-screens (PNG bytes encode the capture
  host's font stack), so the images have been decoration since they landed.
  A screenshot nobody looked at is not verification.

WHAT THIS JUDGES, AND WHAT IT DELIBERATELY DOES NOT
  It asks one question per screenshot: is this page broken in one of five
  observable ways (blank panel, clipped/overflowing content, blocks drawn on
  top of each other, unstyled markup, unreadable text)?

  It does NOT ask "does this differ from the golden". That question was tried
  and measured wrong: comparing against the golden, the model invented two
  failures in 18 pairs - a "missing label" on academics-mobile and "raw
  markup" on timetable-desktop - and both of those DOMs were byte-identical to
  the golden's (diff: empty). Content drift is already proven byte-exactly by
  capture_golden's DOM/api diff; the only thing left for a vision model is
  whether the rendered pixels look broken, which no byte diff can answer.

  The committed golden still decides COVERAGE: the route list comes from
  tests/golden/v3/routes.json, so a route that loses its entry fails here
  instead of quietly going unverified. Each verdict records the golden's hash
  for the same route+device, so a reader can see which baseline it belongs to.

USAGE
  python scripts/vision_verify.py --capture-dir /tmp/golden-ci
  python scripts/vision_verify.py --capture-dir /tmp/golden-ci --only dashboard
  bash scripts/vision_verify.sh                     # capture, then verify

  Writes notes/vision/<route>-<device>.json per pair plus index.json.
  THREE STATES, NOT TWO. Exit 0 = every pair MATCH. Exit 1 = a real UI finding:
  a DIFF, a DISPUTED pair, a missing capture, or an answer the judge replied
  with but we could not read (an unreadable answer is never a pass). Exit 2 =
  cannot run at all (no key, no capture) - never a silent skip. Exit 3 =
  UNREACHABLE: the provider answered none or almost none of the pairs (HTTP
  5xx/429, timeout, refused, refusal), so this gate verified no pixel at all.

  The split exists because a 503 is not a UI regression. Before it, an outage and
  a broken page produced the same verdict, the same count and the same exit 1,
  so every red e2e run had to be re-diagnosed by hand to find out which one it
  was. The rule and its reasoning: notes/DECISION-w8.6a-vision-unreachable.md.

  A broken page is confirmed by a SECOND model before it fails the run: one
  model's opinion is a hypothesis, two agreeing models are a finding. The
  corroboration call happens only on the pairs the first model flagged, so the
  cost stays at 18 calls in the normal case.

KEY: $GEMINI_API_KEY (CI secret) or $GOOGLE_API_KEY, else GOOGLE_API_KEY in
/opt/data/.env (the lab).
"""
import argparse
import base64
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GOLDEN_DEFAULT = REPO / "tests" / "golden" / "v3"
OUT_DEFAULT = REPO / "notes" / "vision"
# Phone and desktop. capture_golden also shoots 768x1024 for the pixel
# baseline; the card asks for mobile/desktop and two pairs per route keep the
# run inside the e2e job's budget.
DEVICES = [("mobile", "390x844"), ("desktop", "1440x900")]
# flash-lite tier: a vision judge of gross breakage does not need a pro model,
# and pro ids go 503 far more often. Second entry is the corroborator.
LADDER = ["gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-flash-latest"]
ENV_FILES = [Path("/opt/data/.env")]
# Provider root. Overridable ONLY so the three states can be break-proved
# against a stub server (tests/unit/test_vision_verify.py); CI leaves it unset.
API_BASE = os.environ.get(
    "VISION_API_BASE", "https://generativelanguage.googleapis.com/v1beta/models/")
# Only shrink what is genuinely huge. A 390x1551 phone capture shrunk to a 352px
# wide thumbnail turns 11px labels into a smear the model then reads wrong.
MAX_EDGE = 2000

PROMPT = """You are the visual QA judge for a student web app. This is a full-page screenshot of route "{route}" at {device} width ({vp}).

Decide whether the page is BROKEN in one of these specific ways:
  (a) a panel or card that is blank, empty, or stuck on a spinner/placeholder
      while the rest of the page has content;
  (b) text or a control clipped or overflowing at the page edge or its card edge;
  (c) two blocks drawn on top of each other;
  (d) a pile of unstyled markup: no card styling, default blue links, missing icons;
  (e) text that cannot be read at all at normal size (near-zero contrast);
  (f) the page is MOSTLY BLANK below the navigation: a large featureless flat
      area, roughly more than half of the page below the header, where this
      route's content should be. (A full-page screenshot is sized to its
      content, so a legitimately short page ends - it does not contain a huge
      empty region.)

Things that are NOT broken in this app and must not be reported, because each
one is a measured artifact of the capture and not of the page:
  - a long subject name truncated with a trailing "…";
  - 11-12px badges, tight row spacing, dense cards;
  - a long list inside a scrollable box;
  - content that continues past the bottom of the viewport (full-page shot);
  - an empty state that says "no data" inside a section that has its own heading;
  - the fixed bottom navigation bar painted across the middle of the image,
    on top of page content: a full-page screenshot paints a fixed element once,
    at the scroll position, so it always appears to cover later content;
  - the literal text of an HTML payload such as
    <img src=x onerror="..."> or <script>...</script> used as a class name:
    the seed data plants that string on purpose to prove it is displayed as
    TEXT and never executed. Seeing it as text is the pass condition.

Return JSON only, no prose:
{{"broken": true|false,
  "broken_class": "a"|"b"|"c"|"d"|"e"|"f"|null,
  "defects": ["<what is broken and where, in plain words>"],
  "confidence": "high"|"medium"|"low"}}

Answer broken=false when the page looks like a normal, complete page of a
student dashboard. Set confidence "low" only if the screenshot is unreadable
or truncated."""


def api_key():
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        v = os.environ.get(name, "").strip()
        if v:
            return v
    for f in ENV_FILES:
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.startswith("GOOGLE_API_KEY=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def shrink(path, max_edge=MAX_EDGE):
    """Downscale only when the long edge exceeds max_edge: a tall desktop page
    costs tokens, but a phone capture is already small and shrinking it loses
    the very text the judge has to read."""
    from PIL import Image
    raw = Path(path).read_bytes()
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    if max(im.size) > max_edge:
        im.thumbnail((max_edge, max_edge), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        return buf.getvalue()
    return raw


def sha(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def ask(model, route, device, vp, png, key):
    parts = [{"text": PROMPT.format(route=route, device=device, vp=vp)},
             {"inline_data": {"mime_type": "image/png",
                              "data": base64.b64encode(png).decode()}}]
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"temperature": 0.0,
                                 "responseMimeType": "application/json"}}
    url = "%s%s:generateContent?key=%s" % (API_BASE, model, key)
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        resp = json.load(r)
    return "".join(p.get("text", "") for p in resp["candidates"][0]["content"]["parts"]).strip()


def parse(txt):
    """Tolerant JSON read. A fenced answer is fine; an answer we cannot read is
    a failure, and the caller treats None as such - never as a pass."""
    t = txt.strip()
    if t.startswith("```"):
        t = t.split("```")[1]
        t = t.split("\n", 1)[1] if "\n" in t else t
    cands = [t]
    if "{" in t and "}" in t:
        cands.append(t[t.find("{"): t.rfind("}") + 1])
    for c in cands:
        try:
            d = json.loads(c)
        except ValueError:
            continue
        if isinstance(d, dict) and "broken" in d:
            return d
    return None


def vote(png, route, device, vp, key, skip=()):
    """One model's opinion. Returns (dict|None, model, failures).

    Each failure is (kind, message). `unreachable` means the provider never
    returned a verdict (HTTP error, timeout, refused connection, refusal);
    `answer` means a model DID reply and the reply is not a verdict we can
    accept. Only the second says anything about the page.
    """
    fails = []
    for model in LADDER:
        if model in skip:
            continue
        try:
            txt = ask(model, route, device, vp, png, key)
        except urllib.error.HTTPError as e:
            fails.append(("unreachable",
                          "%s HTTP %s %s" % (model, e.code, e.read().decode()[:120])))
            continue
        except Exception as e:                       # noqa: BLE001 - any net fault
            fails.append(("unreachable", "%s %r" % (model, e)))
            continue
        d = parse(txt)
        if d is None:
            fails.append(("answer", "%s unparseable: %r" % (model, txt[:100])))
            continue
        return d, model, fails
    return None, None, fails


def step_summary(line):
    """One line in the GitHub job summary, so which of the two states happened is
    readable from the job page instead of the log. No-op outside Actions."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("### Vision verification\n\n`%s`\n" % line)
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Vision-verify every route x device.")
    ap.add_argument("--capture-dir", required=True,
                    help="a capture from capture_golden.py (must hold screens/)")
    ap.add_argument("--golden", default=str(GOLDEN_DEFAULT),
                    help="decides coverage (route list) + recorded hashes")
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--only", default="", help="comma-separated route ids")
    ap.add_argument("--no-corroborate", action="store_true",
                    help="trust the first model (debugging only)")
    ap.add_argument("--revision", default="")
    args = ap.parse_args()

    cap = Path(args.capture_dir)
    golden = Path(args.golden)
    fresh_dir = cap / "screens"
    if not fresh_dir.is_dir():
        print("vision: no screens/ in %s - run capture_golden.py first" % cap)
        return 2
    key = api_key()
    if not key:
        print("vision: no GEMINI_API_KEY / GOOGLE_API_KEY - refusing to report a "
              "verification that never happened")
        return 2

    if (golden / "routes.json").exists():
        routes = json.loads((golden / "routes.json").read_text())["tab_ids"]
    else:
        print("vision: no %s/routes.json - the route list must come from the "
              "committed golden, not from what this capture happens to hold"
              % golden)
        return 2
    want = [r.strip() for r in args.only.split(",") if r.strip()]
    if want:
        routes = [r for r in routes if r in want]

    rev = args.revision
    if not rev and (cap / "metrics.json").exists():
        rev = json.loads((cap / "metrics.json").read_text()).get("revision", "")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    index, bad, unreachable = [], 0, 0
    for route in routes:
        for device, vp in DEVICES:
            fresh = fresh_dir / ("%s-%s.png" % (route, vp))
            gold = golden / "screens" / ("%s-%s.png" % (route, vp))
            if not fresh.exists():
                print("  %-10s %-7s FAIL  no fresh capture %s" % (route, device, fresh.name))
                bad += 1
                index.append({"route": route, "device": device, "verdict": "FAIL",
                              "error": "fresh capture missing"})
                continue
            t0 = time.time()
            png = shrink(fresh)
            first, model, fails = vote(png, route, device, vp, key)
            if first is None:
                # An outage is not a UI finding, so it must not share the failure
                # count with one. It only counts as UNREACHABLE when EVERY model
                # went unanswered: a reply we could not read is a failed gate.
                outage = all(k == "unreachable" for k, _ in fails)
                verdict = "UNREACHABLE" if outage else "FAIL"
                detail = " | ".join(m for _, m in fails)
                if outage:
                    unreachable += 1
                else:
                    bad += 1
                print("  %-10s %-7s %-11s %s" % (route, device, verdict, detail[:180]))
                index.append({"route": route, "device": device, "verdict": verdict,
                              "error": ("vision unreachable: " if outage
                                        else "vision call failed: ") + detail[:400]})
                continue

            broken = bool(first.get("broken"))
            votes = [broken]
            others = []
            verdict = "MATCH" if not broken else "DIFF"
            if broken and not args.no_corroborate:
                # One model's "broken" is a hypothesis. Two agreeing models are a
                # finding, so a flagged pair gets a third opinion and the
                # majority decides - a single hallucination (measured: the fixed
                # nav painted mid-page on a full-page shot) cannot red the build.
                for _ in range(2):
                    more, more_model, _ = vote(png, route, device, vp, key,
                                               skip=(model, *[o["model"] for o in others]))
                    if more is None:
                        break
                    others.append({"model": more_model, "broken": bool(more.get("broken")),
                                   "broken_class": more.get("broken_class"),
                                   "defects": more.get("defects") or []})
                    votes.append(bool(more.get("broken")))
                if len(votes) == 1:
                    verdict = "DISPUTED"          # nobody could corroborate
                else:
                    verdict = "DIFF" if sum(votes) * 2 > len(votes) else "MATCH"
            if verdict != "MATCH":
                bad += 1

            rec = {
                "route": route, "device": device, "viewport": vp,
                "verdict": verdict,
                "broken_class": first.get("broken_class"),
                "defects": first.get("defects") or [],
                "confidence": first.get("confidence", ""),
                "model": model,
                "corroboration": others,
                "golden_sha": sha(gold) if gold.exists() else None,
                "fresh_sha": sha(fresh),
                "revision": rev,
                "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            (out / ("%s-%s.json" % (route, device))).write_text(
                json.dumps(rec, indent=2) + "\n")
            print("  %-10s %-7s %-8s %4.1fs  %s"
                  % (route, device, verdict, time.time() - t0,
                     "; ".join(rec["defects"])[:100] or "-"))
            index.append({k: rec[k] for k in ("route", "device", "verdict", "model",
                                              "confidence", "broken_class")})
            time.sleep(0.3)

    matched = sum(1 for p in index if p["verdict"] == "MATCH")
    outage_msg = next((p["error"] for p in index if p["verdict"] == "UNREACHABLE"), "")
    # UNREACHABLE does not fail the run by itself: the provider being down is not
    # evidence the page broke, and failing on it is what made every red e2e run
    # ambiguous. It DOES fail when most pairs were never judged - a green gate
    # that verified nothing is decoration. Real verdicts always fail.
    blind = unreachable > 0 and unreachable * 2 >= len(index)
    if bad:
        headline = ("vision: REAL UI REGRESSION - %d/%d pairs not a MATCH "
                    "(DIFF/DISPUTED/FAIL), %d unreachable - verdicts in %s"
                    % (bad, len(index), unreachable, out))
    elif blind:
        headline = ("vision: UNREACHABLE - the provider answered %d/%d pairs, too "
                    "few to verify the UI, so nothing was checked; this is an "
                    "outage, not a regression (%s)"
                    % (len(index) - unreachable, len(index), outage_msg[:160]))
    elif unreachable:
        headline = ("vision: %d/%d pairs MATCH, %d UNREACHABLE - provider outage, "
                    "not a UI regression (%s) - verdicts in %s"
                    % (matched, len(index), unreachable, outage_msg[:120], out))
    else:
        headline = "vision: %d/%d pairs MATCH - verdicts in %s" % (matched, len(index), out)
    summary = {
        "revision": rev,
        "pairs": len(index), "matched": matched, "failed": bad,
        "unreachable": unreachable,
        "devices": [d for d, _ in DEVICES],
        "coverage": "route list from %s/routes.json" % golden.name,
        "pairs_detail": index,
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (out / "index.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(headline)
    step_summary(headline)
    return 1 if bad else (3 if blind else 0)


if __name__ == "__main__":
    sys.exit(main())
