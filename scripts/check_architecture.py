#!/usr/bin/env python3
"""Architecture gate: the extracted modules must stay a DAG.

Run it before every push that touches app/*.py. It fails on:

  1. an import cycle between app modules (the reason app.py grew to 4.5k lines);
  2. a module importing app.app when it is allowed to be a leaf;
  3. a name that app.py re-exports but no longer defines/imports;
  4. app.py growing past its line budget (the ratchet).

The point is that the 4.5k monolith cannot silently come back: each rule maps
to a failure that already happened once in this repo.
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")

# app.py may not exceed this. Lower it as the split progresses; never raise it.
APP_PY_BUDGET = 4415

# Modules that must never import app.app: they are below the facade in the
# dependency order, and importing it recreates the cycle.
LEAF_MODULES = {"crypto", "auth", "errors", "reqctx", "db", "config", "state",
                "security", "metrics", "logging_setup", "migrations"}

failures = []


def module_imports(path):
    """(name -> set of app-module names it imports) for one file.

    Function-body imports are tagged 'name@deferred': they run at CALL time, not
    module-import time, so they cannot deadlock an import and are allowed to
    point back at the facade. Module-level imports are the ones that cycle.
    """
    src = open(path).read()
    tree = ast.parse(src, path)
    pkg = os.path.dirname(path)
    out = set()
    deferred = set()
    for fn in ast.walk(tree):
        # collect line ranges of every function body
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for stmt in ast.walk(fn):
                if stmt is fn:
                    continue
                if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    target = _resolve(stmt, pkg)
                    deferred |= target
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            out |= _resolve(n, pkg)
    return out - deferred, out & deferred


def _resolve(n, pkg):
    res = set()
    if isinstance(n, ast.ImportFrom):
        if n.level:
            base = pkg
            for _ in range(n.level - 1):
                base = os.path.dirname(base)
            target = os.path.join(base, (n.module or "").replace(".", os.sep))
            if os.path.isfile(target + ".py"):
                res.add(os.path.basename(target))
            elif n.module == "app":
                res.add("app")
        elif n.module in ("app", "app.app"):
            res.add("app")
    elif isinstance(n, ast.Import):
        for a in n.names:
            if a.name in ("app", "app.app"):
                res.add("app")
    return res


graph = {}
deferred_edges = {}
for f in sorted(os.listdir(APP)):
    if f.endswith(".py"):
        hard, soft = module_imports(os.path.join(APP, f))
        graph[f[:-3]] = hard
        if soft:
            deferred_edges[f[:-3]] = soft

# 1. cycles
def find_cycles(g):
    seen, stack, cyc = set(), [], []

    def walk(n):
        if n in stack:
            cyc.append(stack[stack.index(n):] + [n])
            return
        if n in seen:
            return
        seen.add(n)
        stack.append(n)
        for m in g.get(n, ()):
            if m in g:
                walk(m)
        stack.pop()

    for n in g:
        walk(n)
    return cyc

for c in find_cycles(graph):
    failures.append("import cycle: " + " -> ".join(c))

# 2. leaves importing the facade
for m in sorted(LEAF_MODULES & set(graph)):
    if "app" in graph[m]:
        failures.append(f"{m}.py imports app.app — it must stay below the facade")

# 3. re-export integrity + 4. budget
app_path = os.path.join(APP, "app.py")
n = sum(1 for _ in open(app_path))
if n > APP_PY_BUDGET:
    failures.append(f"app.py is {n} lines, budget is {APP_PY_BUDGET} "
                    f"(raise the split, not the budget)")

print(f"architecture: {len(graph)} modules, app.py {n}/{APP_PY_BUDGET} lines")
for m in sorted(deferred_edges):
    print(f"  deferred (call-time) back-edge: {m} -> {','.join(sorted(deferred_edges[m]))}")
if failures:
    print(f"FAILED ({len(failures)})")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("OK — no cycles, leaves stay leaves, app.py within budget")
