import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { api } from "@/api/client";
import { bulkEnrichmentAction, type EnrichmentRow } from "@/api/taxonomy";
import type { PathRow } from "@/components/settings/TaxonomyPathCards";
import { Taxonomy } from "@/pages/settings/Taxonomy";

vi.mock("@/api/client", () => ({
  api: {
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn().mockResolvedValue({}),
  },
  apiDetail: vi.fn(() => "request failed"),
}));

vi.mock("@/components/settings/TranslationsBoard", () => ({
  TranslationsBoard: () => null,
}));

vi.mock("@/api/taxonomy", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/taxonomy")>();
  return {
    ...actual,
    bulkEnrichmentAction: vi.fn(),
    regenerateJobProposals: vi.fn(),
    fetchDuplicateJobTypes: vi.fn().mockResolvedValue({ groups: [] }),
    mergeJobTypes: vi.fn(),
  };
});

vi.mock("@/api/skillRelations", () => ({
  fetchSkillRelations: vi.fn().mockResolvedValue([]),
  fetchSkillRelationThresholds: vi.fn().mockResolvedValue(null),
  fetchSkillRelationRuns: vi.fn().mockResolvedValue([]),
  saveSkillRelationThresholds: vi.fn(),
  acceptSkillRelation: vi.fn(),
  dismissSkillRelation: vi.fn(),
  removeSkillRelation: vi.fn(),
  saveSkillRelationAlias: vi.fn(),
  createSkillRelation: vi.fn(),
  bulkSkillRelationAction: vi.fn(),
}));

const mockedApi = vi.mocked(api);

function step(partial: Partial<PathRow["steps"][number]> & { id: string; position: number }) {
  return {
    kind: "job",
    label: "",
    optional: false,
    family_key: null,
    family_label: null,
    skill_key: null,
    skill_label: null,
    education_level: null,
    edge_label: "",
    ...partial,
  };
}

const PATHS: PathRow[] = [
  {
    id: "p1",
    title: "Data analyst track",
    description: "From spreadsheets to dashboards.",
    source: "user",
    status: "draft",
    job_code: "data-analyst",
    job_title: "Data Analyst",
    steps: [
      step({
        id: "ps1",
        position: 0,
        kind: "education",
        label: "Bachelor in statistics",
        education_level: "bachelor",
        edge_label: "starts with",
      }),
      step({
        id: "ps2",
        position: 1,
        kind: "skill",
        skill_key: "sql",
        skill_label: "SQL",
        family_key: "technology",
        family_label: "Technology",
      }),
      step({ id: "ps3", position: 2, kind: "certification", label: "Tableau cert", optional: true }),
    ],
  },
];

const THREE_DAYS_AGO = new Date(Date.now() - 3 * 86_400_000).toISOString();

const ENRICHMENT: EnrichmentRow[] = [
  {
    id: "j1",
    code: "software-developer",
    title: "Software Developer",
    proposal: {
      contract_type: "permanent",
      work_hours: { pattern: "full_time", hours_per_week_min: 35, hours_per_week_max: 40 },
      schedule_cues: ["flexible", "shift_work"],
      travel_required: { level: "occasional", days_per_month: 3 },
      benefits_kinds: ["healthcare", "learning"],
      note: "Based on the listed benefits and full-time hours.",
      brand_new_field: { deep: true },
    },
    proposed_at: THREE_DAYS_AGO,
  },
];

const SECOND_ENRICHMENT: EnrichmentRow = {
  id: "j2",
  code: "data-analyst",
  title: "Data Analyst",
  proposal: { contract_type: "permanent" },
  proposed_at: THREE_DAYS_AGO,
};

function renderPage(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/settings/taxonomy" element={<Taxonomy />} />
        <Route path="/skills/:key" element={<div data-testid="skill-page-stub" />} />
      </Routes>
    </MemoryRouter>,
  );
}

function page<T>(items: T[], nextCursor: string | null = null, total = items.length) {
  return { items, next_cursor: nextCursor, total };
}

/** The two queue endpoints answer keyset pages (plan 206); every other GET
 * in the page still answers a bare list. */
function defaultResponse(url: string) {
  if (url === "/admin/jobs/enrichment" || url === "/admin/postings/job-proposals") {
    return { data: page([]) };
  }
  return { data: [] };
}

