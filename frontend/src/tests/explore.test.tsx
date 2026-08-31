import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { Explore } from "@/pages/Explore";
import { explorePostings, fetchPostingDetail } from "@/api/postings";
import { recordSearch, saveSearch } from "@/api/engagement";
import { PostingDetail } from "@/components/PostingDetail";
import type { ExploreResponse, JobPostingItem } from "@/types";

vi.mock("@/api/postings", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/postings")>();
  return {
    ...mod,
    explorePostings: vi.fn(),
    fetchPostingSources: vi.fn().mockResolvedValue([
      { key: "synth", connector_key: "synthetic", open_postings: 3 },
    ]),
    fetchPostingDetail: vi.fn(),
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

function posting(overrides: Partial<JobPostingItem> = {}): JobPostingItem {
  return {
    id: "p1",
    ref: "P3KX9Q2A",
    source_id: "s1",
    external_id: "ext-1",
    title: "Backend Engineer",
    org: "ACME",
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

describe("Explore page (plan 32)", () => {
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
    expect(screen.getByText("mid · 2")).toBeInTheDocument();
    expect(screen.getByText("programming · 2")).toBeInTheDocument();
    expect((await screen.findAllByText("synth")).length).toBeGreaterThan(0);
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

describe("PostingDetail match card (plan 32)", () => {
  it("renders the match score, source attribution, ref and similar rail", async () => {
    mockExplore.mockResolvedValue(exploreResponse());
    vi.mocked(fetchPostingDetail).mockResolvedValue(
      posting({
        match: {
          score: 7.8,
          breakdown: {
            skills: { score: 8.5, weight: 5, detail: "covered" },
            freshness: { score: 6.0, weight: 1, detail: "posted 2 weeks ago" },
          },
          extracted: true,
          estimate: false,
          inputs_hash: "abc",
        },
        source_title: "Synthetic test connector",
        source_connector: "synth",
        source_synced_at: "2026-08-30T00:00:00Z",
        similar: [
          { ref: "AAAA2222", title: "Data Analyst", org: "BetaCo", score: 0.72 },
        ],
        extract: {
          skills: [
            {
              skill_key: "programming",
              required_level: 5,
              priority: "must_have",
              evidence_quote: "strong programming required",
              confidence: 0.95,
            },
          ],
        },
      })
    );
    render(
      <MemoryRouter>
        <PostingDetail postingId="P3KX9Q2A" onClose={() => undefined} />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("match-score")).toHaveTextContent("7.8");
    const attribution = await screen.findByTestId("source-attribution");
    expect(attribution).toHaveTextContent("Synthetic test connector");
    expect(attribution).toHaveTextContent("original listing");
    expect(screen.getByTestId("posting-ref")).toHaveTextContent("P3KX9Q2A");
    expect(screen.getByTestId("similar-rail")).toHaveTextContent("Data Analyst");
  });

  it("flags the archetype estimate for unextracted postings", async () => {
    vi.mocked(fetchPostingDetail).mockResolvedValue(
      posting({
        match: {
          score: 6.4,
          breakdown: {
            archetype_estimate: {
              score: 6.4,
              weight: 5,
              detail: "archetype estimate — deep extraction has not run",
            },
          },
          extracted: false,
          estimate: true,
          inputs_hash: "abc",
        },
      })
    );
    render(
      <MemoryRouter>
        <PostingDetail postingId="P3KX9Q2A" onClose={() => undefined} />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("match-estimate-note")).toHaveTextContent(
      "archetype estimate"
    );
  });
});
