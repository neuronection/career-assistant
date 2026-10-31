import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";

import { Explore } from "@/features/catalog/pages/Explore";
import { resetExploreListCache } from "@/features/catalog/exploreListCache";
import { explorePostings } from "@/api/postings";
import { recordSearch } from "@/api/engagement";
import { fetchCompanies } from "@/api/companies";
import type { ExploreResponse } from "@/types/wire";
import type { PostingOut } from "@/types/wire";

vi.mock("@/api/postings", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/postings")>();
  return {
    ...mod,
    explorePostings: vi.fn(),
    fetchPostingSources: vi.fn().mockResolvedValue([
      { key: "synth", connector_key: "synthetic", open_postings: 3 },
    ]),
  };
});

vi.mock("@/api/companies", () => ({
  fetchCompanies: vi.fn().mockResolvedValue([
    {
      key: "acme",
      name: "Acme Corp",
      status: "active",
      industry_tags: [],
      open_postings: 4,
      has_profile: false,
    },
  ]),
}));

vi.mock("@/api/skills", () => ({
  fetchSkillOntology: vi.fn().mockResolvedValue([
    { key: "programming", label: "Programming", status: "active" },
    { key: "sql", label: "SQL", status: "active" },
  ]),
}));

vi.mock("@/api/stats", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/stats")>();
  const pulse = {
    as_of: "2026-10-31T12:00:00Z",
    status_basis: "open" as const,
    new_24h: { count: 0, prev: 0, delta_pct: null, trend: "flat" as const },
    new_7d: { count: 0, prev: 0, delta_pct: null, trend: "flat" as const },
    new_30d: { count: 0, prev: 0, delta_pct: null, trend: "flat" as const },
    open_total: 0,
    sparkline: [],
    freshness: { as_of: "2026-10-31T12:00:00Z", stale_sources: [] },
  };
  return {
    ...actual,
    fetchPostingStatsSummary: vi.fn().mockResolvedValue(pulse),
    fetchPostingStatsSkills: vi.fn().mockResolvedValue({
      ...pulse,
      window: "30d",
      start: null,
      end: "2026-10-31T12:00:00Z",
      top: [],
      rising: [],
      falling: [],
      categories: [],
      levels: [],
      avg_level: null,
      priority: {},
      avg_skills_per_posting: 0,
    }),
    fetchPostingStatsBreakdown: vi.fn().mockResolvedValue({
      as_of: "2026-10-31T12:00:00Z",
      window: "30d",
      status_basis: "open",
      start: null,
      end: "2026-10-31T12:00:00Z",
      dimension: "source",
      total: 0,
      rows: [],
    }),
  };
});

vi.mock("@/api/engagement", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/engagement")>();
  return {
    ...mod,
    fetchSearches: vi.fn().mockResolvedValue([]),
    recordSearch: vi.fn().mockResolvedValue({ id: "s9", saved: true }),
    updateSearch: vi.fn().mockResolvedValue({ id: "s9" }),
    deleteSearch: vi.fn().mockResolvedValue(undefined),
  };
});

class MockIntersectionObserver {
  static latest: MockIntersectionObserver | null = null;
  private callback: IntersectionObserverCallback;
  observe = vi.fn();
  disconnect = vi.fn();
  unobserve = vi.fn();
  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback;
    MockIntersectionObserver.latest = this;
  }
  static triggerIntersecting() {
    MockIntersectionObserver.latest?.callback(
      [{ isIntersecting: true } as unknown as IntersectionObserverEntry],
      MockIntersectionObserver.latest as unknown as IntersectionObserver
    );
  }
}
vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);

const mockExplore = vi.mocked(explorePostings);
const mockRecord = vi.mocked(recordSearch);
const mockCompanies = vi.mocked(fetchCompanies);

async function pickFromPlaceholder(placeholder: string, query: string, optionName: RegExp | string) {
  const input = screen.getByPlaceholderText(placeholder);
  fireEvent.change(input, { target: { value: query } });
  const option = await screen.findByRole("option", { name: optionName });
  fireEvent.click(option);
}

function posting(overrides: Partial<PostingOut> = {}): PostingOut {
  return {
    id: "p1",
    ref: "P3KX9Q2A",
    source_id: "s1",
    external_id: "ext-1",
    title: "Backend Engineer",
    org: "ACME",
    org_key: "",
    location: { city: "Athens", country: "GR", remote: true },
    url: "https://jobs.example/1",
    seniority: "mid",
    posted_at: "2026-08-20T00:00:00Z",
    status: "mapped",
    fit: 7.5,
    seen: false,
    saved: false,
    notes: "",
    source_key: "synth",
    mapping_reason: "",
    needs_review: false,
    ...overrides,
  };
}

