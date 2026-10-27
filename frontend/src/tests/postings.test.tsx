import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Navigate, Route, Routes } from "react-router-dom";

import { Postings } from "@/features/postings/pages/Postings";
import { PostingsFeed } from "@/features/postings/components/postings/PostingsFeed";
import {
  fetchPostings,
  markPostingsSeen,
  markApplied,
  savePosting,
  searchPostings,
} from "@/api/postings";
import type { PostingOut } from "@/types/wire";

vi.mock("@/api/postings", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/postings")>();
  return {
    ...mod,
    fetchPostings: vi.fn(),
    markPostingsSeen: vi.fn().mockResolvedValue({ marked: 1 }),
    markApplied: vi.fn().mockResolvedValue(undefined),
    savePosting: vi.fn().mockResolvedValue(undefined),
    hidePosting: vi.fn().mockResolvedValue(undefined),
    searchPostings: vi.fn(),
    filterPostings: vi.fn().mockResolvedValue([]),
    fetchFilterPresets: vi.fn().mockResolvedValue([]),
    saveFilterPreset: vi.fn(),
    deleteFilterPreset: vi.fn(),
  };
});

vi.mock("@/api/skills", () => ({
  fetchSkillOntology: vi.fn().mockResolvedValue([
    // mirrors GET /skills — active rows, no `status` field
    { key: "programming", label: "Programming", category: "technical" },
    { key: "sql", label: "SQL", category: "technical" },
  ]),
}));

const mockFetchPostings = vi.mocked(fetchPostings);
const mockSearchPostings = vi.mocked(searchPostings);

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

describe("Postings live tab", () => {
  beforeEach(() => {
    mockFetchPostings.mockResolvedValue({
      items: [posting()],
      total: 1,
      unseen: 1,
    });
  });

  it("renders posting cards with source badge, fit and unseen count", async () => {
    render(
      <MemoryRouter>
        <PostingsFeed />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("postings")).toBeInTheDocument();
    expect(screen.getByTestId("posting-title")).toHaveTextContent("Backend Engineer");
    expect(screen.getByText("synth")).toBeInTheDocument();
    expect(screen.getByText(/1 new/)).toBeInTheDocument();
    expect(screen.getByText(/fit 7\.5/)).toBeInTheDocument();
  });

  it("marks seen and applied when applying through the original url", async () => {
    render(
      <MemoryRouter>
        <PostingsFeed />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByTestId("posting-apply"));
    await waitFor(() => expect(markPostingsSeen).toHaveBeenCalledWith(["p1"]));
    expect(markApplied).toHaveBeenCalledWith("p1", "https://jobs.example/1");
  });

  it("opens the posting detail page when the card is clicked", async () => {
    render(
      <MemoryRouter initialEntries={["/postings"]}>
        <Routes>
          <Route path="/postings" element={<PostingsFeed />} />
          <Route path="/postings/:ref" element={<div data-testid="detail-page" />} />
        </Routes>
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByTestId("posting-details"));
    expect(await screen.findByTestId("detail-page")).toBeInTheDocument();
  });

  it("toggles save and reloads", async () => {
    render(
      <MemoryRouter>
        <PostingsFeed />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByText("Save"));
    await waitFor(() => expect(savePosting).toHaveBeenCalledWith("p1", true));
    await waitFor(() =>
      expect(mockFetchPostings).toHaveBeenCalledWith(
        expect.objectContaining({ saved: false, sort: "fit" })
      )
    );
  });

  it("switches to the saved view", async () => {
    render(
      <MemoryRouter>
        <PostingsFeed />
      </MemoryRouter>
    );
    fireEvent.click(await screen.findByTestId("postings-saved-toggle"));
    await waitFor(() =>
      expect(mockFetchPostings).toHaveBeenCalledWith(
        expect.objectContaining({ saved: true })
      )
    );
  });
});

