import type { ComponentChildren } from 'preact';
import { badge } from '../../design';
import type { DashboardProps } from './contract';

export interface DashboardHost {
  el: HTMLElement;
  props: unknown;
}

/** Client-only marker: only a mounted island can set it. Mirrors sync-age. */
export const HYDRATED_ATTR = 'data-hydrated';

type P = DashboardProps;

/**
 * profile.html — the identity box (no `wlabel`: the identity is its own label).
 *
 * The avatar is the server's own `blobatar` SVG, serialised into the props: one
 * generator, two renderings, so `.blobatar-gaze` / `.mo-root` (gaze.js, the
 * low-tier pause CSS, the soft-refresh live-node key) exist on both paths.
 * `data-morph="ignore"` keeps this node across a soft refresh — idiomorph skips
 * the subtree and dash.js re-attaches the LIVE node by its `.blobatar-gaze` class,
 * carrying the gaze driver's inline `--mo-*` vars with it.
 *
 * `#copyEmail` + `[data-copy]` stay document-delegated (dash.js), which is why
 * this component needs no click handler of its own.
 */
function Profile({ p }: { p: P['profile'] }) {
  return (
    <div class="wbox rounded-box p-4">
      <div class="flex items-center gap-3 min-w-0">
        <div class="avatar shrink-0">
          <div
            class="bg-base-300 w-16 h-16 rounded-full overflow-hidden blobatar-gaze"
            data-morph="ignore"
            dangerouslySetInnerHTML={{ __html: p.avatar }}
          />
        </div>
        <div class="min-w-0 flex-1">
          <div class="text-sm font-semibold truncate">{p.name}</div>
          <button
            type="button"
            id="copyEmail"
            data-email={p.email}
            class="btn btn-ghost btn-xs px-0 min-h-6 font-mono text-base-content/70 gap-1"
            title="Click to copy email"
          >
            <span class="truncate">{p.email}</span>
            <svg class="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M15.666 3.888A2.25 2.25 0 0 0 13.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 0 1-.75.75H9a.75.75 0 0 1-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 0 1-2.25 2.25H6.75A2.25 2.25 0 0 1 4.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 0 1 1.927-.184"
              />
            </svg>
          </button>
          {p.reg_no ? (
            // tabindex/role are what dash.js setupCopyTargets stamps on the
            // served node — the island must not hand back a keyboard-dead copy
            // target just because it painted the node itself.
            <div
              class="text-xs text-base-content/50 font-mono cursor-copy"
              data-copy={p.reg_no}
              title="Click to copy"
              tabindex={0}
              role="button"
            >
              {p.reg_no}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/** today.html:3 — `{% if ticker %}`. */
function Today({ ticker, week }: { ticker: NonNullable<P['ticker']>; week: P['week'] }) {
  return (
    <div class="wbox rounded-box p-4">
      <div class="wlabel">Today</div>
      {week.today_absent ? (
        <div class="flex items-center gap-2 mb-2">
          <span class={badge('error')}>Absent</span>
          <span class="text-xs text-base-content/70">marked today</span>
        </div>
      ) : null}
      {ticker.state !== 'done' && ticker.prev ? (
        <div class="flex items-center gap-3 h-7 opacity-50">
          <span class="w-10 shrink-0 font-mono text-xs tabular-nums">{ticker.prev.start}</span>
          <span class="text-xs min-w-0 truncate" title={ticker.prev.code}>{ticker.prev.code}</span>
        </div>
      ) : null}
      {ticker.now ? (
        <div class="flex flex-col gap-0.5 px-2 py-2">
          <div class="flex items-baseline gap-2.5 min-w-0">
            <span class="font-mono text-[22px] font-bold tabular-nums leading-none shrink-0">{ticker.now.start}</span>
            <span class="text-sm font-bold min-w-0 truncate" title={ticker.now.code}>{ticker.now.code}</span>
            <span class="font-mono text-xs text-base-content/50 shrink-0">&ndash;{ticker.now.end}</span>
          </div>
          {ticker.now.name ? <div class="text-xs text-base-content/60">{ticker.now.name}</div> : null}
        </div>
      ) : (
        <div class="text-sm text-base-content/50">All done for today</div>
      )}
      {ticker.next ? (
        <div class="flex items-center gap-3 h-7 opacity-50">
          <span class="w-10 shrink-0 font-mono text-xs tabular-nums">{ticker.next.start}</span>
          <span class="text-xs min-w-0 truncate" title={ticker.next.code}>{ticker.next.code}</span>
        </div>
      ) : null}
    </div>
  );
}

/** week.html — the hour total is printed as an integer when it is one. */
function Week({ week }: { week: P['week'] }) {
  const hours = Number.isInteger(week.hours) ? String(week.hours) : String(week.hours);
  return (
    <div class="wbox rounded-box p-4">
      <div class="wlabel">This week</div>
      {week.days ? (
        <div class="text-sm">
          <strong>{week.days}</strong> day{week.days !== 1 ? 's' : ''} absent &middot; {hours} hrs lost
        </div>
      ) : (
        <div class="text-sm text-base-content/50">No absences this week</div>
      )}
      {week.dates.length ? (
        <div class="flex flex-wrap gap-1.5 mt-2">
          {week.dates.map((h) => (
            <span class={badge('warning', { softness: 'soft', class: 'font-mono' })} title={`${h.hours} hrs`}>
              {h.date.slice(0, 5)}
            </span>
          ))}
        </div>
      ) : null}
      {week.marks.length ? (
        <div class="mt-3 pt-3 border-t border-base-300">
          <div class="text-[11px] uppercase tracking-wider text-base-content/50 mb-1">marks added</div>
          {week.marks.map((r, i) => (
            <div key={i} class="flex items-baseline justify-between gap-2 py-0.5 text-xs">
              <span class="shrink-0 font-mono text-base-content/60">{r.code}</span>
              <span class="min-w-0 truncate text-base-content/80">{r.name}</span>
              <span class="shrink-0 font-mono text-base-content/50">{r.date}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** attendance.html widget — margin to 75%, risk-first (server order). */
function Budgets({ budgets }: { budgets: P['budgets'] }) {
  return (
    <div class="wbox rounded-box p-4">
      <div class="flex items-baseline justify-between gap-2 mb-2">
        <span class="wlabel !mb-0">Attendance</span>
        <span class="text-[11px] text-base-content/50">to 75%</span>
      </div>
      <div class="widget-scroll" tabindex={0} role="group" aria-label="Scrollable list">
        <ul>
          {budgets.map(([name, val, risk]) => (
            <li class="flex items-baseline gap-3 py-2 border-t border-base-300 first:border-t-0 first:pt-0">
              <span class="min-w-0 truncate text-xs text-base-content/70" title={name}>{name}</span>
              {risk < 2 ? (
                <span class="ml-auto att-neg font-mono text-xs">{val}</span>
              ) : (
                <span class="ml-auto font-mono text-sm tabular-nums text-base-content">{val}</span>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/** marks.html — chips; stale fades AND explains, recent gets the ring + title. */
function Marks({ marks }: { marks: P['marks'] }) {
  return (
    <div class="wbox rounded-box p-4">
      <div class="wlabel">Internal marks</div>
      <div class="flex flex-wrap gap-1.5">
        {marks.map((s) => (
          <span
            class={`${badge('neutral', { softness: 'soft', class: 'font-mono tabular-nums' })}${s.stale ? ' opacity-60' : ''}${s.recent ? ' mark-recent' : ''}`}
            title={
              s.stale
                ? 'Kept from an earlier sync — the latest refresh returned no marks for it'
                : s.recent
                  ? `Entered ${s.entered} — updated in the last 24h`
                  : undefined
            }
          >
            <span class="text-base-content/70">{s.code}</span> <span class="font-medium">{s.scored}/{s.max}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

/** exams.html — the `·`-joined detail line, identical on both breakpoints. */
function ExamMeta({ e }: { e: P['exams'] extends null ? never : NonNullable<P['exams']>['rows'][number] }) {
  return (
    <>
      {e.code} &middot; {e.session_disp}
      {e.slot ? <> &middot; {e.slot}</> : null}
      {e.hall ? (
        <>
          {' '}&middot; Hall {e.hall}
          {e.seat ? <> &middot; Seat {e.seat}</> : null}
        </>
      ) : null}
    </>
  );
}

function Exams({ exams }: { exams: NonNullable<P['exams']> }) {
  return (
    <div class="wbox rounded-box p-4">
      <div class="flex items-center justify-between gap-2 mb-2">
        <span class="flex min-w-0 items-center gap-2 text-[11px] text-base-content/60">
          <span class="shrink-0">End sem exams</span>
          <span class={badge('neutral', { softness: 'soft', class: 'shrink-0' })}>{exams.label}</span>
          <span class={badge('outline', { class: 'text-base-content/60 shrink-0' })}>{exams.source}</span>
        </span>
        <span class="shrink-0 text-xs text-base-content/70">
          {exams.days_until > 0 ? (
            <>
              First exam in <strong>{exams.days_until}</strong> day{exams.days_until !== 1 ? 's' : ''}
            </>
          ) : (
            'Exams under way'
          )}
        </span>
      </div>
      <div class="widget-scroll" tabindex={0} role="group" aria-label="Scrollable list">
        <ul>
          {exams.rows.map((e, i) => (
            <li key={i} class="flex items-start gap-3 py-2 border-t border-base-300 first:border-t-0 first:pt-0">
              <span class="w-9 shrink-0 text-center sm:hidden">
                <span class="block font-mono text-[17px] font-semibold leading-none tabular-nums text-base-content">{e.day}</span>
                <span class="block mt-1 text-[11px] uppercase tracking-wider text-base-content/60">{e.dow}</span>
              </span>
              <span class="min-w-0 flex-1 sm:hidden">
                <span class="block text-sm font-semibold leading-snug text-balance text-base-content">{e.name_disp}</span>
                <span class="block mt-0.5 font-mono text-xs text-base-content/60">
                  <ExamMeta e={e} />
                </span>
              </span>
              <span class="hidden sm:flex sm:w-full sm:items-baseline sm:justify-between sm:gap-4">
                <span class="min-w-0 truncate text-sm">
                  <span class="font-mono text-base-content/60">{e.code}</span>{' '}
                  <span class="text-base-content">{e.name_disp}</span>
                </span>
                <span class="shrink-0 font-mono text-xs text-base-content/60">
                  {e.short} &middot; <ExamMeta e={e} />
                </span>
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/** teachers.html — subject-grouped list; the CTA only exists when a plan does. */
function Teachers({ teachers, fb_plan }: { teachers: P['teachers']; fb_plan: boolean }) {
  return (
    <div class="wbox rounded-box p-4">
      <div class="wlabel">Teachers</div>
      <div class="widget-scroll" tabindex={0} role="group" aria-label="Scrollable list">
        <ul>
          {teachers.map((g, i) => (
            <li key={i} class="py-2 border-t border-base-300 first:border-t-0 first:pt-0">
              <div class="mb-1 flex items-baseline gap-1.5 min-w-0">
                {g.code ? <span class="font-mono text-xs text-base-content/60">{g.code}</span> : null}
                <span class="truncate text-xs text-base-content/80">{g.name}</span>
              </div>
              {g.staff.map((s, j) => (
                <div key={j} class="flex items-center gap-2.5 py-1">
                  <span class="grid size-6 shrink-0 place-items-center rounded-full bg-base-300 font-mono text-[10px] text-base-content/70" aria-hidden="true">
                    {s.ini}
                  </span>
                  <span class="min-w-0 flex-1 truncate text-sm">{s.name}</span>
                  {s.mode ? <span class="shrink-0 font-mono text-xs text-base-content/50">{s.mode}</span> : null}
                </div>
              ))}
            </li>
          ))}
        </ul>
      </div>
      <div class="text-xs text-base-content/70 mt-2">From the mid-sem feedback form</div>
      {fb_plan ? (
        <button id="fb-cta" class="btn btn-primary btn-sm min-h-11" aria-haspopup="dialog">
          Auto-fill mid-sem feedback
        </button>
      ) : null}
    </div>
  );
}

/**
 * One LAYOUT card: `home.html:234-237`'s `.card > .card-body`, class strings
 * copied verbatim.
 *
 * The grid is the island's MOUNT POINT, and main.ts's render replaces that
 * element's CHILDREN — so the island has to emit the cards, not just the
 * widgets. Emitting bare `.wbox`es dropped the grid cell (feedback card
 * collapsed to 58x64), made `closest('.card')` null (scope-profile DUT threw)
 * and orphaned home.html's `.card-body > .wbox` flex rules.
 *
 * The span/row-span/cap mirror the LAYOUT registry in app/views/layout.py,
 * which stays the single source of truth for the card tree. They are spelled
 * out literally here because Tailwind only generates classes it can see as
 * literal text. Change LAYOUT and this must change with it; the `card` /
 * `card-body` counts in dashboard.test.ts are the tripwire.
 */
function Card({ cls, children }: { cls: string; children: ComponentChildren }) {
  return (
    <div class={`card bg-base-200 border border-base-300 ${cls} lg:overflow-hidden`}>
      <div class="card-body p-4 gap-3 lg:min-h-0 lg:overflow-y-auto">{children}</div>
    </div>
  );
}

/**
 * The six dashboard widgets, hydrated.
 *
 * Each widget's guard mirrors its partial's `{% if %}` exactly, so the hydrated
 * tree equals the no-JS one: an empty widget renders nothing, never an empty
 * shell. Returns the fragment; main.ts's render() replaces the mount element's
 * children with it, inside the boundary's try — so a bad prop throws there and
 * the server's markup is restored. Nothing here may defer work to
 * useEffect/useState, whose throws the boundary cannot see.
 */
export default function DashboardPanel({ el, props }: DashboardHost) {
  const p = props as DashboardProps;
  el.setAttribute(HYDRATED_ATTR, '1');
  return (
    <>
      {/* LAYOUT `day`: span 4, row-span 2, always shown (no `when`). */}
      <Card cls="lg:col-span-4 lg:row-span-2">
        <Profile p={p.profile} />
        {p.ticker ? <Today ticker={p.ticker} week={p.week} /> : null}
        <Week week={p.week} />
      </Card>
      {/* LAYOUT `assess`: span 8, cap 0.65 — dropped when marks AND exams are
          both empty, exactly as the route drops a card whose `when` is all
          falsy (layout.py, dashboard.py). */}
      {p.marks.length || p.exams ? (
        <Card cls="lg:col-span-8 lg:max-h-[calc((100dvh-94px)*0.65)]">
          {p.marks.length ? <Marks marks={p.marks} /> : null}
          {p.exams ? <Exams exams={p.exams} /> : null}
        </Card>
      ) : null}
      {/* LAYOUT `people`: span 8, `cols: 2` — the template wraps every widget
          of a cols card in one grid, and the grid itself is unconditional. */}
      {p.budgets.length || p.teachers.length ? (
        <Card cls="lg:col-span-8">
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {p.budgets.length ? <Budgets budgets={p.budgets} /> : null}
            {p.teachers.length ? <Teachers teachers={p.teachers} fb_plan={p.fb_plan} /> : null}
          </div>
        </Card>
      ) : null}
    </>
  );
}
