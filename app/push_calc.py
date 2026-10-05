"""Pure due-calculation for class reminders. No I/O, no clock reads — the
caller passes `now_ist`, so tests drive every edge directly.

Due rule:  start - lead <= now < start  AND the key
(subscription_id, local_date, block_start_epoch, subject_code) is not
already logged. The open left edge gives self-healing catch-up (a missed
or jittered tick still sends), the sent log gives exactly-once, and
`now >= start` never sends.

Block rule: one reminder per block of consecutive class periods with the
SAME subject code AND name, adjacent in SLOTS, never across a break or
lunch divider. The room line prints only when location is non-empty.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
LEAD_CHOICES = (5, 10, 15, 30)
MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class Sub:
    """Subscription as the calc sees it (group resolved by the caller)."""
    id: int
    netid: str
    group_key: str | None
    lead_minutes: int = 10


@dataclass(frozen=True)
class Block:
    day: str
    code: str
    name: str
    location: str
    start: datetime          # aware IST
    end: datetime            # aware IST, end of the block's LAST period
    periods: tuple = field(default=())

    @property
    def local_date(self) -> str:
        return self.start.strftime("%Y-%m-%d")

    @property
    def start_epoch(self) -> int:
        return int(self.start.timestamp())


@dataclass(frozen=True)
class Reminder:
    sub: Sub
    block: Block
    key: tuple               # (sub_id, local_date, start_epoch, code)
    ttl: int                 # seconds until block start at calc time
    retry: bool = False      # failed send being retried inside the window
    row_id: int | None = None  # push_sent_log row for a retry claim

    def message(self, now) -> dict:
        """Payload for the SW. 'in N min' comes from the REAL time left at
        send time — never the configured lead."""
        b = self.block
        mins_left = max(1, int(round((b.start - now).total_seconds() / 60)))
        title = f"{b.name} · starts {b.start:%H:%M}"
        body = f"in {mins_left} min · {b.start:%H:%M}–{b.end:%H:%M}"
        if b.location:
            body += f" · {b.location}"
        return {"title": title, "body": body,
                "tag": f"cls-{b.local_date}-{b.start_epoch}-{b.code}",
                "url": "/#timetable"}


def blocks_for_day(day, day_slots, on_date):
    """day_slots = {period: {'code','name','location'}} -> merged Blocks.

    Merges runs where code+name match and periods are adjacent in the SLOTS
    grid with no break/lunch row between them. Runs end at a break, a gap,
    a subject change, or a name change (a lecture and its lab share a code
    but not a name — the name test keeps them separate).
    """
    from .app import SLOTS  # lazy: avoids import cycle, reuses THE grid
    runs = []
    run = None               # {'code','name','location','periods':[p],'end':'HH:MM'}
    after_break = False
    for s in SLOTS:
        if s["type"] == "break":
            if run:
                runs.append(run); run = None
            after_break = True
            continue
        period = s["period"]
        slot = day_slots.get(period)
        if not slot or not (slot.get("code") or ""):
            if run:
                runs.append(run); run = None
            after_break = False
            continue
        code, name = slot["code"], slot.get("name") or ""
        loc = slot.get("location") or ""
        merge = (run is not None and not after_break
                 and run["code"] == code and run["name"] == name
                 and period == run["periods"][-1] + 1)
        if merge:
            run["periods"].append(period)
            if not run["location"] and loc:
                run["location"] = loc
            run["end"] = s["end"]
        else:
            if run:
                runs.append(run)
            run = {"code": code, "name": name, "location": loc,
                   "periods": [period], "end": s["end"]}
        after_break = False
    if run:
        runs.append(run)

    start_of = {s["period"]: s["start"] for s in SLOTS if s["type"] == "class"}
    blocks = []
    for r in runs:
        start = datetime.combine(on_date, dtime.fromisoformat(start_of[r["periods"][0]]), tzinfo=IST)
        end = datetime.combine(on_date, dtime.fromisoformat(r["end"]), tzinfo=IST)
        blocks.append(Block(day=day, code=r["code"], name=r["name"], location=r["location"],
                            start=start, end=end, periods=tuple(r["periods"])))
    return blocks


def due_reminders(now_ist, subscriptions, timetable_by_group, sent):
    """Everything pure: now, subscriptions, the timetable, and what's logged.

    now_ist       aware datetime (naive is read as IST — serverless hosts run UTC)
    subscriptions iterable of Sub (group_key resolved by the caller)
    timetable_by_group {group_key: {day: {period: slot}}}
    sent          {(sub_id, date, start_epoch, code): (status, attempts, row_id)}
    Returns reminders sorted by block start.
    """
    if now_ist.tzinfo is None:
        now_ist = now_ist.replace(tzinfo=IST)
    day, today = now_ist.strftime("%A"), now_ist.date()
    out = []
    for sub in subscriptions:
        day_slots = (timetable_by_group.get(sub.group_key) or {}).get(day)
        if not day_slots:
            continue
        for block in blocks_for_day(day, day_slots, today):
            lead = timedelta(minutes=sub.lead_minutes)
            if not (block.start - lead <= now_ist < block.start):
                continue
            key = (sub.id, block.local_date, block.start_epoch, block.code)
            st = sent.get(key)
            if st is None:
                retry, row_id = False, None
            elif st[0] == "failed" and st[1] < MAX_ATTEMPTS:
                retry, row_id = True, st[2]
            else:
                continue  # sent / orphaned / skipped / attempts exhausted
            out.append(Reminder(sub=sub, block=block, key=key,
                                ttl=max(0, int((block.start - now_ist).total_seconds())),
                                retry=retry, row_id=row_id))
    out.sort(key=lambda r: (r.block.start, r.sub.id))
    return out
