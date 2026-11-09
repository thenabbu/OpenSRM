"""The dashboard page: one view model, one presentation, nine routes.

Extracted from app/app.py (facade pump, cycle E). `panel_data` is the app's
main data screen — attendance, marks, timetable, exams, fees, academics,
campus, the ticker — as one dict; `index` renders a panel from it, and the
/api/<panel> endpoints (P50) serve slices of the SAME dict as JSON, so the
page and the offline store cannot disagree. It lives here because it is a
VIEW: it only reads, joins and shapes.

`_load_component_tags`, `_week_marks` and `_exams_view` travel with it: nothing
outside the dashboard renders those three, so they are part of this page's view
model rather than general helpers.

`APP_VERSION` is read here too — the login badge and the dashboard both need it,
and one reader means the two cannot drift.
"""
import json
import os
import time
from datetime import date, datetime, timedelta

from flask import abort, redirect, render_template

from ..auth import get_current_user
from ..auto_sync import auto_sync_kick_if_stale
from ..db import component_tags, day_slots, group_id, group_slots, group_subjects, user_dashboard, user_scope_data
from ..db import jload as _jload
from ..portal.parsers.common import _class_key, _group_key
from ..portal.parsers.feedback import _fb_plan
from ..scope.ops import enabled_features
from ..scope_sync import _scope_sync_kick_if_stale, _scope_sync_state
from ..security import require_login
from ..usage_metrics import _track
from . import academics_island, campus_island, fees_island
from .academics import academics_view
from .attendance import (
    _absences_view,
    _attendance_budgets,
    _attendance_index,
    _course_view,
    _join_attendance,
    _month_view,
    _title_case,
    _weekly_slots,
    hourwise_view,
)
from .campus import campus_view
from .fees import _fees_view
from .layout import LAYOUT, WIDGETS
from .marks import _marks_summary, _marks_view
from .profile import merge_personal, scope_profile
from .sync_age import caption as _sync_age_caption
from .sync_age import island_props as _sync_age_props
from .ticker import _today_brief, _today_ticker, _week_updates
from .timetable import (
    _budget_rows,
    _teacher_groups,
    _tools_entries,
    _tt_editor_enabled,
    _tt_fetched_at,
    timetable_html,
)

with open(os.path.join(os.path.dirname(__file__), "..", "..", "VERSION")) as _vf:
    APP_VERSION = _vf.read().strip()


@require_login
def index(active_panel="dashboard"):
    netid = get_current_user()
    if not netid:
        # race: require_login validated, then the row vanished before this
        # re-read (logout in another tab mid-request) — redirect, not 500.
        return redirect("/login")
    return presentation(panel_data(netid, active_panel))


