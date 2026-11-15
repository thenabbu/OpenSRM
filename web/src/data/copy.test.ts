import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { bindCopyTargets, copyValue, setupCopyTargets, COPY_ATTRS } from './copy';

// The copy cluster is the page's a11y path: a `[data-copy]` div is mouse-only
// until something gives it role/tabindex and answers Enter/Space. These tests
// pin the four things that would each break it silently:
//   1. the a11y stamps (role/tabindex/title) land, once per node;
//   2. a repaint's FRESH nodes get stamped — the re-arm; without it the settings
//      block goes back to 24 targets / 0 keyboard-operable;
//   3. click, Enter and Space all copy, and Space does not also scroll;
//   4. #copyEmail routes a refused write to the toast instead of looking fine.
//
// Every case gets a NEW Document: bindCopyTargets is idempotent per root (one
// delegate per document, on purpose), so a shared document would let one case's
// handler answer the next case's click and every count below would be wrong.

let writes: string[];
let doc: Document;

const stubClipboard = (): void => {
  writes = [];
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: {
      writeText: (text: string) => {
        writes.push(text);
        return Promise.resolve();
      },
    },
  });
};

const flush = () => new Promise((r) => setTimeout(r, 0));

/** A copy target as the server or an island emits it: value only, no a11y. */
const target = (value: string, text = value): HTMLElement => {
  doc.body.innerHTML = `<div data-copy="${value}">${text}</div>`;
  return doc.querySelector<HTMLElement>('[data-copy]') as HTMLElement;
};

beforeEach(() => {
  doc = document.implementation.createHTMLDocument('copy');
  stubClipboard();
});

afterEach(() => {
  vi.useRealTimers();
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
});

describe('setupCopyTargets', () => {
  it('makes a plain [data-copy] div a keyboard-operable button', () => {
    const el = target('RA2500000000');
    setupCopyTargets(doc);
    expect(el.getAttribute('role')).toBe(COPY_ATTRS.role);
    expect(el.getAttribute('tabindex')).toBe(String(COPY_ATTRS.tabindex));
    expect(el.title).toBe(COPY_ATTRS.title);
    expect(el.classList.contains('cursor-copy')).toBe(true);
  });

  it('is idempotent: a re-arm does not overwrite a title the author set', () => {
    const el = target('x');
    el.title = 'Registration number';
    setupCopyTargets(doc);
    setupCopyTargets(doc);
    expect(el.title).toBe('Registration number');
  });
});

describe('bindCopyTargets', () => {
  it('copies the data-copy value on click and flashes the target', async () => {
    bindCopyTargets(doc);
    // Painted AFTER the bind: the click delegate sits on the document, so it
    // still reaches it — the "no ids to key on" property a repaint relies on.
    const el = target('RA2500000000', 'visible text');
    el.click();
    await flush();
    expect(writes).toEqual(['RA2500000000']);
    expect(el.textContent).toBe('Copied!');
    expect(el.classList.contains('text-success')).toBe(true);
  });

  it('falls back to the element text when data-copy is empty', () => {
    const el = target('', 'the text');
    expect(copyValue(el)).toBe('the text');
  });

  it('restores the original text after the flash', async () => {
    vi.useFakeTimers();
    bindCopyTargets(doc);
    const el = target('v', 'original');
    el.click();
    await vi.advanceTimersByTimeAsync(0);
    expect(el.textContent).toBe('Copied!');
    await vi.advanceTimersByTimeAsync(1200);
    expect(el.textContent).toBe('original');
    expect(el.classList.contains('text-success')).toBe(false);
  });

  it('Enter and Space both copy, and Space is not allowed to also scroll', async () => {
    bindCopyTargets(doc);
    const el = target('RA2500000000');
    const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
    el.dispatchEvent(enter);
    await flush();
    expect(writes).toEqual(['RA2500000000']);
    expect(enter.defaultPrevented).toBe(true);

    const space = new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true });
    el.dispatchEvent(space);
    await flush();
    expect(writes).toEqual(['RA2500000000', 'RA2500000000']);
    expect(space.defaultPrevented).toBe(true);
  });

  it('ignores keys that are not Enter/Space', async () => {
    bindCopyTargets(doc);
    const el = target('v');
    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }));
    await flush();
    expect(writes).toEqual([]);
  });

  it('is idempotent per document: binding twice does not double the copy', async () => {
    bindCopyTargets(doc);
    bindCopyTargets(doc);
    const el = target('once');
    el.click();
    await flush();
    expect(writes).toEqual(['once']);
  });

  it('RE-ARMS on osrm:island-mounted: a repainted node gets the a11y stamps', () => {
    bindCopyTargets(doc);
    // The island replaces the server's node with its own, unstamped markup.
    doc.body.innerHTML = '<div data-copy="fresh">fresh</div>';
    const fresh = doc.querySelector<HTMLElement>('[data-copy]') as HTMLElement;
    expect(fresh.getAttribute('role')).toBeNull();

    doc.dispatchEvent(new CustomEvent('osrm:island-mounted', { detail: 'settings' }));

    expect(fresh.getAttribute('role')).toBe('button');
    expect(fresh.getAttribute('tabindex')).toBe('0');
  });

  it('copies a node that arrived with the repaint (re-arm + delegate together)', async () => {
    bindCopyTargets(doc);
    doc.body.innerHTML = '<div data-copy="post-repaint">v</div>';
    doc.dispatchEvent(new CustomEvent('osrm:island-mounted'));
    const fresh = doc.querySelector<HTMLElement>('[data-copy]') as HTMLElement;
    fresh.click();
    await flush();
    expect(writes).toEqual(['post-repaint']);
  });
});

describe('#copyEmail', () => {
  // showError() writes to the page's real document (that is the contract — the
  // toast is server-rendered there), so these two cases run against the global
  // document instead of the per-test one. bindCopyTargets is idempotent per
  // root, so the second case reuses the first case's delegate rather than
  // stacking a second one.
  const emailButton = (): HTMLElement => {
    doc = document;
    doc.body.innerHTML =
      '<div id="error-toast" class="hidden"></div>' +
      '<button id="copyEmail" data-email="me@example.com"><span>Copy</span></button>';
    bindCopyTargets(doc);
    return doc.getElementById('copyEmail') as HTMLElement;
  };

  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('copies data-email and relabels the inner span', async () => {
    const btn = emailButton();
    btn.click();
    await flush();
    expect(writes).toEqual(['me@example.com']);
    expect(btn.querySelector('span')!.textContent).toBe('Copied!');
  });

  it("toasts 'Copy failed' when the clipboard refuses", async () => {
    const btn = emailButton();
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: () => Promise.reject(new Error('denied')) },
    });
    btn.click();
    await flush();
    const toast = doc.getElementById('error-toast')!;
    expect(toast.textContent).toBe('Copy failed');
    expect(toast.classList.contains('hidden')).toBe(false);
  });

  it("toasts 'Clipboard unavailable' when there is no Clipboard API", () => {
    const btn = emailButton();
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
    btn.click();
    expect(doc.getElementById('error-toast')!.textContent).toBe('Clipboard unavailable');
  });
});
