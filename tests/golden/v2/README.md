# Golden baseline — v2 (the UI before the Preact migration)

**What this is FOR:** the frozen "previous product". Every file in this dir is
the app as it actually rendered at the v2 tip, so any later change is diffed
against a real artifact instead of someone's memory of the old UI. A restyle or
a route split that silently drops a card, a number, a class or a `<script>` tag
shows up here as a removed line:

```bash
diff -r tests/golden/v2 tests/golden/v3          # before / after the islands
diff -u tests/golden/v2/dom/dashboard.html <(curl -s ...)   # one route, one change
```

`tests/golden/v2` is **before**. `tests/golden/v3` (W3.3) is **after**. The
parent `tests/golden/` dir is an older committed capture that never recorded
which revision it came from (its `metrics.json` has no `revision` key), so it
cannot serve as a reproducible baseline — this dir can, because the capture
writes the SHA it captured into `metrics.json`.

## The exact revision

| | |
|---|---|
| SHA | `1fcbfe6` — *fix(ci): give Tests its own concurrency group so the reusable call survives (#161)* |
| recorded in | `metrics.json` → `"revision": "1fcbfe6"` (written by the capture, not by hand) |
| why this SHA | the v2 tip — last commit before the Preact migration work, see `notes/GROUND_TRUTH_20261113.md` |
| shape | **pre-islands**: zero `[data-island]` anywhere in the tree, so the capture's ready signal degrades to "document complete" |

Contents: 67 files, 2.5 MB — `routes.json` (9 tab ids + `panels_present`, all 9),
`dom/<tab>.html` × 9, `screens/<tab>-<viewport>.png` × 27 (3 viewports),
`api/<endpoint>.json` × 28, `metrics.json`.

## How to regenerate (verbatim)

Playwright does not run on the lab, so the capture runs on the laptop from a
detached worktree of the same SHA. Tool tip `024d5ac` (W3.1) is the capture tool
that supports `--repo` and is byte-reproducible; an older copy of the tool on the
same SHA produces a different set of bytes, so pin both SHAs.

```bash
# laptop: two detached worktrees off any clone of the repo
mkdir -p ~/w32
git -C ~/osrm-w219 fetch origin --prune
git -C ~/osrm-w219 worktree add --detach ~/w32/script 024d5ac   # the capture tool
git -C ~/osrm-w219 worktree add --detach ~/w32/v2     1fcbfe6   # the app under test

# laptop: capture (seeds a clean DATA_DIR, boots its own gunicorn, shuts it down)
cd ~/w32/script
/home/navya/work/osrm-w219/.venv/bin/python scripts/capture_golden.py \
    --repo ~/w32/v2 \
    --python /home/navya/work/osrm-w219/.venv/bin/python \
    --out ~/w32/out-check --port 18185
```

Then, from the repo root (lab or laptop):

```bash
diff -r -x README.md tests/golden/v2 ~/w32/out-check    # expect: no output
```

`-x README.md`: the tool regenerates `README.md` in every output dir from its own
constant, so this hand-written file is the single thing a regen replaces. Every
other file must come back byte-identical — screenshots included.

## What is normalised, and why

Authoritative list: the module docstring of `scripts/capture_golden.py`. Restated
here because anyone reading these files must not mistake a masked value for app
behaviour:

| # | Field | Why it is masked |
|---|---|---|
| 1 | `?v=<hash>` asset queries | `asset()` appends `sha256(file)[:10]`; a deploy detail, not behaviour |
| 2 | Vite build hashes in dist filenames (`SettingsPanel-Crq-6lwG.js` → `SettingsPanel-HASH.js`) | changes on every rebuild of identical source |
| 3 | `data-ts` / `data-full` on the sync line | last-sync epoch, rendered from wall clock |
| 4 | Relative ages (`just now`, `5m ago`, `3d ago`) | wall-clock text, never app state |
| 5 | Epoch ints / ISO timestamps in JSON keys (`ts`, `fetched_at`, `last_sync`) | same |
| 6 | `/internal/metrics` values | live process counters (RSS, histogram sums); names and labels are kept — they are the structural contract |
| 7 | Recorded byte/gzip sizes | computed on the **normalised** bytes, else they wobble by a few bytes per run |
| 8 | blobatar avatar phases (`--mo-phase`, `--mo-look-x`, `--mo-blink`, …) | the avatar SVG is generated per request, so the same student blinks differently on every load; pinned at both ends (recorded body + the document the browser is served) so DOM **and** pixels match |

Everything else is real: text, classes, attributes, DOM order, script lists, API
bodies, pixel content.

## Determinism proof

Two independent captures of `1fcbfe6` into separate dirs (ports 18185 and 18186,
separate processes, ~2 m 22 s each):

```
$ diff -r ~/w32/out-a ~/w32/out-b
$ echo $?
0
```

67 files / 2.5 MB / 27 screenshots, byte-identical including every PNG. The
committed tree here is `out-a` verbatim.

Note: the harness hard-fails if fewer than the 9 tabs are in the DOM
(`panels missing from DOM: [...]`), so a partial 5-of-9 baseline is rejected
rather than committed.
