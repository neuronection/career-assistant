import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import {
  mappingsExtract,
  mappingsIgnore,
  mappingsMap,
  type MappingCandidate,
  type MappingQueueItem,
  type MappingQueueResponse,
} from "@/api/mappings";
import { MappingTriageView } from "@/components/settings/MappingTriageView";

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
    fetchMappingsQueue: vi.fn(),
    fetchMappingsTrace: vi.fn(),
    mappingsExtract: vi.fn(),
    mappingsIgnore: vi.fn(),
    mappingsUnignore: vi.fn(),
    mappingsUnmap: vi.fn(),
    mappingsReview: vi.fn(),
    mappingsRedecide: vi.fn(),
    mappingsMap: vi.fn(),
  };
});

vi.mock("@/api/admin", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/admin")>();
  return {
    ...actual,
    fetchModerationQueue: vi.fn().mockResolvedValue([
      {
        id: "j2",
        code: "data-engineer",
        title: "Data Engineer",
        status: "published",
      },
    ]),
  };
});

vi.mock("@/api/sources", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/sources")>();
  return {
    ...actual,
    fetchAdminSources: vi.fn().mockResolvedValue([
      {
        id: "src-1",
        key: "board-a",
        connector_key: "board",
        kind: "connector",
        schedule_kind: null,
        config: {},
        query_mode: "all",
        query_batch_size: 10,
        query_info: {},
      },
    ]),
  };
});

import { fetchMappingsQueue, fetchMappingsTrace } from "@/api/mappings";

function row(overrides: Partial<MappingQueueItem> = {}): MappingQueueItem {
  return ({
    id: "p-1",
    ref: "AAAA1111",
    title: "Analyst",
    org: "ACME",
    source_id: "src-1",
    state: "not_extracted",
    outcome_reason: "unknown",
    needs_review: false,
    detail_fetched: true,
    extract_version: null,
    mapped: false,
    catalog_job_id: null,
    top_candidate: { job_id: "j1", job_code: "data-analyst", deterministic: 0.4 },
    proposal_state: null,
    review: null,
    ...overrides,
  } as MappingQueueItem);
}

function queueResponse(items: MappingQueueItem[]): MappingQueueResponse {
  return {
    items,
    total: items.length,
    states: { not_extracted: items.length, mapped: 1 },
  };
}

