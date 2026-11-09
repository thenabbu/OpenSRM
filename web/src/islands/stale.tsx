import type { ComponentType } from 'preact';
import type { HostProps } from './contract';
import { ageCaption } from '../lib/syncAge';

export interface StaleProps extends HostProps {
  /** fetch stamp (ms) of the data on screen; 0 = never */
  stamp: number;
  /** whether this copy is past STALE_MS */
  stale: boolean;
  /** injectable clock (tests); defaults to the wall clock */
  nowMs?: () => number;
}

/** Client-only marker: tests and the DUT key off it. */
export const STALE_ATTR = 'data-stale';

/**
 * "(${age} ago)" under the panel, only when the data on screen is past
 * STALE_MS. One implementation for every island: main.ts wraps whatever
 * island it mounted in this, so a panel cannot forget the caption and no
 * island gets its own formatting.
 *
 * A fragment at the panel level, a tiny div for the caption: the caption is a
 * SIBLING of the island's own nodes, so an island's `<>…</>` children stay
 * direct children of the mount (the P6.3 rule) and the mount's flex/grid
 * layout gets one more real child — the caption — not a wrapper around all of
 * them.
 *
 * aria-live: the caption is announced when it appears, and that is the only
 * moment it can change (a re-mount replaces it with a different age).
 * syncAge's buckets are ('15m ago')-style; strip the parens and prefix, and
 * fall back to a generic line if the age is too young to bucket (e.g. a row
 * with no stamp, which ageCaption reports as "Never synced").
 */
export function StaleCaption({ stamp, stale, nowMs = Date.now }: Pick<StaleProps, 'stamp' | 'stale' | 'nowMs'>) {
  if (!stale) return null;
  const age = ageCaption(stamp, nowMs() / 1000).replace(/^\((.*)\)$/, '$1').trim();
  return (
    <div class="text-xs" aria-live="polite" {...{ [STALE_ATTR]: '' }}>
      {age ? `as of ${age}` : 'showing a saved copy that may be out of date'}
    </div>
  );
}

/** Wraps an island so its paint carries the staleness caption. Always used
 *  with `stamp`/`stale`: a fresh paint renders no caption at all. */
export default function withStale(Comp: ComponentType<HostProps>): ComponentType<StaleProps> {
  const Wrapped = ({ stamp, stale, nowMs, ...host }: StaleProps) => (
    <>
      <Comp {...host} />
      <StaleCaption stamp={stamp} stale={stale} nowMs={nowMs} />
    </>
  );
  return Wrapped;
}
