import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";

import {
  MappingManagementSection,
  MAPPING_VIEWS,
  parseMappingView,
} from "@/components/settings/MappingManagementSection";

vi.mock("@/api/mappings", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/mappings")>();
  return {
    ...actual,
    fetchMappingsOverview: vi.fn().mockResolvedValue({
      active: 0,
      last_remap: null,
      legacy_outcome_count: 0,
    }),
    fetchMappingsQueue: vi.fn().mockResolvedValue({ items: [], total: 0, states: {} }),
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="probe">{location.pathname + location.search}</div>;
}

function renderSection(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <MappingManagementSection />
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe("mapping management section shell (plan 205 S1)", () => {
  it("renders the four phase-1 views and lands on overview", () => {
    renderSection("/settings/tools?section=mappings");
    for (const view of MAPPING_VIEWS) {
      expect(
        screen.getByRole("tab", { name: `mappingsConsole.view.${view}` }),
      ).toBeTruthy();
    }
    expect(screen.getByTestId("mappings-view-overview")).toBeTruthy();
    expect(screen.getByTestId("probe").textContent).toBe(
      "/settings/tools?section=mappings",
    );
  });

  it("keeps a bare URL canonical with no rewrite on mount", () => {
    renderSection("/settings/tools?section=mappings");
    expect(screen.getByTestId("probe").textContent).toBe(
      "/settings/tools?section=mappings",
    );
  });

  it("strips an unknown view param back to overview", async () => {
    renderSection("/settings/tools?section=mappings&view=bogus");
    expect(screen.getByTestId("mappings-view-overview")).toBeTruthy();
    await vi.waitFor(() =>
      expect(screen.getByTestId("probe").textContent).toBe(
        "/settings/tools?section=mappings",
      ),
    );
  });

  it("deep-links into triage and switches views through the URL", async () => {
    const user = userEvent.setup();
    renderSection("/settings/tools?section=mappings&view=triage");
    expect(screen.getByTestId("mappings-view-triage")).toBeTruthy();
    await user.click(
      screen.getByRole("tab", { name: "mappingsConsole.view.types-sources" }),
    );
    expect(screen.getByTestId("mappings-view-types-sources")).toBeTruthy();
    expect(screen.getByTestId("probe").textContent).toBe(
      "/settings/tools?section=mappings&view=types-sources",
    );
    await user.click(screen.getByRole("tab", { name: "mappingsConsole.view.overview" }));
    expect(screen.getByTestId("mappings-view-overview")).toBeTruthy();
    expect(screen.getByTestId("probe").textContent).toBe(
      "/settings/tools?section=mappings",
    );
  });

  it("parses the view helper with the overview default", () => {
    expect(parseMappingView(null)).toBe("overview");
    expect(parseMappingView("triage")).toBe("triage");
    expect(parseMappingView("runs")).toBe("runs");
    expect(parseMappingView("bogus")).toBe("overview");
  });

  it("renders the runs view empty state from the i18n keys", async () => {
    render(
      <MemoryRouter initialEntries={["/settings/tools?section=mappings&view=runs"]}>
        <MappingManagementSection />
      </MemoryRouter>,
    );
    expect(
      await screen.findByText("mappingsConsole.empty.runs.title"),
    ).toBeTruthy();
  });
});
