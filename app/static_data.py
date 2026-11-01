"""Declarative app data: timetable slots, the notices feed, the Tools panel.

Extracted from app/app.py (facade pump, cycle A). Nothing here executes — these
are literal tables the views read. Pure data means zero import risk: this module
imports nothing, so it cannot participate in a cycle, and every constant is
re-exported from app.app so existing readers are untouched.

Editing a constant here is the whole change — no logic lives alongside them.
"""
# ── Timetable (SQLite-backed, per-group) ─────────────────────────
SLOTS = [
    {"period": 1, "start": "09:30", "end": "10:20", "type": "class"},
    {"period": 2, "start": "10:20", "end": "11:10", "type": "class"},
    {"period": 0, "start": "11:10", "end": "11:20", "type": "break", "name": "Break"},
    {"period": 3, "start": "11:20", "end": "12:10", "type": "class"},
    {"period": 4, "start": "12:10", "end": "13:00", "type": "class"},
    {"period": 0, "start": "13:00", "end": "14:10", "type": "break", "name": "Lunch"},
    {"period": 5, "start": "14:10", "end": "15:00", "type": "class"},
    {"period": 6, "start": "15:00", "end": "15:50", "type": "class"},
    {"period": 0, "start": "15:50", "end": "16:00", "type": "break", "name": "Break"},
    {"period": 7, "start": "16:00", "end": "16:50", "type": "class"},
]


TIMETABLE_TIME_OFFSETS = {1: 60, 2: 60, 3: 60, 4: 60, 5: 40, 6: 40}

# Where the rendered grid comes from: "official" = portal timetable when the
# group has one (legacy SLOTS as per-group fallback); "manual" = always the
# legacy SLOTS/manual rows — the ops escape hatch if a published official
# timetable is ever wrong beyond a clock offset.
TIMETABLE_SOURCE = "official"


