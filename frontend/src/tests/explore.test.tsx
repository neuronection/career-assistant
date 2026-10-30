import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { Explore } from "@/features/catalog/pages/Explore";
import { explorePostings } from "@/api/postings";
import { fetchCompanies } from "@/api/companies";
import { recordSearch, saveSearch } from "@/api/engagement";
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

vi.mock("@/api/engagement", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/engagement")>();
  return {
    ...mod,
    recordSearch: vi.fn().mockResolvedValue({ id: "s9" }),
    saveSearch: vi.fn().mockResolvedValue({ id: "s9", saved: true }),
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
const mockCompanies = vi.mocked(fetchCompanies);
const mockRecord = vi.mocked(recordSearch);
const mockSave = vi.mocked(saveSearch);

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

  it("saves the current filter set as a saved search", async () => {
    render(
      <MemoryRouter>
        <Explore />
      </MemoryRouter>
    );
    fireEvent.change(await screen.findByTestId("explore-q"), {
      target: { value: "engineer" },
    });
    const button = await screen.findByTestId("save-search");
    await waitFor(() => expect(button).not.toBeDisabled());
    fireEvent.click(button);
    await waitFor(() =>
      expect(mockRecord).toHaveBeenCalledWith(
        expect.objectContaining({
          scope: "postings",
          query: "engineer",
        })
      )
    );
    expect(mockSave).toHaveBeenCalledWith("s9");
    expect(await screen.findByTestId("saved-note")).toBeInTheDocument();
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
});