function mockQueue(url: string, data: unknown) {
  mockedApi.get.mockImplementation(async (requested: string) =>
    requested === url ? { data } : defaultResponse(requested),
  );
}

function mockEnrichmentQueue(rows: EnrichmentRow[], nextCursor: string | null = null) {
  mockQueue("/admin/jobs/enrichment", page(rows, nextCursor));
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.get.mockImplementation(async (url: string) => defaultResponse(url));
  mockedApi.post.mockResolvedValue({});
  vi.mocked(bulkEnrichmentAction).mockResolvedValue({ affected: [], failed: [] });
});

describe("Taxonomy paths tab", () => {
  it("renders draft path cards with target job, status, source and step chips", async () => {
    mockQueue("/admin/paths", PATHS);
    renderPage("/settings/taxonomy?tab=paths");

    const card = await screen.findByTestId("path-card-p1");
    expect(within(card).getByText("Data analyst track")).toBeInTheDocument();
    expect(within(card).getByText("Data Analyst")).toBeInTheDocument();
    expect(within(card).getByText("data-analyst")).toBeInTheDocument();
    expect(within(card).getByText("Draft")).toBeInTheDocument();
    expect(within(card).getByText("From spreadsheets to dashboards.")).toBeInTheDocument();
    expect(within(card).getByText("user")).toBeInTheDocument();
    expect(within(card).getByText("3 steps")).toBeInTheDocument();

    // Compact chips carry position, resolved labels and the optional badge…
    expect(within(card).getByTestId("path-step-chip-0")).toHaveTextContent(
      "1Bachelor in statistics",
    );
    expect(within(card).getByTestId("path-step-chip-1")).toHaveTextContent("SQL");
    expect(within(card).getByTestId("path-step-chip-2")).toHaveTextContent("optional");
    // …while the full step list stays collapsed by default.
    expect(within(card).queryByTestId("path-steps-full-p1")).not.toBeInTheDocument();
  });

  it("expands and collapses the full step list", async () => {
    const user = userEvent.setup();
    mockQueue("/admin/paths", PATHS);
    renderPage("/settings/taxonomy?tab=paths");

    const card = await screen.findByTestId("path-card-p1");
    expect(within(card).queryByTestId("path-steps-full-p1")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("path-steps-toggle-p1"));
    const list = within(card).getByTestId("path-steps-full-p1");
    expect(within(list).getByTestId("path-step-0")).toHaveTextContent(
      "1.Bachelor in statistics · Education · starts with · bachelor",
    );
    expect(within(list).getByTestId("path-step-1")).toHaveTextContent("sql");
    expect(within(list).getByTestId("path-step-2")).toHaveTextContent("optional");

    await user.click(screen.getByTestId("path-steps-toggle-p1"));
    await waitFor(() =>
      expect(within(card).queryByTestId("path-steps-full-p1")).not.toBeInTheDocument(),
    );
  });

  it("publishes a path straight from the card", async () => {
    const user = userEvent.setup();
    mockQueue("/admin/paths", PATHS);
    renderPage("/settings/taxonomy?tab=paths");

    await user.click(await screen.findByTestId("path-publish-p1"));

    await waitFor(() =>
      expect(mockedApi.post).toHaveBeenCalledWith("/admin/paths/p1/publish"),
    );
  });

  it("confirms before rejecting a path", async () => {
    const user = userEvent.setup();
    mockQueue("/admin/paths", PATHS);
    renderPage("/settings/taxonomy?tab=paths");

    await screen.findByTestId("path-card-p1");
    await user.click(screen.getByTestId("path-reject-p1"));
    expect(mockedApi.post).not.toHaveBeenCalled();
    expect(screen.getByText("Reject this draft path?")).toBeInTheDocument();

    // Cancel keeps the draft.
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByText("Reject this draft path?")).not.toBeInTheDocument(),
    );
    expect(mockedApi.post).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("path-reject-p1"));
    const confirm = await screen.findAllByRole("button", { name: "Reject" });
    await user.click(confirm[confirm.length - 1]);

    await waitFor(() =>
      expect(mockedApi.post).toHaveBeenCalledWith("/admin/paths/p1/reject"),
    );
  });

  it("publishes a whole selection from the bar", async () => {
    const user = userEvent.setup();
    mockQueue("/admin/paths", PATHS);
    renderPage("/settings/taxonomy?tab=paths");

    await screen.findByTestId("path-card-p1");
    await user.click(screen.getByTestId("paths-select"));
    await user.click(
      screen.getByRole("checkbox", { name: "Select Data analyst track" }),
    );
    await user.click(screen.getByTestId("paths-bulk-publish"));

    await waitFor(() =>
      expect(mockedApi.post).toHaveBeenCalledWith("/admin/paths/p1/publish"),
    );
    expect(await screen.findByText("1 path published.")).toBeInTheDocument();
  });

  it("shows the empty state without drafts", async () => {
    mockQueue("/admin/paths", []);
    renderPage("/settings/taxonomy?tab=paths");

    expect(await screen.findByText("No draft paths")).toBeInTheDocument();
  });
});

