import type { CampusCard, CampusProps, KvGroup, LineRow } from './contract';
import { text } from '../../design';

export interface CampusHost {
  el: HTMLElement;
  props: unknown;
}

/** Client-only marker: only a mounted island can set it. Mirrors sync-age. */
export const HYDRATED_ATTR = 'data-hydrated';

/** The card chrome (campus.html:209-210). */
const CARD = 'card bg-base-200 border border-base-300';
const BODY = 'card-body p-4 gap-2';
/** The hairline that separates every row/group below the title (campus.html
 *  :216, :228, :235, :242). */
const SEP = 'border-t border-base-300';

/** Hostel/transport: label left, mono value right (campus.html:214-222). */
function KvGroupBlock({ g, first }: { g: KvGroup; first: boolean }) {
  return (
    <div class={`flex flex-col gap-2${first ? '' : ` ${SEP} pt-2`}`}>
      <p class={`text-xs ${text('60')}`}>{g.label}</p>
      {g.pairs.map(([k, v], i) => (
        <div key={`${k}-${i}`} class="flex items-baseline justify-between gap-3">
          <span class={`text-xs ${text('60')} min-w-0 break-words`}>{k}</span>
          <span class="font-mono text-sm text-base-content min-w-0 text-right break-words">{v}</span>
        </div>
      ))}
    </div>
  );
}

/** One placement/library/notification row (campus.html:226-255). */
function LineRowBlock({ r }: { r: LineRow }) {
  return (
    <div class={`flex flex-col gap-1 py-2 ${SEP}`}>
      <div class="flex items-baseline justify-between gap-2">
        <span class="text-sm font-semibold min-w-0 break-words">{r.title}</span>
        {r.badge ? (
          <span class={`badge badge-outline badge-sm shrink-0 ${text('60')}`}>{r.badge}</span>
        ) : null}
      </div>
      {r.sub ? <p class={`text-xs ${text('60')} break-words`}>{r.sub}</p> : null}
      {r.meta ? <p class={`font-mono text-xs ${text('50')} break-words`}>{r.meta}</p> : null}
      {r.extras.length ? (
        <details>
          <summary
            class={`text-xs ${text('60')} cursor-pointer select-none hover:text-base-content/70`}
            data-track-item="marks-component"
          >
            Details
          </summary>
          <dl class="mt-1 flex flex-col gap-1">
            {r.extras.map(([k, v], i) => (
              <div key={`${k}-${i}`} class="flex items-baseline justify-between gap-3">
                <dt class={`text-xs ${text('60')} min-w-0 break-words`}>{k}</dt>
                <dd class="text-xs font-mono text-base-content min-w-0 text-right break-words">{v}</dd>
              </div>
            ))}
          </dl>
        </details>
      ) : null}
    </div>
  );
}

/** One card, whichever of the two shapes it is (campus.html:212-256). */
function Card({ c }: { c: CampusCard }) {
  return (
    <div class={CARD}>
      <div class={BODY}>
        <h3 class="text-base font-semibold">{c.title}</h3>
        {'kv' in c
          ? c.kv.map((g, i) => <KvGroupBlock key={`${g.label}-${i}`} g={g} first={i === 0} />)
          : c.rows.map((r, i) => <LineRowBlock key={`${r.title}-${i}`} r={r} />)}
      </div>
    </div>
  );
}

/** Returns the card stack that replaces the server's children 1:1. */
export function CampusCards({ props }: { props: unknown }) {
  const { cards } = props as CampusProps;
  return (
    <div class="flex flex-col gap-3">
      {cards.map((c, i) => (
        <Card key={`${c.title}-${i}`} c={c} />
      ))}
    </div>
  );
}

/**
 * Thin host: main.ts owns validation (islands/contract.ts) and the error
 * boundary, so this default export only paints. `null` = show nothing, which
 * lets the boundary restore the server's children.
 */
export default function CampusPanel({ props }: CampusHost) {
  if (!props || typeof props !== 'object' || !Array.isArray((props as CampusProps).cards)) return null;
  return <CampusCards props={props} />;
}
