"""Timetable view model: the grid, the NOW hero, and the rendered HTML.

Extracted from app/app.py (facade pump, cycle B). Everything that turns stored
timetable rows into what the timetable panel shows: the period grid, the
per-course attendance tag, the countdown hero, the empty state, and
`timetable_html()` itself — plus `_save_timetable_group`, which is the write
side of the same tables.

Imports nothing from app.app: its needs are app/db.py (rows), app/static_data.py
(the SLOTS grid + TIMETABLE_* knobs), app/views/attendance.py (the row join) and
the portal parsers. Re-exported from app.app, so callers are unchanged.
"""
import json
import os
import re
import time


def _now():
    """The app's clock. Tests pin it by setting app.datetime (test_official_tt,
    test_tt_history), so read it from the facade at call time like views/ticker
    does — a module-level `from datetime import datetime` would freeze it."""
    from ..app import datetime as _dt
    return _dt.now()

from html import escape as _hesc

from .. import static_data as _sd
from ..db import (
    day_slots,
    group_id,
    group_slots,
    group_subjects,
    official_times,
    replace_group_slots,
    set_official_times,
    transaction,
    tt_fetched_at,
    upsert_group,
    upsert_subject,
    user_personal,
    user_scope_data,
)
from ..db import (
    jload as _jload,
)
from ..portal.parsers.common import _group_key, _semester_int
from ..portal.parsers.timetable import DAY_ORDER
from ..static_data import SLOTS, TIMETABLE_TIME_OFFSETS, TOOLS
from .attendance import _join_attendance, _title_case
from .ticker import _now_next_from_slots

log = __import__("logging").getLogger("opensrm")


def _tt_editor_enabled():
    return os.environ.get("TIMETABLE_EDITOR", "archived") == "enabled"


# Release notices, newest first (append at release time). The New badge rides
# the head entry only — release notes verbatim from the real CHANGELOG.


def _budget_rows(courses):
    """Attendance widget: (subject name, signed margin, risk) per subject in
    COURSES order (already sorted pct-ascending = risk-first). Value is the
    MARGIN-SIGNED form of the same _bunk_counts numbers the attendance tab's
    Margin column shows: `-N` = N classes short of 75% (attend N), `+N` = N in
    surplus (can skip N), `0` = exactly at the line — one sign language across
    tab and glance. Names go through _title_case (codes read as jargon on
    the dashboard; custom mixed-case names keep their casing).
    (None, None) rows (nothing held) are dropped, never faked as 0.
    """
    rows = []
    for c in courses:
        skip, attend = c.get("skip_now"), c.get("attend_now")
        if attend is None and skip is None:
            continue
        name = _title_case(c.get("description") or c.get("code", ""))
        if attend is not None:
            rows.append((name, f"-{attend}", 0))
        elif skip:
            rows.append((name, f"+{skip}", 2))
        else:
            rows.append((name, "0", 1))
    return rows


# ── Tools tab (SCOPE-sourced surfaces) ──────────────────────────────
# One entry per SCOPE surface. A row renders ONLY when its feature slug is
# enabled AND its representative op landed a non-empty answer; nothing
# qualifying = empty list = no entry, no tab (zero footprint — the mission
# toggle contract, and the same self-hiding rule the dashboard widgets obey).
# `tab` is the panel that surface's own PR mounts: the row navigates there
# when that panel exists today and renders inert otherwise, so this stays a
# landing surface for the SCOPE rotation instead of a duplicate of it.


def _tools_entries(netid):
    """Rows for the Tools panel: [{"slug","label","hint","op"}].

    Two gates, both required: SCOPE_FEATURES enables the slug (the ops
    contract) and the cold blob holds a non-empty answer for the op (an
    enabled surface with nothing behind it must not advertise itself).
    Costs one users-row read, and only when a feature is enabled at all.
    """
    from app.scope.ops import enabled_features  # lazy: app.scope imports app.db
    on = enabled_features()
    if not on:
        return []
    row = user_scope_data(netid)
    # shape guard on both levels: a corrupt/foreign scope_json must degrade to
    # "no tools", never 500 the dashboard (same rule as _stored in scope.sync
    # and _jload's wrong-shape branch — audit B10).
    blob = _jload(row["scope_json"] if row else None, {})
    rows = []
    for feat, label, hint, op, tab in TOOLS:
        if feat not in on:
            continue
        entry = blob.get(op)
        if isinstance(entry, dict) and entry.get("data"):
            rows.append({"slug": feat, "label": label, "hint": hint,
                         "op": op, "tab": tab})
    return rows


