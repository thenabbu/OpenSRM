import type { FeeDue, FeeReceipt, FeeYear, FeesProps } from './contract';
import { text } from '../../design';
import { markHydrated, type HostProps } from '../../islands/contract';

export type FeesHost = HostProps;

/** Hero + every charge card share the group card chrome (fees.html §1). */
const CARD = 'bg-base-200 border border-base-300 rounded-box p-4';
/** date | label | amount — one grid for paid rows and receipt rows. */
const ROW = 'grid grid-cols-[6.5rem_1fr_auto] gap-x-3 items-baseline';
/** The documented 22px hero step (§4.16), never a bigger invented one. */
const HERO = 'font-mono font-bold text-[22px] tabular-nums';

const rupee = (s: string) => `₹${s}`;

/** Days-left wording; null = no deadline, so nothing to say. */
function daysWord(d: FeeDue): string {
  if (d.overdue) return 'overdue';
  if (d.days_left === 0) return 'last day';
  if (d.days_left === 1) return '1 day left';
  return `${d.days_left} days left`;
}

/** One outstanding charge — named, dated, with the penalty delta (fees.html §1). */
function Charge({ d }: { d: FeeDue }) {
  return (
    <div class={CARD} data-charge>
      <div class="flex items-baseline justify-between gap-3">
        <span class="text-sm font-semibold">{d.head}</span>
        {d.cycle ? <span class={`font-mono text-xs ${text('60')} whitespace-nowrap`}>{d.cycle}</span> : null}
      </div>
      <div class="flex items-baseline flex-wrap gap-x-2 gap-y-1 mt-2">
        <span class={`${HERO} ${d.level}`.trim()}>{rupee(d.amt)}</span>
        {d.deadline ? (
          <span class={`text-xs ${text('60')}`}>{d.overdue ? 'was due' : 'by'} {d.deadline}</span>
        ) : (
          <span class={`text-xs ${text('60')}`}>no due date from SRM yet</span>
        )}
        {/* the words carry the state: only the 22px number takes a status
            hue, because the raw tokens fail AA as 12px text (§4.14) */}
        {d.days_left !== null ? (
          <span class={`font-mono text-xs ${text('60')} tabular-nums whitespace-nowrap`}>{daysWord(d)}</span>
        ) : null}
      </div>
      {d.late_extra ? (
        <p class={`text-xs ${text('60')} mt-1`}>
          Late fee ₹{d.late_extra}{' '}
          {d.penalised || d.overdue ? 'applied' : d.late_on ? `from ${d.late_on}` : 'after the due date'}
        </p>
      ) : null}
      {d.min ? <p class={`text-xs ${text('50')} mt-1`}>part payment taken, ₹{d.min} minimum</p> : null}
    </div>
  );
}

/** Year header + its paid rows (fees.html §2). */
function Year({ y, showHeader }: { y: FeeYear; showHeader: boolean }) {
  return (
    <section>
      {showHeader ? (
        <div class="flex items-baseline justify-between gap-2">
          <h2 class={`font-mono text-xs ${text('60')}`}>{y.year}</h2>
          <span class="font-mono text-sm font-semibold tabular-nums">{rupee(y.total)}</span>
        </div>
      ) : null}
      <div class={`flex flex-col gap-2${showHeader ? ' mt-4' : ''}`}>
        {y.rows.map((r, i) => (
          <div class={ROW} key={`${r.date}-${r.head}-${i}`}>
            <span class={`font-mono text-xs ${text('60')} tabular-nums whitespace-nowrap`}>{r.date}</span>
            <span class="text-sm min-w-0 break-words">{r.head}</span>
            <span class="font-mono text-sm tabular-nums text-right">{rupee(r.amt)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

/** One receipt: summary line, narration + copyable voucher inside (fees.html §3). */
function Receipt({ e, first }: { e: FeeReceipt; first: boolean }) {
  return (
    <details class={first ? 'collapse collapse-arrow fees-rcpt' : 'collapse collapse-arrow fees-rcpt border-t border-base-300'}>
      <summary class={`collapse-title ${ROW} text-sm min-h-0 py-1.5`}>
        <span class={`font-mono text-xs ${text('60')} tabular-nums whitespace-nowrap`}>{e.date}</span>
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
 * Returns the same blocks in the same order the server painted them; the mount
 * point is the `#tab-fees` panel itself, so there is no wrapper element (the
 * P6.3 lesson: a wrapper nests a level the CSS does not expect).
 *
 * The page chrome (navbar, dock, modals, the sync caption) is NOT here: it stays
 * server markup, and returning only these nodes is what keeps hydration a pure
 * repaint. Everything runs inside the boundary's try, so a bad prop throws there
 * and the server's markup is restored — nothing may defer work to useEffect.
 */
export default function FeesPanel({ el, props }: FeesHost) {
  markHydrated(el);
  const p = props as FeesProps;
  return (
    <>
      {p.dues.length ? (
        <>
          {p.due_sum ? (
            <div class="flex items-baseline justify-between gap-3 mb-3">
              <span class="text-sm font-semibold">Owed</span>
              <span class={`${HERO} ${p.level}`.trim()}>{rupee(p.due_sum)}</span>
            </div>
          ) : null}
          <div class="flex flex-col gap-3">
            {p.dues.map((d, i) => (
              <Charge key={`${d.head}-${i}`} d={d} />
            ))}
          </div>
          <p class={`text-xs ${text('60')} mt-3`}>Pay through the SRM portal.</p>
        </>
      ) : p.years.length ? (
        <p class={`text-sm ${text('60')}`}>Nothing due.</p>
      ) : null}
      {p.years.length ? (
        /* a card, like every other block on the page: bare rows on the page
           background read as an unfinished list (§4.19) */
        <div class={`${CARD}${p.dues.length ? ' mt-6' : ' mt-4'}`}>
          <div class="flex items-baseline justify-between gap-3">
            <h1 class="text-base font-semibold">
              Paid
              {p.year_label ? <span class={`font-mono text-xs font-normal ${text('60')}`}> {p.year_label}</span> : null}
            </h1>
            <span class="font-mono text-sm font-semibold tabular-nums">{rupee(p.paid_total)}</span>
          </div>
          <div class="flex flex-col gap-5 mt-4">
            {p.years.map((y) => (
              <Year key={y.year} y={y} showHeader={p.multi_year} />
            ))}
          </div>
        </div>
      ) : p.dues.length ? (
        <p class={`text-xs ${text('50')} mt-4`}>No payments recorded yet.</p>
      ) : null}
      {p.ledger.length ? (
        <details class={`collapse collapse-arrow bg-base-200 border border-base-300 rounded-box${p.years.length || p.dues.length ? ' mt-6' : ''}`}>
          <summary class="collapse-title text-sm font-semibold">
            Payment receipts <span class={`font-mono ${text('60')} tabular-nums`}>({p.ledger.length})</span>
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