def presentation(vm):
    """Render one panel from panel_data()'s view model.

    The page-only tail: the hourwise section, the Absences-vs-hourwise choice
    for `monthly`, the two background kicks, the per-panel template name and
    the P3.1 404 gate. /api/<panel> (app/blueprints/panels.py) does NOT go
    through this — it serves `vm["data"]`, the same numbers without them.

    `monthly` stays the complete list in `vm`; only the render sees the
    choice. No panel template reads `monthly` without `hourwise` (/attendance
    branches on `hourwise` first), so moving that choice here is what keeps
    this split behaviour-neutral: keeping it inside panel_data would have
    made an hourwise user whose grid came back empty silently lose the
    Absences card.
    """
    netid = vm["netid"]
    group_key, monthly = vm["group_key"], vm["monthly"]
    hourwise = vm["hourwise"]
    monthly_abs = [] if hourwise else monthly
    # an authenticated visit that finds the SCOPE blob missing/stale starts
    # the background sync — the surfaces fill in on the next reload
    _scope_sync_kick_if_stale(netid)
    # portal data has no background refresher of its own: without this a
    # dashboard opened the next morning shows yesterday's numbers until
    # someone presses sync. No-op inside AUTO_SYNC_STALE_S, and off when
    # the knob is 0.
    auto_sync_kick_if_stale(netid)
    # Each route renders only its own panel: "/" -> home.html, everything else
    # -> <panel>.html. (The old 1,060-line 9-panel dashboard.html is gone: it was
    # never routed after P3.1 and only existed as a duplication.)
    tpl = "home.html" if vm["panel"] == "dashboard" else f"{vm['panel']}.html"
    # P3.1: every panel template wraps its <main> content in a {% if %} on its
    # own data, so with no data the route would serve 200 + page chrome + an
    # empty <main>. The nav entry is hidden in that same case, so nobody can
    # arrive here by clicking — only a stale bookmark or a push deep link — and
    # a URL that renders nothing is a broken link, not a page: 404 (all four
    # gated routes alike). /attendance's hourwise/marks/exams sections have
    # independent fallbacks, so it is not gated this way.
    gated = {"campus": vm["campus"]["show"], "academics": vm["academics"],
             "fees": vm["fees"], "tools": vm["tools"]}
    if not gated.get(vm["panel"], True):
        abort(404)
    return render_template(
        tpl, netid=netid, courses=vm["courses"], monthly=monthly_abs,
        hourwise=hourwise,
        days_left_90=next((c["days_left_90"] for c in vm["courses"] if c["days_left_90"] is not None), None),
        stop=next((c["stop"] for c in vm["courses"] if c["stop"] is not None), None),
        days_left_exam=next((c["days_left_exam"] for c in vm["courses"] if c["days_left_exam"] is not None), None),
        last=vm["last"], last_epoch=vm["last_epoch"], hours_old=vm["hours_old"],
        has_budgets=vm["has_budgets"],
        # P4.1: the sync caption is progressive enhancement — the server paints
        # exactly what the island would (same bucket table), so first paint is
        # correct with JS blocked and hydration is a no-op repaint.
        sync_age_text=_sync_age_caption(vm["last_epoch"]),
        sync_age_props=_sync_age_props(vm["last_epoch"], vm["last"]),
        student_name=vm["student_name"], dash=vm["dash"], marks=vm["marks_view"],
        marks_summary=vm["marks_summary"],
        academics=vm["academics"],
        fees=vm["fees"],
        academics_props=academics_island.block(academics_island.props(vm["academics"]))
        if vm["academics"] else "",
        fees_props=fees_island.block(fees_island.props(vm["fees"])) if vm["fees"] else "",
        exams=vm["exams"], faculty=vm["faculty_view"], fb_plan=vm["fb_plan"],
        # card/widget engine: layout registry + derived widget data (route-side
        # joins — partials consume flat dicts only)
        layout=vm["layout"], widget_specs=WIDGETS,
        ticker=_today_ticker(vm["group_key"]), budgets=vm["wctx"]["budgets"],
        teach_groups=vm["wctx"]["teach_groups"],
        version=APP_VERSION,
        timetable=timetable_html(vm["group_key"], vm["attendance"]),
        tt_fetched_at=_tt_fetched_at(vm["group_key"]),
        tt_editor_enabled=_tt_editor_enabled(),
        # scope-filled copy of personal (portal values win, scope gaps only);
        # the profile widget's avatar stays the generated blobatar
        personal=merge_personal(vm["personal_data"], vm["scope_fields"]),
        campus=vm["campus"],
        campus_props=campus_island.block(campus_island.props(vm["campus"])),
        tools=vm["tools"],
        scope_sync_state=_scope_sync_state(netid))