describe("Taxonomy enrichment tab", () => {
  it("renders known proposal keys as labeled rows with chips", async () => {
    mockEnrichmentQueue(ENRICHMENT);
    renderPage("/settings/taxonomy?tab=enrichment");

    const card = await screen.findByTestId("enrichment-row-j1");
    expect(within(card).getByText("Software Developer")).toBeInTheDocument();
    expect(within(card).getByText("software-developer")).toBeInTheDocument();

    const contract = within(card).getByTestId("enrichment-field-j1-contract_type");
    expect(within(contract).getByText("Contract type")).toBeInTheDocument();
    expect(within(contract).getByText("Permanent")).toBeInTheDocument();

    const hours = within(card).getByTestId("enrichment-field-j1-work_hours");
    expect(within(hours).getByText("Full time")).toBeInTheDocument();
    expect(within(hours).getByText("35–40 h / week")).toBeInTheDocument();

    const schedule = within(card).getByTestId("enrichment-field-j1-schedule_cues");
    expect(within(schedule).getByText("Flexible")).toBeInTheDocument();
    expect(within(schedule).getByText("Shift work")).toBeInTheDocument();

    const travel = within(card).getByTestId("enrichment-field-j1-travel_required");
    expect(within(travel).getByText("Occasional")).toBeInTheDocument();
    expect(within(travel).getByText("~3 d / month")).toBeInTheDocument();

    const benefits = within(card).getByTestId("enrichment-field-j1-benefits_kinds");
    expect(within(benefits).getByText("Healthcare")).toBeInTheDocument();
    expect(within(benefits).getByText("Learning")).toBeInTheDocument();

    const note = within(card).getByTestId("enrichment-field-j1-note");
    expect(within(note).getByText("Based on the listed benefits and full-time hours.")).toBeInTheDocument();
  });

  it("collapses unknown proposal keys into the raw disclosure", async () => {
    const user = userEvent.setup();
    mockEnrichmentQueue(ENRICHMENT);
    renderPage("/settings/taxonomy?tab=enrichment");

    const card = await screen.findByTestId("enrichment-row-j1");
    expect(within(card).queryByText("brand_new_field")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("enrichment-raw-toggle-j1"));
    const raw = within(card).getByTestId("enrichment-raw-j1");
    expect(raw).toHaveTextContent("brand_new_field");
    expect(raw).not.toHaveTextContent("contract_type");

    await user.click(screen.getByTestId("enrichment-raw-toggle-j1"));
    await waitFor(() =>
      expect(within(card).queryByTestId("enrichment-raw-j1")).not.toBeInTheDocument(),
    );
  });

  it("shows when the proposal was made", async () => {
    mockEnrichmentQueue(ENRICHMENT);
    renderPage("/settings/taxonomy?tab=enrichment");

    const chip = await screen.findByTestId("enrichment-proposed-j1");
    expect(chip).toHaveTextContent("days ago");
    expect(chip).toHaveAttribute("title");
  });

  it("applies directly and confirms before discarding", async () => {
    const user = userEvent.setup();
    mockEnrichmentQueue([ENRICHMENT[0], SECOND_ENRICHMENT]);
    renderPage("/settings/taxonomy?tab=enrichment");

    await screen.findByTestId("enrichment-row-j1");
    await user.click(screen.getByTestId("enrichment-apply-j1"));
    await waitFor(() =>
      expect(mockedApi.post).toHaveBeenCalledWith("/admin/jobs/j1/enrichment/apply"),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("enrichment-row-j1")).not.toBeInTheDocument(),
    );

    await user.click(screen.getByTestId("enrichment-reject-j2"));
    expect(mockedApi.post).not.toHaveBeenCalledWith("/admin/jobs/j2/enrichment/reject");
    expect(screen.getByText("Discard this proposal?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByText("Discard this proposal?")).not.toBeInTheDocument(),
    );

    await user.click(screen.getByTestId("enrichment-reject-j2"));
    const confirm = await screen.findAllByRole("button", { name: "Discard" });
    await user.click(confirm[confirm.length - 1]);
    await waitFor(() =>
      expect(mockedApi.post).toHaveBeenCalledWith("/admin/jobs/j2/enrichment/reject"),
    );
  });

  it("shows the empty state without proposals", async () => {
    mockEnrichmentQueue([]);
    renderPage("/settings/taxonomy?tab=enrichment");

    expect(await screen.findByText("No enrichment proposals")).toBeInTheDocument();
  });
});

