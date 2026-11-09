import { ageCaption } from '../lib/syncAge';

/**
 * P7.2 — staleness caption for a cache-served island.
 *
 * One implementation for every panel: the island mounts from the cache, this
 * appends the age beneath the mount so the user can tell "this is what we had
 * at 09:12" from "this is live". Reuses syncAge's ageCaption rather than a
 * second formatter, so the wording stays identical to the sync-line caption.
 *
 * Returns the created element (or null when there is nothing to say) so the
 * caller can remove it again on a fresh load.
 */
export const STALE_ATTR = 'data-island-stale';

/**
 * `fetchedAt` arrives in MILLISECONDS (load.ts writes `Date.now()`), but
 * `ageCaption(ts, nowS)` takes SECONDS. Converting here, once, is what makes
 * the caption appear at all: passing ms straight through made the difference
 * negative, which reads as "fresh" inside FRESH_S, so every stale panel
 * silently rendered no caption. Its old test fed pre-converted seconds and so
 * could not see this.
 */
export function showStale(el: HTMLElement, fetchedAt: number, nowS: number): HTMLElement | null {
  removeStale(el);
  const fetchedS = fetchedAt > 1e12 ? Math.floor(fetchedAt / 1000) : fetchedAt;
  const caption = ageCaption(fetchedS, nowS);
  // ageCaption returns '' inside FRESH_S: a fresh payload needs no label.
  if (!caption) return null;

  const span = document.createElement('span');
  span.setAttribute(STALE_ATTR, '');
  span.setAttribute('aria-live', 'polite');
  span.className = 'block text-[11px] text-base-content/50 leading-5 mt-1';
  span.textContent = `as of ${caption.replace(/^\(|\)$/g, '')}`;

  // Sibling, not child: the island's own children are replaced on re-mount,
  // and the caption must survive that (it is about the mount, not inside it).
  el.insertAdjacentElement('afterend', span);
  return span;
}

/**
 * Remove ONLY the caption this mount owns. Looking up `[data-island-stale]`
 * on the parent finds the FIRST caption in the whole panel — so one island
 * refreshing would delete a different island's caption. The caption is
 * inserted immediately after `el`, so only that immediate sibling counts.
 */
export function removeStale(el: HTMLElement): void {
  const next = el.nextElementSibling;
  if (next && next.hasAttribute(STALE_ATTR)) next.remove();
}
