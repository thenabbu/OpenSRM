import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  DEL_ERR_CLASS,
  SCOPE_BACKOFF_AFTER,
  SCOPE_DELAY_MS,
  SCOPE_FIRST_DELAY_MS,
  SCOPE_MAX_TRIES,
  SCOPE_SLOW_DELAY_MS,
  SCOPE_STATUS_URL,
  TAG_URL,
  bindDeleteAccount,
  bindDetailsDismiss,
  bindTagSave,
  startScopePoll,
} from './userActions';

// W5.4c ported four dash.js user-actions rows. One describe block per matrix
// row, named the way the matrix names it: each block is the check that fails if
// that row's port is removed.

const fresh = (html = ''): Document => {
  const doc = document.implementation.createHTMLDocument('user');
  doc.body.innerHTML = html;
  return doc;
};

const json = (body: unknown, init: ResponseInit = {}): Response =>
  new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' }, ...init });

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  delete (window as unknown as { __osrmOutbox?: unknown }).__osrmOutbox;
});

// ── dash-marks-tag-save ───────────────────────────────────────────────────
describe('dash-marks-tag-save', () => {
  const page = (): Document =>
    fresh(`
      <form id="tag" method="post" action="/marks/tag">
        <input type="hidden" name="code" value="21CSS201T">
        <input type="hidden" name="component" value="FT-II">
        <select name="role"><option value="IE-2" selected>IE-2</option></select>
      </form>
      <form id="other" method="post" action="/elsewhere"><input name="a" value="1"></form>`);

  it('intercepts the /marks/tag submit, POSTs the fields with Accept: application/json', async () => {
    const doc = page();
    const spy = vi.fn(async () => json({ ok: true }));
    vi.stubGlobal('fetch', spy);
    bindTagSave(doc);

    const ev = new Event('submit', { bubbles: true, cancelable: true });
    doc.getElementById('tag')!.dispatchEvent(ev);

    expect(ev.defaultPrevented).toBe(true);           // no navigation
    await vi.waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    const [url, init] = spy.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(TAG_URL);
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>).Accept).toBe('application/json');
    const sent = init.body as FormData;
    expect(sent.get('code')).toBe('21CSS201T');
    expect(sent.get('role')).toBe('IE-2');
  });

  it('leaves any other form alone', () => {
    const doc = page();
    const spy = vi.fn(async () => json({ ok: true }));
    vi.stubGlobal('fetch', spy);
    bindTagSave(doc);

    const ev = new Event('submit', { bubbles: true, cancelable: true });
    doc.getElementById('other')!.dispatchEvent(ev);

    expect(ev.defaultPrevented).toBe(false);
    expect(spy).not.toHaveBeenCalled();
  });

  it('a rejected tag ({"ok":false}) is an answer: toast, never queued', async () => {
    const doc = page();
    doc.body.setAttribute('data-netid', 'zz9999');
    const queueWrite = vi.fn(async () => 'id');
    (window as unknown as { __osrmOutbox?: unknown }).__osrmOutbox = { queueWrite, startOutbox: vi.fn() };
    document.body.innerHTML = '<div id="error-toast"></div>';
    vi.stubGlobal('fetch', vi.fn(async () => json({ ok: false, error: 'bad tag' })));
    bindTagSave(doc);

    doc.getElementById('tag')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() =>
      expect(document.getElementById('error-toast')!.textContent).toBe('bad tag'),
    );
    expect(queueWrite).not.toHaveBeenCalled();
  });

  it('a TRANSPORT failure with a netid defers the exact fields to the outbox', async () => {
    const doc = page();
    doc.body.setAttribute('data-netid', 'zz9999');
    const queueWrite = vi.fn(async () => 'id');
    const startOutbox = vi.fn(async () => ({}));
    (window as unknown as { __osrmOutbox?: unknown }).__osrmOutbox = { queueWrite, startOutbox };
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('offline');
    }));
    bindTagSave(doc);

    doc.getElementById('tag')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(queueWrite).toHaveBeenCalledTimes(1));
    expect(queueWrite).toHaveBeenCalledWith('zz9999', 'tag', {
      code: '21CSS201T',
      component: 'FT-II',
      role: 'IE-2',
    });
    await vi.waitFor(() => expect(startOutbox).toHaveBeenCalled());
  });
});

