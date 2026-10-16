"""Dashboard card/widget registries: LAYOUT + WIDGETS (moved from app.app;
re-exported from app.app; index() reads them through app.app's namespace)."""

# ── Dashboard card/widget engine ────────────────────────────────────────────
# Contract (session spec, engine-spec.md): a card is one LAYOUT entry (grid
# span + widget ids); a widget is one WIDGETS entry pointing at a partial that
# emits its OWN label + box — no data -> it emits nothing (DESIGN §4.12
# empty=hidden). Adding/removing a card or widget edits ONLY these dicts:
# no template, route or test churn beyond the widget's own partial.
LAYOUT = [
    {"id": "day", "span": 4, "row_span": 2,
     "widgets": ["profile", "today", "week", "notices"]},
    # `when` = route-context vars that must be truthy for the card to render
    # (all-empty card -> no orphan shell). Missing `when` = always show.
    # `cap` = lg max-height as a fraction of the viewport-fit grid
    # (calc((100dvh-94px)*cap)) — clamps row 1's content height so a heavy
    # exams/marks load can't starve row 2 (stress: uncapped auto row 1 = 640px
    # crushed row 2 to 2px at 1024x768). % rows don't work: maximize-tracks
    # STRETCHES them to the limit (row 1 ate 65% even with normal data).
    {"id": "assess", "span": 8, "when": ["marks_summary", "exams"],
     "cap": "0.65", "widgets": ["marks", "exams"]},
    {"id": "people", "span": 8, "when": ["budgets", "teach_groups"],
     "cols": 2, "widgets": ["attendance", "teachers"]},
]
# min_w = measured plateaus (mockup measure_widgets.py): a card's inner width
# must stay >= min_w for every widget it carries (span math, not vibes).
WIDGETS = {
    "profile":    {"partial": "partials/widgets/profile.html",  "min_w": 250},
    "today":      {"partial": "partials/widgets/today.html",    "min_w": 260},
    "week":       {"partial": "partials/widgets/week.html",     "min_w": 250},
    "notices":    {"partial": "partials/widgets/notices.html",  "min_w": 300},
    "marks":      {"partial": "partials/widgets/marks.html",    "min_w": 560},
    "exams":      {"partial": "partials/widgets/exams.html",    "min_w": 560},
    "attendance": {"partial": "partials/widgets/attendance.html", "min_w": 300},
    "teachers":   {"partial": "partials/widgets/teachers.html", "min_w": 358},
}