describe("Taxonomy enrichment bulk", () => {
  it("applies the selection through the batch endpoint", async () => {
    const user = userEvent.setup();
    mockEnrichmentQueue(ENRICHMENT);
    vi.mocked(bulkEnrichmentAction).mockResolvedValue({
      affected: ["j1"],
      failed: [],
    });
    renderPage("/settings/taxonomy?tab=enrichment");

    await screen.findByTestId("enrichment-row-j1");
    await user.click(screen.getByTestId("enrichment-select"));
    await user.click(
      screen.getByRole("checkbox", { name: "Select Software Developer" }),
    );
    await user.click(screen.getByTestId("enrichment-bulk-apply"));

    await waitFor(() =>
      expect(bulkEnrichmentAction).toHaveBeenCalledWith(["j1"], "apply"),
    );
    expect(await screen.findByText("1 proposal applied.")).toBeInTheDocument();
  });

  it("confirms the batch discard and keeps per-item failures visible", async () => {
    const user = userEvent.setup();
    mockEnrichmentQueue(ENRICHMENT);
    vi.mocked(bulkEnrichmentAction).mockResolvedValue({
      affected: [],
      failed: [{ id: "j1", reason: "proposal vanished" }],
    });
    renderPage("/settings/taxonomy?tab=enrichment");

    await screen.findByTestId("enrichment-row-j1");
    await user.click(screen.getByTestId("enrichment-select"));
    await user.click(
      screen.getByRole("checkbox", { name: "Select Software Developer" }),
    );
    await user.click(screen.getByTestId("enrichment-bulk-reject"));
    expect(bulkEnrichmentAction).not.toHaveBeenCalled();
    expect(screen.getByText("Discard 1 proposal?")).toBeInTheDocument();

    const confirm = await screen.findAllByRole("button", { name: "Discard" });
    await user.click(confirm[confirm.length - 1]);

    await waitFor(() =>
      expect(bulkEnrichmentAction).toHaveBeenCalledWith(["j1"], "reject"),
    );
    expect(
      await screen.findByTestId("taxonomy-bulk-failure-j1"),
    ).toHaveTextContent("proposal vanished");
  });
});

class MockIntersectionObserver {
  static latest: MockIntersectionObserver | null = null;
  private callback: IntersectionObserverCallback;

  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback;
    MockIntersectionObserver.latest = this;
  }

  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return [];
  }

  static triggerIntersecting() {
    MockIntersectionObserver.latest?.callback(
      [{ isIntersecting: true } as unknown as IntersectionObserverEntry],
      MockIntersectionObserver.latest as unknown as IntersectionObserver,
    );
  }
}

vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);