function renderView() {
  return render(
    <MemoryRouter initialEntries={["/settings/tools?section=mappings&view=triage"]}>
      <MappingTriageView />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(fetchMappingsQueue).mockResolvedValue(queueResponse([row()]));
  vi.mocked(fetchMappingsTrace).mockResolvedValue({
    posting: {
      id: "p-1",
      ref: "AAAA1111",
      title: "Analyst",
      org: "ACME",
      status: "new",
      state: "not_extracted",
      created_at: null,
    },
    outcome: {
      state: "unmapped",
      reason: "unknown",
      method: null,
      confidence: null,
      reason_prose: "best overlap 0.40 below 0.62",
    },
    signals: {},
    features: {
      mapping_version: 2,
      space_key: null,
      degraded: null,
      policy: null,
      candidates: [
      {
        job_id: "j1",
        job_code: "data-analyst",
        deterministic: 0.4,
        semantic: null,
        blend: null,
        shared_skills: [],
      } as MappingCandidate,
    ],
    },
    proposal: null,
    review: null,
    review_row: null,
    extract_version: null,
    needs_review: false,
    detail_fetched_at: null,
    journal: [],
    ai_generation_ids: [],
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("mapping triage view (plan 205 S3)", () => {
  it("renders the rows with their state badges and counts", async () => {
    renderView();
    const rows = await screen.findAllByTestId("mappings-queue-row");
    expect(rows).toHaveLength(1);
    expect(rows[0].getAttribute("data-state")).toBe("not_extracted");
    expect(
      within(rows[0]).getByText("mappingsConsole.state.not_extracted"),
    ).toBeTruthy();
    expect(screen.getByTestId("mappings-total").textContent).toBe(
      "mappingsConsole.triage.total",
    );
  });

  it("renders the empty bucket state", async () => {
    vi.mocked(fetchMappingsQueue).mockResolvedValue(
      queueResponse([]) as MappingQueueResponse,
    );
    renderView();
    expect(
      await screen.findByText("mappingsConsole.triage.queueEmptyTitle"),
    ).toBeTruthy();
  });

  it("re-fetches when the state filter changes", async () => {
    const user = userEvent.setup();
    renderView();
    await screen.findAllByTestId("mappings-queue-row");
    await user.selectOptions(
      screen.getByTestId("mappings-state-filter"),
      "not_extracted",
    );
    await waitFor(() =>
      expect(fetchMappingsQueue).toHaveBeenLastCalledWith(
        expect.objectContaining({ state: "not_extracted" }),
      ),
    );
  });

  it("opens the trace drawer from a row and shows the outcome", async () => {
    const user = userEvent.setup();
    renderView();
    const rows = await screen.findAllByTestId("mappings-queue-row");
    await user.click(within(rows[0]).getByTestId("mappings-trace-AAAA1111"));
    expect(await screen.findByTestId("mappings-trace-body")).toBeTruthy();
    expect(screen.getByText("best overlap 0.40 below 0.62")).toBeTruthy();
    expect(fetchMappingsTrace).toHaveBeenCalledWith("p-1");
  });

  it("runs the bulk extract action on the selection", async () => {
    const user = userEvent.setup();
    vi.mocked(mappingsExtract).mockResolvedValue({
      affected: 1,
      missing: [],
      queued: 1,
      skipped: 0,
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderView();
    await screen.findAllByTestId("mappings-queue-row");
    await user.click(screen.getByTestId("mappings-select"));
    await user.click(
      await screen.findByRole("checkbox", { name: "selection.selectAll" }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("mappings-bulk-extract")).toBeEnabled(),
    );
    await user.click(screen.getByTestId("mappings-bulk-extract"));
    await waitFor(() => expect(mappingsExtract).toHaveBeenCalledWith(["p-1"]));
    expect(confirmSpy).toHaveBeenCalled();
  });

  it("runs the ignore action with the reason from the panel", async () => {
    const user = userEvent.setup();
    vi.mocked(mappingsIgnore).mockResolvedValue({ affected: 1, missing: [], ignored: ["p-1"] });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderView();
    await screen.findAllByTestId("mappings-queue-row");
    await user.click(screen.getByTestId("mappings-select"));
    await user.click(
      await screen.findByRole("checkbox", { name: "selection.selectAll" }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("mappings-bulk-ignore")).toBeEnabled(),
    );
    await user.click(screen.getByTestId("mappings-bulk-ignore"));
    await user.click(screen.getByTestId("mappings-ignore-confirm"));
    await waitFor(() =>
      expect(mappingsIgnore).toHaveBeenCalledWith(["p-1"], "no_good_type", ""),
    );
  });
});

describe("mapping triage picker and detail link (plan 205 AD6)", () => {
  it("maps any published type through the picker", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(mappingsMap).mockResolvedValue({
      id: "p-1",
      status: "mapped",
      mapping_method: "manual",
      catalog_job_id: "j2",
    });
    const user = userEvent.setup();
    renderView();
    const rows = await screen.findAllByTestId("mappings-queue-row");
    await user.click(within(rows[0]).getByTestId("mappings-trace-AAAA1111"));
    const select = await screen.findByTestId("job-type-picker-select");
    await waitFor(() =>
      expect(
        within(select).getByRole("option", { name: /data-engineer/ }),
      ).toBeTruthy(),
    );
    await user.selectOptions(select, "j2");
    await user.click(screen.getByTestId("mappings-map-selected"));
    await waitFor(() => expect(mappingsMap).toHaveBeenCalledWith("p-1", "j2"));
    confirm.mockRestore();
  });

  it("links a not-extracted row to the source detail mode", async () => {
    renderView();
    const rows = await screen.findAllByTestId("mappings-queue-row");
    const link = within(rows[0]).getByTestId("mappings-detail-mode-AAAA1111");
    expect(link.getAttribute("href")).toBe("/settings/tools?section=sources");
  });
});