// ── dash-delete-account ───────────────────────────────────────────────────
describe('dash-delete-account', () => {
  // <dialog> is the safety property under test: it starts CLOSED, and a closed
  // dialog cannot be clicked. showModal is stubbed because jsdom has no
  // top-layer, but `open` is tracked so the test reads the real flow.
  const page = (): Document => {
    const doc = fresh(`
      <button id="delete-account-btn">Delete my data</button>
      <dialog id="delete-account-modal">
        <div id="del-status"></div>
        <button id="del-confirm">Delete permanently</button>
      </dialog>`);
    const dlg = doc.getElementById('delete-account-modal') as HTMLDialogElement;
    dlg.showModal = function showModal() {
      this.open = true;
    };
    return doc;
  };

  it('opens the dialog on the row click and does NOT POST', () => {
    const doc = page();
    const spy = vi.fn(async () => json({ ok: true }));
    vi.stubGlobal('fetch', spy);
    bindDeleteAccount(doc);

    (doc.getElementById('delete-account-btn') as HTMLElement).click();

    expect((doc.getElementById('delete-account-modal') as HTMLDialogElement).open).toBe(true);
    expect(spy).not.toHaveBeenCalled();
  });

  it('BINDING ALONE NEVER DELETES — the confirm button must be clicked', async () => {
    const doc = page();
    const spy = vi.fn(async () => json({ ok: true }));
    vi.stubGlobal('fetch', spy);
    bindDeleteAccount(doc);

    await new Promise((r) => setTimeout(r, 20));      // any stray boot-time call
    expect(spy).not.toHaveBeenCalled();
    expect((doc.getElementById('del-confirm') as HTMLButtonElement).disabled).toBe(false);
  });

  it('confirm POSTs /api/account/delete once and lands on /login', async () => {
    const doc = page();
    // A followed redirect: the server 302s to /login, so the response the fetch
    // sees has `redirected === true`. jsdom's Response.redirected is a fixed
    // false, so it is stubbed for real-browser fidelity.
    const res = new Response(null, { status: 200 });
    Object.defineProperty(res, 'redirected', { value: true });
    const spy = vi.fn(async () => res);
    vi.stubGlobal('fetch', spy);
    const loc = { href: '/settings' };
    vi.stubGlobal('location', loc);
    bindDeleteAccount(doc);

    (doc.getElementById('delete-account-modal') as HTMLDialogElement).showModal();
    (doc.getElementById('del-confirm') as HTMLElement).click();

    await vi.waitFor(() => expect(loc.href).toBe('/login'));
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy.mock.calls[0][0]).toBe('/api/account/delete');
    expect((spy.mock.calls[0][1] as RequestInit).method).toBe('POST');
  });

  it('a failed delete re-enables the button and says nothing was removed', async () => {
    const doc = page();
    vi.stubGlobal('fetch', vi.fn(async () => json({ ok: false, error: 'boom' }, { status: 500 })));
    const loc = { href: '/settings' };
    vi.stubGlobal('location', loc);
    bindDeleteAccount(doc);

    (doc.getElementById('del-confirm') as HTMLElement).click();

    await vi.waitFor(() =>
      expect((doc.getElementById('del-confirm') as HTMLButtonElement).disabled).toBe(false),
    );
    const status = doc.getElementById('del-status')!;
    expect(status.textContent).toBe('boom');
    expect(status.className).toBe(DEL_ERR_CLASS);
    expect(loc.href).toBe('/settings');               // no navigation on failure
  });

  // Regression: the settings route is reached by a soft navigation, which
  // replaces the DOM. A boot-time bind then sits on detached nodes — the row
  // was inert while a DIRECT load of /settings worked, so this test binds on a
  // route without the row first, swaps the markup in, and binds again.
  it('binds the row a soft-nav swap puts in the document, exactly once per node', async () => {
    const doc = fresh('<div id="route"></div>');
    const spy = vi.fn(async () => json({ ok: true }));
    vi.stubGlobal('fetch', spy);
    const loc = { href: '/settings' };
    vi.stubGlobal('location', loc);

    expect(bindDeleteAccount(doc)).toBe(false);       // boot route has no row

    doc.getElementById('route')!.innerHTML = `
      <button id="delete-account-btn">Delete my data</button>
      <dialog id="delete-account-modal">
        <div id="del-status"></div>
        <button id="del-confirm">Delete permanently</button>
      </dialog>`;
    const dlg = doc.getElementById('delete-account-modal') as HTMLDialogElement;
    dlg.showModal = function showModal() {
      this.open = true;
    };

    expect(bindDeleteAccount(doc)).toBe(true);        // the swapped-in row binds
    expect(bindDeleteAccount(doc)).toBe(true);        // repeat call is a no-op

    (doc.getElementById('delete-account-btn') as HTMLElement).click();
    expect(dlg.open).toBe(true);
    expect(spy).not.toHaveBeenCalled();               // the row alone never deletes

    (doc.getElementById('del-confirm') as HTMLElement).click();
    await vi.waitFor(() => expect(loc.href).toBe('/login'));
    expect(spy).toHaveBeenCalledTimes(1);             // ONE confirm = ONE POST
  });
});

