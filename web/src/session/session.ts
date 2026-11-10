import { SCHEMA_VERSION, db, wipeAll, writeMeta } from '../db';
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
const NETID_RE = /^[a-z0-9]{2,20}$/;

/** Remember which student this device belongs to, so an OFFLINE boot can read
 *  their rows. The shell is deliberately PII-free — it carries no
 *  `data-netid` — which is exactly right for the HTTP cache but leaves the app
 *  with no cache key when the server is unreachable. So the netid is kept in
 *  Dexie's `meta` store instead: device-local, alongside the rows it keys, and
 *  cleared by the same logout wipe. It never leaves the device. */
async function rememberNetid(n: string): Promise<void> {
  try {
    const existing = await db.meta.get(n);
    // Two rows-invariant rules, both learned the hard way:
    //  * `last_sync` must NOT be emptied. evictOldest() picks its victim with
    //    Math.min(...Object.values(last_sync)); on an empty object that is
    //    Infinity, so a row written with `last_sync: {}` becomes the permanent
    //    eviction victim and the first quota retry wipes the cache.
    //  * A row must still EXIST, or an offline boot has no netid to key the
    //    cache with (that was the "(none)" above).
    // So: seed one panel's timestamp — truthful, since this runs after the
    // page has the student's session — and keep every other field as found.
    const seed = existing?.last_sync && Object.keys(existing.last_sync).length
      ? existing.last_sync
      : { session: Date.now() };
    await writeMeta({
      netid: n,
      last_sync: seed,
      schemaVersion: existing?.schemaVersion ?? SCHEMA_VERSION,
      flags: { ...(existing?.flags ?? {}), owner: true },
    });
  } catch {
    // meta is best-effort: a failure only costs the offline cache key.
  }
}

/** Recover the remembered netid on an offline boot. Returns it only when
 *  exactly one student is remembered — two means a shared device, and guessing
 *  would hand one student another's rows. */
async function recallNetid(): Promise<string | undefined> {
  try {
    const metas = await db.meta.toArray();
    const ids = metas.map((m) => m.netid).filter((n) => typeof n === 'string' && NETID_RE.test(n));
    return ids.length === 1 ? ids[0] : undefined;
  } catch {
    return undefined;
  }
}

export function bootstrapSession(doc: Document = document): string | undefined {
  const raw = doc.body?.dataset.netid ?? '';
  const clean = raw.trim().toLowerCase();
  // Same grammar the server validates (app/app.py): lowercase alnum, 2-20.
  if (NETID_RE.test(clean)) {
    setNetid(clean);
    void rememberNetid(clean);
    return netid;
  }
  setNetid(undefined);
  return netid;
}

/** Async boot for the case the sync path cannot cover: a SHELL page (offline,
 *  or served from the SW) carries no `data-netid`, so the sync bootstrap above
 *  finds nothing and every island would read the cache with no key. This falls
 *  back to the remembered netid. Safe by construction: it only returns when
 *  exactly one student is remembered, and it is the same key the rows use. */
export async function bootstrapSessionOffline(doc: Document = document): Promise<string | undefined> {
  const sync = bootstrapSession(doc);
  if (sync) return sync;
  const remembered = await recallNetid();
  console.warn(`[boot] shell page: remembered netid = ${remembered ?? '(none)'}`);
  if (remembered) setNetid(remembered);
  // The per-group stores need their key too; without it the cache read misses
  // even though the rows are present (this is what made offline "work" but
  // paint nothing).
  recalledGroupKey = await recallGroupKey();
  return remembered;
}

/** Group key for the per-group stores (timetable/attendance/marks). Absent in
 *  the page today, so every per-group read uses the '' bucket the server writes
 *  until a page emits one — read here, never invented by a call site. */
/** Group key recovered from the last online boot, for a SHELL page.
 *  Same reason as the netid: the per-group stores are keyed `[netid, groupKey]`,
 *  so an offline read with the wrong key is a cache miss even though the rows
 *  are sitting right there. Remembered next to the netid in `meta`. */
let recalledGroupKey = '';

export function sessionGroupKey(doc: Document = document): string {
  const live = (doc.body?.dataset.groupKey ?? '').trim();
  if (live) {
    if (live !== recalledGroupKey) {
      recalledGroupKey = live;
      void rememberGroupKey(live);
    }
    return live;
  }
  return recalledGroupKey;
}

async function rememberGroupKey(gk: string): Promise<void> {
  try {
    const metas = await db.meta.toArray();
    const owner = metas.length === 1 ? metas[0] : undefined;
    if (!owner) return;                      // ambiguous device: store nothing
    await writeMeta({
      ...owner,
      flags: { ...(owner.flags ?? {}), groupKey: gk },
    });
  } catch {
    // best-effort, same as the netid
  }
}

async function recallGroupKey(): Promise<string> {
  try {
    const metas = await db.meta.toArray();
    if (metas.length !== 1) return '';
    const gk = metas[0]?.flags?.['groupKey'];
    return typeof gk === 'string' ? gk : '';
  } catch {
    return '';
  }
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
