import { act, useRef, type RefObject } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { useMainScrollRestoration } from "@/hooks/useMainScrollRestoration";
import { resetScrollJournal } from "@/lib/scrollJournal";

let scroller: HTMLElement | null = null;
let scrollTop = 0;

function Harness() {
  const navigate = useNavigate();
  const location = useLocation();
  const mainRef = useRef<HTMLDivElement | null>(null);
  useMainScrollRestoration(mainRef as unknown as RefObject<HTMLElement | null>);
  return (
    <div>
      <div ref={mainRef} data-testid="scroller">
        {location.pathname}
      </div>
      <button onClick={() => navigate("/detail")}>push-detail</button>
      <button onClick={() => navigate(-1)}>history-back</button>
      <button onClick={() => navigate("/list", { state: { listReturn: true } })}>
        list-return
      </button>
      <button onClick={() => navigate("/list", { replace: true })}>replace-list</button>
    </div>
  );
}

describe("useMainScrollRestoration (plan 172)", () => {
  beforeEach(() => {
    resetScrollJournal();
    scrollTop = 0;
    scroller = null;
  });

  afterEach(() => {
    if (scroller) {
      delete (scroller as unknown as { scrollTop?: number }).scrollTop;
    }
  });

  function renderHarness() {
    const { baseElement } = render(
      <MemoryRouter initialEntries={["/list"]}>
        <Routes>
          <Route path="*" element={<Harness />} />
        </Routes>
      </MemoryRouter>,
      { baseElement: document.body }
    );
    scroller = baseElement.querySelector<HTMLElement>('[data-testid="scroller"]')!;
    Object.defineProperty(scroller, "scrollTop", {
      configurable: true,
      get: () => scrollTop,
      set: (value: number) => {
        scrollTop = value;
      },
    });
    return scroller;
  }

  it("a fresh PUSH scrolls to top, POP restores, list-return PUSH restores", () => {
    const el = renderHarness();

    act(() => {
      scrollTop = 500;
      fireEvent.scroll(el);
    });

    act(() => {
      fireEvent.click(screen.getByText("push-detail"));
    });
    expect(screen.getByTestId("scroller")).toHaveTextContent("/detail");
    expect(scrollTop).toBe(0);

    act(() => {
      scrollTop = 300;
      fireEvent.scroll(el);
    });

    act(() => {
      fireEvent.click(screen.getByText("history-back"));
    });
    expect(screen.getByTestId("scroller")).toHaveTextContent("/list");
    expect(scrollTop).toBe(500);

    act(() => {
      fireEvent.click(screen.getByText("push-detail"));
    });
    expect(scrollTop).toBe(0);

    act(() => {
      fireEvent.click(screen.getByText("list-return"));
    });
    expect(screen.getByTestId("scroller")).toHaveTextContent("/list");
    expect(scrollTop).toBe(500);
  });

  it("REPLACE navigation never moves the scroll", () => {
    const el = renderHarness();

    act(() => {
      scrollTop = 420;
      fireEvent.scroll(el);
    });

    act(() => {
      fireEvent.click(screen.getByText("push-detail"));
    });
    expect(scrollTop).toBe(0);

    act(() => {
      scrollTop = 260;
    });

    act(() => {
      fireEvent.click(screen.getByText("replace-list"));
    });
    expect(screen.getByTestId("scroller")).toHaveTextContent("/list");
    expect(scrollTop).toBe(260);
  });
});
