import { describe, expect, it, beforeEach, vi } from "vitest";
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { DevMenu } from "@/components/DevMenu";
import { useDevModeStore, resetDevMode } from "@/stores/devModeStore";

describe("devModeStore", () => {
  beforeEach(() => {
    window.localStorage.clear();
    resetDevMode();
    vi.useFakeTimers();
  });

  it("starts locked", () => {
    expect(useDevModeStore.getState().enabled).toBe(false);
  });

  it("unlocks after 5 taps within the window and persists", () => {
    const store = useDevModeStore.getState();
    for (let i = 0; i < 5; i += 1) {
      act(() => {
        store.tap();
        vi.advanceTimersByTime(300);
      });
    }
    expect(useDevModeStore.getState().enabled).toBe(true);
    expect(window.localStorage.getItem("career.dev-mode")).toBe("1");
  });

  it("resets the tap streak when the window expires", () => {
    const store = useDevModeStore.getState();
    for (let i = 0; i < 4; i += 1) {
      act(() => {
        store.tap();
        vi.advanceTimersByTime(300);
      });
    }
    act(() => {
      vi.advanceTimersByTime(3000);
      store.tap();
      vi.advanceTimersByTime(300);
      store.tap();
    });
    expect(useDevModeStore.getState().enabled).toBe(false);
    act(() => {
      store.tap();
      vi.advanceTimersByTime(300);
      store.tap();
      vi.advanceTimersByTime(300);
      store.tap();
    });
    expect(useDevModeStore.getState().enabled).toBe(true);
  });

  it("locks again and clears persistence", () => {
    const store = useDevModeStore.getState();
    act(() => {
      for (let i = 0; i < 5; i += 1) store.tap();
    });
    act(() => {
      useDevModeStore.getState().disable();
    });
    expect(useDevModeStore.getState().enabled).toBe(false);
    expect(window.localStorage.getItem("career.dev-mode")).toBeNull();
  });
});

describe("DevMenu", () => {
  beforeEach(() => {
    vi.useRealTimers();
    window.localStorage.clear();
    resetDevMode();
  });

  it("lists no pages while locked", () => {
    render(<DevMenu />, { wrapper: MemoryRouter });
    fireEvent.click(screen.getByTestId("dev-menu-trigger"));
    expect(screen.getByTestId("dev-menu")).toHaveTextContent(/dev mode is locked/i);
    expect(screen.queryByText("Postings")).not.toBeInTheDocument();
  });

  it("lists in-dev pages and navigates when unlocked", async () => {
    act(() => {
      for (let i = 0; i < 5; i += 1) useDevModeStore.getState().tap();
    });
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<div data-testid="home" />} />
          <Route path="/postings" element={<div data-testid="postings-target" />} />
          <Route path="/autopilot" element={<div data-testid="autopilot-target" />} />
          <Route path="/interviews" element={<div data-testid="interviews-target" />} />
          <Route path="/growth" element={<div data-testid="growth-target" />} />
        </Routes>
        <DevMenu />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId("dev-menu-trigger"));
    expect(screen.getByTestId("dev-menu-item-postings")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("dev-menu-item-postings"));
    await waitFor(() => {
      expect(screen.getByTestId("postings-target")).toBeInTheDocument();
    });
  });

  it("locks again from the popover", () => {
    act(() => {
      for (let i = 0; i < 5; i += 1) useDevModeStore.getState().tap();
    });
    render(<DevMenu />, { wrapper: MemoryRouter });
    fireEvent.click(screen.getByTestId("dev-menu-trigger"));
    fireEvent.click(screen.getByTestId("dev-menu-lock"));
    expect(useDevModeStore.getState().enabled).toBe(false);
    expect(window.localStorage.getItem("career.dev-mode")).toBeNull();
  });
});
