# P7.6 — why `#island-attendance` paints 0 rows (diagnosis, evidence first)

Run: 2026-11-10, seeded lab server on :18291, real Chromium, console + DOM
mutation capture. Dist: `app-8wAe8lWI.js` (mtime 2026-11-10 11:27).

## Established by observation, not reading

Server HTML carries the block **and** the rows:

```
302: <script type="application/json" id="island-attendance">{"courses":[8 courses]}</script>
304: <div class="mrows" data-island="attendance" data-props="#island-attendance">
```

Hook on `Element.prototype.replaceChildren` for the mount node:

```
6732ms BEFORE replaceChildren call#1 children=8
6732ms AFTER  replaceChildren call#1 children=0
6813ms   microtask call#1 children=8 mrows=8     <-- FIRST MOUNT PAINTS 8 ROWS
6906ms BEFORE replaceChildren call#2 children=8
6919ms AFTER  replaceChildren call#2 children=0
6919ms   microtask call#2 children=0 mrows=0     <-- SECOND MOUNT PAINTS 0
```

Stack for both, decoded against the bundle
(`Kd` = `mountBounded`, `Jd` = `hydrateIsland`, `Yd` = `hydrateAll`):

```
at Kd (app-8wAe8lWI.js:58:105858)
at Jd (app-8wAe8lWI.js:58:106308)
at async Yd (app-8wAe8lWI.js:58:106771)
```

`Yd` has exactly ONE call site in the bundle. Two executions of it therefore
mean **the entry module body ran twice**.

## Root cause

| Where | URL |
|---|---|
| `theme.html:100` via `asset_dist('app')` | `/static/dist/assets/app-8wAe8lWI.js?v=940e00e950` |
| every island chunk, e.g. `AttendancePanel-DQ0SFj5b.js` | `import{n as e}from"./app-8wAe8lWI.js"` — **no query** |

Same bytes, **two module-map keys** → the bundle is evaluated twice → its
top-level IIFE `(async()=>{await Td(document); await Yd(document, …)})()` runs
twice → `mountBounded` is called twice on the **same** element.

The first evaluation is complete and correct (8 rows). The second evaluation is
a *different module instance* whose `preact` is a different module namespace, so
rendering its tree into a container already owned by the first instance
reconciles to nothing. `mountBounded` also calls `el.replaceChildren()` first,
so the server paint is gone before that empty tree lands.

The card's `claimed` WeakSet does not help: it lives in the module that is
evaluated twice, so each evaluation has its own fresh WeakSet.

Browser request log confirming two fetches of the entry:

```
/static/dist/assets/app-8wAe8lWI.js?v=940e00e950
/static/dist/assets/app-8wAe8lWI.js          <-- second, un-versioned
```

## Which of the card's four hypotheses

- [ ] mount replaced by an empty render
- [ ] component throws and the boundary restores an empty mount
- [ ] element measured is not the element mounted
- [x] **the same module is evaluated twice and the second mount reconciles the
      first tree away** — none of the four named exactly this; it is the
      "double mount" *family*, but the trigger is the URL split, not a dead guard.

## Fix direction

Make the versioned URL and the chunk-relative URL the same key. Cheapest
correct option: stop versioning the Vite entry at all — Vite filenames are
content-hashed (`app-8wAe8lWI.js`), so `?v=` adds nothing but the split.
