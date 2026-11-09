import type { MarksComponent, MarksProps, MarksSubject } from './contract';

export interface MarksHost {
  el: HTMLElement;
  props: unknown;
}

/** Client-only marker: only a mounted island can set it. Mirrors sync-age. */
export const HYDRATED_ATTR = 'data-hydrated';

const CHIP = 'inline-flex items-center justify-center w-14 h-5 shrink-0 rounded-full bg-base-300 text-base-content/70 font-mono text-xs';

/**
 * One component line — the DOM of marks.html:216-256.
 *
 * The `<details>` tagging form is NOT rendered: it is a POST form that the
 * server-rendered markup already provides, and cloning it here would either
 * duplicate the form id (`tag-<code>-<name>`, marks.html:222) or fork the
 * markup. The island paints the reading surface; the tag control stays the
 * server's, and only becomes visible because hydration replaces the card body
 * — so it is rendered, not omitted. See TagForm below for the reason it is
 * kept as markup rather than reimplemented as a controlled component.
 */
function TagForm({ s, cpt }: { s: MarksSubject; cpt: MarksComponent }) {
  const selected = cpt.confirmed ?? cpt.derived;
  const status = cpt.confirmed
    ? ` · confirmed ${cpt.confirmed === 'none' ? 'neither' : cpt.confirmed}`
    : ' · not confirmed yet';
  return (
    <details class="relative shrink-0" id={`tag-${s.code}-${cpt.name.replace(/ /g, '-')}`}>
      <summary
        class="tooltip tooltip-left flex items-center justify-center w-6 h-6 rounded-full cursor-pointer list-none [&::-webkit-details-marker]:hidden text-base-content/50 hover:text-base-content/70"
        data-tip={`Mark ${cpt.name} as the IE-1/IE-2 exam`}
      >
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L6.832 19.82a4.5 4.5 0 01-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 011.13-1.897L16.862 4.487z" />
          <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-3.75-3.75" />
        </svg>
        <span class="sr-only">Tag {cpt.name}</span>
      </summary>
      <form
        method="post"
        action="/marks/tag"
        class="absolute end-0 top-full mt-1 z-10 w-60 bg-base-200 border border-base-300 rounded-box p-3 flex flex-col gap-2"
      >
        <input type="hidden" name="code" value={s.code} />
        <input type="hidden" name="component" value={cpt.name} />
        <p class="text-xs text-base-content/60">Derived {cpt.derived || 'none'}{status}</p>
        <fieldset class="fieldset p-0">
          <legend class="fieldset-legend text-xs">Role</legend>
          <select name="role" class="select select-sm w-full">
            <option value="IE-1" selected={selected === 'IE-1'}>IE-1</option>
            <option value="IE-2" selected={selected === 'IE-2'}>IE-2</option>
            <option value="none" selected={selected !== 'IE-1' && selected !== 'IE-2'}>Neither</option>
          </select>
        </fieldset>
        <button class="btn btn-sm btn-primary hover:bg-base-300 focus-visible:outline-accent w-full">Save</button>
      </form>
    </details>
  );
}

/** One component: chip + date + score, plus the nested IE row when converted. */
function Component({ s, cpt }: { s: MarksSubject; cpt: MarksComponent }) {
  return (
    <div class="py-1">
      <div class="flex items-center gap-2">
        <span class={CHIP}>{cpt.name}</span>
        {cpt.date_disp ? <span class="text-xs font-mono text-base-content/50">{cpt.date_disp}</span> : null}
        <span class="font-mono text-xs tabular-nums ml-auto">{cpt.score_disp}/{cpt.max_disp}</span>
        <TagForm s={s} cpt={cpt} />
      </div>
      {cpt.ie ? (
        <div class="flex items-center gap-2 ps-6 mt-0.5">
          <span class={CHIP}>{cpt.ie.role}</span>
          <span class="text-xs text-base-content/50">{cpt.ie.confirmed ? 'confirmed' : 'derived'}</span>
          <span class="font-mono text-xs tabular-nums ml-auto">{cpt.ie.score_disp}/{cpt.ie.max_disp}</span>
        </div>
      ) : null}
    </div>
  );
}

/** One subject card — marks.html:205-262. */
function Subject({ s }: { s: MarksSubject }) {
  return (
    <div class="bg-base-200 border border-base-300 rounded-box p-4">
      <div class="flex items-baseline justify-between gap-2">
        <span class="font-mono text-xs text-base-content/60">{s.code}</span>
        {/* neutral number; exactly one outlier on the page may take the accent (§2.7) */}
        <span class={`font-mono font-bold text-lg tabular-nums${s.outlier ? ' text-secondary' : ''}`}>{s.pct}%</span>
      </div>
      <h3 class="text-sm font-semibold leading-snug">{s.title || s.code}</h3>
      <div class="font-mono text-xs text-base-content/50 tabular-nums mb-2">{s.scored_disp}/{s.max_disp}</div>
      <div class="border-t border-base-300 pt-2">
        {s.components.length > 0 ? (
          s.components.map((cpt) => <Component key={cpt.name} s={s} cpt={cpt} />)
        ) : (
          <p class="text-xs text-base-content/50 italic">No assessment data</p>
        )}
      </div>
    </div>
  );
}

/**
 * The marks cards, hydrated.
 *
 * Returns the `.grid` of subject cards; main.ts's render() replaces the mount
 * element's children with it. Rendering happens inside the boundary's try, so
 * a bad prop throws there and the server's markup is restored — nothing here
 * may defer work to useEffect/useState, whose throws the boundary cannot see.
 */
export default function MarksPanel({ el, props }: MarksHost) {
  el.setAttribute(HYDRATED_ATTR, '1');
  const { subjects } = props as MarksProps;
  return (
    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
      {subjects.map((s) => <Subject key={s.code} s={s} />)}
    </div>
  );
}
