import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  PULL_THRESHOLD,
  SPRING_MS,
  bindPullToRefresh,
  dialogOpen,
  excludedRegion,
  refreshRunning,
  rubberBand,
} from './pullToRefresh';

// W5.4e ported the four pull.js rows. One describe block per matrix row, named
// the way the matrix names it: each block is the check that fails if the port
// is removed. The end-to-end gesture (real browser, coarse pointer) lives in
// tests/e2e/test_pull_dut.py — that one, not this file, is what catches a
// double-fire, because only it counts actual POST /api/refresh.

const fresh = (): Document => document.implementation.createHTMLDocument('pull');

type WinOpts = { coarse?: boolean; scrolled?: number; reduced?: boolean };
const fakeWin = (o: WinOpts = {}): Window =>
  ({
    matchMedia: (q: string) => ({
      matches: q.includes('pointer: coarse') ? !!o.coarse : !!o.reduced,
    }),
    scrollY: o.scrolled ?? 0,
  }) as unknown as Window;

const touch = (
  doc: Document,
  type: string,
  y: number,
  target: EventTarget = doc.body,
): void => {
  const e = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(e, 'touches', {
    value: type === 'touchend' || type === 'touchcancel' ? [] : [{ clientY: y }],
  });
  target.dispatchEvent(e);
};

/** A coarse-pointer page with the gesture bound and its refresh counted. */
const page = (o: WinOpts = { coarse: true }) => {
  const doc = fresh();
  const win = fakeWin(o);
  const refresh = vi.fn();
  bindPullToRefresh(doc, win, refresh);
  return { doc, win, refresh };
};

const pull = (doc: Document, from: number, to: number): void => {
  touch(doc, 'touchstart', from);
  touch(doc, 'touchmove', to);
};

afterEach(() => {
  vi.useRealTimers();
});

