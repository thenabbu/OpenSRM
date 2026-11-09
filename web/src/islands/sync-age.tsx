import type { HostProps } from './contract';
import type { SyncAgeProps } from './contract';
import { ageCaption } from '../lib/syncAge';

export interface SyncAgeHost extends HostProps {
  props: SyncAgeProps;
}

/** The in-flight caption dash.js writes (ref()); live state, not an age. */
const SYNCING = 'Syncing…';
/** Client-only marker: tests and CSS key off it, the server never writes it. */
export const HYDRATED_ATTR = 'data-hydrated';

/**
 * The navbar sync caption, hydrated. The server painted identical text and
 * classes (app/views/sync_age.py), so the first paint here changes nothing.
 * What hydration ADDS: the caption re-ages itself every 60s and stamps
 * `data-hydrated` — evidence only a mounted island can produce. Returns null
 * and drives the existing span, so Preact never deletes or re-creates nodes
 * the server owns (no flash, no focus loss, no layout shift).
 */
export default function SyncAge({ el, props }: SyncAgeHost) {
  // main.ts's mountBounded clears the mount BEFORE rendering (render() alone
  // only appends), and it captured the server's child nodes first, so a throw
  // still restores them. Do not rely on Preact emptying anything for you.
  const paint = (): void => {
    if (el.textContent === SYNCING) return;   // a refresh is in flight: not ours
    const text = props.busy ?? ageCaption(props.ts, Date.now() / 1000);
    el.textContent = text;
    el.classList.toggle('hidden', !text);
    el.title = props.full;
  };
  paint();
  el.setAttribute(HYDRATED_ATTR, '1');
  // one timer per mount; lives as long as the page (re-mounts are guarded by
  // data-hydrated in main.ts)
  window.setInterval(paint, 60_000);
  return null;
}
