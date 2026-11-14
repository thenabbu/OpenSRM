# Golden baseline — v3 (the UI *after* the Preact islands)

**What this is FOR:** the "current product", frozen. Every file here is the app
as it actually rendered at the branch tip, so the next change is diffed against a
real artifact instead of someone's memory of the UI. A restyle, a route split or
an island that silently drops a card, a number, a class or a `<script>` tag shows
up here as a removed line:

```bash
diff -r tests/golden/v2 tests/golden/v3        # before / after the islands
diff -u tests/golden/v3/dom/dashboard.html <(curl -s ...)   # one route, one change
```

`tests/golden/v2` is **before** (pre-islands, `1fcbfe6`). This dir is **after**
(post-islands). Both record the SHA they were captured at in `metrics.json`, so
both are reproducible; the parent `tests/golden/` dir is an older capture that
never recorded its revision and cannot be.

## The exact revision

| | |
|---|---|
| SHA | `6ebdeae` — *feat(golden): --check mode — capture and diff against a committed baseline* |
| recorded in | `metrics.json` → `"revision": "6ebdeae"` (written by the capture, not by hand) |
| why this SHA | the `feat/preact-migration` tip when the capture ran. Every commit between it and the last app change touches `tests/` or `scripts/` only, so the rendered UI is the same — and `metrics.json`'s `revision` is exempt in the gate for exactly that reason |
| shape | **post-islands**: all 9 panels carry `data-island` + `data-props` + `data-hydrated="1"` |
| tool SHA | the same commit — `--check` landed here, so tool and app are one checkout |

Contents: 68 files, 2.4 MB — `routes.json` (9 tab ids + `panels_present`, all 9),
`dom/<tab>.html` × 9, `screens/<tab>-<viewport>.png` × 27 (3 viewports),
`api/<endpoint>.json` × 30, `metrics.json`.

## The gate: `--check`

This is the point of the dir. CI re-captures and diffs, so drift is a red build
instead of a user noticing:

```bash
bash scripts/capture_golden.sh --check                 # ~2.5 min, exit 0 == matches
bash scripts/capture_golden.sh --check --no-screens    # what CI runs (see below)
```

It captures into a throwaway dir, compares byte-for-byte, and prints **every**
differing file by name (`differs: dom/dashboard.html`, `only in golden: …`,
`only in capture: …`), exiting 1 on any difference. Two exemptions, both
deliberate:

| exempt | why |
|---|---|
| `README.md` | the tool regenerates it, so this hand-written file would always differ |
| `metrics.json` → `revision` | provenance, not behaviour: it names the SHA the golden was *captured* at, which is by definition older than the HEAD being checked. Comparing it would leave the gate permanently red one commit after every capture |

`--no-screens` is not a weakening, it is honesty about physics: the PNGs encode
the capture host's font stack (the app ships no webfonts — it asks for
`-apple-system, "Segoe UI", Roboto, "Noto Sans", Arial` and the host decides),
so a GitHub runner cannot be byte-compared with a laptop capture. On CI the gate
therefore covers `dom/`, `api/`, `routes.json` and `metrics.json`; a same-host run
compares the pixels too. CI job: **e2e** (`Golden drift (tests/golden/v3
--check)`), not unit — the step boots gunicorn and drives chromium, and the
browsers are installed there.

## How to regenerate (verbatim)

Playwright does not run on the lab, so the capture runs on the laptop from a
checkout of the recorded SHA:

```bash
# laptop
cd ~/w33/repo && git fetch origin && git checkout --detach 6ebdeae
.venv/bin/python scripts/capture_golden.py \
    --repo "$PWD" --python "$PWD/.venv/bin/python" \
    --out ~/w33/out-check --port 18185
```

Then, on the host holding the goldens:

```bash
diff -r -x README.md tests/golden/v3 ~/w33/out-check     # expect: no output
```

`-x README.md`: the tool regenerates `README.md` in every output dir from its own
constant, so this hand-written file is the single thing a regen replaces. Every
other file must come back byte-identical — screenshots included, on this host.

## What is normalised, and why

Authoritative list: the module docstring of `scripts/capture_golden.py`. Restated
in `tests/golden/v2/README.md`; the eight rules are unchanged (asset `?v=` hashes,
Vite build hashes, `data-ts`/`data-full`, relative ages, epoch/ISO timestamps,
`/internal/metrics` values, sizes computed on normalised bytes, blobatar avatar
phases). Everything else is real: text, classes, attributes, DOM order, script
lists, API bodies, pixel content.

## Determinism proof

Two independent captures of `6ebdeae` into separate dirs (ports 18185 and 18186,
separate processes, 145 s and 143 s):

```
$ diff -r ~/w33/out-a ~/w33/out-b
$ echo $?
0
```

69 files / 2.4 MB / 27 screenshots, byte-identical including every PNG. The
committed tree here is `out-a` minus the generated README.

## What moved between v2 and v3

`diff -rq v2 v3` = 52 differing entries: **all 9 `dom/` pages**, **13 `api/`
bodies**, **all 27 screenshots**, plus two new endpoints
(`api/static_dist_assets_app-HASH.css.json`, `…js.json` — the island bundles,
pre-v3 there were none). That is the migration's blast radius, on the record.
