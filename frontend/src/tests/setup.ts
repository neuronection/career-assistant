import "@testing-library/jest-dom/vitest";

import { initI18n } from "@/lib/i18n";

void initI18n();

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
Element.prototype.scrollTo = Element.prototype.scrollTo ?? (() => {});

if (typeof window.matchMedia === "undefined") {
  window.matchMedia = () =>
    ({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }) as never;
}