// ── pull-refresh-gesture ──────────────────────────────────────────────────
describe('pull-refresh-gesture', () => {
  it('tracks the finger with the rubber band and moves the body by transform', () => {
    const { doc } = page();
    pull(doc, 100, 300);
    // raw 200 -> 200 * (1 - e^(-200/120)) = ~162.3
    expect(rubberBand(200)).toBeCloseTo(162.3, 0);
    expect(doc.body.style.transform).toBe(`translateY(${rubberBand(200)}px)`);
  });

  it('release past the threshold fires the refresh exactly once, with quiet=false', () => {
    const { doc, refresh } = page();
    pull(doc, 100, 300);
    touch(doc, 'touchend', 300);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(refresh).toHaveBeenCalledWith(false);
  });

  it('release below the threshold springs back and fires nothing', () => {
    vi.useFakeTimers();
    const { doc, refresh } = page();
    pull(doc, 100, 150);                       // ~17px effective
    expect(rubberBand(50)).toBeLessThan(PULL_THRESHOLD);
    touch(doc, 'touchend', 150);
    expect(refresh).not.toHaveBeenCalled();
    expect(doc.body.style.transform).toBe('translateY(0)');
    vi.advanceTimersByTime(SPRING_MS);
    expect(doc.body.style.transform).toBe('');
  });

  it('a SECOND touchend does not fire a second refresh (double-fire guard)', () => {
    const { doc, refresh } = page();
    pull(doc, 100, 300);
    touch(doc, 'touchend', 300);
    touch(doc, 'touchend', 300);
    touch(doc, 'touchcancel', 300);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('never binds on a fine pointer (mouse never pulls) and adds no indicator', () => {
    const { doc, refresh } = page({ coarse: false });
    pull(doc, 100, 300);
    touch(doc, 'touchend', 300);
    expect(doc.body.style.transform).toBe('');
    expect(refresh).not.toHaveBeenCalled();
    expect(doc.body.children.length).toBe(0);
  });

  it('ignores a gesture that starts below the top of the page', () => {
    const { doc, refresh } = page({ coarse: true, scrolled: 600 });
    pull(doc, 100, 300);
    touch(doc, 'touchend', 300);
    expect(doc.body.style.transform).toBe('');
    expect(refresh).not.toHaveBeenCalled();
  });

  it('drops the rotation under prefers-reduced-motion, keeps the tracking', () => {
    const { doc } = page({ coarse: true, reduced: true });
    pull(doc, 100, 300);
    const ind = doc.body.lastElementChild as HTMLElement;
    expect(ind.style.transform).toContain('translateY(');
    expect(ind.style.transform).not.toContain('rotate');
  });
});

// ── pull-excluded-regions ─────────────────────────────────────────────────
describe('pull-excluded-regions', () => {
  it('matches a widget scroller, the timetable editor and a draggable', () => {
    const doc = fresh();
    doc.body.innerHTML = `
      <div class="widget-scroll"><span id="a">a</span></div>
      <div id="tt-editor"><span id="b">b</span></div>
      <div draggable="true"><span id="c">c</span></div>
      <p><span id="d">d</span></p>`;
    for (const id of ['a', 'b', 'c']) {
      expect(excludedRegion(doc.getElementById(id)!)).toBe(true);
    }
    expect(excludedRegion(doc.getElementById('d')!)).toBe(false);
    expect(excludedRegion(doc)).toBe(false);
  });

  it('a pull started inside an excluded region moves nothing and fires nothing', () => {
    const { doc, refresh } = page();
    doc.body.innerHTML = '<div class="widget-scroll"><span id="in">x</span></div>';
    const inner = doc.getElementById('in')!;
    touch(doc, 'touchstart', 100, inner);
    touch(doc, 'touchmove', 300, inner);
    expect(doc.body.style.transform).toBe('');
    touch(doc, 'touchend', 300, inner);
    expect(refresh).not.toHaveBeenCalled();
  });
});

// ── pull-dialog-guard ─────────────────────────────────────────────────────
describe('pull-dialog-guard', () => {
  it('detects an open <dialog> and the legacy modal class', () => {
    const doc = fresh();
    expect(dialogOpen(doc)).toBe(false);
    doc.body.innerHTML = '<dialog open></dialog>';
    expect(dialogOpen(doc)).toBe(true);
    doc.body.innerHTML = '<div class="modal-open"></div>';
    expect(dialogOpen(doc)).toBe(true);
    doc.body.innerHTML = '<dialog></dialog>';
    expect(dialogOpen(doc)).toBe(false);
  });

  it('a pull with a dialog open moves nothing and fires nothing', () => {
    const { doc, refresh } = page();
    doc.body.innerHTML = '<dialog open></dialog>';
    pull(doc, 100, 300);
    expect(doc.body.style.transform).toBe('');
    touch(doc, 'touchend', 300);
    expect(refresh).not.toHaveBeenCalled();
  });
});

// ── pull-refresh-running-guard ────────────────────────────────────────────
describe('pull-refresh-running-guard', () => {
  it('detects the spinning icon and both busy button markers', () => {
    const doc = fresh();
    expect(refreshRunning(doc)).toBe(false);
    doc.body.innerHTML = '<button data-refresh></button>';
    expect(refreshRunning(doc)).toBe(false);
    doc.body.innerHTML = '<button data-refresh aria-disabled="true"></button>';
    expect(refreshRunning(doc)).toBe(true);
    doc.body.innerHTML = '<button data-refresh disabled></button>';
    expect(refreshRunning(doc)).toBe(true);
    doc.body.innerHTML = '<button data-refresh></button><i class="refresh-icon animate-spin"></i>';
    expect(refreshRunning(doc)).toBe(true);
  });

  it('a pull while a refresh is already running fires nothing', () => {
    const { doc, refresh } = page();
    doc.body.innerHTML = '<button data-refresh aria-disabled="true"></button>';
    pull(doc, 100, 300);
    touch(doc, 'touchend', 300);
    expect(doc.body.style.transform).toBe('');
    expect(refresh).not.toHaveBeenCalled();
  });
});