def _teacher_groups(faculty):
    """Faculty rows -> flat teacher-group dicts for the Teachers widget
    (subject-first grouping is the widget's whole view; initials derived
    HERE, not in the template). faculty == _faculty_view output."""
    out = []
    for f in faculty:
        staff = []
        for _sid, tname, kind in f["staff"]:
            # portal writes "Dr.Priyanka" with no space — normalise for display
            tname = re.sub(r"^(Dr|Mr|Ms|Mrs|Prof)\.(?=\S)", r"\1. ", tname)
            parts = tname.split()
            given = parts[0] if parts else ""
            # honorifics are not initials: "Dr.Priyanka Gupta" -> PG, not DG
            m = re.match(r"^(?:Dr|Mr|Ms|Mrs|Prof)\.?(.*)$", given, re.I)
            if m:
                given = m.group(1) or (parts[1] if len(parts) > 1 else given)
            sur = parts[-1] if len(parts) > 1 else ""
            ini = (given[:1] + sur[:1]) if given else ""
            staff.append({"name": tname, "mode": kind, "ini": ini.upper()})
        out.append({"code": f["code"], "name": f["name"], "staff": staff})
    return out


def _day_slots(group_key):
    """group_key -> {day: {period: slot}} or None when no timetable exists."""
    return day_slots(group_key)

def _tt_grid(group_key):
    """Resolved weekly TIME grid for a group — same row shape SLOTS has
    (class rows + period-0 break dividers), so ticker/push/panel consumers
    swap SLOTS -> _tt_grid(group_key) without other changes.

    official mode (default): the group's RAW published time row
    (timetable_groups.official_times) + TIMETABLE_TIME_OFFSETS; gaps >= 10 min
    between corrected periods become dividers (the official page has none —
    break/lunch exist only as gaps). Fallback to legacy SLOTS whenever there
    is no official data to trust: group missing, never published, raw JSON
    corrupt, offsets producing overlap — any anomaly degrades to the grid we
    know instead of failing the render.

    TIMETABLE_SOURCE = "manual" is the ops escape hatch: always SLOTS."""
    # read through the MODULE, never a copied name: tests/ops flip
    # app.TIMETABLE_SOURCE at runtime (the facade proxies it here).
    if _sd.TIMETABLE_SOURCE != "official":
        return SLOTS
    raw_txt = official_times(group_key)
    if not raw_txt:
        return SLOTS
    try:
        raw = json.loads(raw_txt)
        parsed = []
        for k in raw:
            p = int(k)
            sm, em = raw[k].split("-")
            s = int(sm.split(":")[0]) * 60 + int(sm.split(":")[1]) + TIMETABLE_TIME_OFFSETS.get(p, 0)
            e = int(em.split(":")[0]) * 60 + int(em.split(":")[1]) + TIMETABLE_TIME_OFFSETS.get(p, 0)
            if e <= s:
                raise ValueError("inverted period %d after offset" % p)
            parsed.append((p, s, e))
        parsed.sort(key=lambda t: t[1])
        if any(parsed[i][1] < parsed[i - 1][2] for i in range(1, len(parsed))):
            raise ValueError("corrected periods overlap")
    except Exception as ex:
        log.debug("timetable grid: official_times unusable (%r) — SLOTS fallback", ex)
        return SLOTS
    out = []
    for i, (p, s, e) in enumerate(parsed):
        if i:
            gap = s - parsed[i - 1][2]
            if gap >= 10:
                out.append({"period": 0, "start": "%02d:%02d" % divmod(parsed[i - 1][2], 60),
                            "end": "%02d:%02d" % divmod(s, 60), "type": "break",
                            "name": "Lunch" if gap >= 30 else "Break"})
        out.append({"period": p, "start": "%02d:%02d" % divmod(s, 60),
                    "end": "%02d:%02d" % divmod(e, 60), "type": "class"})
    return out


def _tt_fetched_at(group_key):
    """Epoch of the last official timetable sync for this group (0 = never)."""
    v = tt_fetched_at(group_key)
    return int(v) if v else 0