NOTICES = [
    {"ver": "v2.8.0", "date": "31 Oct", "title": "Attendance reads to a decimal",
     "body": "Attendance used to round to a whole percent, so 74.98% showed as 75% - the "
             "exact figure SRM detains you for being under. Every percentage (subjects, "
             "month-by-month, and the can-skip line) now truncates to one decimal and "
             "never rounds up: 74.98% reads 74.9%, with the red bar to match."},
    {"ver": "v2.7.1", "date": "31 Oct", "title": "Ops tiles read the right number",
     "body": "Two ops-dashboard tiles were showing nonsense: the push-scheduler tile "
             "reported '56 years' before its first run, and after a deploy some tiles "
             "showed two stacked values from the old and new container at once. Fixed. "
             "Nothing in the app itself changed."},
    {"ver": "v2.7.0", "date": "30 Oct", "title": "Timetable, rebuilt around your subject names",
     "body": "The timetable is one clean card per class now - the subject name leads, the "
             "course code and room sit underneath it, and your attendance tag moves to the "
             "far right of the same line, so a phone fits a whole day without scrolling. "
             "Breaks read as quiet dashed rules between cards instead of crowding the list."},
    {"ver": "v2.6.1", "date": "30 Oct", "title": "Campus data arrives much faster",
     "body": "The second data source that feeds your fees, results and subject list was "
             "being asked for one item at a time, waiting for each answer before asking "
             "the next. Those answers now come back in parallel, so a full refresh finishes "
             "in about a third of the time it used to. Results and transcripts are also "
             "cached for a day now instead of half an hour - that data cannot change "
             "between two refreshes in the same afternoon, so re-downloading it was wasted "
             "work. Nothing on any page has changed."},
    {"ver": "v2.6.0", "date": "30 Oct", "title": "The app now watches how you use it",
     "body": "OpenSRM now keeps track of which tabs actually get read, how busy the app "
             "is hour by hour, and how long each part of a sync takes - the portal, the "
             "campus backend, and saving the result. It is all aggregate or a short code "
             "that stands in for your account, never your netid and never anything you "
             "type. Nothing about the pages you see has changed; this is what lets "
             "problems get found before you have to report them."},
    {"ver": "v2.5.1", "date": "30 Oct", "title": "Status tiles show their numbers",
     "body": "The small status tiles on the ops dashboard - the ones that reduce a "
             "whole chart to a single number - were drawing in their alert colour no "
             "matter what the value was, so a perfectly healthy service still looked "
             "like it was down. They now show the real reading. Nothing about the app "
             "itself changed."},
    {"ver": "v2.5.0", "date": "29 Oct", "title": "Everything, measured",
     "body": "The app now keeps a running tally of what it is actually doing: every "
             "page it serves and how long each took, every database query, every call to "
             "the campus backend, every notification it tries to deliver, and its own "
             "memory and storage use. Nothing about you is in it - the counts are grouped "
             "by page and action, never by student. It is what turns a vague 'it feels "
             "slow' into a named page and a named time."},
    {"ver": "v2.4.1", "date": "28 Oct", "title": "SCOPE panels actually fill in",
     "body": "The SCOPE tabs had data waiting on the backend but nothing ever asked "
             "for it, so they stayed empty. Collection now starts in the background "
             "after login and whenever the stored copy goes stale, and the page picks "
             "it up on its own once it lands - so the Tools, Academics, Fees and "
             "Campus panels show up. Attendance Margin also now reads the same as the "
             "dashboard widget: +N classes you can still miss, -N you must attend."},
    {"ver": "v2.4.0", "date": "27 Oct", "title": "More personal details",
     "body": "Settings -> Personal details now picks up the extra facts the "
             "official SCOPE student app already knows - parents' names, date of "
             "birth, admitted date, address, university and advisors - shown only "
             "where the portal doesn't already list them."},
    {"ver": "v2.3.0", "date": "27 Oct", "title": "Academics, in one place",
     "body": "A new Academics tab starts with your CGPA and the credits you have "
             "earned, then drops each semester open onto its subjects as one line "
             "each - code, name, grade - with credits and SGPA in the summary. "
             "Failures wear a tinted red; everything else stays quiet."},
    {"ver": "v2.2.0", "date": "27 Oct", "title": "Fees, without the digging",
     "body": "A Fees tab shows what you still owe, and once nothing is due it opens "
             "straight into what you have paid, grouped by academic year with the "
             "date first and the amount on the right. The full receipt history sits "
             "in a collapsed ledger you can open when you actually need a voucher "
             "number."},
    {"ver": "v2.1.0", "date": "26 Oct", "title": "Attendance, hour by hour",
     "body": "The absences list turns into a real attendance view: open any month "
             "and each date drops down as a row of periods showing P, A or OD, "
             "joined to your timetable so hovering a cell tells you which subject "
             "that hour actually was."},
    {"ver": "v2.0.0", "date": "27 Oct", "title": "SRM's own app backend, and a Tools tab",
     "body": "OpenSRM now talks to the same backend the official SRM SCOPE student app uses, "
             "so fee records, exam results, library loans, hostelling and placement "
             "details can come from the source the college itself ships with. This "
             "release is the groundwork: the connection, the feature switches and this "
             "Tools tab. The cards for each of those arrive over the next updates — "
             "phones also get a tidier bar, with refresh on the left of the logo and "
             "settings on the right, and Settings' place in the bottom bar goes to Tools."},
    {"ver": "v1.32.0", "date": "26 Oct", "title": "A cleaner edge",
     "body": "The empty strip along the right side is gone, and the scrollbar "
             "is now a thin bar that only appears while you are using it — it "
             "floats over the page instead of pushing it around. The top bar "
             "runs edge to edge and stays put while you scroll."},
    {"ver": "v1.31.1", "date": "26 Oct", "title": "The page stays put",
     "body": "A refresh used to nudge the cards in from the left edge and "
             "down from the menu after every sync. They now stay exactly "
             "where they were."},
    {"ver": "v1.31.0", "date": "24 Oct", "title": "Leaner under the hood",
     "body": "The server got a much smaller update package, so future "
             "updates download faster. Nothing you can see changes — same "
             "app, lighter behind the scenes."},
    {"ver": "v1.30.0", "date": "20 Oct", "title": "Swipe to refresh",
     "body": "Pull down from the top on your phone to refresh \u2014 the "
             "same gesture you know from apps, right inside OpenSRM."},
    {"ver": "v1.29.0", "date": "20 Oct", "title": "Kind to weak phones",
     "body": "The animated avatar now rests when it is off screen, and "
             "weak devices get a calm version automatically \u2014 less "
             "battery and smoother scrolling for everyone."},
    {"ver": "v1.28.0", "date": "20 Oct", "title": "Feels like an app",
     "body": "Taps now respond instantly, tabs glide instead of snapping, "
             "and dialogs slide up from the bottom on phones \u2014 the "
             "small motion touches that make it feel native."},
    {"ver": "v1.27.2", "date": "20 Oct", "title": "Security upkeep",
     "body": "A routine security update of the tools the server uses "
             "under the hood. Nothing changes in how the app looks or "
             "works."},
    {"ver": "v1.27.1", "date": "20 Oct", "title": "Smarter feedback button",
     "body": "The auto-fill feedback option now checks the portal before "
             "showing itself: while the mid-sem feedback form is closed on "
             "the portal, the button hides itself automatically and returns "
             "on its own when the form opens again — no more dead buttons."},
    {"ver": "v1.27.0", "date": "20 Oct", "title": "Refresh without the flash",
     "body": "Refreshing now updates your numbers right where they are "
             "— no more white flash, lost scroll position or "
             "re-loading of the page after a sync."},
    {"ver": "v1.26.3", "date": "20 Oct", "title": "Instant repeat visits",
     "body": "The app now remembers its own files: styles and scripts "
             "that have not changed are no longer re-downloaded on every "
             "launch, so opening the dashboard again is much faster and "
             "uses less data. New versions still arrive automatically "
             "right after each update."},
    {"ver": "v1.26.2", "date": "19 Oct", "title": "Faster first paint",
     "body": "The app's stylesheet is now built ahead of time and served "
             "straight from this server, instead of each phone compiling "
             "CSS in the browser on every launch. The page shows sooner, "
             "works with no third-party requests, and nothing changes in "
             "how it looks."},
    {"ver": "v1.26.1", "date": "19 Oct", "title": "Under-the-hood tidy-up",
     "body": "A defensive fix so an unusually long subject code in the Today "
             "widget can never push the page sideways on a phone — the code "
             "truncates instead. Nothing changes with normal timetables. Also "
             "adds the measuring tools used for the upcoming performance work."},
    {"ver": "v1.26.0", "date": "18 Oct", "title": "Self-checking reminders",
     "body": "The job that sends class-reminder pushes now reports its own "
             "health on the server's metrics page, so if it ever stops "
             "running, the server itself raises an alarm instead of the "
             "reminders just quietly not arriving. Nothing changes in how "
             "reminders look on your end."},
    {"ver": "v1.25.0", "date": "15 Oct", "title": "Delete my data",
     "body": "Settings now has a \"Delete my data\" row: it opens an explainer "
             "listing exactly what is erased (your account, login sessions, "
             "reminder subscriptions, usage rows, your edit attributions) and "
             "what is never touched — the SRM portal itself, shared timetables "
             "and other students' accounts. Nothing is removed until you "
             "confirm, and afterwards you are signed out back to the login page."},
    {"ver": "v1.24.0", "date": "15 Oct", "title": "Server health check + hardening",
     "body": "The server now answers a small health endpoint that is checked "
             "every 30 seconds, so a broken server is noticed immediately "
             "instead of timing out in your dashboard. The app also runs in a "
             "locked-down container (no root, read-only filesystem, capped "
             "memory and process limits), so a fault inside it stays inside "
             "it. Nothing changes in how you use the app."},
    {"ver": "v1.23.0", "date": "15 Oct", "title": "Syncs wait in line instead of failing",
     "body": "Clicking sync while another sync is already running no longer fails with "
             "\"Sync in progress\" — it waits up to 45 seconds for its turn (logins go "
             "ahead of refreshes, and the progress bar shows how many syncs are ahead) "
             "and only gives the busy error if the wait runs out."},
    {"ver": "v1.22.1", "date": "15 Oct", "title": "Sessions hardened at rest",
     "body": "Session tokens are now stored in the database only as SHA-256 "
             "digests, so a copied database file can no longer be used to log "
             "in as you — and your existing session keeps working across this "
             "update. Requests that try to change your data from another "
             "website are also refused now."},
    {"ver": "v1.22.0", "date": "15 Oct", "title": "Smarter syncs — no wasted portal visits",
     "body": "Syncing twice in a row no longer hits the portal twice: a refresh within "
             "5 minutes of your last sync is answered from the data you already have, "
             "and refreshes started while one is already running now wait for and "
             "share that sync instead of showing a \"Sync in progress\" error."},

    {"ver": "v1.21.0", "date": "15 Oct", "title": "Clearer sync errors + sync health monitoring",
     "body": "A failed sync now says exactly what went wrong (wrong password, "
             "portal busy, or the portal changed) instead of a generic error. "
             "We also track sync success, timing and portal failures "
             "server-side — with a one-command canary check — so a portal "
             "change is caught before it reaches your dashboard."},
    {"ver": "v1.20.2", "date": "15 Oct", "title": "Fewer database-is-locked errors",
     "body": "Concurrent requests used to hit SQLite's 5-second lock wait "
             "limit and show a database-is-locked error; the app now waits "
             "up to 10 seconds, and operators can switch to WAL journaling "
             "with the SQLITE_JOURNAL_MODE setting for smoother concurrent "
             "access. Nothing changes for existing installs by default."},
    {"ver": "v1.20.1", "date": "14 Oct", "title": "Refresh keeps your subjects",
     "body": "A refresh whose marks page failed to parse used to blank the "
             "subjects already stored on your account. Stored subjects, marks, "
             "exam schedule, faculty and attendance are now kept whenever the "
             "fresh value comes back empty, and every kept value is logged "
             "instead of being written silently."},
    {"ver": "v1.20.0", "date": "14 Oct", "title": "Dashboard layout fixes",
     "body": "Uniform 15px spacing everywhere (no more 30px gaps or mystery "
             "19px right gutter); cards no longer scroll when their widgets "
             "fit; attendance shows subject names with +skip/-attend margins; "
             "freshly entered marks are faintly highlighted and show up in "
             "This Week; the profile blobatar is bigger now."},
    {"ver": "v1.19.0", "date": "13 Oct", "title": "Feedback button follows the portal",
     "body": "Auto-fill hides itself while the portal's mid-sem feedback service is "
             "closed and comes back when it reopens; the dashboard now fits your "
             "screen without scrolling on desktop; every release ships a notice here."},
    {"ver": "v1.18.0", "date": "12 Oct", "title": "Official timetable from the portal",
     "body": "Timetable syncs straight from the portal's published grid (manual "
             "editing archived); syncs now keep your session through a mid-scrape relogin."},
    {"ver": "v1.17.0", "date": "12 Oct", "title": "Settings tab",
     "body": "Personal details, notification preferences and log out consolidated "
             "into one Settings tab."},
    {"ver": "v1.16.0", "date": "11 Oct", "title": "Card dashboard + notices",
     "body": "Dashboard rebuilt as cards and widgets: class ticker, skip "
             "glance, subject-grouped teachers and this notices panel."},
    {"ver": "v1.15.4", "date": "10 Oct", "title": "Institute email + marks fixes",
     "body": "Profile shows your @srmist.edu.in address; marks list every "
             "subject, stale entries flagged, trailing zeroes trimmed."},
]




