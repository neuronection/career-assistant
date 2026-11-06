import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import {
  fetchJobTypesBreakdown,
  fetchSourcesBreakdown,
  type JobTypesBreakdown,
  type SourceBreakdown,
} from "@/api/mappings";
import { MappingTypesSourcesView } from "@/components/settings/MappingTypesSourcesView";

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
    fetchSourcesBreakdown: vi.fn(),
    fetchJobTypesBreakdown: vi.fn(),
  };
});

function sourceEntry(overrides: Partial<SourceBreakdown> = {}): SourceBreakdown {
  return {
    source_id: "src-1",
    key: "board-a",
    title: "Board A",
    kind: "posting",
    detail_mode: "all",
    paused: false,
    active: 4,
    described: 3,
    extracted: 2,
    mapped: 1,
    accounted: 2,
    states: { not_extracted: 2, mapped: 1, ignored: 1 },
    reasons: { below_threshold: 1 },
    last_run_at: "2026-11-05T10:00:00Z",
    ...overrides,
  };
}

function typesEntry(overrides: Partial<JobTypesBreakdown["items"][number]> = {}) {
  return {
    job_id: "j-1",
    code: "data-analyst",
    title: "Data Analyst",
    family: "Data",
    mapped_postings: 3,
    open_roles: 2,
    zero_postings: false,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(fetchSourcesBreakdown).mockResolvedValue({ items: [sourceEntry()] });
  vi.mocked(fetchJobTypesBreakdown).mockResolvedValue({
    items: [typesEntry(), typesEntry({ job_id: "j-2", code: "zero-role", zero_postings: true, mapped_postings: 0 })],
    proposal_clusters: [{ job_type: "Prompt Wrangler", postings: 4 }],
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("mapping types & sources view (plan 205 S4)", () => {
  it("renders the per-source funnel table with the detail mode", async () => {
    render(
      <MemoryRouter>
        <MappingTypesSourcesView />
      </MemoryRouter>,
    );
    const rows = await screen.findAllByTestId("mappings-source-row");
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain("Board A");
    expect(rows[0].textContent).toContain("all");
    expect(screen.getByTestId("mappings-sources-table")).toBeTruthy();
  });

  it("flags zero-posting job types and lists the proposal clusters", async () => {
    render(
      <MemoryRouter>
        <MappingTypesSourcesView />
      </MemoryRouter>,
    );
    const typeRows = await screen.findAllByTestId("mappings-job-type-row");
    expect(typeRows).toHaveLength(2);
    expect(typeRows[1].textContent).toContain("mappingsConsole.typesSources.zero");
    const clusters = screen.getByTestId("mappings-proposal-clusters");
    expect(clusters.textContent).toContain("Prompt Wrangler");
  });

  it("renders the empty state when nothing exists", async () => {
    vi.mocked(fetchSourcesBreakdown).mockResolvedValue({ items: [] });
    vi.mocked(fetchJobTypesBreakdown).mockResolvedValue({
      items: [],
      proposal_clusters: [],
    });
    render(
      <MemoryRouter>
        <MappingTypesSourcesView />
      </MemoryRouter>,
    );
    expect(
      await screen.findByText("mappingsConsole.typesSources.emptyTitle"),
    ).toBeTruthy();
  });
});
