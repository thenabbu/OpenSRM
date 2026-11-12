# P2.3b — css_parity: root cause + fix

## The real defect (not "two files, delete one")
At HEAD there is exactly ONE `app/static/dist/assets/app-*.css`
(`app-BYQAjcJM.css`, 36014 B) — the audit's "found two" text was from a tree
where a prior rebuild had left two behind. The genuine failure is different
and worse:

```
$ git show HEAD:app/static/dist/assets/app-BYQAjcJM.css | grep -o '@layer [a-z]*' | sort -u
@layer base
@layer components
@layer properties
@layer theme
          # NO '@layer daisyui' — zero daisyUI rules, zero .btn/.card/.alert
```

`web/tailwind.css` has `@plugin "daisyui" { themes: false; }` and was added in
`c9c67ac` (P2.1). The committed dist CSS was minified from an entry that did
NOT have that plugin — i.e. it is a **stale build artifact**, and it is the
only copy the app actually serves (manifest `src/main.ts -> css: app-BYQAjcJM.css`).

css_parity on HEAD fails for the right reasons:
```
3 cascade-order: no daisyUI component rule found
4 components: daisyUI components missing: alert, avatar, badge, btn, card, ...
6 size-backstop: dist 36014B < 80% of legacy 159092B
7 no-missing-class: 373 class tokens lost
```

## Why "delete the orphan" was the wrong instruction
HEAD has one CSS and it is referenced by `dist/manifest.json` AND precached by
`sw.js` (revision hashed). Deleting it deletes the stylesheet the app loads.
The stale artifact is the file IN USE; the fix is to replace it with a real
build of the current source, which is what the in-flight rebuild did.

## The fix applied
Rebuild `app/static/dist/` from `web/` (Vite + Tailwind v4 + daisyUI) and ship
the WHOLE dist together — manifest.json, every hashed asset, AND sw.js — never
sw.js alone (worker/dist mismatch is a known outage here).

After rebuild:
```
app-Dw5KSv9_.css 163407B, @layer daisyui x6, .btn present
css_parity: PASS — 3 sheets in source order, 222 hand rules at depth 0,
            daisyUI before hand sheets, components + keyframes intact
```

## Gate wiring
- `scripts/gates.sh`: `run_step "CSS parity (css_parity.py)"` in the static
  gates block + listed in `--list`.
- `.github/workflows/tests.yml`: step before the unit suites in the `tests`
  job (the `web/` job is separate, so the committed dist is what this checks).

## Second defect found while wiring
`css_parity.py` used to demand exactly one `app-*.css` and fail with
"found [two names]" — but it had no way to say WHICH is the keeper. A Vite
rebuild legitimately leaves the previous hash behind between `build` and `rm`.
Added `referenced_dist_css()`: reads `dist/manifest.json` (what assets_dist.py
maps through) and names the keeper + orphans on failure.
