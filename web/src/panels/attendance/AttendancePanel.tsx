import { tint } from '../../design';
import type { AttendanceCourse, AttendanceProps } from './contract';

export interface AttendanceHost {
  el: HTMLElement;
  props: unknown;
}

/** Client-only marker: only a mounted island can set it. Mirrors sync-age. */
export const HYDRATED_ATTR = 'data-hydrated';

/** Two-decimal string the server also rounds to (attendance.html:244 `|round(2)`). */
const r2 = (n: number): string => String(Math.round(n * 100) / 100);

/**
 * One course meter row — the DOM of attendance.html:234-252.
 *
 * The island re-derives the layout geometry (hatch band, connector midpoint) from
 * `fill`, exactly as the template's Jinja `{% set %}`s do, because those were
 * derived server-side into template locals and never reached the view model.
 * `nudge` and `pole` DID reach it, so they are passed through, not recomputed —
 * a hydration must never disagree with the no-JS paint about label placement.
 */
function Row({ c }: { c: AttendanceCourse }) {
  const hatchLeft = r2(Math.min(c.fill, 75));
  const hatchWidth = r2(Math.abs(c.fill - 75));
  const conn = c.attend_now ?? c.skip_now;
  const nums = c.pole ? (
    <div class="pnums">
      <span class="pn pn-75" style={`left:75%`}>{c.t75}</span>
      <span class="pn pn-tot">{c.attended} / {c.max_hours}</span>
    </div>
  ) : (
    <div class="pnums">
      <span class="pn pn-now" style={`left:${r2(c.fill)}%`}>{c.attended}</span>
      <span class="pn pn-75" style={`left:75%`}>{c.t75}</span>
      <span class="pn pn-tot">{c.max_hours}</span>
    </div>
  );
  return (
    <div class={`mrow ${c.nudge}`.trim()}>
      <div class="mtop">
        <span class="mname">{c.description}</span>
        <span class="mpct">{c.pct_disp}%</span>
      </div>
      {nums}
      <div class="meter" role="img" aria-label={c.label}>
        <i class={tint(c.tint)} style={`width:${r2(c.fill)}%`} />
        <i class="mhatch" style={`left:${hatchLeft}%;width:${hatchWidth}%`} />
        <i class="mtick" />
      </div>
      <div class="pcts">
        <span class="pct pct-0">0%</span>
        <span class="pct pct-75" style={`left:75%`}>75%</span>
      </div>
      {conn ? (
        <div class="pconn">
          <i style={`left:${hatchLeft}%;width:${hatchWidth}%`} />
          <span style={`left:${r2((c.fill + 75) / 2)}%`}>{conn}</span>
        </div>
      ) : null}
    </div>
  );
}

/**
 * The attendance course meters, hydrated.
 *
 * Returns the `.mrows` grid; main.ts's render() replaces the mount element's
 * children with it. Rendering happens inside the boundary's try, so a bad prop
 * throws there and the server's markup is restored — nothing here may defer work
 * to useEffect/useState, whose throws the boundary cannot see.
 */
export default function AttendancePanel({ el, props }: AttendanceHost) {
  el.setAttribute(HYDRATED_ATTR, '1');
  const { courses } = props as AttendanceProps;
  return (
    <div class="mrows">
      {courses.map((c) => <Row key={c.code} c={c} />)}
    </div>
  );
}