def panel_data(netid, active_panel="dashboard"):
    """The dashboard view model for `netid`: what every panel shows, as data.

    ONE computation, two consumers — presentation() renders templates from it
    and the /api/<panel> endpoints serve a slice of it as JSON, so the page and
    the offline store cannot disagree.

    EXCLUDED on purpose: everything that is already-rendered HTML or a UI flag
    rather than a value, plus `layout`/`widget_specs` (the card registry):
      * timetable  — timetable_html() output. Consumers get `schedule` instead,
                     the structured {day: {period: {code, name, location,
                     attendance}}} grid the HTML is drawn from, attendance
                     join already applied. Storing HTML in IndexedDB is the
                     coupling the rewrite exists to remove.
      * layout, widget_specs  — LAYOUT/WIDGETS presentation registry.
      * version, tt_editor_enabled — UI flags.
      * tools — the Tools panel's link registry (app-owned URLs), not data.
      * sync captions — derived from last_epoch, which IS included, so a
                     consumer formats its own relative time.
    Display strings that the page prints verbatim (`pct_disp`, `due_disp`,
    `days_left_90`, `fill`, ...) stay IN: they are the same numbers the page
    shows and the offline copy wants them for parity; they cost nothing.
    """
    row = user_dashboard(netid)
    _track("page_view", target="dashboard", user=netid)
    data = _jload(row["attendance_json"] if row else None,
                  {"courses": [], "monthly": [], "period": None, "daily_absent": {}})
    last_epoch = row["last_fetch"] if row and row["last_fetch"] else 0
    last = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(last_epoch)) if last_epoch else "never"

    hours_old = int((time.time() - last_epoch) / 3600) if last_epoch else None
    # CL / CLASS IN CHARGE is kept: it is real portal attendance — its hours
    # are in the portal's own Total row (7 subjects 289 + CL 5 = 294) and
    # students asked to see it (Oct 2026). w=0 (absent from the timetable)
    # keeps it out of the Estimates budgets automatically.
    courses = sorted((_course_view(x) for x in data.get("courses", [])), key=lambda c: c["pct"])  # risk-first: lowest % first
    # Absences card: one structure per month — the monthly attendance bar with
    # that month's absence chips directly under it (absence rows join by the
    # same normalized label _absences_view produces).
    abs_by_label = {g["label"]: g["rows"] for g in _absences_view(data.get("daily_absent", {}))}
    monthly = []
    for m in data.get("monthly", []):
        v = _month_view(m)
        label = _title_case(str(m.get("month", "")).replace(" / ", " "))
        v["label"] = label
        v["abs_rows"] = abs_by_label.pop(label, [])
        monthly.append(v)
    for label, rows in abs_by_label.items():  # degrade: drill-down months with no cumulative row
        # pct None = chip-only block (template skips the bar entirely — a
        # fallback month must never render as a numeric 0% / fake red bar,
        # DESIGN §4.15; a junk daily_absent key lands here as label+chips too)
        monthly.append({"month": label, "label": label, "pct": None, "abs_rows": rows})

    # Extract student name from personal details
    personal_data = _jload(row["personal_details_json"] if row else None, {})
    # SCOPE profile enrichment (slug `profile`) — gate-first: feature off or
    # no stored scope data -> {} and the Settings template is today's input
    # unchanged. personal_data itself stays the portal's dict (it feeds the
    # timetable group key / marks class key); only the rendered copy is
    # merged, scope filling gaps, portal values winning (app/views/profile.py).
    _scope_fields = scope_profile(_jload(row["scope_json"] if row else None, {}))
    student_name = personal_data.get("Student Name", "").title()

    # Marks: server-rendered (tab + dashboard widget). Re-synced hot data.
    marks_raw = _jload(row["marks_json"] if row else None, [])
    marks_view = _marks_view(marks_raw,
                             _load_component_tags(_class_key(personal_data, netid), marks_raw))
    marks_summary = _marks_summary(marks_raw)

    # Academics tab (SCOPE): stored cold blob only — no network on the render
    # path. None = zero footprint (feature off / no academics ops stored / all
    # sections empty), which is what gates the navbar item, dock item and panel.
    academics = academics_view(user_scope_data(netid), enabled_features())
    # Fees tab: server-rendered from the cold SCOPE blob (marks-tab pattern;
    # no new DB columns). Feature 'fees' off or no fee/finance rows -> None
    # -> the template renders no navbar item and no panel (empty=hidden,
    # DESIGN §4.12 — same self-hide rule as empty cards).
    srow = user_scope_data(netid)
    fees = _fees_view(_jload(srow["scope_json"] if srow else None, {}),
                      enabled_features())

    # End-sem schedule card (official iden=126 table primary, scribe probe as
    # fallback; None -> card hidden). Rows are kept: _exam_stop needs the raw
    # dates for the budget horizon (spec §1.2).
    exam_rows = _jload(row["exam_schedule_json"] if row else None, [])
    exams = _exams_view(exam_rows)

    # Faculty map card (harvested from the mid-sem feedback form; {} -> hidden).
    # Keyed by subject NAME — the feedback form carries no subject codes.
    faculty_map = _jload(row["faculty_map_json"] if row else None, {})
    faculty_view = _faculty_view(faculty_map, data.get("courses", []))
    # Preview of what the opt-in fill would submit (same builder as the endpoint).
    # ARCHIVED while the portal's feedback window is closed (fb_open=0 — now
    # learned by EVERY sync's probe, not just the daily cold one, plus the
    # fill endpoint's portal-confirmed self-heal): empty plan -> the CTA and
    # the modal both vanish (empty=hidden, DESIGN §4.12) and come back
    # automatically on the next sync that finds the window open again. The
    # Teachers list itself is historical data and stays.
    fb_open = row["fb_open"] if row and row["fb_open"] is not None else 1
    fb_plan = _fb_plan(faculty_map) if fb_open else []

    # Dashboard home tab: profile + today/week brief
    group_key = _group_key(personal_data) if personal_data else None
    # Attendance budgets (spec §3): w is gid-scoped to THIS user; stop is one global
    # horizon shared by every subject (min parsed exam date − 1, §0/R6).
    weekly = _weekly_slots(group_key)
    today = date.today()
    for c in courses:
        c["w"] = weekly.get(c["code"], 0)
        c.update(_attendance_budgets(c["attended"], c["max_hours"], c["w"],
                                     data.get("period"), exam_rows, today))
    # no timetable -> no budgets anywhere -> the Estimates card would render
    # header-only (empty-state rule DESIGN §8); hide the whole block instead
    has_budgets = any(c.get("m90") is not None or c.get("m_end") is not None for c in courses)
    attendance = _attendance_index(courses)  # spec §4 join — consumed by timetable_html
    # Detailed attendance (SCOPE hourwise × timetable): replaces the Absences
    # card when the feature, the group's timetable and the stored hour rows
    # are all present; otherwise the Absences card renders exactly as on main.
    # Data, not presentation: /api/attendance serves it too. Computed HERE,
    # after courses (hourwise_view joins the course objects), and kept ahead
    # of `dash` only because that is where it always was.
    hourwise = _hourwise_section(netid, group_key, monthly)
    dash = {
        # institute mail is NetID@srmist.edu.in (the portal login page states
        # it verbatim) — the personal Gmail from the profile is NOT shown here
        "email": f"{netid}@srmist.edu.in",
        "reg_no": personal_data.get("Register No.", ""),
        "today": _today_brief(group_key),
        "week": _week_updates(data.get("daily_absent", {})),
        "absent_today": any(
            r.get("date") == datetime.now().strftime("%d-%m-%Y")
            for rows in (data.get("daily_absent") or {}).values() for r in rows),
    }
    # week widget's second block: components the portal entered this Mon–Sun
    dash["week"]["marks"] = _week_marks(marks_raw)

    # card/widget engine: layout registry + derived widget data (route-side
    # joins — partials consume flat dicts only). Cards whose `when` context
    # vars are ALL empty are dropped here so no orphan shell renders.
    _wctx = {"marks_summary": marks_summary, "exams": exams,
             "budgets": _budget_rows(courses),
             "teach_groups": _teacher_groups(faculty_view)}
    layout = [c for c in LAYOUT
              if not c.get("when") or any(_wctx.get(n) for n in c["when"])]
    # Campus tab: shape-driven SCOPE cards off the same row (scope_json).
    # Each card builds ONLY when its feature slug is on and it has rows, so
    # every card self-hides — and with none left the tab is never registered
    # (alive-empty = no UI, never an error). Scope toggles are a request-time
    # knob, so the feature set is read per request like every other gate.
    campus = campus_view(_jload(row["scope_json"] if row else None, {}),
                         enabled_features())
    tools = _tools_entries(netid)
    return dict(
        # ── panels the API serves (app/blueprints/panels.py) ──
        courses=courses,          # /api/attendance: code, pct, budgets, tints
        monthly=monthly,          # /api/attendance: month bars + absence chips
        hourwise=hourwise,        # /api/attendance: detailed grid (None = feature off)
        fees=fees,                # /api/fees: None when gated (one rule)
        campus=campus,            # /api/campus: {"show", "cards"}
        academics=academics,      # /api/academics: {"cgpa", "courses"} or None
        schedule=_schedule(group_key, attendance),  # timetable AS DATA, not HTML
        # ── the rest of the page model (home/marks/timetable/settings) ──
        netid=netid, panel=active_panel, data=data, personal_data=personal_data,
        scope_fields=_scope_fields, student_name=student_name,
        marks_view=marks_view, marks_summary=marks_summary, exams=exams,
        faculty_view=faculty_view, fb_plan=fb_plan, group_key=group_key,
        attendance=attendance, has_budgets=has_budgets, dash=dash, tools=tools,
        layout=layout, wctx=_wctx, last=last, last_epoch=last_epoch,
        hours_old=hours_old,
    )


