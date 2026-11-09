import type { AcadRow, AcademicsProps, Cat, CourseRow, Sem } from './contract';
import { text } from '../../design';

export interface AcademicsHost {
  el: HTMLElement;
  props: unknown;
}

/** Client-only marker: only a mounted island can set it. Mirrors sync-age. */
export const HYDRATED_ATTR = 'data-hydrated';

/** Both cards share this chrome (academics.html:207, 253). */
const CARD = 'bg-base-200 border border-base-300 rounded-box';
/** The summary row of every dropdown (academics.html:216, 257). */
const SUM = 'min-h-11 cursor-pointer list-none [&::-webkit-details-marker]:hidden';
/** The grade pill, tinted by the server's two booleans (academics.html:236). */
const gradeClass = (r: AcadRow): string =>
  `${r.tint_o || r.tint_f ? 'acad-g ' : ''}${r.tint_o ? 'acad-g-o' : ''}${r.tint_f ? 'acad-g-f' : ''}`.trim();
const CHEV = (
  <svg class={`acad-chev w-4 h-4 ${text('50')}`} viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
    <path d="M6 8l4 4 4-4" stroke-linecap="round" stroke-linejoin="round" />
  </svg>
);

/** One semester's subject row (academics.html:232-239). */
function SemRow({ r }: { r: AcadRow }) {
  return (
    <li class="acad-srow flex items-baseline gap-2 py-1.5 text-sm">
      <span class="min-w-0 flex-1 break-words">
        <span class={`font-mono text-xs ${text('60')}`}>{r.code}</span>
        <span class={`${text('50')} px-0.5`} aria-hidden="true">|</span>
        <span>{r.title}</span>
      </span>
      <span class={`shrink-0 font-mono text-sm tabular-nums ${gradeClass(r)}${r.completed ? '' : ' ' + text('50')}`.trim()}>
        {r.grade || '-'}
      </span>
    </li>
  );
}

/** A semester dropdown: header + SGPA/credits line + its rows (academics.html:214-243). */
function SemRowGroup({ s }: { s: Sem }) {
  return (
    <details class="acad-sem" data-track-item="academics-transcript">
      <summary class={`flex items-center justify-between gap-2 py-2 ${SUM}`}>
        <span class="flex items-baseline gap-2 min-w-0">
          <span class="text-sm font-medium">
            Semester <span class="font-mono tabular-nums">{s.sem}</span>
          </span>
        </span>
        <span class="flex items-baseline gap-2 shrink-0">
          <span class={`font-mono text-xs ${text('50')} tabular-nums`}>{s.credits} cr</span>
          <span class={`font-mono text-xs ${text('60')} tabular-nums uppercase`}>
            {s.label && s.label !== '-' ? s.label : ''}
          </span>
          {CHEV}
        </span>
      </summary>
      <div class="flex items-baseline gap-3 pb-2 pt-1 text-xs">
        <span class={`font-mono ${text('60')} tabular-nums`}>SGPA {s.sgpa}</span>
        <span class={`font-mono ${text('60')} tabular-nums`}>{s.credits} credits</span>
      </div>
      <ul class="pb-2 flex flex-col">
        {s.rows.map((r, i) => (
          <SemRow key={`${r.code}-${i}`} r={r} />
        ))}
      </ul>
    </details>
  );
}

