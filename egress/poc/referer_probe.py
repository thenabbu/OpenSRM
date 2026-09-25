#!/usr/bin/env python3
"""Probe: does the captcha fetch survive (a) wrong-host Referer (srm.200871.xyz), (b) NO Referer?
Page GET + captcha GET only, no login POST. Gaps between runs to respect F5 rate limits."""
import base64
import http.cookiejar
import re
import time
import urllib.request
import urllib.error

PT = "21781f952a65cc1baf09c8593ad0b8baf61842cccce7b3fa"
BASE = "https://srm-egress.200871.xyz"
PAGE_PATH = "/srmiststudentportal/students/loginManager/youLogin.jsp"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

def run(label, referer):
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    req = urllib.request.Request(BASE + PAGE_PATH, headers={
        "x-proxy-token": PT, "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    html = opener.open(req, timeout=25).read().decode("utf-8", "replace")
    nonce = re.search(r"nonce:\s*'([^']+)'", html).group(1)
    cap_path = re.search(r'id="secure_captcha"[^>]*data-src="([^"]+)"', html).group(1)
    proof = base64.b64encode((nonce + ":sp.srmist.edu.in").encode()).decode()
    h = {
        "x-proxy-token": PT,
        "X-Domain-Proof": proof,
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/png,image/*,*/*;q=0.8",
    }
    if referer:
        h["Referer"] = referer
    req2 = urllib.request.Request(BASE + cap_path, headers=h)
    try:
        r = opener.open(req2, timeout=25)
        data = r.read()
        ok = data[:8] == b"\x89PNG\r\n\x1a\n"
        print(f"{label}: HTTP {r.status} bytes={len(data)} PNG={ok}")
    except urllib.error.HTTPError as e:
        print(f"{label}: HTTP {e.code} (blocked)")

run("A wrong-referer (srm.200871.xyz)", "https://srm.200871.xyz/srmiststudentportal/students/loginManager/youLogin.jsp")
time.sleep(20)
run("B no-referer", None)
time.sleep(20)
run("C control (portal referer)", "https://sp.srmist.edu.in/srmiststudentportal/students/loginManager/youLogin.jsp")
