"""
Widget DOM parity DUT — the pattern-prover for the widget port (W5.1).

ONE widget, TWO paints, ONE contract. The server paints
`app/templates/partials/widgets/profile.html`; the island wipes that mount
(`main.ts` mountBounded -> `el.replaceChildren()`) and paints its own nodes from
`web/src/panels/dashboard/DashboardPanel.tsx`. Both must produce the same
element tree with the same attribute NAMES, in the same ORDER, with the same
values — the four things the widget carries (name, email, `.blobatar-gaze`
avatar, `#copyEmail`) all reach the browser through those attributes.

Why attributes and not text: three bugs in this migration came from an island
reproducing the visible content while dropping an attribute. Text-snapshot
parity passed all three. `data-email` is the load-bearing one here — drop it and
`#copyEmail` looks perfect and copies nothing.

How: the SAME seeded page is loaded twice against the same server — once with
`java_script_enabled=False` (the server paint) and once normally (the island
paint, gated on `[data-island="dashboard"][data-hydrated]` so a page that never
hydrated cannot pass as a match). Only attributes declared in CLIENT_STAMPS are
dropped, and they are dropped from BOTH sides, never just the island's — an
island-only allowlist is how a dropped server attribute hides.

CLIENT_STAMPS are the runtime marks of separate scripts, not part of either
paint's contract:
  data-offscreen-obs, style  — perf.js/dash.js avatar IntersectionObserver + gaze
                               driver inline `--mo-*` vars
  data-copy-ready, tabindex,
  role                       — dash.js setupCopyTargets keyboard/copy arming
  data-hydrated              — main.ts mount marker
They are then asserted SEPARATELY as present on the island paint: that is the
`osrm:island-mounted` re-arm, i.e. proof dash.js/gaze.js re-bound to the island's
nodes instead of the detached server nodes they armed at load.

Adding a widget: one entry in WIDGETS. Everything else is generic.

Run:  python tests/e2e/test_widget_parity_dut.py   (needs a seeded server on DUT_BASE)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATA_DIR", "/tmp/osrm-widget-parity")
from _seed import mint_token, require_own_server, seed_rich  # noqa: E402

seed_rich()
TOK = mint_token()
BASE = os.environ.get("DUT_BASE", "http://127.0.0.1:18180")
require_own_server(BASE)

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# ── the contract ─────────────────────────────────────────────────────────
CLIENT_STAMPS = {
    "data-offscreen-obs",
    "style",
    "data-copy-ready",
    "tabindex",
    "role",
    "data-hydrated",
}

# mount: the island that owns the widget (data-hydrated proves it painted);
# anchor: the widget's identity element on the page.
WIDGETS = [
    {
        "name": "profile",
        "server": "app/templates/partials/widgets/profile.html",
        "island": "web/src/panels/dashboard/DashboardPanel.tsx",
        "mount": '[data-island="dashboard"]',
        "anchor": "#copyEmail",
        "box": ".wbox",
        # what the island's own nodes must have been re-armed WITH, after mount
        "rearmed": [
            ("document.querySelector('#copyEmail').closest('.wbox').querySelector('[data-copy]')",
             "data-copy-ready"),
            ("document.querySelector('.blobatar-gaze')", "data-offscreen-obs"),
        ],
    },
]

SNAPSHOT = """([anchorSel, boxSel]) => {
  const anchor = document.querySelector(anchorSel);
  if (!anchor) return null;
  const box = anchor.closest(boxSel);
  if (!box) return null;
  const out = [];
  const walk = (n, depth) => {
    out.push({
      tag: n.tagName.toLowerCase(),
      depth,
      // NamedNodeMap iterates in document order, which is what "same order" means
      attrs: [...n.attributes].map(a => [a.name, a.value]),
      text: n.children.length ? '' : n.textContent.trim().slice(0, 80),
    });
    for (const c of n.children) walk(c, depth + 1);
  };
  walk(box, 0);
  return out;
}"""


def strip(snap):
    return [
        (n["depth"], n["tag"], [(k, v) for k, v in n["attrs"] if k not in CLIENT_STAMPS], n["text"])
        for n in snap
    ]


def render(rows):
    return "".join(
        f"{'  ' * d}<{t}> " + " ".join(f'{k}="{v}"' for k, v in a) + (f" text={x!r}" if x else "")
        for d, t, a, x in rows
    )


def first_diff(server, island):
    for i, (s, c) in enumerate(zip(server, island)):
        if s != c:
            return f"node #{i}\n      server: {s}\n      island: {c}"
    if len(server) != len(island):
        return f"node count: server {len(server)} vs island {len(island)}"
    return ""


from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as p:
    b = p.chromium.launch(args=["--font-render-hinting=none", "--force-color-profile=srgb"])
    for w in WIDGETS:
        name = w["name"]
        # ── paint 1: the server, no JS ──────────────────────────────────
        ctx = b.new_context(java_script_enabled=False)
        ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
        page = ctx.new_page()
        page.goto(BASE + "/", wait_until="load")
        server_snap = page.evaluate(SNAPSHOT, [w["anchor"], w["box"]])
        check(f"{name}: server paints the widget ({w['server']})",
              server_snap is not None and len(server_snap) >= 8,
              f"nodes={len(server_snap) if server_snap else 0}")
        ctx.close()

        # ── paint 2: the island, after hydration ────────────────────────
        ctx = b.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_cookies([{"name": "srm_session", "value": TOK, "url": BASE}])
        page = ctx.new_page()
        page.goto(BASE + "/", wait_until="load")
        page.wait_for_selector(f'{w["mount"]}[data-hydrated]', timeout=15_000)
        page.wait_for_timeout(600)          # dash.js/gaze.js re-arm on the mount event
        island_snap = page.evaluate(SNAPSHOT, [w["anchor"], w["box"]])
        check(f"{name}: island paints the widget ({w['island']})",
              island_snap is not None and len(island_snap) >= 8,
              f"nodes={len(island_snap) if island_snap else 0}")

        if server_snap and island_snap:
            s_rows, i_rows = strip(server_snap), strip(island_snap)
            diff = first_diff(s_rows, i_rows)
            check(f"{name}: island DOM == server DOM (tag, attribute names, ORDER, values)",
                  not diff,
                  diff)
            if diff:
                print("    ---- server ----\n" + render(s_rows))
                print("    ---- island ----\n" + render(i_rows))

            # positive control: the pair above cannot be satisfied by two empty
            # or stripped trees — the load-bearing attributes must be there.
            s_attrs = {k for _, _, a, _ in s_rows for k, _ in a}
            i_attrs = {k for _, _, a, _ in i_rows for k, _ in a}
            need = {"class", "id", "data-email", "type", "title", "data-copy"}
            check(f"{name}: contract attributes present on BOTH paints",
                  need <= s_attrs and need <= i_attrs,
                  f"missing server={sorted(need - s_attrs)} island={sorted(need - i_attrs)}")

            # the re-arm: dash.js/gaze.js must have re-bound to the ISLAND's
            # nodes (they first armed against the server markup we replaced)
            for expr, attr in w["rearmed"]:
                ok = page.evaluate(
                    "([expr, attr]) => { const el = eval(expr);"
                    " return !!el && el.hasAttribute(attr); }",
                    [expr, attr],
                )
                check(f"{name}: client script re-armed the island's node ({attr})", ok, expr)
        ctx.close()

    try:
        b.close()
    except Exception:
        pass

fails = [n for n, ok in results if not ok]
print(f"\nTOTAL: {len(results)} checks | PASS {len(results) - len(fails)} | FAIL {len(fails)}")
if fails:
    print("FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