# ── Tools tab (SCOPE-sourced surfaces) ──────────────────────────────
# One entry per SCOPE surface. A row renders ONLY when its feature slug is
# enabled AND its representative op landed a non-empty answer; nothing
# qualifying = empty list = no entry, no tab (zero footprint — the mission
# toggle contract, and the same self-hiding rule the dashboard widgets obey).
# `tab` is the panel that surface's own PR mounts: the row navigates there
# when that panel exists today and renders inert otherwise, so this stays a
# landing surface for the SCOPE rotation instead of a duplicate of it.
TOOLS = [
    # (slug, label, hint, gate op, tab). The tab is where the row sends you: a
    # surface with its own panel names it, one that lives inside an existing
    # tab points there. dash.js marks a row inert when that panel is absent, so
    # a not-yet-mounted surface degrades to a disabled row, never a dead link.
    ("fees", "Fees", "Dues, payments and receipts", "getFeeDetails", "fees"),
    # gates on the RELEASED-results op: the provisional/revaluation endpoints
    # are empty outside their window, so keying the entry on them left Academics
    # hidden even with a full grade history (caught in review).
    ("academics", "Academics", "Results, grades and credits",
     "getExamDetails", "academics"),
    # hourwise renders inside the Attendance tab, not a panel of its own, and
    # its gate op is what the detailed grid needs (rows, not the summary list).
    ("hourwise", "Attendance by hour", "Every period, joined to your timetable",
     "getHourwiseAttendance", "attendance"),
    # profile fills the Personal details section inside Settings.
    ("profile", "Personal details", "Parents, date of birth, address",
     "getStudentPersonalDetails", "settings"),
    ("library", "Library", "Issued books, due dates, fines",
     "getLibraryTransaction", "campus"),
    ("campus", "Hostel & transport", "Room, mess and bus route",
     "getHostelDetails", "campus"),
    ("campus", "Notifications", "Campus notices and circulars",
     "getViewNotificationListJson", "campus"),
    ("placement", "Placement", "Offers, eligibility, registration",
     "getStudentAllOfferedJobs", "campus"),
]
