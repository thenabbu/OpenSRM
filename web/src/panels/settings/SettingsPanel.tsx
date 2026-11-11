import type { Detail, Group, SettingsProps } from './contract';
import { text } from '../../design';

export interface SettingsHost {
  el: HTMLElement;
  props: unknown;
}

/** Client-only marker: only a mounted island can set it. Mirrors sync-age. */
export const HYDRATED_ATTR = 'data-hydrated';

/** settings.html:189 — one collapse, and the groups nested inside it. */
const COLLAPSE = 'collapse collapse-arrow bg-base-200 border border-base-300';
const TITLE = 'collapse-title text-sm font-semibold flex items-center justify-between gap-2';

/** One key/value cell (settings.html:228-232). */
function Cell({ d }: { d: Detail }) {
  return (
    <div class={d.wide ? 'sm:col-span-2' : undefined}>
      <div class={`text-xs uppercase tracking-wide ${text('50')}`}>{d.key}</div>
      <div class={d.mono ? 'text-sm font-mono break-words' : 'text-sm break-words'} data-copy={d.value}>
        {d.value}
      </div>
    </div>
  );
}

/** One group collapse: title, count badge, then the 1/2-col grid (settings.html:217-235). */
function GroupBlock({ g }: { g: Group }) {
  return (
    <div class={COLLAPSE}>
      <input type="checkbox" aria-label={`Toggle ${g.title}`} />
      <div class={TITLE}>
        <span>{g.title}</span>
        <span class="badge badge-sm">{g.items.length}</span>
      </div>
      <div class="collapse-content">
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-2">
          {g.items.map((d, i) => <Cell key={`${d.key}-${i}`} d={d} />)}
        </div>
      </div>
    </div>
  );
}

/** The personal-details block: identity header + groups, or the empty alert. */
export function PersonalDetails({ props }: { props: unknown }) {
  const { personal, count } = props as SettingsProps;
  return (
    <div class={COLLAPSE} id="personal-details">
      <input type="checkbox" aria-label="Toggle personal details" />
      <div class={TITLE}>
        <span>Personal details</span>
        {personal ? <span class="badge badge-sm">{count}</span> : null}
      </div>
      <div class="collapse-content">
        {!personal ? (
          <div class="alert alert-soft alert-info">No personal details available.</div>
        ) : (
          <div class="flex flex-col gap-3">
            {personal.name || personal.program ? (
              <div class="card bg-base-200 border border-base-300">
                <div class="card-body p-4">
                  {personal.name ? (
                    <div class="text-lg font-semibold" data-copy={personal.name}>{personal.name}</div>
                  ) : null}
                  {personal.program ? (
                    <div class={`text-sm font-mono ${text('60')} break-words mt-1`} data-copy={personal.program}>
                      {personal.program}
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}
            {personal.groups.map((g, i) => <GroupBlock key={`${g.title}-${i}`} g={g} />)}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Thin host: main.ts owns validation (islands/contract.ts) and the error
 * boundary, so this default export only paints. `null` = show nothing, which
 * lets the boundary restore the server's children.
 */
export default function SettingsPanel({ el, props }: SettingsHost) {
  // Marks the node as client-owned BEFORE returning, inside the boundary's try:
  // a throw here still leaves the server's children restored and un-marked.
  el.setAttribute(HYDRATED_ATTR, '1');
  // The mount IS #personal-details (settings.html:189), so the block returned
  // here carries that same id — the server's node is replaced, not nested.
  return <PersonalDetails props={props} />;
}
