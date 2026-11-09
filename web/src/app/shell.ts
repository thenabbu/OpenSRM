/**
 * P7.4 — the offline app shell.
 *
 * The service worker deliberately refuses to cache HTML (a cached page holds
 * attendance, marks and PII, and cannot be bound to the current session on a
 * shared profile — app/static/sw.js, "HTML pages" branch). So an offline
 * navigation gets that generic 503 page and the app never mounts: the islands
 * read `/api/<panel>` on mount, which Dexie can only answer if something
 * rendered them.
 *
 * This is that something. When a panel island reads nothing but an `offline`
 * failure (`loadPanel` already consulted the cache), the shell paints a
 * skeleton — SAME mount role, attributes and class — from the cached envelope
 * stored in `meta`, and boots the normal island bootstrap on it. The read path
 * then runs again, hits the cache (it was a timed-out network attempt, not a
 * missing one), and paints. One bootstrap, one read path.
 *
 * `dumb user test` bar: no retry here, no second fetch, no new module.
 */
import type { Panel } from '../db';
import { readPanel } from '../db';

export const SHELL_ATTR = 'data-shell';
const NETID_ATTR = 'netid';
const UA_ATTR = 'ua';

/** Role, attributes and class copied from the real mount point (the panel
 *  <div> or the <div class="card"> around it). */
export type ShellAttrs = { role: string | null; attrs: [string, string][]; className: string };

type Envelope = {
  shell: ShellAttrs;
  html: string;
  student: string;
  cortex: string;      // class for <body>, so sizing rules still match
};

/** `userAgent` is stored too: it is what tells a clean switch (another device)
 *  from a same-UA render diff (the code moved). Painter: `data-shell="renders"`. */
export function shellData(s: ShellAttrs, html: string, student = '',
                          cortex = '', ua = ''): Record<string, string> {
  return {
    [SHELL_ATTR]: 'renders',
    [NETID_ATTR]: '',
    ...(student ? { student } : {}),
    ...(cortex ? { cortex } : {}),
    ...(ua ? { [UA_ATTR]: ua } : {}),
    'data-html': html,
  };
}

// ── Writer: page-side, called from the island bootstrap (loader.ts) after a
// successful read. Stores the envelope under `meta`, so the shell survives a
// logout wipe (in progress) or a schema bump (a later card's problem).
export type Shell = { mount: HTMLElement };
export type ShellRepeat = { attrs: ShellAttrs; html: string; student: string }; 

/** What a successful render should leave behind: the mount's role + attrs
 *  (readable at boot: no interaction has touched them yet), the serialized
 *  body minus its script tags, our student name, and — implicitly, above —
 *  the netid currently held. `writes`/`writesMarks` never patch a written
 *  envelope's format; that is a schema bump and belongs to a Dexie version. */
export const SHELL_VERSION = 1;

export type ShellEnvelope = {
  v: typeof SHELL_VERSION;
  shell: ShellAttrs;
  html: string;
  student: string;
  cortex: string;
  ua: string;
};

/**
 * Build the envelope from the live page. The body is captured BEFORE the
 * islands hydrate (the bootstrap's capture step runs in the same tick), so a
 * `<div data-island>` in the HTML is a bare mount, exactly what the shell
 * repaints and re-hydrates.
 */
export function captureBody(doc: Document): string {
  const body = doc.body.cloneNode(true) as HTMLElement;
  for (const s of Array.from(body.querySelectorAll('script'))) s.remove();
  return body.innerHTML;
}

export const recordShell = (netid: string, env: ShellEnvelope): Promise<void> =>
  writeMeta(netid, { [SHELL_STORE_KEY]: env });

export const SHELL_STORE_KEY = 'shell';

// ── Reader: shell-side. Only `offline` hands over: unauthenticated, not_found,
// http and invalid are answers, not absences, and the shell must not invent a
// page for them (a logged-out browser gets signed back in, not shown data).
export const isOffline = (reason: string) => reason === 'network';

export async function shellFromCache(netid: string): Promise<ShellEnvelope | undefined> {
  const env = await readMetaEnvelope(netid);
  return env && env.v === SHELL_VERSION && env.html ? env : undefined;
}

// ── The one DB touch, kept in DB-land (db.ts owns Dexie; this module must not).
import { readMeta, writeMeta } from '../db/meta';
const readMetaEnvelope = async (netid: string) =>
  (await readMeta<ShellEnvelope>(netid, SHELL_STORE_KEY)) ?? undefined;
export type { Panel };
export type MetaShell = ShellEnvelope;
