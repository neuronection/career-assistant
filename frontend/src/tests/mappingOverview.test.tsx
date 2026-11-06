import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import {
  fetchMappingsOverview,
  fetchMappingsTrend,
  mappingsBackfill,
  mappingsCaptureSnapshot,
  type MappingOverviewWithSwitches,
} from "@/api/mappings";
import { MappingOverviewView } from "@/components/settings/MappingOverviewView";
import { MappingRunsView } from "@/components/settings/MappingRunsView";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      let out = key;
      for (const [name, value] of Object.entries(params ?? {})) {
        out = out.split(`{{${name}}}`).join(String(value));
      }
      return out;
    },
    i18n: { language: "en" },
  }),
}));

vi.mock("@/api/mappings", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/mappings")>();
  return {
    ...actual,
    fetchMappingsOverview: vi.fn(),
    fetchMappingsTrend: vi.fn().mockResolvedValue({ items: [] }),
    mappingsBackfill: vi.fn(),
    mappingsCaptureSnapshot: vi.fn(),
  };
});

function overview(
  overrides: Partial<MappingOverviewWithSwitches> = {},
): MappingOverviewWithSwitches {
  return {
    active: 10,
    described: 8,
    extracted: 5,
    mapped: 3,
    accounted: { mapped: 3, machine_terminal: 2, human_terminal: 1, total: 6 },
    states: {
      mapped: 3,
      no_skills: 2,
      ignored: 1,
      not_extracted: 4,
    },
    gate: { floor: 0.95, rate: 0.6, pass: false },
    methods: { skill_overlap: 3 },
    reasons: { no_skills: 2 },
    proposals_pending: 2,
    switches: { job_proposals: true, semantic_rescue: true, semantic_rerank: false },
    last_remap: {
      job_id: "job-1",
      status: "succeeded",
      created_at: "2026-11-05T10:00:00Z",
      error: null,
    },
    health: { spaces: [] },
    legacy_outcome_count: 4,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(fetchMappingsOverview).mockResolvedValue(overview());
});

afterEach(() => {
  vi.clearAllMocks();
});

function renderView(node: React.ReactNode) {
  return render(<MemoryRouter>{node}</MemoryRouter>);
}

describe("mapping overview view (plan 205 S5)", () => {
  it("renders the funnel tiles with the accounted split and the gate", async () => {
    renderView(<MappingOverviewView />);
    expect(await screen.findByTestId("mappings-stat-tiles")).toBeTruthy();
    expect(screen.getByTestId("mappings-tile-accounted")).toBeTruthy();
    expect(screen.getByTestId("mappings-gate").getAttribute("data-pass")).toBe(
      "false",
    );
    expect(screen.getByTestId("mappings-gate").textContent).toContain(
      "mappingsConsole.overview.gateFail",
    );
    expect(screen.getByTestId("mappings-bar-not_extracted")).toBeTruthy();
    expect(screen.getByTestId("mappings-bar-mapped")).toBeTruthy();
  });

  it("shows the empty state before postings exist", async () => {
    vi.mocked(fetchMappingsOverview).mockResolvedValue(
      overview({ active: 0, legacy_outcome_count: 0 }),
    );
    renderView(<MappingOverviewView />);
    expect(
      await screen.findByText("mappingsConsole.overview.emptyTitle"),
    ).toBeTruthy();
  });

  it("offers the backfill action only when legacy rows exist and reloads after", async () => {
    const user = userEvent.setup();
    vi.mocked(mappingsBackfill).mockResolvedValue({ job_id: "j", created: true });
    const first = renderView(<MappingOverviewView />);
    expect(await screen.findByTestId("mappings-backfill")).toBeTruthy();
    await user.click(screen.getByTestId("mappings-backfill"));
    expect(mappingsBackfill).toHaveBeenCalled();
    expect(
      await screen.findByText("mappingsConsole.overview.backfillQueued"),
    ).toBeTruthy();
    first.unmount();

    vi.mocked(fetchMappingsOverview).mockResolvedValue(
      overview({ legacy_outcome_count: 0 }),
    );
    renderView(<MappingOverviewView />);
    await screen.findByTestId("mappings-stat-tiles");
    expect(screen.queryByTestId("mappings-backfill")).toBeNull();
  });
});

describe("mapping runs view (plan 205 S5)", () => {
  it("shows the three switches read-only with the Taxonomy home link", async () => {
    renderView(<MappingRunsView />);
    await screen.findByTestId("mappings-run-controls");
    const controls = screen.getByTestId("mappings-run-controls").textContent ?? "";
    expect(controls).toContain("mappingsConsole.overview.switch.jobProposals");
    expect(controls).toContain("mappingsConsole.overview.switch.semanticRescue");
    expect(controls).toContain("mappingsConsole.overview.switch.semanticRerank");
    const link = screen.getByTestId("mappings-switch-link");
    expect(link.getAttribute("href")).toBe("/settings/taxonomy?tab=relations");
  });

  it("links the job index to Tools → Retrieval (no second reindex action)", async () => {
    renderView(<MappingRunsView />);
    await screen.findByTestId("mappings-runs");
    const index = screen.getByTestId("mappings-index-link");
    expect(index.getAttribute("href")).toBe("/settings/tools?section=retrieval");
    expect(screen.queryByTestId("mappings-reindex")).toBeNull();
    expect(screen.getByTestId("mappings-audit-link")).toBeTruthy();
    expect(screen.getByTestId("mappings-runbook-link")).toBeTruthy();
    expect(screen.getByTestId("mappings-last-remap").textContent).toContain(
      "mappingsConsole.overview.lastRemap",
    );
  });
});

describe("mapping trend + snapshot (plan 205 S9)", () => {
  beforeEach(() => {
    vi.mocked(fetchMappingsTrend).mockResolvedValue({
      items: [
        {
          captured_at: "2026-11-05T00:00:00Z",
          basis: "scheduled",
          total: 10,
          described: 10,
          extracted: 9,
          mapped: 4,
          accounted: 6,
          machine_terminal: 1,
          human_terminal: 1,
          reasons: {},
          policy_hash: null,
        },
        {
          captured_at: "2026-11-06T00:00:00Z",
          basis: "scheduled",
          total: 11,
          described: 11,
          extracted: 10,
          mapped: 5,
          accounted: 7,
          machine_terminal: 1,
          human_terminal: 1,
          reasons: {},
          policy_hash: null,
        },
      ],
    });
  });

  it("feeds the accounted sparkline from the trend and captures a manual snapshot", async () => {
    const user = userEvent.setup();
    vi.mocked(mappingsCaptureSnapshot).mockResolvedValue({
      snapshot_id: "s-1",
      total: 10,
      accounted: 6,
    });
    renderView(<MappingOverviewView />);
    await screen.findByTestId("mappings-stat-tiles");
    const tile = screen.getByTestId("mappings-tile-accounted");
    await waitFor(() => expect(tile.textContent.trim().length).toBeGreaterThan(0));
    await user.click(screen.getByTestId("mappings-snapshot"));
    await waitFor(() => expect(mappingsCaptureSnapshot).toHaveBeenCalled());
    expect(await screen.findByText("mappingsConsole.overview.snapshotDone")).toBeTruthy();
  });
});