def _schedule(group_key, attendance):
    """The timetable tab's grid as DATA — what timetable_html renders from.

    {day: {period: {code, name, location, attendance}}} with the spec §4
    attendance join already applied (a joined course dict or None for "no
    data"). This is the JSON-side counterpart of timetable= (an escaped HTML
    string): the API needs values, not markup. Empty dict = no timetable.
    """
    gid = group_id(group_key) if group_key else None
    if gid is None:
        return {}
    custom_codes = {r[0] for r in group_subjects(gid) if r[3] and r[0]} if attendance else set()
    out = {}
    for r in group_slots(gid):
        out.setdefault(r[0], {})[r[1]] = {
            "code": r[2] or "", "name": r[3] or "", "location": r[4] or "",
            # the ROW rule of timetable_html (audit 2026-09-27): a custom subject
            # never joins; otherwise code-exact, then normalized name.
            "attendance": _join_attendance(attendance, custom_codes, r[2] or "", r[3] or ""),
        }
    return out


# ── P3.1: one document -> nine real routes ───────────────────────────────
# Each panel is its own URL; every route runs the SAME view model (index()
# computes the data once) but renders a per-route template containing only that
# panel. index keeps endpoint `index` (Flask pins it on __name__). The eight
# wrappers below are bare per-panel endpoints; they exist as real `def`s so
# __name__ == the endpoint name (FlatBlueprint derives endpoint from __name__).
def attendance():
    return index("attendance")


