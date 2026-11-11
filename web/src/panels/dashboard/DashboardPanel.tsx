import { badge } from '../../design';
import type { DashboardProps } from './contract';

export interface DashboardHost {
  el: HTMLElement;
  props: unknown;
}

/** Client-only marker: only a mounted island can set it. Mirrors sync-age. */
export const HYDRATED_ATTR = 'data-hydrated';

type P = DashboardProps;

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
      {p.ticker ? <Today ticker={p.ticker} week={p.week} /> : null}
      <Week week={p.week} />
      {p.budgets.length ? <Budgets budgets={p.budgets} /> : null}
      {p.marks.length ? <Marks marks={p.marks} /> : null}
      {p.exams ? <Exams exams={p.exams} /> : null}
      {p.teachers.length ? <Teachers teachers={p.teachers} fb_plan={p.fb_plan} /> : null}
    </>
  );
}
