"""Login Flow UX Guide — source-level checks (no server, no portal traffic).
Complements guide_check.py (DOM) and guide_server.py (live HTTP)."""
import re, sys, os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = open(os.path.join(REPO, "app/app.py")).read()
js = open(os.path.join(REPO, "app/static/login.js")).read()
rows = []

def ck(item, cond, ev=""):
    rows.append((item, cond, ev))
    print(f"[{'PASS' if cond else 'FAIL'}] {item}" + (f"  — {ev}" if ev else ""))

# §1 normalization lives server-side on EVERY credential route, not just /api/login
for route in ("def api_login(", "def api_login_preflight("):
    i = app.find(route)
    seg = app[i:i + 1200]   # api_login validates JSON for ~15 lines before netid
    ck(f"§1 normalization (strip+lower+strip-domain) in {route[:-1]}",
       bool(re.search(r'\.strip\(\)\.lower\(\)\.split\("@"\)\[0\]', seg)),
       seg.split("\n")[15:17] and re.search(r'netid = .*', seg).group(0)[:100])

# §2 paste: no handler, no preventDefault, no readonly games in login.js
ck("§2 no paste handler anywhere in login.js", "paste" not in js, "grep 'paste' -> 0")
ck("§2 no readonly toggling on the password field", "readOnly" not in js and "readonly" not in js)

# §5 enumeration: no account-existence wording in the whole app, ever
exist = re.findall(r"(?i)no such|not exist|does not exist|no account|unknown user|user not found", app)
ck("§5 zero account-existence wording anywhere in app.py", not exist, f"matches={exist}")

# §5 the credential rejection is ONE fixed generic string (portal text is never relayed)
ck("§5 credential failure is a single fixed generic message",
   'return False, "invalid credentials — check your NetID/password"' in app)
# api_login must return res['error'] without branching on the netid's existence
body = app[app.find("def api_login("):]
body = body[:body.find("\n@app.route", 10)]
ck("§5 /api/login passes the mapped error through with no per-netid branch",
   "res[\"error\"]" in body and not re.search(r"if .*(exists|found|known)", body),
   "no existence branch between fetch_attendance and the response")

# §4 documents the deliberate skip: no conditional-UI call in source
ck("§4 no conditional-UI passkey call in login.js (deliberate skip, see PR)",
   "mediation" not in js and "credentials.get" not in js)

# §5 no vague lockout wording survives
ck("§5 no 'Try again later' anywhere in the API", "Try again later." not in app)

fails = [r for r in rows if not r[1]]
print("\n" + "=" * 72)
print(f"STATIC: {len(rows)} items | PASS {len(rows)-len(fails)} | FAIL {len(fails)}")
print("ALL PASS" if not fails else "FAILURES PRESENT")
sys.exit(1 if fails else 0)
