#!/usr/bin/env bash
# promtool checks for ops/observability/ — config, rules, and the rule unit
# tests — using the SAME pinned Prometheus image the compose file deploys.
# Run from the repo root: bash scripts/ci_promtool.sh
# (CI: tests.yml runs it as its own step; the exit code is the gate.)
#
# The tree is piped in over stdin (tar) instead of bind-mounted: the image
# declares VOLUME /etc/prometheus (binds there are shadowed by an anonymous
# volume) and this keeps the script location-independent — no path the
# docker daemon must see, so it behaves identically in CI and on a dev box.
set -euo pipefail

PROM_IMG="prom/prometheus:v3.13.4@sha256:87861b8cf91579109319ebc300f3f1060e6da9c05d6ae8ad15a20c879e84e32e"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/ops/observability/prometheus"

run() {
  # $1 = shell command run after extraction; PROMTOOL_CHECKS env passes it.
  tar -C "$SRC" -cf - . | docker run --rm -i --entrypoint sh "$PROM_IMG" -c '
    set -e
    mkdir -p /tmp/work
    tar -xf - -C /tmp/work
    sed -i "s#/etc/prometheus#/tmp/work#g" /tmp/work/prometheus.yml
    '"$1"
}

echo "== promtool check config =="
run "promtool check config /tmp/work/prometheus.yml"
echo "== promtool check rules =="
run "promtool check rules /tmp/work/rules/opensrm.yml"
echo "== promtool test rules =="
run "cd /tmp/work/rules && promtool test rules opensrm.test.yml"
echo "promtool: all checks passed"