describe("Skill-level search & provenance", () => {
  beforeEach(() => {
    mockFetchPostings.mockResolvedValue({
      items: [posting()],
      total: 1,
      unseen: 1,
    });
    mockSearchPostings.mockResolvedValue({
      items: [posting({ id: "p2", coverage: 8.2 })],
      total: 1,
      unseen: 0,
    });
  });

  it("shows the provenance chip (raw / fast-mapped / extracted)", async () => {
    const first = render(
      <MemoryRouter>
        <PostingsFeed />
      </MemoryRouter>
    );
    const chip = await screen.findByTestId("posting-provenance");
    expect(chip).toHaveTextContent("raw"); // no mapping yet in this fixture
    first.unmount();

    mockFetchPostings.mockResolvedValue({
      items: [
        posting({ id: "p9", mapping_method: "skill_overlap", extract_version: 1 }),
      ],
      total: 1,
      unseen: 0,
    });
    render(
      <MemoryRouter>
        <PostingsFeed />
      </MemoryRouter>
    );
    const extracted = await screen.findByTestId("posting-provenance");
    expect(extracted).toHaveTextContent("extracted");
  });

  it("filters via the rail: skill + min level compose a filter spec", async () => {
    const { filterPostings } = await import("@/api/postings");
    const mockFilter = vi.mocked(filterPostings);
    mockFilter.mockResolvedValue([]);

    render(
      <MemoryRouter>
        <PostingsFeed />
      </MemoryRouter>
    );
    await screen.findByTestId("postings");

    // open the filter rail
    fireEvent.click(screen.getByText("Filters"));
    fireEvent.click(screen.getByText("Skills"));

    // type a skill and add it via the type-ahead
    const input = document.querySelector('[data-as="picker-input"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: "programming" } });
    const option = await screen.findByRole("option", { name: /Programming/ });
    fireEvent.click(option);

    // min level
    fireEvent.change(screen.getByLabelText("Min level"), {
      target: { value: "4" },
    });

    // graph expansion: sub-skills by default, related + 2 hops on request
    expect(screen.getByRole("tab", { name: "Sub-skills" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    fireEvent.click(screen.getByRole("tab", { name: "Related" }));
    fireEvent.click(screen.getByRole("button", { name: "2 hops" }));

    // the browse modal lists the ontology (regression: "No skills found")
    fireEvent.click(screen.getByRole("button", { name: /browse full catalog/i }));
    await waitFor(() =>
      expect(document.querySelector('[data-as="picker-browse-list"]')).toBeTruthy(),
    );
    const browseList = document.querySelector(
      '[data-as="picker-browse-list"]',
    ) as HTMLElement;
    expect(within(browseList).getByText("Programming")).toBeTruthy();
    expect(within(browseList).getByText("SQL")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /done/i }));

    // auto-apply (debounced) → the spec reaches the filter endpoint
    await waitFor(() => expect(mockFilter).toHaveBeenCalled(), { timeout: 3000 });
    const calls = mockFilter.mock.calls;
    const spec = calls[calls.length - 1]?.[0];
    expect(spec.skills.include).toContain("programming");
    expect(spec.skills.min_level).toBe(4);
    expect(spec.skills.expand).toBe("related");
    expect(spec.skills.hops).toBe(2);
  }, 10000);
});

describe("Postings shell", () => {
  it("redirects /explore into the search subtab and renders the feed by default", async () => {
    mockFetchPostings.mockResolvedValue({
      items: [],
      unseen: 0,
    } as never);
    render(
      <MemoryRouter initialEntries={["/explore"]}>
        <Routes>
          <Route path="/postings" element={<Postings />}>
            <Route index element={<PostingsFeed />} />
            <Route path="search" element={<div data-testid="explore-body" />} />
          </Route>
          <Route path="/explore" element={<Navigate to="/postings/search" replace />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByTestId("postings-page")).toBeInTheDocument();
    expect(screen.getByTestId("postings-tab-search")).toHaveAttribute("aria-current", "page");
  });
});
