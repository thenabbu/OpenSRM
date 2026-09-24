import base64
import http.cookiejar
import json
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0,"/app")
from app.app import solve_captcha_b64

DIRECT = "https://sp.srmist.edu.in"
BASE = DIRECT + "/srmiststudentportal"
HOST = "sp.srmist.edu.in"
ROUTE = sys.argv[1] if len(sys.argv)>1 else "direct"  # direct|worker
if ROUTE == "worker":
    DIRECT = "https://srm-egress.200871.xyz"
    BASE = DIRECT + "/srmiststudentportal"
    TOKEN = os.environ.get("SRM_PROXY_TOKEN")
else:
    TOKEN = None

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
H = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
     "Accept-Language": "en-US,en;q=0.9"}
if TOKEN: H["x-proxy-token"] = TOKEN

t0=time.time()
html = opener.open(urllib.request.Request(f"{BASE}/students/loginManager/youLogin.jsp",headers=H),timeout=20).read().decode(errors="ignore")
cookies = {c.name:c.value for c in jar}
print(f"[{ROUTE}] 1. GET page {len(html)}b  cookies={list(cookies)}")
has_ts = any(k.startswith('TS') for k in cookies)
print(f"    F5 TS persistence cookie present: {has_ts}")

def g(p):
    m=re.search(p,html); return m.group(1) if m else None
# nonce lives in 1st SECURE_CONFIG block as: nonce: '...'
nonce=g(r"nonce\s*:\s*'([^']+)'")
seed=g(r"captchaText\s*[=:]\s*['\"]([^'\"]+)['\"]")
dfield=g(r"domainFieldName\s*[=:]\s*['\"]([^'\"]+)['\"]")
cfield=g(r"captchaFieldName\s*[=:]\s*['\"]([^'\"]+)['\"]")
rdelim=g(r"randomDelimiter\s*[=:]\s*['\"]([^'\"]+)['\"]")
hp=re.search(r'name="(ph_[^"]+)"',html); honeypot=hp.group(1) if hp else None
img=re.search(r'<img[^>]*id="secure_captcha"[^>]*>',html)
src=re.search(r'data-src="([^"]+)"',img.group(0)).group(1)
print(f"    nonce={nonce} seed={seed} dfield={dfield} cfield={cfield} rdelim={rdelim}")

# fetch page's own captcha WITH correct Domain-Proof = btoa(nonce:host)
dp=base64.b64encode(f"{nonce}:{HOST}".encode()).decode()
img_url=(DIRECT+src) if src.startswith("/") else src
if img_url.startswith(DIRECT): img_url=img_url.replace(DIRECT, DIRECT)  # same base
# for worker route, rewrite origin->worker
if ROUTE=="worker" and img_url.startswith("https://sp.srmist.edu.in"):
    img_url=img_url.replace("https://sp.srmist.edu.in", DIRECT)
imgb=opener.open(urllib.request.Request(img_url,headers={**H,"X-Domain-Proof":dp,"Referer":f"https://{HOST}/srmiststudentportal/students/loginManager/youLogin.jsp"}),timeout=20).read()
open(f"/tmp/g5_{ROUTE}_captcha.png","wb").write(imgb)
ocr=solve_captcha_b64(base64.b64encode(imgb).decode())
print(f"2. captcha img {len(imgb)}b OCR='{ocr}'")

# POST
dtoken=base64.b64encode(HOST[::-1].encode()).decode()
elapsed=str(max(5,int(time.time()-t0)))
cptoken=base64.b64encode(f"{elapsed}{rdelim}3".encode()).decode()
fields={"username": os.environ["SRM_NETID"], "password": os.environ["SRM_PASSWORD"],honeypot:"","captcha":ocr,
 "fpPayload":"","fpToken":"",
 "telemetryPayload":base64.b64encode(json.dumps({
   "startTime":int(time.time()*1000-10000),"currentDomain":HOST,"timezoneOffset":-330,
   "screenWidth":1920,"screenHeight":1080,"colorDepth":24,"devicePixelRatio":1,
   "platform":"Win32","userAgent":UA,"language":"en-US","hardwareConcurrency":8,
   "deviceMemory":8,"touchSupport":False,"webdriver":False,"mouseClicks":5,
   "mouseMovements":32,"keystrokeCount":10,"typingSpeedMs":8500,"canvasHash":"-27fdeb33",
   "submitTime":int(time.time()*1000),"timeOnPageMs":10000}).encode()).decode(),
 dfield:dtoken,cfield:cptoken}
data=urllib.parse.urlencode(fields).encode()
req=urllib.request.Request(f"{BASE}/LoginServlet",data=data,method="POST")
req.add_header("Content-Type","application/x-www-form-urlencoded")
req.add_header("Origin",f"https://{HOST}")
req.add_header("Referer",f"https://{HOST}/srmiststudentportal/students/loginManager/youLogin.jsp")
for k,v in H.items(): req.add_header(k,v)
t1=time.time()
resp=opener.open(req,timeout=20)
body=resp.read().decode(errors="ignore")
post_cookies={c.name:c.value for c in jar}
print(f"3. POST {len(body)}b ({(time.time()-t1)*1000:.0f}ms) url={resp.url}")
print(f"    cookies after POST={list(post_cookies)}")

if "HRDSystem" in body or "HRDSystem" in resp.url:
    print(f"\n*** [{ROUTE}] LOGIN SUCCESS ***")
elif "Invalid captcha" in body:
    print(f"\n[{ROUTE}] -> Invalid captcha (submitted '{ocr}')")
elif "Invalid credentials" in body:
    print(f"\n[{ROUTE}] -> Invalid credentials => CAPTCHA PASSED, password rejected")
else:
    a=re.search(r'Invalid[^<]+',body); print(f"\n[{ROUTE}] -> {a.group(0) if a else 'unknown'}"); 
    if not a: print("   head:",re.sub(r'<[^>]+>','',body)[:200])
