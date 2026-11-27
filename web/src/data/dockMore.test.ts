import { describe, expect, it, beforeEach } from 'vitest';
import { bindDockMore, isOpen, setOpen, SHEET_ID, TRIGGER_ID, MARKER } from './dockMore';

/** The markup bindDockMore expects: a sheet with an inner wrapper + a trigger. */
function mount(): void {
  document.body.innerHTML = `
    <div id="${SHEET_ID}"><div class="inner"><a href="/fees">Fees</a></div></div>
    <div class="dock"><a href="/">Home</a><button id="${TRIGGER_ID}">More</button></div>`;
  delete (window as unknown as Record<string, unknown>)[MARKER];
}

const sheet = (): HTMLElement => document.getElementById(SHEET_ID)!;
const trigger = (): HTMLElement => document.getElementById(TRIGGER_ID)!;

describe('dock More sheet', () => {
  beforeEach(mount);

  it('binds and starts closed', () => {
    expect(bindDockMore(document)).toBe(true);
    expect(isOpen(sheet())).toBe(false);
    expect(trigger().getAttribute('aria-expanded')).toBe('false');
  });

  it('returns false when the document has no dock (desktop)', () => {
    document.body.innerHTML = '<main>no dock here</main>';
    expect(bindDockMore(document)).toBe(false);
  });

  it('toggles on trigger click and sets aria-expanded', () => {
    bindDockMore(document);
    trigger().click();
    expect(isOpen(sheet())).toBe(true);
    expect(trigger().getAttribute('aria-expanded')).toBe('true');
    trigger().click();
    expect(isOpen(sheet())).toBe(false);
  });

  it('closed sheet is inert, open sheet is not', () => {
    bindDockMore(document);
    const inner = sheet().firstElementChild as HTMLElement;
    expect(inner.hasAttribute('inert')).toBe(true);
    trigger().click();
    expect(inner.hasAttribute('inert')).toBe(false);
  });

  it('Escape closes and returns focus to the trigger', () => {
    bindDockMore(document);
    trigger().click();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(isOpen(sheet())).toBe(false);
    expect(document.activeElement).toBe(trigger());
  });

  it('a click outside the sheet and trigger closes it', () => {
    bindDockMore(document);
    trigger().click();
    document.body.click();
    expect(isOpen(sheet())).toBe(false);
  });

  it('a click inside the sheet does NOT close it (the row handler does)', () => {
    bindDockMore(document);
    trigger().click();
    (sheet().querySelector('a') as HTMLElement).dispatchEvent(
      new MouseEvent('click', { bubbles: true }),
    );
    // the row itself closes on navigate; the delegated outside-close must not
    // be what fired, so a bare span click inside stays open
    setOpen(sheet(), trigger(), true);
    (sheet().querySelector('.inner') as HTMLElement).click();
    expect(isOpen(sheet())).toBe(true);
  });

  it('a row click closes the sheet', () => {
    bindDockMore(document);
    trigger().click();
    (sheet().querySelector('a') as HTMLElement).click();
    expect(isOpen(sheet())).toBe(false);
  });

  it('closes on osrm:route-swapped', () => {
    bindDockMore(document);
    trigger().click();
    document.dispatchEvent(new Event('osrm:route-swapped'));
    expect(isOpen(sheet())).toBe(false);
  });

  it('is idempotent: a second bind does not stack a second toggle', () => {
    bindDockMore(document);
    bindDockMore(document);
    trigger().click();
    expect(isOpen(sheet())).toBe(true);   // one toggle, not open-then-closed
  });
});
