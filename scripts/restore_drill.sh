#!/usr/bin/env bash
# Restore drill — prove a daily snapshot restores cleanly WITHOUT touching prod.
#
# Materialises the snapshot into a TEMP DB, runs PRAGMA integrity_check, and
# prints schema version + per-table row counts next to the live DB's (read-only;
# the temp DB is deleted on exit; nothing is written into the snapshot dir or
# the data volume). Run it on the lab host:
#
#   bash scripts/restore_drill.sh                          # newest snapshot
#   bash scripts/restore_drill.sh /path/srm.20261016.snapshot.db.gz [live.db]
#
# Verdict: FAIL on integrity error, missing core tables, or a drill schema NEWER
# than live (restoring it would downgrade past what the app re-migrates).
# Row-count deltas vs live are INFO — the snapshot is up to a day old, so
# high-churn tables (usage_events, cookies, push_*) legitimately differ.
# The second arg overrides the live DB (default: the running prod container);
# that override is also how this script is tested off-host.
set -euo pipefail

SNAP=${1:-}
if [ -z "$SNAP" ]; then
    SNAP=$(ls -1t /data/ssd120/backups/opensrm/srm.*.snapshot.db.gz 2>/dev/null | head -1) || true
fi
[ -n "$SNAP" ] && [ -r "$SNAP" ] || { echo "FAIL: no snapshot given and none found"; exit 1; }
LIVE=${2:-}

DRILL=$(mktemp /tmp/srm-drill-XXXXXX.db)
trap 'rm -f "$DRILL"' EXIT
gunzip -c "$SNAP" > "$DRILL"
echo "snapshot: $SNAP"

if ! INT=$(sqlite3 "$DRILL" "PRAGMA integrity_check;" 2>&1); then
    echo "FAIL: integrity_check -> ${INT:-unreadable database}"; exit 1
fi
[ "$INT" = "ok" ] || { echo "FAIL: integrity_check -> $INT"; exit 1; }
echo "integrity_check: ok"

for t in users schema_version; do
    n=$(sqlite3 "$DRILL" "select count(*) from $t;" 2>/dev/null || echo "")
    [ -n "$n" ] || { echo "FAIL: core table missing in snapshot: $t"; exit 1; }
done
DRILL_SCHEMA=$(sqlite3 "$DRILL" "select coalesce(max(version),0) from schema_version;")
echo "drill schema max(version): $DRILL_SCHEMA"

live_counts() {
    if [ -n "$LIVE" ]; then
        for t in $(sqlite3 "$LIVE" "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name;"); do
            printf '%s\t%s\n' "$t" "$(sqlite3 "$LIVE" "select count(*) from \"$t\";")"
        done
    else
        docker exec opensrm python3 -c "
import sqlite3
c = sqlite3.connect('/app/data/srm.db')
for (t,) in c.execute(\"select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name\"):
    print(t, c.execute('select count(*) from \"%s\"' % t).fetchone()[0], sep='\t')
"
    fi
}

if [ -n "$LIVE" ]; then
    LIVE_SCHEMA=$(sqlite3 "$LIVE" "select coalesce(max(version),0) from schema_version;")
else
    LIVE_SCHEMA=$(docker exec opensrm python3 -c "import sqlite3;print(sqlite3.connect('/app/data/srm.db').execute('select coalesce(max(version),0) from schema_version').fetchone()[0])")
fi
echo "live  schema max(version): $LIVE_SCHEMA"
[ "$DRILL_SCHEMA" -le "$LIVE_SCHEMA" ] || { echo "FAIL: drill schema $DRILL_SCHEMA > live $LIVE_SCHEMA (restore would downgrade)"; exit 1; }

echo "table rows: drill vs live (delta)"
join -t "$(printf '\t')" \
     <(for t in $(sqlite3 "$DRILL" "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name;"); do
           printf '%s\t%s\n' "$t" "$(sqlite3 "$DRILL" "select count(*) from \"$t\";")"
       done | sort) \
     <(live_counts | sort) \
    | awk -F'\t' '{printf "%-28s %8d %8d %+8d\n", $1, $2, $3, $3-$2}'
echo "DRILL PASS: snapshot is restorable (schema $DRILL_SCHEMA <= live $LIVE_SCHEMA, integrity ok)"
