import type { TtBreak, TtDay, TtRow, TtSig, TimetableProps } from './contract';

export interface TimetableHost {
  el: HTMLElement;
  props: unknown;
}

/** Client-only marker: only a mounted island can set it. Mirrors sync-age. */
export const HYDRATED_ATTR = 'data-hydrated';

/** The attendance tag's words (timetable.py:451-459) — number and word
 *  space-separated and contiguous so the phrase reads as one. */
const sigText = (s: TtSig): string =>
  s.cls === 'warn' ? `${s.num} margin` : `${s.cls === 'ok' ? 'can skip' : 'attend'} ${s.num}`;

/** Tooltip behind that number (timetable.py:278-288). */
const sigPhrase = (s: TtSig): string =>
  s.cls === 'danger'
    ? `${s.num} in a row to reach 75%`
    : s.cls === 'warn' ? 'one miss drops below 75%' : 'skippable, still 75%';

/** One class row — timetable.py:464-472. */
function Row({ r }: { r: TtRow }) {
  return (
    <div class={r.live ? 'tt-row tt-row--now' : 'tt-row'}>
      <div class="tt-time">
        <b>{r.start}</b>
        <span>{r.end}</span>
      </div>
      <div class="tt-info">
        <b>{r.name}</b>
        <span class="tt-sub">
          <span class="tt-code">{r.code}</span>
          <span class="tt-tail">
            {r.location ? <span class="tt-chip">{r.location}</span> : null}
            {r.sig ? (
              <span class={`tt-tag tt-tag--${r.sig.cls}`} title={sigPhrase(r.sig)}>
                {sigText(r.sig)}
              </span>
            ) : (
              <span class="tt-tag tt-tag--none">no data</span>
            )}
          </span>
        </span>
      </div>
    </div>
  );
}

/** One day panel — hero/selector are not here: they stay server-painted. */
function Panel({ d }: { d: TtDay }) {
  return (
    <div class="day-panel" id={`panel-${d.day}`}>
      {d.empty ? <div class="tt-off">No classes</div> : null}
      {d.rows.map((x) =>
        x.kind === 'break' ? (
          <div class="tt-brk">{(x as TtBreak).label}</div>
        ) : (
          <Row r={x as TtRow} />
        ),
      )}
    </div>
  );
}

/**
 * The timetable day panels, hydrated.
 *
 * Returns the panels in the same order the server painted them; render()
 * replaces the mount's children. No wrapper element here — the mount point is
 * already the `.panels` container (the P6.3 lesson: a wrapper inside it nests a
 * level the CSS does not expect).
 *
 * Everything runs inside the boundary's try, so a bad prop throws there and
 * the server's markup is restored — nothing may defer work to useEffect.
 */
export default function TimetablePanel({ el, props }: TimetableHost) {
  el.setAttribute(HYDRATED_ATTR, '1');
  const { days } = props as TimetableProps;
  return (
    <>
      {days.map((d) => (
        <Panel key={d.day} d={d} />
      ))}
    </>
  );
}
