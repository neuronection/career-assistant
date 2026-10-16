import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ExtensionSurfacePage } from "@/pages/ExtensionSurface";
import { extensionNavItems } from "@/config/nav";
import {
  SURFACE_ITEM_ACTION_IDS,
  SURFACE_NODE_TYPES,
  SURFACE_RUN_ACTION_IDS,
  SurfaceRenderer,
  type SurfaceRow,
  type SurfaceView,
} from "@/components/ui/SurfaceRenderer";

// plan 32 Phase 4 — career's fixture wall on the FRONTEND: the vendored
// family parity fixtures (`contracts/surface-renderer.fixtures.json`)
// rendered through the library SurfaceRenderer the career host consumes
// via the dist overlay. Implementations may differ, outputs may not.

type Fixture = {
  id: string;
  degradeProbe?: boolean;
  surface: {
    nodes: Record<string, unknown>[];
    rows?: Record<string, unknown>[];
    values?: Record<string, unknown>;
    groups?: Record<string, string>;
    labels?: Record<string, string>;
  };
  filters?: { id: string; options: { value: string; label?: string }[] }[];
  activeFilters?: Record<string, string>;
  truncatedLabel?: string;
  expect: Record<string, unknown>[];
};

const fixtures: Fixture[] = JSON.parse(
  readFileSync(
    join(__dirname, "../../../contracts/surface-renderer.fixtures.json"),
    "utf8",
  ),
).cases;

const asText = (value: unknown): string =>
  value === undefined || value === null ? "" : String(value);

function queryTestId(container: HTMLElement, testId: string): HTMLElement | null {
  return container.querySelector(`[data-testid="${CSS.escape(testId)}"]`);
}

describe("career surface host — the family fixture wall (frontend)", () => {
  it("is rendered through the library renderer with a closed vocabulary", () => {
    const vocab = JSON.parse(
      readFileSync(
        join(__dirname, "../../../contracts/surface-renderer.fixtures.json"),
        "utf8",
      ),
    ).vocabulary;
    expect(SURFACE_NODE_TYPES as readonly string[]).toEqual(vocab.components);
    expect(SURFACE_RUN_ACTION_IDS as readonly string[]).toEqual(vocab.actions.run);
    expect(SURFACE_ITEM_ACTION_IDS as readonly string[]).toEqual(vocab.actions.item);
  });

  it.each(fixtures.map((fixture) => [fixture.id, fixture] as const))(
    "fixture case: %s",
    async (_caseId, fixtureCase) => {
      const actions: { id: string; rowId?: string }[] = [];
      const filterEvents: Array<[string, string | null]> = [];
      const utils = render(
        <div data-testid="surface-fixture-mount">
          <CareerSurfaceMount
            fixtureCase={fixtureCase}
            actions={actions}
            filterEvents={filterEvents}
          />
        </div>,
      );
      for (const entry of fixtureCase.expect) {
        assertExpectation(entry, utils.container);
      }
      const clicks = fixtureCase.expect.filter((entry) => entry.kind === "click");
      const user = userEvent.setup();
      for (const entry of clicks) {
        const event = entry.event as Record<string, unknown>;
        const target = queryTestId(utils.container, asText(entry.click)) as HTMLElement | null;
        expect(target, `missing click target ${entry.click}`).not.toBeNull();
        await user.click(target!);
        if (typeof (event ?? {}).facet === "string") {
          expect(filterEvents[filterEvents.length - 1]).toEqual([event.facet, event.value]);
        } else {
          expect(actions[actions.length - 1]).toEqual({
            id: event.id,
            rowId: event.rowId ?? undefined,
          });
        }
      }
      const changes = fixtureCase.expect.filter((entry) => entry.kind === "change");
      for (const entry of changes) {
        const select = queryTestId(utils.container, asText(entry.select)) as HTMLSelectElement;
        expect(select).not.toBeNull();
        await user.selectOptions(select, asText(entry.value));
        const event = entry.event as Record<string, unknown>;
        expect(filterEvents[filterEvents.length - 1]).toEqual([event.facet, event.value]);
      }
      expect(utils.container.querySelector("script, iframe, style, img, object, embed")).toBeNull();
      expect(utils.container.querySelector('a[href^="javascript:"]')).toBeNull();
      utils.unmount();
    },
  );
});

function CareerSurfaceMount({
  fixtureCase,
  actions,
  filterEvents,
}: {
  fixtureCase: Fixture;
  actions: { id: string; rowId?: string }[];
  filterEvents: Array<[string, string | null]>;
}) {
  return (
    <SurfaceRenderer
      surface={
        {
          nodes: fixtureCase.surface.nodes,
          rows: (fixtureCase.surface.rows ?? []) as unknown as SurfaceRow[],
          values: fixtureCase.surface.values,
          groups: fixtureCase.surface.groups,
        } as unknown as SurfaceView
      }
      labels={fixtureCase.surface.labels}
      truncatedLabel={fixtureCase.truncatedLabel}
      filters={fixtureCase.filters}
      activeFilters={fixtureCase.activeFilters}
      onAction={(action: { id: string; rowId?: string }) => actions.push(action)}
      onFilterChange={(facetId: string, value: string | null) => filterEvents.push([facetId, value])}
    />
  );
}

