import { wipeAll } from '../db';
import { clearShells } from './shell';

/**
 * Session scope: which netid this page is caching against, and what logout
 * must destroy before the server session goes away.
 *
 * There is no `data-netid` in any template and the `srm_session` cookie is an
 * opaque httponly token (app/auth.py:59) — the netid is NOT on the page, so
 * nothing about it may be invented here either. The first client-side code
 * that learns a netid (`loadPanel` under P5.3) calls `setNetid`; logout wipes
 * that value's rows. No setter call = nothing cached under this page session.
 */
let netid: string | undefined;

export const setNetid = (n: string | undefined): void => void (netid = n || undefined);
export const currentNetid = (): string | undefined => netid;

/**
 * Adopt the netid the page was rendered for, from `<body data-netid>`.
 *
 * P7.1: the server now emits it (app/views/layout.py + the template's <body>),
 * and this is the ONLY place it is read. Deliberately NOT from `<title>` or the
 * navbar: those are display strings — a copy edit or a rename there would
 * silently re-key the cache and hand a student another student's rows, or wipe
 * their own. A missing/blank attribute leaves `netid` undefined, which makes
 * `loadPanel` a no-op and the logout wipe a no-op: an unknown owner caches
 * nothing rather than caching against a guess.
 *
 * Returns the netid it adopted, or undefined when the page carried none.
 */
export function bootstrapSession(doc: Document = document): string | undefined {
  const raw = doc.body?.dataset.netid ?? '';
  const clean = raw.trim().toLowerCase();
  // Same grammar the server validates (app/app.py): lowercase alnum, 2-20.
  setNetid(/^[a-z0-9]{2,20}$/.test(clean) ? clean : undefined);
  return netid;
}

/** Group key for the per-group stores (timetable/attendance/marks). Absent in
 *  the page today, so every per-group read uses the '' bucket the server writes
 *  until a page emits one — read here, never invented by a call site. */
export function sessionGroupKey(doc: Document = document): string {
  return (doc.body?.dataset.groupKey ?? '').trim();
}
/** The wipe must never outlive the navigation it blocks. */
export const WIPE_CAP_MS = 1500;

const sanitize = (u: string): string | null => {
  try {
    return new URL(u, location.href).href;
  } catch {
    return null;
  }
};

/**
 * Await a logout wipe, but never longer than `capMs`. Resolves (never rejects)
 * on a hung wipe, a throwing IndexedDB (Safari private mode throws from
 * `indexedDB.open`, and Dexie turns that into a rejected ready promise — which
 * `wipeAll` resolves around), or a missing `indexedDB` entirely.
 */
export async function wipeCapped(netidArg = netid, capMs = WIPE_CAP_MS): Promise<void> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const cap = new Promise<void>((resolve) => {
    timer = setTimeout(resolve, capMs);
  });
  try {
    await Promise.race([wipeAll(netidArg), cap]);
  } catch {
    // wipeAll is already try/catch'd; this is the belt for a non-Dexie throw.
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Idempotent: a second call (double-click, two tabs) sees the same `netid`
 * and finds nothing left to delete.
 *
 * `href` is the link's OWN href and is where navigation goes after the wipe —
 * on this app that is `/logout` (the server drops the session); `/login` is
 * only the default for a caller that has no link. Returns the URL navigation
 * was released to, or `null` when it was not a parseable URL at all.
 */
export async function onLogout(
  href: string = '/login',
  opts: { netid?: string | undefined; navigate?: (u: string) => void } = {},
): Promise<string | null> {
  // Wipe EVERY netid, not just this one. Personal data is allowed to live on
  // the device while a student is logged in — that is what makes offline work —
  // but logout must leave no trace, and on a shared device "no trace" includes
  // a previous student's rows, which a netid-scoped delete would happily keep.
  // Passing undefined is wipeAll's documented "clear every store" branch.
  await wipeCapped(undefined);
  // And the shell cache: offline markup with no PII in it, but a logged-out
  // device should have no trace of the app's cached surfaces either.
  await clearShells();
  const target = sanitize(href);
  if (!target) return null;
  (opts.navigate ?? ((u: string) => location.assign(u)))(target);
  return target;
}

/** Bind the wipe in front of the real logout link. Returns an unbinder. The
 *  <a href> stays as-is: with no JS (or a failed wipe) the browser navigates
 *  normally — progressive enhancement, never a dead button. */
export function wireLogoutLink(
  doc: Document = document,
  navigate: (u: string) => void = (u) => location.assign(u),
): () => void {
  const link = doc.querySelector<HTMLAnchorElement>('a[href="/logout"]');
  if (!link) return () => {};
  const onClick = (e: MouseEvent): void => {
    // let the browser handle new-tab / new-window and modified clicks
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    void onLogout(link.href, { navigate });
  };
  link.addEventListener('click', onClick);
  return () => link.removeEventListener('click', onClick);
}
