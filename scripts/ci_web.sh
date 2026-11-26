#!/usr/bin/env bash
# P2.4b web/ CI gate: install -> typecheck -> unit tests.
# Called from tests.yml (job `web`). Kept as a script so the workflow stays one
# step instead of three and the local repro is the same line CI runs:
#   bash scripts/ci_web.sh
#
# Node version is pinned by the workflow (setup-node, 22.x), NOT here — see the
# comment on that step in tests.yml for why 22 and not the lab's 26.
set -euo pipefail
R="$(cd "$(dirname "$0")/.." && pwd)"
cd "$R/web"

echo "== node $(node -v) / pnpm $(pnpm -v) =="

# --frozen-lockfile: a lockfile that does not match package.json is a failure,
# not a silent re-resolve. If a dependency ever needs a build script it is NOT
# in package.json's pnpm.onlyBuiltDependencies (currently just esbuild), pnpm
# prints an ignored-build-scripts warning here instead of running it. Do not
# paper over that with --config.dangerouslyAllowAllBuilds=true in CI: that runs
# arbitrary postinstall code from any transitive dep on the runner.
pnpm install --frozen-lockfile

echo "== tsc --noEmit (src/) =="
pnpm exec tsc --noEmit

# The design-token tests use @ts-expect-error as a real compile-time assertion
# ("an invalid variant must not compile"). The root tsconfig excludes *.test.ts,
# so this second config is the only thing that checks them. `pnpm build` runs it,
# so the gate must too or CI would pass a tree the local build rejects.
echo "== tsc -p tsconfig.design.json (design token negative tests) =="
pnpm exec tsc -p tsconfig.design.json

echo "== vitest run =="
pnpm exec vitest run