describe("Taxonomy queue paging (plan 206)", () => {
  it("appends the next enrichment window when the sentinel comes into view", async () => {
    let queueCalls = 0;
    mockedApi.get.mockImplementation(async (requested: string) => {
      if (requested === "/admin/jobs/enrichment") {
        queueCalls += 1;
        return {
          data:
            queueCalls === 1
              ? page([ENRICHMENT[0]], "cursor-1", 2)
              : page([SECOND_ENRICHMENT]),
        };
      }
      return defaultResponse(requested);
    });
    renderPage("/settings/taxonomy?tab=enrichment");

    await screen.findByTestId("enrichment-row-j1");
    expect(screen.getByTestId("enrichment-load-more-sentinel")).toBeInTheDocument();

    await act(async () => {
      MockIntersectionObserver.triggerIntersecting();
    });

    expect(await screen.findByTestId("enrichment-row-j2")).toBeInTheDocument();
    expect(screen.getByTestId("enrichment-row-j1")).toBeInTheDocument();
    expect(screen.queryByTestId("enrichment-load-more-sentinel")).not.toBeInTheDocument();

    const secondCall = mockedApi.get.mock.calls.filter(
      ([url]) => url === "/admin/jobs/enrichment",
    )[1];
    const secondConfig = secondCall?.[1] as { params?: { cursor?: string } } | undefined;
    expect(secondConfig?.params?.cursor).toBe("cursor-1");
  });

  it("keeps the loaded windows after a moderation decision", async () => {
    const user = userEvent.setup();
    mockEnrichmentQueue([ENRICHMENT[0], SECOND_ENRICHMENT]);
    renderPage("/settings/taxonomy?tab=enrichment");

    await screen.findByTestId("enrichment-row-j1");
    await user.click(screen.getByTestId("enrichment-apply-j1"));

    await waitFor(() =>
      expect(screen.queryByTestId("enrichment-row-j1")).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId("enrichment-row-j2")).toBeInTheDocument();
    const queueCalls = mockedApi.get.mock.calls.filter(
      ([url]) => url === "/admin/jobs/enrichment",
    );
    expect(queueCalls).toHaveLength(1);
  });

  it("tops the window up when a decision empties the loaded page", async () => {
    const user = userEvent.setup();
    let queueCalls = 0;
    mockedApi.get.mockImplementation(async (requested: string) => {
      if (requested === "/admin/jobs/enrichment") {
        queueCalls += 1;
        return {
          data:
            queueCalls === 1
              ? page([ENRICHMENT[0]], "cursor-1", 2)
              : page([SECOND_ENRICHMENT]),
        };
      }
      return defaultResponse(requested);
    });
    renderPage("/settings/taxonomy?tab=enrichment");

    await screen.findByTestId("enrichment-row-j1");
    await user.click(screen.getByTestId("enrichment-apply-j1"));

    expect(await screen.findByTestId("enrichment-row-j2")).toBeInTheDocument();
    expect(screen.queryByText("No enrichment proposals")).not.toBeInTheDocument();
  });

  it("auto-loads the next job proposal window, with the button as a fallback", async () => {
    const proposalRow = (id: string, ref: string) => ({
      id,
      ref,
      title: "Observability Engineer",
      org: "Acme",
      proposal: { title_norm: "Observability Engineer", skills: [] },
      proposed_at: THREE_DAYS_AGO,
      suggested_family_key: null,
      mapping_signals: null,
      extract_version: 5,
    });
    let proposalCalls = 0;
    mockedApi.get.mockImplementation(async (requested: string) => {
      if (requested === "/admin/postings/job-proposals") {
        proposalCalls += 1;
        return {
          data:
            proposalCalls === 1
              ? page([proposalRow("p1", "REF-1")], "proposal-cursor", 2)
              : page([proposalRow("p2", "REF-2")]),
        };
      }
      return defaultResponse(requested);
    });
    renderPage("/settings/taxonomy?tab=enrichment");

    await screen.findByTestId("job-proposal-row-p1");
    expect(screen.getByTestId("job-proposals-load-more-sentinel")).toBeInTheDocument();
    expect(screen.getByTestId("job-proposals-load-more")).toBeInTheDocument();

    await act(async () => {
      MockIntersectionObserver.triggerIntersecting();
    });

    expect(await screen.findByTestId("job-proposal-row-p2")).toBeInTheDocument();
    expect(screen.getByTestId("job-proposal-row-p1")).toBeInTheDocument();
    expect(screen.queryByTestId("job-proposals-load-more")).not.toBeInTheDocument();
  });
});