// ── dash-details-dismiss ──────────────────────────────────────────────────
describe('dash-details-dismiss', () => {
  const page = (): Document =>
    fresh(`
      <details id="panel"><summary id="sum">tag</summary><form id="form"></form></details>
      <h3 id="outside">x</h3>`);

  it('closes an open details on an outside click', () => {
    const doc = page();
    bindDetailsDismiss(doc);
    const d = doc.getElementById('panel') as HTMLDetailsElement;
    d.open = true;

    doc.getElementById('outside')!.dispatchEvent(new MouseEvent('click', { bubbles: true }));

    expect(d.open).toBe(false);
  });

  it('ignores clicks inside it, including the summary that toggles it', () => {
    const doc = page();
    // The summary click cannot be asserted on `open`: jsdom's own activation
    // behaviour flips it after dispatch in both documents (measured). What the
    // dismiss OWNS is the decision, so that is what is captured — an outside
    // click closes, an inside click (form or summary) does not.
    const d = doc.getElementById('panel') as HTMLDetailsElement;
    const closes: boolean[] = [];
    doc.addEventListener('click', () => closes.push(d.open));
    d.open = true;
    bindDetailsDismiss(doc);

    doc.getElementById('form')!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(closes).toEqual([true]);                   // touched nothing
    doc.getElementById('sum')!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(closes).toEqual([true, true]);             // summary is inside => ignored
    doc.getElementById('outside')!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(closes).toEqual([true, true, false]);      // outside => closed
  });
});