function exploreResponse(overrides: Partial<ExploreResponse> = {}): ExploreResponse {
  return {
    items: [posting()],
    total: 1,
    next_cursor: null,
    facets: {
      source: { synth: 3 },
      seniority: { mid: 2, senior: 1 },
      remote_policy: { remote: 2 },
      education: { bachelor: 2 },
      posted: { "7d": 1, older: 2 },
      skills: { programming: 2, sql: 1 },
    },
    ...overrides,
  };
}

beforeEach(() => {
  resetExploreListCache();
  mockExplore.mockResolvedValue(exploreResponse());
  mockCompanies.mockResolvedValue({
    items: [
    {
      key: "acme",
      name: "Acme Corp",
      status: "active",
      industry_tags: [],
      open_postings: 4,
      has_profile: false,
    },
    ],
    facets: null,
  });
});

function openSection(title: string) {
  fireEvent.click(screen.getByText(title));
}

describe("Explore page", () => {
  it("renders filters, facet counts and results", async () => {
    render(
      <MemoryRouter>
        <Explore />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("explore")).toBeInTheDocument();
    expect(await screen.findByTestId("posting-title")).toHaveTextContent(
      "Backend Engineer"
    );
    openSection("Seniority");
    openSection("Sources");
    // facet counts ride the tri-state chips
    expect(screen.getByTestId("seniority-mid")).toHaveTextContent("Mid-level");
    expect(screen.getByTestId("seniority-mid")).toHaveTextContent("2");
    expect(screen.getByText("programming · 2")).toBeInTheDocument();
    expect(screen.getByTestId("source-synth")).toHaveTextContent("synth");
  });

  it("passes v2 lifestyle filters and the org picker to the API", async () => {
    mockExplore.mockResolvedValue(exploreResponse());
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <Explore />
      </MemoryRouter>
    );
    await screen.findByTestId("explore");

    openSection("Contract");
    openSection("Travel");
    openSection("Schedule");
    openSection("Organization");
    await user.click(screen.getByTestId("contract-internship"));
    await user.click(screen.getByTestId("travel-none"));
    await user.click(screen.getByTestId("schedule-nights"));
    await pickFromPlaceholder("Add organization…", "Acme", /Acme Corp/);

    await waitFor(() => {
      const call = mockExplore.mock.calls[mockExplore.mock.calls.length - 1][0];
      expect(call.contract).toBe("internship");
      expect(call.travel).toBe("none");
      expect(call.schedule).toBe("nights");
      expect(call.org).toEqual(["Acme Corp"]);
    });
  });

  it("applies the q + skills + window filters and loads more pages", async () => {
    const page = (cursor: string | null, ids: string[]) => ({
      items: ids.map((id, i) => posting({ id, ref: `REF${i}0000` })),
      total: 4,
      next_cursor: cursor,
      facets: {},
    });
    mockExplore.mockImplementation(async (params) =>
      (params as { cursor?: string })?.cursor
        ? page(null, ["p3", "p4"])
        : page("abc", ["p1", "p2"])
    );
    render(
      <MemoryRouter>
        <Explore />
      </MemoryRouter>
    );
    await screen.findByTestId("explore");

    fireEvent.change(screen.getByTestId("explore-q"), {
      target: { value: "engineer" },
    });
    await pickFromPlaceholder("Add skill…", "prog", /Programming/);
    fireEvent.change(await screen.findByTestId("skill-level-programming"), {
      target: { value: "4" },
    });
    openSection("Posted");
    fireEvent.click(screen.getByTestId("posted-7d"));

    await waitFor(() =>
      expect(mockExplore).toHaveBeenLastCalledWith(
        expect.objectContaining({
          q: "engineer",
          skills: "programming:4",
          posted_within: "7d",
          sort: "fit",
        })
      )
    );

    // infinite scroll: reaching the sentinel auto-loads the next page —
    // there is no load-more button anymore
    expect(screen.queryByTestId("load-more")).not.toBeInTheDocument();
    MockIntersectionObserver.triggerIntersecting();
    await waitFor(() =>
      expect(mockExplore).toHaveBeenLastCalledWith(
        expect.objectContaining({ cursor: "abc" })
      )
    );
    // page 2 appended: 2 + 2 cards on screen
    expect(screen.getAllByTestId("posting-card")).toHaveLength(4);
  });

  it("inverts a seniority facet into an exclude on the second click", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <Explore />
      </MemoryRouter>
    );
    await screen.findByTestId("explore");

    openSection("Seniority");
    await user.click(screen.getByTestId("seniority-mid"));
    await waitFor(() =>
      expect(mockExplore).toHaveBeenLastCalledWith(
        expect.objectContaining({ seniority: "mid" })
      )
    );
    await user.click(screen.getByTestId("seniority-mid"));
    await waitFor(() =>
      expect(mockExplore).toHaveBeenLastCalledWith(
        expect.objectContaining({ seniority_exclude: "mid" })
      )
    );
    const call = mockExplore.mock.calls[mockExplore.mock.calls.length - 1][0];
    expect(call.seniority).toBeUndefined();

    // third click clears the value entirely (off → include → exclude → off)
    await user.click(screen.getByTestId("seniority-mid"));
    await waitFor(() => {
      const cleared = mockExplore.mock.calls[mockExplore.mock.calls.length - 1][0];
      expect(cleared.seniority).toBeUndefined();
      expect(cleared.seniority_exclude).toBeUndefined();
    });
  });

  it("clears a selected chip from its remove button", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <Explore />
      </MemoryRouter>
    );
    await screen.findByTestId("explore");
    openSection("Seniority");
    await user.click(screen.getByTestId("seniority-mid"));
    await waitFor(() =>
      expect(screen.getByTestId("seniority-mid")).toHaveAttribute("aria-pressed", "true")
    );
    await user.click(screen.getByTestId("seniority-mid-clear"));
    await waitFor(() => {
      const call = mockExplore.mock.calls[mockExplore.mock.calls.length - 1][0];
      expect(call.seniority).toBeUndefined();
      expect(call.seniority_exclude).toBeUndefined();
    });
    expect(screen.getByTestId("seniority-mid")).toHaveAttribute("aria-pressed", "false");
  });

  it("excludes skills, sources and organizations", async () => {
    render(
      <MemoryRouter>
        <Explore />
      </MemoryRouter>
    );
    await screen.findByTestId("explore");

    openSection("Organization");
    openSection("Sources");
    await pickFromPlaceholder("Exclude skill…", "prog", /Programming/);
    await waitFor(() =>
      expect(mockExplore).toHaveBeenLastCalledWith(
        expect.objectContaining({ skill_exclude: "programming" })
      )
    );

    // right-click excludes directly
    fireEvent.contextMenu(screen.getByTestId("source-synth"));
    await waitFor(() =>
      expect(mockExplore).toHaveBeenLastCalledWith(
        expect.objectContaining({ source_exclude: "synth" })
      )
    );

    await pickFromPlaceholder("Exclude organization…", "Acme", /Acme Corp/);
    await waitFor(() =>
      expect(mockExplore).toHaveBeenLastCalledWith(
        expect.objectContaining({ org_exclude: ["Acme Corp"] })
      )
    );
  });

  it("renders excluded skills and organizations as excluded chips", async () => {
    render(
      <MemoryRouter
        initialEntries={["/postings?skill_exclude=java&org_exclude=Acme%2C+Inc."]}
      >
        <Explore />
      </MemoryRouter>
    );
    await screen.findByTestId("explore");
    const excludedPickers = document.querySelectorAll(".ca-picker-exclude");
    expect(excludedPickers).toHaveLength(2);
    const skillChip = screen.getByText("java").closest("li");
    expect(skillChip).toHaveTextContent("−java");
    expect(excludedPickers[0]).toContainElement(skillChip as HTMLElement);
    const orgChip = screen.getByText("Acme, Inc.").closest("li");
    expect(orgChip).toHaveTextContent("−Acme, Inc.");
    expect(excludedPickers[1]).toContainElement(orgChip as HTMLElement);
  });

  it("shows the preset bar and saves the current view", async () => {
    render(
      <MemoryRouter>
        <Explore />
        <LocationProbe />
      </MemoryRouter>
    );
    await screen.findByTestId("preset-bar");
    fireEvent.change(await screen.findByTestId("explore-q"), {
      target: { value: "engineer" },
    });
    const save = screen.getByTestId("preset-save");
    await waitFor(() => expect(save).not.toBeDisabled());
    fireEvent.click(save);
    fireEvent.change(await screen.findByTestId("preset-name-input"), {
      target: { value: "Engineer" },
    });
    fireEvent.click(screen.getByTestId("preset-save-confirm"));
    await waitFor(() =>
      expect(mockRecord).toHaveBeenCalledWith(
        expect.objectContaining({
          scope: "postings",
          query: "engineer",
          saved: true,
          name: "Engineer",
          filters: expect.objectContaining({ q: "engineer" }),
        })
      )
    );
    expect(await screen.findByTestId("preset-note")).toHaveTextContent("Preset saved");
  });

  it("clears all filters", async () => {
    render(
      <MemoryRouter>
        <Explore />
      </MemoryRouter>
    );
    fireEvent.change(await screen.findByTestId("explore-q"), {
      target: { value: "engineer" },
    });
    fireEvent.click(await screen.findByTestId("clear-filters"));
    expect(screen.getByTestId("explore-q")).toHaveValue("");
  });

  it("excludes seen postings from the filter rail", async () => {
    render(
      <MemoryRouter>
        <Explore />
      </MemoryRouter>
    );
    await screen.findByTestId("explore");
    expect(mockExplore).toHaveBeenLastCalledWith(
      expect.not.objectContaining({ seen_exclude: expect.anything() })
    );
    fireEvent.click(screen.getByTestId("seen-exclude"));
    await waitFor(() =>
      expect(mockExplore).toHaveBeenLastCalledWith(
        expect.objectContaining({ seen_exclude: true })
      )
    );
    expect(screen.getByTestId("explore-filter-count")).toHaveTextContent("1");
  });

  it("sorts from the results toolbar and offers relevance only with a query", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <Explore />
      </MemoryRouter>
    );
    await screen.findByTestId("explore");

    await user.click(screen.getByRole("combobox", { name: "Sort" }));
    expect(screen.queryByRole("option", { name: "Relevance" })).not.toBeInTheDocument();
    await user.click(await screen.findByRole("option", { name: "Highest salary" }));
    await waitFor(() =>
      expect(mockExplore).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: "salary" })
      )
    );

    fireEvent.change(screen.getByTestId("explore-q"), { target: { value: "engineer" } });
    await user.click(screen.getByRole("combobox", { name: "Sort" }));
    await user.click(await screen.findByRole("option", { name: "Relevance" }));
    await waitFor(() =>
      expect(mockExplore).toHaveBeenLastCalledWith(
        expect.objectContaining({ q: "engineer", sort: "relevance" })
      )
    );

    fireEvent.change(screen.getByTestId("explore-q"), { target: { value: "" } });
    await waitFor(() =>
      expect(mockExplore).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: "fit" })
      )
    );
  });

  it("restores sort and filters from the URL on load", async () => {
    render(
      <MemoryRouter
        initialEntries={["/postings?sort=salary&q=engineer&seniority=mid&seen_exclude=true"]}
      >
        <Explore />
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(mockExplore).toHaveBeenLastCalledWith(
        expect.objectContaining({
          sort: "salary",
          q: "engineer",
          seniority: "mid",
          seen_exclude: true,
        })
      )
    );
    expect(screen.getByTestId("explore-q")).toHaveValue("engineer");
    expect(screen.getByTestId("seen-exclude")).toBeChecked();
  });

  it("writes sort and filter changes back to the URL", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/postings"]}>
        <Explore />
        <LocationProbe />
      </MemoryRouter>
    );
    await screen.findByTestId("explore");

    fireEvent.click(screen.getByTestId("seen-exclude"));
    await waitFor(() =>
      expect(screen.getByTestId("location-search").textContent).toContain("seen_exclude=true")
    );

    await user.click(screen.getByRole("combobox", { name: "Sort" }));
    await user.click(await screen.findByRole("option", { name: "Newest" }));
    await waitFor(() => {
      const search = screen.getByTestId("location-search").textContent ?? "";
      expect(search).toContain("sort=fresh");
      expect(search).toContain("seen_exclude=true");
    });

    fireEvent.click(screen.getByTestId("clear-filters"));
    await waitFor(() =>
      expect(screen.getByTestId("location-search").textContent).toBe("")
    );
    expect(screen.getByTestId("seen-exclude")).not.toBeChecked();
  });
});

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location-search">{location.search}</span>;
}
