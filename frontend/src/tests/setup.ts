import "@testing-library/jest-dom/vitest";

afterEach(() => {
  localStorage.clear();
});

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

global.ResizeObserver = global.ResizeObserver ?? (ResizeObserverStub as never);

Element.prototype.hasPointerCapture =
  Element.prototype.hasPointerCapture ?? (() => false);
Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => {});
Element.prototype.setPointerCapture =
  Element.prototype.setPointerCapture ?? (() => {});

if (typeof window.matchMedia === "undefined") {
  window.matchMedia = () =>
    ({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }) as never;
}
