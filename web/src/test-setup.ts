/**
 * jsdom shims for APIs the official blobatar gaze driver expects.
 *
 * Kept to the two things it actually reads. `matchMedia` decides whether to
 * drive the eyes at all (reduced motion wins), and `ResizeObserver` re-measures
 * on layout change. jsdom ships neither, and without the shim every test that
 * mounts an avatar throws out of a timer long after its assertions passed.
 */
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

if (!window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof window.ResizeObserver;
}
