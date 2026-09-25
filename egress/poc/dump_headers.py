#!/usr/bin/env python3
"""Dump ALL Set-Cookie headers (raw) from page + captcha fetches via worker, showing what a browser/cookiejar would accept or reject."""
import base64
import http.cookiejar
import re
import urllib.request
import urllib.error

PT = "21781f952a65cc1baf09c8593ad0b8baf61842cccce7b3fa"
BASE = "https://srm-egress.200871.xyz"
PAGE_PATH = "/srmiststudentportal/students/loginManager/youLogin.jsp"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

req = urllib.request.Request(BASE + PAGE_PATH, headers={
    "x-proxy-token": PT, "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
})
resp = opener.open(req, timeout=25)
print("PAGE status:", resp.status)
print("PAGE ALL HEADERS:")
for k, v in resp.headers.items():
    print(f"  {k}: {v[:160]}")
# get_all on Set-Cookie
print("PAGE set-cookie (all):", resp.headers.get_all("Set-Cookie"))
html = resp.read().decode("utf-8", "replace")

nonce = re.search(r"nonce:\s*'([^']+)'", html).group(1)
cap_path = re.search(r'id="secure_captcha"[^>]*data-src="([^"]+)"', html).group(1)
proof = base64.b64encode((nonce + ":sp.srmist.edu.in").encode()).decode()

req2 = urllib.request.Request(BASE + cap_path, headers={
    "x-proxy-token": PT,
    "X-Domain-Proof": proof,
    "Referer": "https://sp.srmist.edu.in" + PAGE_PATH,
    "User-Agent": UA,
    "Accept": "image/avif,image/webp,image/png,image/*,*/*;q=0.8",
})
try:
    resp2 = opener.open(req2, timeout=25)
    data = resp2.read()
    print("CAPTCHA status:", resp2.status, "bytes:", len(data), "ct:", resp2.headers.get("Content-Type"))
    print("CAPTCHA set-cookie:", resp2.headers.get_all("Set-Cookie"))
except urllib.error.HTTPError as e:
    print("CAPTCHA HTTP", e.code)
    print("CAPTCHA set-cookie:", e.headers.get_all("Set-Cookie"))
    print("body head:", e.read()[:300])

print("cookies jar now:", [(c.name, c.domain, c.path) for c in cj])
