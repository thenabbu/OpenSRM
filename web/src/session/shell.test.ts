import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { warmShells } from './shell';

/**
 * The snapshot cache is netid-keyed, and warming for one student must DELETE
 * every entry belonging to another — that is the only thing stopping a shared
 * phone from serving student A's marks to student B. These checks are the
 * smallest thing that fails if that prune is removed.
 */

const BASE = 'https://osrm.test';
const abs = (p: string): string => new URL(p, BASE).href;

class FakeCache {
  entries = new Map<string, Response>();

  async put(key: string, res: Response): Promise<void> {
    this.entries.set(abs(key), res);
  }

  async match(key: string): Promise<Response | undefined> {
    return this.entries.get(abs(key));
  }

  async delete(key: string): Promise<boolean> {
    return this.entries.delete(abs(key));
  }

  async keys(): Promise<Request[]> {
    return [...this.entries.keys()].map((u) => new Request(u));
  }

  paths(): string[] {
    return [...this.entries.keys()].map((u) => new URL(u).pathname).sort();
  }
}

class FakeCaches {
  caches = new Map<string, FakeCache>();

  async open(name: string): Promise<FakeCache> {
    let c = this.caches.get(name);
    if (!c) {
      c = new FakeCache();
      this.caches.set(name, c);
    }
    return c;
  }

  async delete(name: string): Promise<boolean> {
    return this.caches.delete(name);
  }
}

const PANELS = 9;

let store: FakeCaches;

function stubEnv(netid: string | null, statuses: Record<string, number> = {}): void {
  store = new FakeCaches();
  vi.stubGlobal('caches', store);
  vi.stubGlobal('navigator', { onLine: true, serviceWorker: { controller: {} } });
  document.body.dataset.netid = netid ?? '';
  if (!netid) delete document.body.dataset.netid;
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    const path = new URL(input, BASE).pathname;
    if (path.endsWith('.json')) return new Response('{}', { status: 404 });
    const status = statuses[path] ?? 200;
    return new Response('<html><body>page</body></html>', {
      status,
      headers: { 'content-type': 'text/html; charset=utf-8' },
    });
  }));
}

const snapPaths = (): string[] =>
  (store.caches.get('opensrm-snap') as FakeCache).paths().filter((p) => p !== '/__snap/__owner');

describe('warmShells: the offline snapshot cache', () => {
  beforeEach(() => {
    vi.useRealTimers();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    delete document.body.dataset.netid;
  });

  it(`stores one snapshot per route (${PANELS}) plus the owner record`, async () => {
    stubEnv('zz9999');
    const n = await warmShells();
    expect(n).toBe(PANELS);
    const cache = store.caches.get('opensrm-snap') as FakeCache;
    expect(await (await cache.match('/__snap/__owner'))?.text()).toBe('zz9999');
    expect(snapPaths()).toEqual(expect.arrayContaining([
      '/__snap/zz9999/dashboard',
      '/__snap/zz9999/settings',
    ]));
    expect(snapPaths().every((p) => p.startsWith('/__snap/zz9999/'))).toBe(true);
  });

  it('a second student on the same device REPLACES the first (no mixing)', async () => {
    stubEnv('zz9999');
    await warmShells();
    expect(snapPaths().every((p) => p.startsWith('/__snap/zz9999/'))).toBe(true);

    stubEnv('zz8888');
    await warmShells();
    expect(snapPaths().every((p) => p.startsWith('/__snap/zz8888/'))).toBe(true);
    expect(snapPaths().some((p) => p.startsWith('/__snap/zz9999/'))).toBe(false);
    const cache = store.caches.get('opensrm-snap') as FakeCache;
    expect(await (await cache.match('/__snap/__owner'))?.text()).toBe('zz8888');
  });

  it('bails before touching the network when the page has no netid', async () => {
    stubEnv(null);
    const n = await warmShells();
    expect(n).toBe(0);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('skips a route the server did not render for this student', async () => {
    stubEnv('zz9999', { '/settings': 401 });
    const n = await warmShells();
    expect(n).toBe(PANELS - 1);
    expect(snapPaths()).not.toContain('/__snap/zz9999/settings');
  });
});
