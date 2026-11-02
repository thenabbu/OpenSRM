#!/usr/bin/env bash
# Deploy the maintenance Worker: DNS origin record + tunnel ingress rule +
# Worker upload + zone route. Idempotent — safe to re-run.
#
#   ./deploy.sh            # build, deploy, verify
#   ./deploy.sh --dry-run  # show what would change, touch nothing
#
# Auth: CF API token with Workers edit + Tunnel read/edit + DNS edit scope.
# Read from $CF_TOKEN, else from the lab's docker env file (never committed).
set -euo pipefail
cd "$(dirname "$0")"

ACCOUNT=6861cc3276134b677ad93f92561fa95c
ZONE=e7e0257dc67334eaea9e52603bd8adbf
TUNNEL=c2308be7-6527-4da3-a96c-49c4b4c918c0
HOST=srm.200871.xyz
ORIGIN_HOST=srm-origin.200871.xyz
SCRIPT=srm-maintenance
DRY=false
[ "${1:-}" = "--dry-run" ] && DRY=true

api() { curl -sS -H "Authorization: Bearer $T" "$@"; }

# --- token ---------------------------------------------------------------
T="${CF_TOKEN:-}"
if [ -z "$T" ]; then
  # lab keeps CF_FULL_TOKEN possibly twice (dead stub first) and with a
  # trailing "# comment"; keep the first candidate that the API accepts.
  while read -r cand; do
    [ -z "$cand" ] && continue
    if curl -sS -H "Authorization: Bearer $cand" \
        "https://api.cloudflare.com/client/v4/user/tokens/verify" \
        | grep -q '"status":"active"'; then
      T="$cand"; break
    fi
  done < <(ssh lab 'grep CF_FULL_TOKEN /docker/.env | cut -d= -f2- | sed "s/[[:space:]]*#.*//"' 2>/dev/null)
fi
[ -z "$T" ] || [ "$T" = "null" ] && { echo "no usable CF token (set CF_TOKEN)" >&2; exit 1; }
echo "token OK"

# --- 1. origin DNS record ------------------------------------------------
have=$(api "https://api.cloudflare.com/client/v4/zones/$ZONE/dns_records?name=$ORIGIN_HOST" \
       | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("result") or []))')
if [ "$have" = "0" ]; then
  echo "create CNAME $ORIGIN_HOST -> $TUNNEL.cfargotunnel.com"
  $DRY || api -X POST -H "Content-Type: application/json" \
    "https://api.cloudflare.com/client/v4/zones/$ZONE/dns_records" \
    --data "{\"type\":\"CNAME\",\"name\":\"$ORIGIN_HOST\",\"content\":\"$TUNNEL.cfargotunnel.com\",\"proxied\":true,\"ttl\":1,\"comment\":\"origin target for $SCRIPT worker\"}" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print("  ok" if d.get("success") else d.get("errors"))'
else
  echo "CNAME $ORIGIN_HOST already present"
fi

# --- 2. tunnel ingress rule ---------------------------------------------
# PUT replaces the WHOLE ingress list, so always GET -> merge -> PUT.
# Never rebuild the list from memory.
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
api "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT/cfd_tunnel/$TUNNEL/configurations" \
  | python3 -c 'import json,sys; json.dump(json.load(sys.stdin)["result"]["config"], open(sys.argv[1],"w"), indent=2)' "$tmp/cfg.json"

python3 - "$tmp/cfg.json" "$HOST" "$ORIGIN_HOST" > "$tmp/payload.json" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1])); host, origin_host = sys.argv[2], sys.argv[3]
ing = cfg['ingress']
if not any(r.get('hostname') == origin_host for r in ing):
    src = next(r for r in ing if r.get('hostname') == host)
    clone = json.loads(json.dumps(src)); clone['hostname'] = origin_host
    ing.insert(ing.index(src) + 1, clone)   # right after the original, keeps catch-all last
    changed = True
else:
    changed = False
json.dump({'config': cfg}, sys.stdout)
print('', end='', file=sys.stderr)
sys.stderr.write(f"ingress {'updated' if changed else 'unchanged'} ({len(ing)} rules)\n")
PY

if grep -q 'origin_host' "$tmp/payload.json" 2>/dev/null || ! api "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT/cfd_tunnel/$TUNNEL/configurations" | grep -q "\"$ORIGIN_HOST\""; then
  echo "PUT tunnel ingress"
  $DRY || api -X PUT -H "Content-Type: application/json" \
    "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT/cfd_tunnel/$TUNNEL/configurations" \
    --data @"$tmp/payload.json" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print("  version", (d.get("result") or {}).get("version")) if d.get("success") else print(d.get("errors"))'
fi

# --- 3. build + upload worker -------------------------------------------
./build.sh
if $DRY; then echo "[dry-run] would upload $SCRIPT"; else
  echo "upload $SCRIPT"
  api -X PUT \
    -F "metadata=@metadata.json;type=application/json" \
    -F "worker.js=@worker.js;type=application/javascript+module" \
    "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT/workers/scripts/$SCRIPT" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print("  uploaded" if d.get("success") else d.get("errors"))'
fi

# --- 4. zone route (fail-open; see DEPLOY.md) ---------------------------
routes=$(api "https://api.cloudflare.com/client/v4/zones/$ZONE/workers/routes")
echo "$routes" | grep -q "\"$HOST/\*\"" && existing_route=true || existing_route=false
if $existing_route; then
  fo=$(echo "$routes" | python3 -c 'import json,sys;print(next((r["request_limit_fail_open"] for r in json.load(sys.stdin)["result"] if r["pattern"]==sys.argv[1]), None))' "$HOST/*")
  echo "route $HOST/* present (fail_open=$fo)"
fi
if ! $existing_route || [ "$fo" != "True" ]; then
  # request_limit_fail_open can only be set at CREATE; PATCH returns 10405.
  if $existing_route; then
    rid=$(echo "$routes" | python3 -c 'import json,sys;print(next(r["id"] for r in json.load(sys.stdin)["result"] if r["pattern"]==sys.argv[1]))' "$HOST/*")
    echo "recreating route (fail_open was $fo)"
    $DRY || api -X DELETE "https://api.cloudflare.com/client/v4/zones/$ZONE/workers/routes/$rid" >/dev/null
  fi
  echo "create route $HOST/*"
  $DRY || api -X POST -H "Content-Type: application/json" \
    "https://api.cloudflare.com/client/v4/zones/$ZONE/workers/routes" \
    --data "{\"pattern\":\"$HOST/*\",\"script\":\"$SCRIPT\",\"request_limit_fail_open\":true}" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); r=d.get("result") or {}; print("  ok fail_open=%s" % r.get("request_limit_fail_open")) if d.get("success") else print(d.get("errors"))'
fi

$DRY && { echo "[dry-run] done"; exit 0; }

# --- 5. verify ----------------------------------------------------------
echo "verify:"
code=$(curl -s -o /dev/null -w '%{http_code}' "https://$ORIGIN_HOST/")
echo "  $ORIGIN_HOST -> $code  (530 = tunnel down, 3xx/2xx = origin reachable)"
code=$(curl -s -o /dev/null -w '%{http_code}' "https://$HOST/")
echo "  $HOST -> $code"
echo "To prove the outage page: ssh lab 'docker stop cloudflared', curl $HOST (expect 503 + x-opensrm-maintenance), then 'docker start cloudflared'."
