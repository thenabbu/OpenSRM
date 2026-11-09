import type { ToolRow, ToolsProps } from './contract';
import { text } from '../../design';

export interface ToolsHost {
  el: HTMLElement;
  props: unknown;
}

/** Client-only marker: only a mounted island can set it. Mirrors sync-age. */
export const HYDRATED_ATTR = 'data-hydrated';

/** The list item + link chrome (tools.html:257-273). */
const LINK = 'pressable flex items-center justify-between gap-3 bg-base-300/50 border border-base-300 rounded-box px-4 py-3.5 hover:bg-base-300 transition-colors';

/** One destination row: label + hint, chevron (tools.html:259-273). */
function Row({ t }: { t: ToolRow }) {
  return (
    <li>
      <a href={`/${t.tab}`} data-tool-tab={t.tab} data-tool-slug={t.slug} class={LINK}>
        <span class="min-w-0">
          <span class="block text-sm font-semibold">{t.label}</span>
          <span class={`block text-xs ${text('60')} mt-0.5 truncate`}>{t.hint}</span>
        </span>
        <svg class={`w-4 h-4 shrink-0 ${text('60')}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
        </svg>
      </a>
    </li>
  );
}

/** The tools list. Fragment: the <ul> sits where the server's <ul> sits. */
export default function ToolsPanel({ props }: ToolsHost) {
  const { rows } = props as ToolsProps;
  // No wrapper <ul>: tools.html:211 puts data-island="tools" ON the <ul> and
  // its children are the <li> rows. Returning a <ul> here nests a second list
  // inside the first (the P6.3/P6.6/P6.7 bug, now caught by island-verify).
  return (
    <>
      {rows.map((t) => <Row key={t.slug} t={t} />)}
    </>
  );
}