// ── dash-scope-poll ───────────────────────────────────────────────────────
describe('dash-scope-poll', () => {
  // Own scheduler: the assertions are about the DELAYS, so the test drives the
  // clock itself instead of trusting a timer implementation.
  const driver = () => {
    const pending: Array<{ fn: () => void; ms: number }> = [];
    return {
      schedule: (fn: () => void, ms: number) => {
        pending.push({ fn, ms });
        return 0;
      },
      pending,
      async run(ms: number) {
        const i = pending.findIndex((p) => p.ms === ms);
        expect(i, `no scheduled tick at ${ms}ms (have ${pending.map((p) => p.ms)})`).toBeGreaterThanOrEqual(0);
        const [p] = pending.splice(i, 1);
        p.fn();
        await new Promise((r) => setTimeout(r, 0));
      },
    };
  };

  it('does nothing when the page did not arrive mid-sync', () => {
    const doc = fresh('');
    doc.body.setAttribute('data-scope-sync', 'complete');
    const spy = vi.fn(async () => json({ ok: true, state: 'complete' }));
    const sched = driver();
    startScopePoll(doc, spy as unknown as typeof fetch, vi.fn(), sched.schedule);
    expect(sched.pending).toHaveLength(0);
    expect(spy).not.toHaveBeenCalled();
  });

  it('polls running twice then repaints EXACTLY ONCE on complete, and stops', async () => {
    const doc = fresh('');
    doc.body.setAttribute('data-scope-sync', 'running');
    const spy = vi
      .fn()
      .mockResolvedValueOnce(json({ ok: true, state: 'running' }))
      .mockResolvedValueOnce(json({ ok: true, state: 'running' }))
      .mockResolvedValueOnce(json({ ok: true, state: 'complete' }));
    const repaint = vi.fn(async () => undefined);
    const sched = driver();
    startScopePoll(doc, spy as unknown as typeof fetch, repaint, sched.schedule);

    await sched.run(SCOPE_FIRST_DELAY_MS);            // first attempt
    expect(spy).toHaveBeenCalledTimes(1);
    expect(repaint).not.toHaveBeenCalled();

    await sched.run(SCOPE_DELAY_MS);
    expect(spy).toHaveBeenCalledTimes(2);

    await sched.run(SCOPE_DELAY_MS);
    expect(spy).toHaveBeenCalledTimes(3);
    expect(repaint).toHaveBeenCalledTimes(1);

    expect(sched.pending).toHaveLength(0);            // complete => no next tick
    await sched.run(SCOPE_DELAY_MS).catch(() => {});
    expect(spy).toHaveBeenCalledTimes(3);
  });

  it('stops silently on "off"', async () => {
    const doc = fresh('');
    doc.body.setAttribute('data-scope-sync', 'stale');
    const spy = vi.fn(async () => json({ ok: true, state: 'off' }));
    const repaint = vi.fn();
    const sched = driver();
    startScopePoll(doc, spy as unknown as typeof fetch, repaint, sched.schedule);

    await sched.run(SCOPE_FIRST_DELAY_MS);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(repaint).not.toHaveBeenCalled();
    expect(sched.pending).toHaveLength(0);
  });

  it('backs off to 8 s after the 10th try, and gives up at MAX_TRIES', async () => {
    const doc = fresh('');
    doc.body.setAttribute('data-scope-sync', 'running');
    const spy = vi.fn(async () => json({ ok: true, state: 'running' }));
    const sched = driver();
    startScopePoll(doc, spy as unknown as typeof fetch, vi.fn(), sched.schedule);

    await sched.run(SCOPE_FIRST_DELAY_MS);
    // tries goes 1..10 at the 4 s cadence; the 11th tick schedules 8 s
    while (sched.pending.some((p) => p.ms === SCOPE_DELAY_MS)) {
      await sched.run(SCOPE_DELAY_MS);
    }
    expect(spy).toHaveBeenCalledTimes(SCOPE_BACKOFF_AFTER + 1);
    expect(sched.pending.map((p) => p.ms)).toEqual([SCOPE_SLOW_DELAY_MS]);

    // exhaust the budget: every remaining tick is 8 s, then it stops for good
    for (let i = 0; i < SCOPE_MAX_TRIES + 5 && sched.pending.length; i++) {
      await sched.run(SCOPE_SLOW_DELAY_MS);
    }
    expect(sched.pending).toHaveLength(0);
    expect(spy.mock.calls.at(-1)![0]).toBe(SCOPE_STATUS_URL);
  });
});
