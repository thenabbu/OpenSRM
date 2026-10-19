# Phase 2 status — pre-compiled CSS (smoothness campaign)

State at gateway restart, 2026-10-19 ~16:30 IST. Branch
`perf/phase-2-precompiled-css` fully committed + pushed. PR not yet created.

## Campaign position

- **Phase 0 MERGED (PR #82) + DEPLOYED** — prod badge verified `OpenSRM
  v1.26.1`, `post_deploy.sh` 6/6 PASS. Baseline lives in `docs/perf/baseline.md`,
  36 before-shots in `docs/screenshots/perf-baseline/`.
- **Phase 1 MERGED (PR #86)** — rules-first docs (AGENTS/README/SECURITY/
  runbook/DESIGN §7, §9, §10.16 "Performance rules", checklist; verify76
  D27/D53 flipped). Docs-only, no bump, no deploy.
- **Phase 2 implemented, gated green, awaiting the parity pass + PR.**
- Granted standing order: "go on autonomously" = merge each phase when CI
  green, keep building; deploy each runtime phase per house default (done
  once for phase 0).

## Phase 2 — what is DONE (all committed)

- `app/static/src.css` (source(none) + explicit @source for determinism;
  plain-CSS @imports last = cascade order unchanged), `app/static/
  safelist/classes.html` (LAYOUT col-span 4/8/12, row-span-2, sm:grid-cols
  1/2/3, progress-success/warning/error, lg:max-h-[calc((100dvh-94px)*0.65)]),
  `scripts/build-css.sh` (pinned TW standalone v4.3.3 sha256
  dc61b3ac6b8c9ca874c0cc4c57b2409791a64c5540404ca5f5367360babc313a,
  daisyUI 5.7.46 tgz sha256 bc7ec4d7d4a30daebd1f11bbb25f7a96527f818d473aead7679201b34c77590c;
  node_modules symlink at repo root during build, trap-removed, gitignored;
  gzip budget gate 36864 B). Standalone path is TESTED working (the prompt's
  untested path): bare `@plugin "daisyui"` resolves via directory walk-up.
- Committed `app/static/app.css`: 149040 B raw / **23944 B gzipped** (budget
  35 KB ✓). Rebuild = byte-identical (CI check will pass).
- `asset()` jinja global in app/app.py (mtime-keyed sha256[:10], registered
  inside `create_app` so factory apps get it) + CSP drops both jsdelivr
  entries. theme.html: `<meta name="color-scheme" content="dark">` first
  line, `html { background: oklch(20% 0 0); }` in the inline style, CDN tags
  replaced by `{{ asset('app.css') }}`. dashboard.html: 3 stylesheet links
  removed. Only login+dashboard include theme.html.
- `tests/test_css_safelist.py` 10/10 [unit] — rendered dynamic-family tokens
  ⊆ app.css + asset link + no CDN; **red-tested** (empty safelist → 8/10
  naming missing tokens). AGENTS matrix row + tests.yml unit step + lint.yml
  "rebuild + git diff --exit-code" check added. verify76 L47 flipped to pin
  the compiled build (theme.html asset link, no jsdelivr, TW/DAISY pins,
  safelisted class present in app.css).
- v1.26.2 trio + NOTICES "Faster first paint" prepended.
- Gates green: verify76 72/72 · ruff app/ · uv lock --check · test_layout
  25/25 · test_css_safelist 10/10 · build-css byte-identical.

## After-numbers (scripts/perf_baseline.py, merged-tree run, /tmp/p2metrics_final.md)

| metric | baseline (phase 0) | phase 2 |
|---|---|---|
| cold FCP | 3244 ms | 3392 ms (variance) |
| cold DCL / load | 6974 / 7089 ms | **3790 / 3832 ms** |
| cold wall→networkidle | 8862 ms | **5550 ms** |
| cold wire bytes | 393.2 KB | **313.0 KB** (zero third-party) |
| requests | 14 | 10 |
| tab-switch long tasks | 15 / 5822 ms | 9 / 1187 ms (some run variance) |
| warm wire bytes | 180.7 KB | 247.5 KB — **expected**: app.css is no-store until Phase 3 makes ?v= assets immutable |
| sync / animations | reload; 8 infinite | unchanged (Phase 4/6 targets) |

## OPEN: the visual-parity pass (where work stopped)

Facts already proven:
1. **Code parity is proven**: old (origin/main @2d1cfce) vs new (branch)
   servers → computed styles + geometry IDENTICAL (style probes), and
   det-style screenshots of both servers differ by **0.01%**. The compiled
   cascade reproduces the CDN world exactly.
2. Same-server double-shot: **0.0%** → capture is deterministic.
3. Dashboard pair diffs = **the v1.26.2 release notice content itself**
   (notices card renders new text) — EXPECTED, not a regression.
4. Capture method matters: `is_mobile` emulation, font flags and seed-to-shot
   latency all shift pixels; before/after must be captured back-to-back by
   the same script (skill rule, re-confirmed).
5. Residual UNEXPLAINED: attendance pair (perf-baseline vs perf-baseline)
   = 13.16% any / 2.16% strong, spread across all row bands; raw pixels show
   navbar-end glyphs (refresh/sync-line zone, x≈609-749 @DPR2 y≈56) at
   different x positions between runs — leading hypothesis: the
   **relative-time sync-line text** ("(Nm ago)") differs because seed→shot
   latency differed between runs (renderSyncLines shows it after 300 s),
   shifting navbar-end glyphs; meter-row bands still need localisation.

Next steps (resume here):
1. Re-capture BEFORE and AFTER **in one process, back-to-back**: temporary
   worktree of origin/main runs perf_baseline shots → immediately run the
   branch's shots (already done once at 15:38/15:47 — REDO within <5 min of
   each seed so the sync-line stays hidden both sides, or poke
   `renderSyncLines` to hidden state). Diff again; expect near-zero except
   the notices text.
2. If attendance still differs: crop+numeric-diff one meter row, then probe
   computed styles under the EXACT shot context (is_mobile=True, DPR2,
   font flags).
3. Remaining phase-2 work after parity: local browser DUTs (test_sw, xss,
   navbar, dash_fit, personal, marks_dut, att_dut, delete_dut,
   feedback_dut/contrast, guide_check, official_tt), full gates, PR body
   (before/after shots under docs/screenshots/, metrics table), PR, CI,
   merge (standing grant), deploy (badge → v1.26.2), CF purge via
   post_deploy.sh.

## Resume environment

- Worktree: `/opt/data/cache/scratch/perf-phase-2-css/wt` (branch
  `perf/phase-2-precompiled-css`, pushed). venv `/opt/data/opensrm-repo/.venv`,
  browsers `PLAYWRIGHT_BROWSERS_PATH=/opt/data/cache/scratch/pw-browsers`
  (reinstall: `.venv/bin/playwright install --only-shell chromium` — scratch
  prunes idle).
- Toolchain cache for build-css.sh: `/opt/data/cache/scratch/perf-phase-2-css/toolchain`
  (pass `OPENSRM_CSS_CACHE=<that dir>` to skip re-download).
- Live helper servers (may be dead after restart): 18187 = old code +
  /tmp/osrm-parity-old, 18188 = branch + /tmp/osrm-parity-new (both seeded
  seed_rich). Temp worktree `/tmp/main-shots-wt` (detached origin/main with
  a patched perf_baseline copy) — remove when done.
- Probe scripts: /tmp/style_probe.py, /tmp/att_probe.py, /tmp/det_shoot.py,
  /tmp/mob_shoot.py, /tmp/rowdiff.py; parity images /tmp/cmp_*.png,
  /tmp/true_pair_diff.png, /tmp/before_anom_*.png.
- perf_baseline.py got a click-fallback for the tab-shot hash-restore race
  (in the branch copy only; main's copy still has the flake ~1 run in N).
- Phases 3-8 remain per the campaign prompt (soft-refresh assets, in-place
  refresh, motion, low-end tier, pull-to-refresh, guardrail tests).
