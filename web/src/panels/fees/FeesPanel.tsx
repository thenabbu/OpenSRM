import type { FeeDue, FeeReceipt, FeeYear, FeesProps } from './contract';
import { text } from '../../design';

export interface FeesHost {
  el: HTMLElement;
  props: unknown;
}

/** Client-only marker: only a mounted island can set it. Mirrors sync-age. */
export const HYDRATED_ATTR = 'data-hydrated';

/** Hero + every card shares the group card chrome (fees.html:207,216). */
const CARD = 'bg-base-200 border border-base-300 rounded-box p-4';
/** The date | rule | content | amount row grid (fees.html:244, 267). */
const ROW = 'grid grid-cols-[auto_1px_1fr_auto] gap-x-3 items-baseline';
/** The vertical hairline cell inside that grid. */
const RULE = '-my-0.5 self-stretch border-l border-base-300';

const rupee = (s: string) => `₹${s}`;

/** Outstanding dues hero — absent entirely when nothing is owed (fees.html:206). */
function Hero({ p }: { p: FeesProps }) {
  if (!p.due_disp) return null;
  return (
    <div class={CARD}>
      <div class="flex items-baseline justify-between gap-3">
        <span class="text-sm font-semibold">Outstanding dues</span>
        <span class={`font-mono font-bold text-2xl tabular-nums ${p.level}`.trim()}>
          {rupee(p.due_disp)}
        </span>
      </div>
      <p class={`text-xs ${text('50')} mt-1`}>As reported by the SCOPE backend</p>
    </div>
  );
}

/** One outstanding charge line (fees.html:218-223). */
function Due({ d }: { d: FeeDue }) {
  return (
    <div class="flex items-baseline justify-between gap-3">
      <span class="text-sm">
        {d.due ? <span class="whitespace-nowrap">Due {d.due}</span> : 'Outstanding'}
        {d.penalised ? (
          <span class="text-xs text-error"> penalty applied</span>
        ) : d.penalty ? (
          <span class={`text-xs ${text('50')} whitespace-nowrap`}> penalty after {d.penalty}</span>
        ) : null}
      </span>
      <span class={`font-mono text-sm tabular-nums ${text('70')}`}>{rupee(d.amt)}</span>
    </div>
  );
}

/** Year header + its paid rows (fees.html:236-253). */
function Year({ y }: { y: FeeYear }) {
  return (
    <section>
      <div class="flex items-baseline justify-between gap-2">
        <h2 class={`font-mono text-xs ${text('60')}`}>{y.year}</h2>
        <span class="font-mono text-sm font-semibold tabular-nums">{rupee(y.total)}</span>
      </div>
      <div class="flex flex-col gap-2 mt-4">
        {y.rows.map((r) => (
          <div class={ROW}>
            <span class={`font-mono text-xs ${text('60')} tabular-nums`}>{r.date}</span>
            <span class={RULE} aria-hidden="true" />
            <span class="text-sm min-w-0 break-words">{r.head}</span>
            <span class="font-mono text-sm tabular-nums text-right">{rupee(r.amt)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

/** One receipt: summary line, narration + copyable voucher inside (fees.html:265-282). */
function Receipt({ e, first }: { e: FeeReceipt; first: boolean }) {
  return (
    <details class={first ? 'collapse collapse-arrow fees-rcpt' : 'collapse collapse-arrow fees-rcpt border-t border-base-300'}>
      <summary class={`collapse-title ${ROW} text-sm min-h-0 py-1.5`}>
        <span class={`font-mono text-xs ${text('60')} tabular-nums`}>{e.date}</span>
        <span class={RULE} aria-hidden="true" />
        <span class="text-sm min-w-0 truncate">{e.head}</span>
        <span class="font-mono text-sm font-semibold tabular-nums text-right">{rupee(e.amt)}</span>
      </summary>
      <div class="collapse-content pt-1">
        {e.vno ? (
          <span
            class={`font-mono text-xs ${text('60')} cursor-pointer`}
            data-copy={e.vno}
            title="Click to copy voucher no."
          >
            #{e.vno}
          </span>
        ) : null}
        {e.full ? <p class={`text-xs ${text('60')} break-words mt-1`}>{e.full}</p> : null}
      </div>
    </details>
  );
}

/**
 * The fees tab's rows, hydrated.
 *
 * Returns the same six blocks in the same order the server painted them; the
 * mount point is the `#tab-fees` panel itself, so there is no wrapper element
 * (the P6.3 lesson: a wrapper nests a level the CSS does not expect).
 *
 * The page chrome (navbar, dock, modals, the sync caption) is NOT here: it stays
 * server markup, and returning only these nodes is what keeps hydration a pure
 * repaint. Everything runs inside the boundary's try, so a bad prop throws there
 * and the server's markup is restored — nothing may defer work to useEffect.
 */
export default function FeesPanel({ el, props }: FeesHost) {
  el.setAttribute(HYDRATED_ATTR, '1');
  const p = props as FeesProps;
  return (
    <>
      <Hero p={p} />
      {p.dues.length ? (
        <div class={`${CARD}${p.due_disp ? ' mt-3' : ''}`}>
          <div class="flex flex-col gap-2">
            {p.dues.map((d, i) => (
              <Due key={i} d={d} />
            ))}
          </div>
        </div>
      ) : null}
      {p.years.length ? (
        <>
          <div class={`flex items-baseline justify-between gap-3${p.due_disp ? ' mt-5' : ''}`}>
            <h1 class="text-base font-semibold">Paid</h1>
            <span class={`font-mono text-sm ${text('60')} tabular-nums`}>{rupee(p.paid_total)}</span>
          </div>
          <div class="flex flex-col gap-5 mt-3">
            {p.years.map((y) => (
              <Year key={y.year} y={y} />
            ))}
          </div>
        </>
      ) : null}
      {p.ledger.length ? (
        <details class={`collapse collapse-arrow bg-base-200 border border-base-300 rounded-box${p.years.length ? ' mt-5' : ''}`}>
          <summary class="collapse-title text-sm font-semibold">
            Receipts <span class={`font-mono ${text('60')} tabular-nums`}>({p.ledger.length})</span>
          </summary>
          <div class="collapse-content">
            {p.ledger.map((e, i) => (
              <Receipt key={e.vno || i} e={e} first={i === 0} />
            ))}
          </div>
        </details>
      ) : null}
    </>
  );
}
