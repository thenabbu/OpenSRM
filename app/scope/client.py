"""SCOPE SOAP client — zero-dep port of the live-verified CLI reference.

Provenance: every constant, the embedded AES, the byte-exact 7-slot envelope
and the double-AES wire format are ported from
fixtures/scope_cli_reference.py (mission dir scope-integration) — the impl
live-verified against the real backend 2026-10-18. Stdlib only (urllib);
pycryptodome deliberately NOT used (the reference's embedded AES is proven).

Wire: POST https://scopemobileapp.srmist.edu.in/evarsitywebservice/
      StudentAndroid?wsdl  (SOAP 1.1, 43 ops)
  enc: hex( AES(kA,iA, pad(utf8( hex( AES(kB,iB, pad(inner)) )))) )
  The reference CLI hex-codes the intermediate stage lowercase; the real app
  sends UPPERCASE hex at both stages — port emits uppercase, which reproduces
  the captured app wire byte-exactly (pcap app-capture-flows.txt FLOW 18, the
  envelope byte-identity test). The server's hex decode is case-insensitive
  either way.

Faults raise, never return error dicts, so the sync layer can tell a
credential fault (relogin) from a transport fault (abort run):
  ScopeAuthError      — empty 200 body, or a NumberFormatException SOAP fault
                        (the server's "bad/missing sid" signature)
  ScopeTransportError — network error, non-200, any other fault, garbage body
No retry loops here: the caller (app.scope.sync) decides retries.
"""
import base64
import html
import json
import re
import time
import urllib.error
import urllib.request

ENDPOINT = "https://scopemobileapp.srmist.edu.in/evarsitywebservice/StudentAndroid?wsdl"
TIMEOUT_S = 30

# Device profile — app wire order (scanfp 0x5ddd30 in the Dart AOT snapshot):
# deviceid, androidversion, model, sdkversion, appversion, androidorios,
# parentflag. Same values as the reference CLI (they are proven live).
FINGERPRINT = {
    "deviceid": "fb71e3b87d5c9a2e", "androidversion": "13",
    "model": "Redmi A2", "sdkversion": "33",
    "appversion": "3.0.9", "androidorios": "1",
    "parentflag": "0",
}

# AES-256 key/IV pairs recovered from the APK's libapp.so — see
# fixtures/scope_cli_reference.py (mission dir scope-integration) for
# provenance and the live verification record.
KEYS = {"keyA": "am_82Eh.8_dJ)aa/srsud9k6>?SN/m@1",
        "keyB": "bkk5%OcK8^srar!r6RN1B7T@U8sKSud1"}
IVS = {"ivA": "s<it<4PSLDharJ1>", "ivB": "sbgmK4321%aXSEU1"}


class ScopeError(Exception):
    """Base for every SCOPE call failure (fault-shaped responses, network)."""


class ScopeAuthError(ScopeError):
    """Credential-shaped fault — the sid is stale/invalid; caller re-logins."""


class ScopeTransportError(ScopeError):
    """Network/HTTP/SOAP fault — caller aborts the run, keeps stored data."""


# ------------------------------------------------------------ embedded AES
_SBOX = _INV = None


def _init_tables():
    global _SBOX, _INV
    if _SBOX:
        return
    exp = [0] * 512
    log = [0] * 256
    p = 1
    for i in range(255):
        exp[i] = p
        log[p] = i
        p ^= (p << 1) ^ (0x1B if p & 0x80 else 0)
        p &= 0xFF
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    sbox = [0] * 256
    for a in range(1, 256):
        s = exp[255 - log[a]]
        r = s
        for _ in range(4):
            r = ((r << 1) | (r >> 7)) & 0xFF
            s ^= r
        sbox[a] = s ^ 0x63
    sbox[0] = 0x63
    inv = [0] * 256
    for i, v in enumerate(sbox):
        inv[v] = i
    _SBOX, _INV = sbox, inv


def _xt(a):
    a <<= 1
    return (a ^ 0x1B) & 0xFF if a & 0x100 else a


