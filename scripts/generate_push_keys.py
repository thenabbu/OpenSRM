#!/usr/bin/env python3
"""One-time push key generator for OpenSRM.

Generates the three values the Web Push feature needs and prints them as
`export` lines to append to lab /docker/.env (and later copy VERBATIM into
Vercel Production env vars):

  VAPID_PUBLIC_KEY   base64url uncompressed P-256 point (safe to show)
  VAPID_PRIVATE_KEY  base64url raw 32-byte scalar      (SECRET — never commit)
  PUSH_TICK_SECRET   urlsafe token                      (SECRET — never commit)

Rules (see docs/push.md):
  * Run this ONLY if the variable is missing from /docker/.env. Replacing
    the VAPID keypair invalidates every stored subscription.
  * Append, never rewrite /docker/.env; keep its permissions.
  * Never print these into logs, commits, docs or chat.

VAPID_SUBJECT is not generated — use the contact email already in the repo,
PREFIXED as a URI: mailto:<email>  (py_vapid strict-checks `sub`; a bare
email raises "Missing sub" before any HTTP and every send fails).
"""
import base64
import secrets
import sys


def main():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError:
        print("needs the app venv: .venv/bin/python scripts/generate_push_keys.py", file=sys.stderr)
        return 1
    k = ec.generate_private_key(ec.SECP256R1())
    priv = k.private_numbers().private_value.to_bytes(32, "big")
    pub = k.public_key().public_bytes(serialization.Encoding.X962,
                                      serialization.PublicFormat.UncompressedPoint)
    if len(sys.argv) > 1 and sys.argv[1] == "--public-only":
        print(base64.urlsafe_b64encode(pub).rstrip(b"=").decode())
        return 0
    print("# append to lab /docker/.env (only when missing):")
    print("export VAPID_PUBLIC_KEY=" + base64.urlsafe_b64encode(pub).rstrip(b"=").decode())
    print("export VAPID_PRIVATE_KEY=" + base64.urlsafe_b64encode(priv).rstrip(b"=").decode())
    print("export PUSH_TICK_SECRET=" + secrets.token_urlsafe(32))
    return 0

if __name__ == "__main__":
    sys.exit(main())