function assertExpectation(expectation: Record<string, unknown>, container: HTMLElement): void {
  switch (expectation.kind) {
    case "note":
    case "no-html":
      return;
    case "component": {
      const id = asText(expectation.id);
      const el = queryTestId(container, `surface-${id}`);
      expect(el, `component ${id} missing`).not.toBeNull();
      if (expectation.value !== undefined) {
        const value = asText(expectation.value);
        const texts = Array.from(el!.querySelectorAll("*")).map((child) => child.textContent);
        expect(texts).toContain(value);
      }
      if (expectation.label !== undefined) {
        const label = asText(expectation.label);
        const texts = Array.from(el!.querySelectorAll("*")).map((child) => child.textContent);
        expect(texts).toContain(label);
      }
      if (expectation.columns !== undefined) {
        const headers = Array.from(el!.querySelectorAll("th")).map((th) => th.textContent);
        expect(headers).toEqual((expectation.columns as unknown[]).map(asText));
      }
      if (expectation.rows !== undefined) {
        for (const row of expectation.rows as Record<string, unknown>[]) {
          const rowEl = queryTestId(container, `surface-row-${asText(row.rowId)}`);
          expect(rowEl, `row ${row.rowId} missing`).not.toBeNull();
          const cells = Array.from(
            el!.querySelectorAll(`[data-testid^="surface-cell-${asText(row.rowId)}-"]`),
          );
          expect(
            cells.map((cell) => cell.querySelector(".block")?.textContent ?? cell.textContent),
          ).toEqual(((row.cells ?? []) as unknown[]).map(asText));
          if (row.evidenceSummary !== undefined) {
            const summary = queryTestId(container, `surface-evidence-${asText(row.rowId)}`);
            expect(summary?.querySelector("summary")?.textContent).toBe(
              asText(row.evidenceSummary),
            );
          }
        }
      }
      if (expectation.optionText !== undefined) {
        const select = el!.querySelector("select") as HTMLSelectElement;
        expect(
          Array.from(select.options).map((option) => option.textContent),
        ).toEqual((expectation.optionText as unknown[]).map(asText));
      }
      return;
    }
    case "bar": {
      const bar = queryTestId(container, `surface-${asText(expectation.id)}`)?.querySelector(
        '[role="progressbar"]',
      );
      expect(bar).not.toBeNull();
      if (expectation.label !== undefined) {
        expect(bar!.getAttribute("aria-label")).toBe(asText(expectation.label));
      }
      expect(bar!.getAttribute("aria-valuenow")).toBe(String(expectation.percent));
      return;
    }
    case "row": {
      const row = queryTestId(container, `surface-row-${asText(expectation.rowId)}`);
      expect(row, `row ${expectation.rowId} missing`).not.toBeNull();
      if (expectation.title !== undefined) {
        expect(row!.querySelector(".truncate")?.textContent).toBe(asText(expectation.title));
      }
      if (expectation.badge !== undefined) {
        const badgeTexts = Array.from(row!.querySelectorAll('[data-as="badge"]')).map((badge) =>
          badge.textContent,
        );
        expect(badgeTexts).toContain(asText(expectation.badge));
      }
      if (expectation.meta !== undefined) {
        for (const segment of expectation.meta as unknown[]) {
          const rowTexts = Array.from((row as HTMLElement).querySelectorAll("*")).map(
            (child) => child.textContent,
          );
          expect(rowTexts).toContain(asText(segment));
        }
      }
      if (expectation.evidenceSummary !== undefined) {
        expect(row!.querySelector("summary")?.textContent).toBe(
          asText(expectation.evidenceSummary),
        );
      }
      if (expectation.actionLabel !== undefined) {
        const buttonLabels = Array.from((row as HTMLElement).querySelectorAll("button")).map(
          (button) => button.textContent,
        );
        expect(buttonLabels).toContain(asText(expectation.actionLabel));
      }
      if (expectation.section !== undefined) {
        const section = expectation.section as { heading: string; count: number };
        const area = (row as HTMLElement).closest("section");
        expect(area?.getAttribute("aria-label")).toBe(asText(section.heading));
        expect(area?.querySelectorAll('[data-testid^="surface-row-"]').length).toBe(
          section.count,
        );
      }
      return;
    }
    case "text": {
      const el = within(container);
      const match = el.getByText(asText(expectation.text));
      if (expectation.role !== undefined) {
        expect(match.getAttribute("role")).toBe(asText(expectation.role));
      }
      if (expectation.aria !== undefined) {
        for (const [name, value] of Object.entries(expectation.aria as Record<string, unknown>)) {
          expect(match.getAttribute(name)).toBe(asText(value));
        }
      }
      return;
    }
    case "click":
    case "change":
      return;
    case "absent": {
      expect(queryTestId(container, asText(expectation.testid))).toBeNull();
      return;
    }
    default:
      throw new Error(`unknown expectation kind ${String(expectation.kind)}`);
  }
}

// ---------------------------------------------------------------- page glue