def _save_timetable_group(netid, res):
    """Upsert the student's timetable group + scraped subjects, then persist the
    official portal timetable (formId 10). Own transaction, warn-only — a
    timetable write must never fail a sync.

    Called from /api/login AND /api/refresh (refresh had no group/subject
    upsert before, so subjects and the official grid would only ever update on
    a fresh login; hot syncs skip formId 17 so the group key comes from stored
    cold data there).

    Preserve contract: no "timetable" grid in res (section unpublished, shape
    drift, dead JSP) -> no slot writes, stored rows untouched. A published grid
    is an atomic whole-group replace stamped source='official' (UNIQUE
    group/day/period means one source at a time per group — the archived
    editor does the same replace stamped 'manual'). Locations typed into the
    editor carry forward: the portal publishes no rooms."""
    try:
        personal = dict(res.get("personal") or {})
        if not personal:
            prow = user_personal(netid)
            try:
                personal = json.loads(prow[0]) if prow and prow[0] else {}
            except Exception:
                personal = {}
        gk = _group_key(personal)
        if not gk:
            return
        with transaction():
            upsert_group(gk, personal.get("Program", ""), int(personal.get("Batch", 0) or 0),
                         _semester_int(personal.get("Semester", "")), personal.get("Section", ""))
            gid = group_id(gk)
            for sub in res.get("courses") or []:
                upsert_subject(gid, sub["code"], sub["name"], sub["credits"], 0)
            tt = res.get("timetable")
            if isinstance(tt, dict) and tt.get("grid"):
                old_loc = {(r[0], r[1]): (r[2], r[4]) for r in group_slots(gid) if r[4]}
                known = {r[0]: r[1] for r in group_subjects(gid)}
                legend = tt.get("legend") or {}
                rows = []
                for day, slots in tt["grid"].items():
                    for p, code in slots.items():
                        if not code:
                            continue
                        # same rule as the editor path (app.py:~3020): carry the
                        # room forward only while the slot's CODE is unchanged —
                        # a swapped subject drops the old room (review #3)
                        prev = old_loc.get((day, int(p)))
                        loc = prev[1] if prev and prev[0] == code else ""
                        rows.append((day, int(p), code,
                                     legend.get(code) or known.get(code) or code, loc))
                replace_group_slots(gid, rows, "official")
                set_official_times(gk, json.dumps({str(k): v for k, v in sorted(tt["times"].items())}),
                                   int(time.time()))
                log.debug("timetable official save netid=%s group=%s rows=%d", netid, gk, len(rows))
    except Exception as e:
        log.warning("timetable group/subject save failed netid=%s: %r", netid, e, exc_info=True)


def _tt_att_sig(course):
    """One glance signal for a timetable slot (spec §1.B): the text carries the
    meaning, colour only reinforces. None → neutral "no data", never a numeric 0%."""
    if not course or course.get("max_hours", 0) <= 0:
        return None
    skip, attend = course.get("skip_now"), course.get("attend_now")
    if skip is None and attend is None:
        return None
    if attend is not None:
        return {"cls": "danger", "text": "attend %d" % attend, "num": attend}
    if skip == 0:
        return {"cls": "warn", "text": "no margin", "num": 0}
    return {"cls": "ok", "text": "can skip %d" % skip, "num": skip}

def _tt_sig_phrase(sig):
    """The words behind an attendance number, one short clause (no sentence)."""
    if not sig:
        return ""
    if sig["cls"] == "danger":
        return "{n} in a row to reach 75%".format(n=sig["num"])
    if sig["cls"] == "warn":
        return "one miss drops below 75%"
    return "skippable, still 75%"