/** CGPA hero: the figure, earned credits, then one dropdown per semester (academics.html:207-247). */
function Cgpa({ c }: { c: NonNullable<AcademicsProps['cgpa']> }) {
  return (
    <div class={`${CARD} p-5`}>
      <h3 class="text-sm font-semibold">CGPA</h3>
      <div class="mt-1 font-mono font-bold text-[22px] leading-none tabular-nums">{c.value}</div>
      <div class={`mt-2 font-mono text-sm ${text('60')} tabular-nums`}>{c.credits_disp}</div>
      {c.sems.length ? (
        <div class="mt-4 pt-3 border-t border-base-300 flex flex-col">
          {c.sems.map((s) => (
            <SemRowGroup key={`${s.sem}-${s.label}`} s={s} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** One subject line inside a category: pending has no grade, completed has one (academics.html:270-297). */
function CourseRowLine({ r, pending }: { r: CourseRow; pending: boolean }) {
  return (
    <li class={`${pending ? '' : 'acad-srow '}flex items-baseline gap-2 py-1.5 text-sm`}>
      <span class="min-w-0 flex-1 break-words">
        <span class={`font-mono text-xs ${text('60')}`}>{r.code}</span>
        <span class={`${text('50')} px-0.5`} aria-hidden="true">|</span>
        <span class={pending ? text('60') : ''}>{r.title}</span>
        {!pending && r.month ? (
          <span class={`font-mono text-xs ${text('50')} tabular-nums whitespace-nowrap`}>{r.month}</span>
        ) : null}
        {!pending && r.attempts ? (
          <span class={`text-xs ${text('50')} whitespace-nowrap`}>&middot; {r.attempts} attempts</span>
        ) : null}
      </span>
      <span
        class={
          pending
            ? `shrink-0 font-mono text-xs ${text('50')} tabular-nums`
            : `shrink-0 font-mono text-sm tabular-nums ${gradeClass(r)}`.trim()
        }
        title={pending ? 'Not completed yet' : undefined}
      >
        {pending ? '-' : r.grade}
      </span>
    </li>
  );
}

/** A degree category: credits + meter in the summary, PENDING FIRST then completed (academics.html:255-305). */
function Category({ c }: { c: Cat }) {
  return (
    <details class="acad-cat">
      <summary class={`py-2 ${SUM}`}>
        <span class="flex items-center justify-between gap-2">
          <span class="min-w-0 flex-1 text-sm" title={c.name}>{c.name}</span>
          <span class="shrink-0 flex items-baseline gap-2">
            <span class={`font-mono text-xs tabular-nums ${text('60')}`}>{c.acq}/{c.req}</span>
            {CHEV}
          </span>
        </span>
        {c.req ? (
          <div
            class="meter"
            role="img"
            aria-label={`${c.name}: ${c.acq} of ${c.req} credits${c.done ? ', complete' : ''}`}
          >
            <i class="mz" style={c.fill} />
          </div>
        ) : null}
      </summary>
      <ul class="pb-2 flex flex-col">
        {c.pending.map((r, i) => (
          <CourseRowLine key={`p-${r.code}-${i}`} r={r} pending />
        ))}
        {c.completed.map((r, i) => (
          <CourseRowLine key={`c-${r.code}-${i}`} r={r} pending={false} />
        ))}
      </ul>
      {!c.pending.length && !c.completed.length ? (
        <div class={`pb-2 text-xs ${text('50')}`}>No subjects listed for this category.</div>
      ) : null}
    </details>
  );
}

/** Credits & subjects: overall totals, then one dropdown per category (academics.html:253-307). */
function Courses({ c }: { c: NonNullable<AcademicsProps['courses']> }) {
  return (
    <div class={`${CARD} p-4`}>
      <div class="flex items-baseline justify-between gap-2">
        <h3 class="text-base font-semibold">Credits &amp; subjects</h3>
        <span class={`font-mono text-xs ${text('50')} tabular-nums`}>{c.overall.acq}/{c.overall.req}</span>
      </div>
      <div class={`mt-1 font-mono text-xs ${text('50')} tabular-nums`}>
        {c.pending} of {c.total} subjects pending
      </div>
      <div class="mt-2 flex flex-col">
        {c.cats.map((x) => (
          <Category key={x.name} c={x} />
        ))}
      </div>
    </div>
  );
}

/**
 * The academics tab's two cards, hydrated.
 *
 * Mounts on `#tab-academics` itself, replacing the inner `flex flex-col gap-3`
 * stack — the same node the server painted, so there is no wrapper level
 * (the P6.3 lesson). Returns [] when both sections are null, which is what the
 * template paints for a gated tab.
 *
 * Everything runs inside the boundary's try (main.ts mountBounded), so a bad
 * prop throws there and the server's markup is restored.
 */
export default function AcademicsPanel({ el, props }: AcademicsHost) {
  el.setAttribute(HYDRATED_ATTR, '1');
  const p = props as AcademicsProps;
  if (!p.cgpa && !p.courses) return null;
  return (
    <div class="flex flex-col gap-3">
      {p.cgpa ? <Cgpa c={p.cgpa} /> : null}
      {p.courses ? <Courses c={p.courses} /> : null}
    </div>
  );
}