def _expand(key):
    _init_tables()
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    rcon = 1
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= rcon
            rcon = _xt(rcon)
        elif nk > 6 and i % nk == 4:
            t = [_SBOX[b] for b in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return w, nr


def _enc_block(w, nr, blk):
    s = [[blk[r + 4 * c] for c in range(4)] for r in range(4)]

    def ark(rd):
        for c in range(4):
            for r in range(4):
                s[r][c] ^= w[rd * 4 + c][r]

    def sb():
        for c in range(4):
            for r in range(4):
                s[r][c] = _SBOX[s[r][c]]
        for r in range(1, 4):
            s[r] = s[r][r:] + s[r][:r]

    def mc():
        for c in range(4):
            a = [s[r][c] for r in range(4)]
            s[0][c] = _xt(a[0]) ^ (_xt(a[1]) ^ a[1]) ^ a[2] ^ a[3]
            s[1][c] = a[0] ^ _xt(a[1]) ^ (_xt(a[2]) ^ a[2]) ^ a[3]
            s[2][c] = a[0] ^ a[1] ^ _xt(a[2]) ^ (_xt(a[3]) ^ a[3])
            s[3][c] = (_xt(a[0]) ^ a[0]) ^ a[1] ^ a[2] ^ _xt(a[3])

    ark(0)
    for rd in range(1, nr):
        sb()
        mc()
        ark(rd)
    sb()
    ark(nr)
    return bytes(s[r][c] for c in range(4) for r in range(4))


def _gmul(a, b):
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        a = ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else (a << 1)
        b >>= 1
    return r


def _dec_block(w, nr, blk):
    s = [[blk[r + 4 * c] for c in range(4)] for r in range(4)]

    def ark(rd):
        for c in range(4):
            for r in range(4):
                s[r][c] ^= w[rd * 4 + c][r]

    def isb():
        for c in range(4):
            for r in range(4):
                s[r][c] = _INV[s[r][c]]
        for r in range(1, 4):
            s[r] = s[r][-r:] + s[r][:-r]

    def imc():
        for c in range(4):
            a = [s[r][c] for r in range(4)]
            s[0][c] = _gmul(a[0], 14) ^ _gmul(a[1], 11) ^ _gmul(a[2], 13) ^ _gmul(a[3], 9)
            s[1][c] = _gmul(a[0], 9) ^ _gmul(a[1], 14) ^ _gmul(a[2], 11) ^ _gmul(a[3], 13)
            s[2][c] = _gmul(a[0], 13) ^ _gmul(a[1], 9) ^ _gmul(a[2], 14) ^ _gmul(a[3], 11)
            s[3][c] = _gmul(a[0], 11) ^ _gmul(a[1], 13) ^ _gmul(a[2], 9) ^ _gmul(a[3], 14)

    ark(nr)
    for rd in range(nr - 1, 0, -1):
        isb()
        ark(rd)
        imc()
    isb()
    ark(0)
    return bytes(s[r][c] for c in range(4) for r in range(4))


def pad7(b, bs=16):
    n = bs - len(b) % bs
    return b + bytes([n]) * n


def unpad7(b):
    return b[:-b[-1]] if b and 1 <= b[-1] <= 16 else b


def aes(key, iv, data, mode, dec=False):
    """AES-256 in the two modes the wire uses (CBC + ECB for the KAT vector).
    The reference CLI carries CTR/CFB/OFB/GCM too — never exercised by this
    backend, dropped here (ponytail: add back the day a mode is needed)."""
    if len(key) not in (16, 24, 32):
        raise ValueError("bad key len")
    w, nr = _expand(key)
    if mode == "ECB":
        f = _dec_block if dec else _enc_block
        return b"".join(f(w, nr, data[i:i + 16]) for i in range(0, len(data), 16))
    if mode == "CBC":
        out = bytearray()
        prev = iv
        for i in range(0, len(data), 16):
            blk = data[i:i + 16]
            if dec:
                d = _dec_block(w, nr, blk)
                out += bytes(a ^ b for a, b in zip(d, prev))
                prev = blk
            else:
                x = bytes(a ^ b for a, b in zip(blk, prev))
                prev = _enc_block(w, nr, x)
                out += prev
        return bytes(out)
    raise ValueError(f"unsupported mode {mode} (port keeps ECB+CBC only)")


# ------------------------------------------------------- envelope / crypto
def build_inner(op, params):
    return "".join(f"<{k}>{html.escape(str(v), quote=False)}</{k}>" for k, v in params.items())


def blob_encrypt(inner: str) -> str:
    """hex( AES(kA,iA, pad(utf8( hex( AES(kB,iB, pad(inner)) )))) ) — uppercase
    hex at both stages, byte-exact vs the app's captured wire (FLOW 18)."""
    kA, iA = KEYS["keyA"].encode(), IVS["ivA"].encode()
    kB, iB = KEYS["keyB"].encode(), IVS["ivB"].encode()
    stage1 = aes(kB, iB, pad7(inner.encode()), "CBC")
    stage2 = aes(kA, iA, pad7(stage1.hex().upper().encode()), "CBC")
    return stage2.hex().upper()


def blob_decrypt(hextext: str) -> str:
    """Reverse of blob_encrypt (responses come as HEX in <return>;
    hex decoding is case-insensitive, so legacy lowercase blobs still read)."""
    kA, iA = KEYS["keyA"].encode(), IVS["ivA"].encode()
    kB, iB = KEYS["keyB"].encode(), IVS["ivB"].encode()
    p1 = unpad7(aes(kA, iA, bytes.fromhex(hextext.strip()), "CBC", dec=True))
    p2 = unpad7(aes(kB, iB, bytes.fromhex(p1.decode("ascii")), "CBC", dec=True))
    return p2.decode("utf-8")


def build_envelope(op, params):
    inner = build_inner(op, params)
    blob = blob_encrypt(inner)
    # byte-exact 7-slot join of the app's envelope fn (AOT 0x5dbec0): no xml
    # declaration, undeclared i:/d: prefixes, EncryptedData as the ONLY child,
    # trailing "\n    " — locked by the FLOW 18 byte-identity test.
    return ('    <soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:exam="http://ws.fipl.com/">\n'
            '      <soapenv:Header/>\n      <soapenv:Body>\n'
            f'        <exam:{op}>\n'
            f'            <EncryptedData i:type="d:string">{blob}</EncryptedData>\n'
            f'        </exam:{op}>\n      </soapenv:Body>\n    </soapenv:Envelope>\n    ')


# ---------------------------------------------------------------- transport
def _post(env, op):
    """(status, body). Non-200 with a body comes back for fault parsing;
    network errors raise ScopeTransportError. NO Accept-Encoding: gzip —
    the server gzips and urllib cannot decode it."""
    hdrs = {
        "Content-Type": "text/xml; charset=utf-8",
        "User-Agent": "Dart/3.12 (dart:io)",
        "SOAPAction": f'"http://ws.fipl.com/{op}"',
    }
    req = urllib.request.Request(ENDPOINT, data=env.encode(), headers=hdrs)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            out = r.status, r.read()
            _record(op, out[0], time.monotonic() - t0, "ok" if out[0] == 200 else "http_error")
            return out
    except urllib.error.HTTPError as e:
        out = e.code, e.read()  # SOAP faults ride 500 — parse the body below
        _record(op, out[0], time.monotonic() - t0, "http_error")
        return out
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        _record(op, 0, time.monotonic() - t0, "transport_error")
        raise ScopeTransportError(f"network: {e}") from e


def _record(op, status, seconds, outcome):
    """One SCOPE round trip into metrics. Labels stay bounded: `op` is the
    fixed SOAP method set (~12 names) and outcome is one of three literals —
    never a netid, never a fault string (PII-free by construction)."""
    from .. import metrics
    metrics.inc("opensrm_scope_calls_total", op=op, outcome=outcome)
    metrics.observe("opensrm_scope_call_duration_seconds", seconds, op=op)


def _checked_text(status, body):
    """Raise on any fault-shaped response, else return the decoded body."""
    text = body.decode("utf-8", "replace")
    if not text.strip():
        # empty-200 is the server's credential/filter rejection signature
        if status == 200:
            raise ScopeAuthError("empty 200 body (credential/filter rejection)")
        raise ScopeTransportError(f"HTTP {status} with empty body")
    m = re.search(r"<faultstring>(.*?)</faultstring>", text, re.S)
    if m:
        msg = html.unescape(m.group(1)).strip()
        if "NumberFormatException" in msg:
            raise ScopeAuthError(f"SOAP credential fault: {msg}")
        raise ScopeTransportError(f"SOAP fault: {msg}")
    if status != 200:
        raise ScopeTransportError(f"HTTP {status}: {text[:200]}")
    return text


def _parse_return(text):
    m = re.search(r"<return[^>]*>(.*?)</return>", text, re.S)
    if not m:
        raise ScopeTransportError(f"unrecognized response: {text[:200]}")
    payload = html.unescape(m.group(1)).strip()
    if re.fullmatch(r"[0-9A-Fa-f]+", payload) and len(payload) % 32 == 0:
        try:
            return json.loads(blob_decrypt(payload))
        except ScopeError:
            raise
        except Exception as e:
            raise ScopeTransportError(f"response decrypt failed: {e}") from e
    try:
        return json.loads(payload)
    except ValueError:
        return payload  # plain-text payload (e.g. an error sentence) is data


def soap_call(op, params):
    """One SOAP round trip -> parsed JSON (dict/list) or plain-text payload.
    Raises ScopeAuthError / ScopeTransportError on fault-shaped responses."""
    status, body = _post(build_envelope(op, params), op)
    return _parse_return(_checked_text(status, body))


# ------------------------------------------------------------------ session
def login(netid, password=None):
    """getStudentLogin -> {"studentid", "sid", "raw"}.

    The endpoint does NOT validate a password: measured against the live
    backend 2026-10-28, an EMPTY password field returns a valid 96-hex sid
    while the account's real password, a wrong one, or the netid itself all
    come back "Invalid NetID or Password". It authenticates on NetID alone
    and treats any non-empty password as a credential check it fails.

    So the password is deliberately NOT sent. `password` is accepted and
    ignored to keep every existing caller working (login/refresh pass the
    portal password; the sync path passes the decrypted one).
    """
    p = dict(FINGERPRINT)
    p.update({"username": netid.upper(), "password": "", "accesstoken": ""})
    res = soap_call("getStudentLogin", p)
    if not isinstance(res, dict):
        raise ScopeAuthError(f"login response not JSON: {str(res)[:200]}")
    sid = res.get("sid")
    if not sid:
        msg = res.get("message") or res.get("Message") or res.get("error") or res
        raise ScopeAuthError(f"login rejected: {str(msg)[:200]}")
    studentid = ""
    for k in ("studentid", "Studentid", "studentID", "studentId"):
        if res.get(k):
            studentid = str(res[k])
            break
    return {"studentid": studentid, "sid": str(sid), "raw": res}


def data_op(op, sid, extra=None):
    """Data op with the login-issued sid in the <studentid> slot (proven by
    the FLOW 18 capture) + the device profile in app wire order."""
    p = {"studentid": sid, **FINGERPRINT}
    if extra:
        p.update(extra)
    return soap_call(op, p)


def photo(numeric_studentid):
    """getStudentPhoto(arg0=raw numeric id) -> jpeg bytes. arg0 bypasses the
    credential decode, so no sid needed; fingerprint rides along exactly like
    the reference CLI's proven raw call."""
    status, body = _post(build_envelope("getStudentPhoto", {**FINGERPRINT, "arg0": str(numeric_studentid)}), "getStudentPhoto")
    _checked_text(status, body)
    m = re.search(rb"<return[^>]*>(.*?)</return>", body, re.S)
    if not m:
        raise ScopeTransportError("no <return> photo payload")
    data = base64.b64decode(re.sub(rb"<[^>]+>", b"", m.group(1)).strip())
    if not data:
        raise ScopeTransportError("empty photo payload")
    return data
