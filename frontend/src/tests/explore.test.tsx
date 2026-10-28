import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { Explore } from "@/features/catalog/pages/Explore";
import { explorePostings } from "@/api/postings";
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

vi.mock("@/components/ui", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/components/ui")>();
  const FakeCombobox = (props: { value?: string; onChange: (v: string) => void }) => (
    <input
      data-testid="skill-combobox"
      value={props.value ?? ""}
      onChange={(e) => props.onChange(e.target.value)}
    />
  );
  return { ...mod, SearchableDropdown: FakeCombobox };
});

const mockExplore = vi.mocked(explorePostings);
const mockRecord = vi.mocked(recordSearch);
const mockSave = vi.mocked(saveSearch);

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
});

describe("Explore page", () => {
  it("renders filters, facet badges and results", async () => {
    render(
      <MemoryRouter>
        <Explore />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("explore")).toBeInTheDocument();
    expect(await screen.findByTestId("posting-title")).toHaveTextContent(
      "Backend Engineer"
    );
    // facet badges drive the filter sidebar
    expect(screen.getByText("Mid-level · 2")).toBeInTheDocument();
    expect(screen.getByText("programming · 2")).toBeInTheDocument();
    expect((await screen.findAllByText("synth")).length).toBeGreaterThan(0);
  });

  it("passes v2 lifestyle filters to the API", async () => {
    mockExplore.mockResolvedValue(exploreResponse());
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <Explore />
      </MemoryRouter>
    );
    await screen.findByTestId("explore");

    await user.click(screen.getByTestId("contract-internship"));
    await user.click(screen.getByTestId("travel-none"));
    await user.click(screen.getByTestId("schedule-nights"));
    await user.type(screen.getByTestId("org-filter"), "Acme");

    await waitFor(() => {
      const call = mockExplore.mock.calls[mockExplore.mock.calls.length - 1][0];
      expect(call.contract).toBe("internship");
      expect(call.travel).toBe("none");
      expect(call.schedule).toBe("nights");
      expect(call.org).toBe("Acme");
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
    fireEvent.change(screen.getByTestId("skill-combobox"), {
      target: { value: "programming" },
    });
    fireEvent.change(screen.getByTestId("level-select"), {
      target: { value: "4" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add skill filter" }));
    fireEvent.change(screen.getByTestId("posted-within"), {
      target: { value: "7d" },
    });

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

    fireEvent.click(await screen.findByTestId("load-more"));
    await waitFor(() =>
      expect(mockExplore).toHaveBeenLastCalledWith(
        expect.objectContaining({ cursor: "abc" })
      )
    );
    // page 2 appended: 2 + 2 cards on screen
    expect(screen.getAllByTestId("posting-card")).toHaveLength(4);
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
