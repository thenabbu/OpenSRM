// app/static/push.js ships UNBUNDLED — Flask serves it from /static/push.js,
// so there is no module to import: the file is read from disk and executed in
// jsdom under the repo's own vitest harness.
//
// The bug this pins down: render() selects the saved lead_minutes on #push-lead
// while a SEPARATE floating promise fills that select starting with
// `innerHTML = ''`. Resolve the fill last and it wipes the selection — the user
// sees "5 minutes" (or blank) while the server still holds "30".
import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// vitest runs with cwd = web/, whose parent is the repo root.
const ROOT = resolve(process.cwd(), '..');
const read = (rel: string) => readFileSync(join(ROOT, rel), 'utf8');
const PUSH_JS = read('app/static/push.js');

// The card as app/templates/settings.html ships it. #push-lead is EMPTY on the
// server — that empty select is half the bug, so the template is asserted too.
const CARD = `
  <div class="card bg-base-200 border border-base-300" id="push-card">
    <div class="card-body p-4 gap-3">
      <h3 class="text-base font-semibold">Notifications</h3>
      <input type="checkbox" id="push-toggle" class="toggle" hidden>
      <p class="text-sm" id="push-state">Loading…</p>
      <div id="push-controls" hidden>
        <label class="flex items-center justify-between gap-3 text-sm" for="push-lead">
          <span>Remind me</span>
          <select id="push-lead" class="select select-sm w-auto"></select>
        </label>
        <div id="push-types" hidden>
          <input type="checkbox" id="push-type-reminders" class="toggle">
          <input type="checkbox" id="push-type-exams" class="toggle">
        </div>
        <button id="push-enable" class="btn btn-accent btn-sm">Enable reminders</button>
        <button id="push-test" class="btn btn-outline btn-sm" hidden>Send</button>
        <p class="text-sm" id="push-feedback" role="status"></p>
      </div>
      <p class="text-sm" id="push-hint" hidden></p>
    </div>
  </div>`;

const SAVED = 30;
const STATUS = {
  ok: true, configured: true, enabled: true, allowlisted: true,
  // no endpoint_hash: the browser/server resync branch is not what is under
  // test here, and skipping it keeps crypto.subtle out of the fixture.
  subscription: { lead_minutes: SAVED, notify_reminders: true, notify_exams: true },
  lead_choices: [5, 10, 15, 30],
};

type Req = { url: string; resolve: (body: unknown) => void };

const settle = async (ticks = 8) => {
  for (let i = 0; i < ticks; i++) await new Promise((r) => setTimeout(r, 0));
};

/** Execute the shipped file in this jsdom, with fetch holding every request. */
function runPushJs() {
  const pending: Req[] = [];
  vi.stubGlobal('fetch', (url: string) =>
    new Promise((resolve) => {
      pending.push({
        url,
        resolve: (body: unknown) =>
          resolve({ status: 200, ok: true, json: async () => body }),
      });
    }),
  );
  vi.stubGlobal('PushManager', class {});
  vi.stubGlobal('Notification', { permission: 'granted' });
  vi.stubGlobal('navigator', {
    userAgent: 'Mozilla/5.0 (X11; Linux x86_64)',
    serviceWorker: { register: async () => REG, ready: Promise.resolve(REG) },
  });
  new Function(PUSH_JS)();
  return pending;
}

const REG = {
  pushManager: {
    getSubscription: async () => ({
      endpoint: 'https://fcm.example/one',
      toJSON: () => ({ endpoint: 'https://fcm.example/one' }),
    }),
  },
};

const lead = () => document.getElementById('push-lead') as HTMLSelectElement;

/**
 * Answer the requests in a chosen order and return the select.
 * 'newest-first' is the pathological order: render()'s own /api/push/status is
 * answered before the option fill, so the fill lands last and re-writes the
 * select. On fixed code that order is unreachable (render is not called at all
 * until the fill resolves) and the driver degrades to newest == only.
 */
async function drive(order: 'newest-first' | 'oldest-first') {
  document.body.innerHTML = CARD;
  const pending = runPushJs();
  for (let guard = 0; guard < 12; guard++) {
    await settle();
    if (!pending.length) break;
    pending.splice(order === 'newest-first' ? pending.length - 1 : 0, 1)[0]!.resolve(STATUS);
  }
  await settle();
  return lead();
}

beforeEach(() => {
  document.body.innerHTML = '';
  vi.unstubAllGlobals();
});

describe('push.js lead-time select', () => {
  it('settings.html ships #push-lead empty (the half of the bug the fix must not rely on)', () => {
    const tpl = read('app/templates/settings.html');
    expect(tpl).toMatch(/<select id="push-lead"[^>]*><\/select>/);
  });

  it('selects the saved lead_minutes when the option fill resolves BEFORE render()', async () => {
    const sel = await drive('oldest-first');
    expect(sel.options.length).toBe(STATUS.lead_choices.length);
    expect(sel.value).toBe(String(SAVED));
  });

  it('selects the saved lead_minutes when the fill resolves AFTER render()', async () => {
    // Fails on the pre-fix file: render() sets .value against an option-less
    // select (no match -> ''), then the fill's innerHTML='' + appendChild
    // leaves the first choice selected while the server holds SAVED.
    const sel = await drive('newest-first');
    expect(sel.options.length).toBe(STATUS.lead_choices.length);
    expect(sel.value).toBe(String(SAVED));
  });
});