def timetable():
    return index("timetable")


def marks():
    return index("marks")


def campus():
    return index("campus")


def academics():
    return index("academics")


def fees():
    return index("fees")


def tools():
    return index("tools")


def settings():
    return index("settings")
# end P3.1


def _load_component_tags(class_key, marks):
    """Confirmed IE tags for this class's components -> {(code, name): row}.
    Keys carry no netid on purpose: one student's confirmation applies to the
    whole class (and is later reused by the GPA predictor)."""
    wanted = {f"{class_key}|{s.get('code', '')}|{c.get('name', '')}":
              (s.get("code", ""), c.get("name", ""))
              for s in marks for c in s.get("components", [])}
    if not wanted:
        return {}
    rows = component_tags(wanted)
    return {wanted[r[0]]: {"role": r[1], "raw_max": r[2], "scaled_max": r[3]} for r in rows}


def _week_marks(marks):
    """Week widget: components whose portal 'Entered on' falls in the current
    Mon–Sun week (IST server date) — `code · name · date` rows, newest first.
    The week column's second job: what got ADDED this week, next to what got
    missed. Empty list = the block stays hidden (empty=hidden, DESIGN §8)."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    out = []
    for m in marks or []:
        for cpt in m.get("components", []):
            try:
                d = datetime.strptime(cpt.get("entered", "") or "", "%d/%b/%Y").date()
            except (ValueError, TypeError):
                continue
            if monday <= d <= today:
                out.append({"code": m.get("code", ""), "name": cpt.get("name", ""),
                            "_d": d, "date": d.strftime("%d %b")})
    out.sort(key=lambda r: r["_d"], reverse=True)
    for r in out:
        del r["_d"]
    return out

def _exams_view(rows):
    """Dashboard card: end-sem rows sorted by real date + countdown.
    None when empty (card hidden)."""
    if not rows:
        return None
    def ts(r):
        try:
            return datetime.strptime(r.get("date", ""), "%d-%m-%Y")
        except ValueError:
            return datetime.max
    rows = sorted(rows, key=ts)
    for r in rows:  # display fields; junk dates fall back to the raw value
        try:
            d = datetime.strptime(r.get("date", ""), "%d-%m-%Y")
        except ValueError:
            d = None
        r["short"] = d.strftime("%d %b") if d else r.get("date", "")
        r["day"] = str(d.day) if d else r.get("date", "")[:2]
        r["dow"] = d.strftime("%a") if d else ""
        # portal returns ALL-CAPS names; shouty when wrapped on a narrow screen
        r["name_disp"] = " ".join(w.capitalize() for w in r.get("name", "").split())
        # portal codes: students know AN/FN natively — show them as-is
        r["session_disp"] = r.get("session", "")
    first = ts(rows[0])
    last = ts(rows[-1])
    days = (first.date() - datetime.now().date()).days
    if (first.year, first.month) == (last.year, last.month):
        label = first.strftime("%b %Y")
    elif first.year == last.year:
        label = first.strftime("%b") + "\u2013" + last.strftime("%b %Y")
    else:
        label = first.strftime("%b %Y") + "\u2013" + last.strftime("%b %Y")
    # Source badge: rows from the official 126 table carry a clock "slot";
    # scribe-leak rows don't. Mixed view = official dates + scribe estimates.
    n_official = sum(1 for r in rows if r.get("slot"))
    source = ("Official" if n_official == len(rows)
              else "Official + est." if n_official else "Estimated")
    return {"rows": rows, "label": label, "days_until": days, "source": source}



def _faculty_view(faculty_map, courses):
    """Stored faculty map + scraped courses -> sorted card rows.
    {} / no staff entries -> [] (card hidden). Joins the feedback form's
    subject NAME to the scraped course CODE via whitespace-normalised match.

    Course rows come from attendance_json, whose real shape is `description`
    (seen live Oct 8 2026: KeyError 'name' 500'd every dashboard); `name` is
    the test-seed shape — accept both."""
    _by_name = {" ".join((c.get("name") or c.get("description") or "").split()).upper():
                c.get("code", "") for c in courses}
    out = []
    for name, entry in faculty_map.items():
        staff = [(sid, " ".join(nm.split("-")[0].split()).title(),
                  (nm.split("-")[1].strip() if "-" in nm else ""))
                 for sid, nm in (entry.get("staff") or [])]
        # the harvester's Unknown placeholder (portal listed no staff) is not a person
        if not staff or all(sid == "0" for sid, _n, _k in staff):
            continue
        code = _by_name.get(" ".join(name.split()).upper(), "")
        out.append({"code": code, "name": name.title(), "raw": name, "staff": staff})
    out.sort(key=lambda x: x["name"])
    return out


def _hourwise_data(netid, group_key):
    """SCOPE hour rows + the join inputs for this user, or None when ANY leg
    is missing — feature 'hourwise' in SCOPE_FEATURES, a group with slots,
    and a non-empty getHourwiseAttendance — so a missing leg leaves today's
    Absences card untouched (zero regression by construction). Nothing
    cached: scope_json may be hours old, it is history and still renders.
    """
    if "hourwise" not in enabled_features() or not group_key:
        return None
    gid = group_id(group_key)
    slots = day_slots(group_key)
    if gid is None or not slots:
        return None
    row = user_scope_data(netid)
    try:
        stored = json.loads(row["scope_json"] or "{}") if row else {}
    except (ValueError, TypeError):
        stored = {}
    hw = stored.get("getHourwiseAttendance") or {} if isinstance(stored, dict) else {}
    rows = hw.get("data") if isinstance(hw, dict) else None
    if not isinstance(rows, list) or not rows:
        return None
    # custom subjects keep the state but lose the name (join spec: never invent)
    custom = {r[0] for r in group_subjects(gid) if r[3] and r[0]}
    ts = hw.get("ts") if isinstance(hw, dict) else None
    ts = int(ts) if isinstance(ts, (int, float)) and ts else 0
    return rows, slots, custom, ts, \
        (time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts)) if ts else "never")


def _hourwise_section(netid, group_key, monthly):
    """The Detailed attendance section's context, or None to keep the Absences
    card. Month rows follow the portal's own monthly list (its `MMM / YYYY`
    label, its bar %), and a month only SCOPE knows about still renders."""
    hw = _hourwise_data(netid, group_key)
    if not hw:
        return None
    rows_hw, slots_hw, custom_hw, ts_hw, full_hw = hw
    grid = hourwise_view(rows_hw, slots_hw, custom_hw,
                         {m["label"]: m for m in monthly})
    if not grid["months"]:
        return None
    grid["ts"] = ts_hw
    grid["full"] = full_hw
    return grid