const PAGE_VIEW = {
  extensionId: "career-cv-gallery",
  version: "1.0.0",
  title: "CV layout gallery",
  surface: {
    kind: "page",
    degraded: { window: "page" },
    nodes: [
      { id: "status", type: "badge", bind: "mode.status" },
      { id: "layouts-shipped", type: "stat", bind: "totals.layouts" },
      { id: "filters", type: "filter-bar", filters: ["language"] },
      { id: "gallery", type: "cards", of: "items" },
      { id: "evidence", type: "evidence" },
      { id: "actions", type: "actions", actions: ["run:export"] },
    ],
    labels: {
      "report.status": "Status",
      "report.layouts-shipped": "Layouts shipped",
      "report.gallery": "Gallery",
      "action.run:export": "Export gallery data",
      "status.browse": "Browsing",
    },
    rows: [
      {
        id: "compact",
        values: { layout: "Compact", language: "en" },
        title: "Compact",
        badge: "Recommended",
        meta: ["single column"],
        evidence: { rule: "listing-coverage" },
        evidenceSummary: "38 of 42 sampled listings fit",
        actions: ["item:open"],
      },
    ],
    values: { mode: { status: "browse" }, totals: { layouts: 4 } },
    groups: {},
    filters: [{ id: "language", options: [{ value: "en", label: "English" }] }],
  },
  placeholders: [],
  manifestSummary: {
    kind: "mini-app",
    packKind: "surface",
    tier: "T0",
    originClass: "imported",
    capabilities: ["ui:page", "report", "run"],
    surfaces: { honored: ["page", "panel"], degrades: { window: "page" }, declared: [] },
    configSchema: {},
    description: null,
  },
};

const mocks = vi.hoisted(() => ({
  fetchSurfacePage: vi.fn(),
  exportSurfacePage: vi.fn(),
}));

vi.mock("@/api/extensions", () => ({
  fetchSurfaceCards: vi.fn().mockResolvedValue([]),
  fetchSurfacePage: mocks.fetchSurfacePage,
  exportSurfacePage: mocks.exportSurfacePage,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/extensions/career-cv-gallery"]}>
      <Routes>
        <Route path="/extensions/:extensionId" element={<ExtensionSurfacePage />} />
        <Route path="/cv" element={<div data-testid="cv-studio" />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("the extension surface page", () => {
  beforeEach(() => {
    mocks.fetchSurfacePage.mockReset();
    mocks.exportSurfacePage.mockReset();
    Object.defineProperty(window.URL, "createObjectURL", {
      value: vi.fn(() => "blob:fake"),
      configurable: true,
    });
    Object.defineProperty(window.URL, "revokeObjectURL", {
      value: vi.fn(),
      configurable: true,
    });
    HTMLAnchorElement.prototype.click = vi.fn();
  });

  it("renders the mini-app declarative surface host-side", async () => {
    mocks.fetchSurfacePage.mockResolvedValue(PAGE_VIEW);
    renderPage();
    await screen.findByTestId("extension-surface-page");
    expect(screen.getByText("CV layout gallery")).toBeInTheDocument();
    expect(screen.getByTestId("surface-status")).toHaveTextContent("browse");
    expect(screen.getByTestId("surface-row-compact")).toBeInTheDocument();
    expect(screen.getByText("Evidence — 38 of 42 sampled listings fit")).toBeInTheDocument();
    expect(screen.getByTestId("surface-degrade-chip")).toBeInTheDocument();
  });

  it("binds the typed actions: export downloads, item:open routes to the studio", async () => {
    const user = userEvent.setup();
    mocks.fetchSurfacePage.mockResolvedValue(PAGE_VIEW);
    mocks.exportSurfacePage.mockResolvedValue({
      extensionId: "career-cv-gallery",
      version: "1.0.0",
      source: "x",
      rows: [],
      values: {},
    });
    renderPage();
    await screen.findByTestId("extension-surface-page");
    await user.click(screen.getByTestId("surface-action-run:export"));
    await waitFor(() => expect(mocks.exportSurfacePage).toHaveBeenCalledWith("career-cv-gallery"));
    await user.click(screen.getByTestId("surface-action-item:open-compact"));
    await waitFor(() => expect(screen.getByTestId("cv-studio")).toBeInTheDocument());
  });

  it("the kill switch is the empty state — a disabled install 404s into it", async () => {
    mocks.fetchSurfacePage.mockRejectedValue({ response: { status: 404 } });
    renderPage();
    await waitFor(() => expect(screen.getByTestId("surface-page-missing")).toBeInTheDocument());
  });

  it("extension nav rows map from the registry cards", () => {
    const items = extensionNavItems(
      [{ extensionId: "career-cv-gallery", title: "CV layout gallery", routes: "/extensions/career-cv-gallery" }],
      (key) => key,
    );
    expect(items).toEqual([
      {
        id: "/extensions/career-cv-gallery",
        label: "CV layout gallery",
        icon: expect.anything(),
        section: "nav.sectionExtensions",
      },
    ]);
    expect(
      extensionNavItems(
        [{ extensionId: "x", title: "x", routes: null }],
        (key) => key,
      ),
    ).toEqual([]);
  });
});