def _tt_countdown(mins):
    """Human span for the hero: minutes under an hour, else "8h 49m".
    A bare "in 529 min" is an engineering leak, not a time a student reads."""
    try:
        mins = int(mins)
    except (TypeError, ValueError):
        return ""
    if mins < 60:
        return "in %d min" % mins
    return "in %dh %02dm" % (mins // 60, mins % 60)


def _tt_hero(title, sub, disc="check"):
    """Hero anatomy of the reference design: a 30px tinted disc holding one
    stroke icon, a 16px semibold title, a 12px grey subline. The disc is the
    only place hue appears — the words carry the state (DESIGN §2.6)."""
    name = "check"
    if disc == "clock":
        name = "clock"
    return ("<div class=\"tt-hero\">"
            "<span class=\"tt-hero-disc\"><svg viewBox=\"0 0 24 24\" aria-hidden=\"true\">"
            "<path d=\"{path}\"></path></svg></span>"
            "<div class=\"tt-hero-txt\"><strong>{t}</strong>"
            "<div class=\"tt-hero-sub\">{s}</div></div>"
            "<span class=\"tt-hero-day\">{d}</span></div>").format(
        path=("m5 12 5 5 9-10" if name == "check"
              else "M12 8v4l2.5 1.5M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0"),
        t=title, s=sub, d=_now().strftime("%a"))


def _tt_empty(title, sub):
    return ("<div class=\"tt-card\"><div class=\"tt-empty\">"
            "<strong>{t}</strong><div class=\"tt-hero-sub\">{s}</div>"
            "</div></div>").format(t=title, s=sub)


def timetable_html(group_key, attendance=None):
    """Render the Timetable tab.

    Layout follows the approved reference design: one solid hero card, a
    rounded pill day selector, then one solid card per class row — a 3-column
    grid of [mono time pair | code over name | room chip + attendance tag].
    Breaks are dashed rules BETWEEN rendered classes, never a card.

    Every slot value is user-writable through /api/timetable, so all of it is
    escaped at the single choke point below (audit 2026-09-27)."""
    if not group_key:
        return _tt_empty("No timetable found", "No timetable exists for your group yet.")
    gid = group_id(group_key)
    if gid is None:
        return _tt_empty("No timetable set", "Your group has no timetable yet.")
    day_slots = {}
    # attendance join (spec §4): custom short-circuits BEFORE any name match —
    # a custom subject typed with a portal-matching name must never join.
    custom_codes = set()
    if attendance:
        for r in group_subjects(gid):
            if r[3] and r[0]:
                custom_codes.add(r[0])
    for r in group_slots(gid):
        if r[0] not in day_slots:
            day_slots[r[0]] = {}
        # audit 2026-09-27: slots are written by ANY user of the group via
        # /api/timetable and rendered with {{ timetable | safe }} — escape at
        # this single choke point (covers hero + rows + room) or one student's
        # custom subject name becomes stored XSS in classmates' dashboards.
        day_slots[r[0]][r[1]] = {"code": _hesc(str(r[2] or "")),
                                 "name": _hesc(str(r[3] or "")),
                                 "location": _hesc(str(r[4] or ""))}
        # raw (unescaped) pair for the join + sig lookup; rendered values above stay escaped
        day_slots[r[0]][r[1]]["_att"] = _join_attendance(
            attendance, custom_codes, str(r[2] or ""), str(r[3] or ""))
    if not any(day_slots.get(d) for d in DAY_ORDER):
        return _tt_empty("Timetable empty", "No classes are mapped for your section.")
    today = _now().strftime("%A")
    grid = _tt_grid(group_key)

    # ── Hero: what is happening on the default day, right now ──────────────
    # index of the day's LAST filled class slot: a break at/after it is NOT
    # part of today's schedule (otherwise the hero says "Break until 16:00"
    # after the last class instead of "Done for today")
    last_cls = -1
    for i, s in enumerate(grid):
        if s["type"] == "class" and today in day_slots and s["period"] in day_slots[today]:
            last_cls = i
    today_slots = []
    for i, s in enumerate(grid):
        if s["type"] == "break":
            if i < last_cls:
                today_slots.append(s)
        elif today in day_slots and s["period"] in day_slots[today]:
            m = day_slots[today][s["period"]]
            today_slots.append(dict(s, code=m["code"], name=m["name"],
                                    location=m["location"],
                                    **({"_att": m["_att"]} if "_att" in m else {})))
    hero_status = _now_next_from_slots(today, today_slots)
    if hero_status is None or hero_status["kind"] == "done":
        hero = _tt_hero("Done for today", "No more classes")
    elif hero_status["kind"] == "break":
        hero = _tt_hero("On %s" % hero_status["label"],
                        "Until %s" % hero_status["until"], disc="clock")
    elif hero_status["kind"] == "current":
        sig = _tt_att_sig(hero_status.get("_att")) if "_att" in hero_status else None
        hero = _tt_hero(
            _title_case(hero_status["name"]),
            "%s &middot; now &middot; ends %s%s" % (
                hero_status["code"], hero_status["until"],
                (" &middot; " + sig["text"]) if sig else ""))
    elif hero_status["kind"] == "next":
        # name first, code on the subline — the same hierarchy as the rows
        hero = _tt_hero(
            _title_case(hero_status["name"]),
            "%s &middot; starts %s &middot; %s" % (
                hero_status["code"], hero_status["at"],
                _tt_countdown(hero_status["in_mins"])),
            disc="clock")
    else:
        hero = _tt_hero("No classes today", "Nothing scheduled")

    # ── Day selector: rounded pills, checked one inverts to the primary fill ──
    default_day = today if today in DAY_ORDER else "Monday"
    radios = "".join(
        "<input type=radio name=ttday id=day-{0} class=tt-radio{1}>".format(
            d, " checked" if d == default_day else "") for d in DAY_ORDER)
    tabs = "".join(
        "<label for=day-{0}>{1}</label>".format(d, d[:3]) for d in DAY_ORDER)

    # ── One panel per day ─────────────────────────────────────────────────
    _n = _now()
    now_mins = _n.hour * 60 + _n.minute
    panels = []
    for d in DAY_ORDER:
        # which class slots this day actually has — a break divider only makes
        # sense BETWEEN two rendered classes (no trailing "Break" after the
        # day's last class, no orphan divider above the first one)
        present = [s["type"] == "class" and s["period"] in day_slots.get(d, {})
                   for s in grid]
        day_last = max((i for i, p in enumerate(present) if p), default=-1)
        rows = []
        for i, s in enumerate(grid):
            if s["type"] == "break":
                if any(present[:i]) and i < day_last:
                    rows.append("<div class=tt-brk>{0}</div>".format(s["name"]))
                continue
            sl = day_slots.get(d, {}).get(s["period"])
            if not sl:
                continue
            code, name = sl["code"], _title_case(sl["name"])
            loc = sl.get("location", "")
            sm = int(s["start"][:2]) * 60 + int(s["start"][3:])
            em = int(s["end"][:2]) * 60 + int(s["end"][3:])
            live = ""
            if d == today and sm <= now_mins < em:
                live = " tt-row--now"
            sig = _tt_att_sig(sl.get("_att"))
            # the room chip is the secondary datum; the attendance tag is the
            # only element allowed hue, and it only appears on deviation
            tail = ""
            if loc:
                tail += "<span class=tt-chip>{0}</span>".format(loc)
            if sig:
                # read as one phrase, number and word space-separated and
                # contiguous in the markup: "attend 3" / "can skip 13" take the
                # word first, the zero-margin case reads as "0 margin".
                txt = ("%d margin" % sig["num"] if sig["cls"] == "warn"
                       else {"danger": "attend", "ok": "can skip"}[sig["cls"]]
                            + " %d" % sig["num"])
                tail += ('<span class="tt-tag tt-tag--{k}" title="{tip}">{t}</span>'
                         ).format(k=sig["cls"], tip=_hesc(_tt_sig_phrase(sig)), t=txt)
            else:
                tail += '<span class="tt-tag tt-tag--none">no data</span>'
            rows.append(
                "<div class=\"tt-row{live}\">"
                "<div class=tt-time><b>{start}</b><span>{end}</span></div>"
                # the subject NAME is what a student scans for; the course code
                # is the identifier underneath it (Navya 2026-10-30).
                # code and the room/tag pair share ONE line under the name
                # (the tag pushed to the far right) so a phone row is two
                # lines, not three.
                "<div class=tt-info><b>{name}</b>"
                "<span class=tt-sub><span class=tt-code>{code}</span>"
                "<span class=tt-tail>{tail}</span></span></div></div>".format(
                    live=live, start=s["start"], end=s["end"],
                    code=code, name=name, tail=tail))
        if not rows:
            rows.append("<div class=tt-off>No classes</div>")
        panels.append("<div class=day-panel id=panel-{0}>{1}</div>".format(
            d, "".join(rows)))

    return ("<div class=tt-wrap>" + radios + hero
            + "<div class=tt-days>" + tabs + "</div>"
            + "<div class=panels>" + "".join(panels) + "</div></div>")
