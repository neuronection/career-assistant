import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";

import { Explore } from "@/features/catalog/pages/Explore";
import {
  dropExploreListPosting,
  patchExploreListPosting,
  peekExploreList,
  rememberExploreList,
  resetExploreListCache,
} from "@/features/catalog/exploreListCache";
import { explorePostings } from "@/api/postings";
import type { ExploreResponse } from "@/types/wire";
import type { PostingOut } from "@/types/wire";

vi.mock("@/api/postings", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/postings")>();
  return {
    ...mod,
    explorePostings: vi.fn(),
    fetchPostingSources: vi.fn().mockResolvedValue([]),
  };
});

vi.mock("@/api/companies", () => ({
  fetchCompanies: vi.fn().mockResolvedValue({ items: [], facets: null }),
}));

vi.mock("@/api/skills", () => ({
  fetchSkillOntology: vi.fn().mockResolvedValue([]),
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
      ...pulse,
      window: "30d",
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
  };
});

class MockIntersectionObserver {
  static latest: MockIntersectionObserver | null = null;
  observe = vi.fn();
  disconnect = vi.fn();
  unobserve = vi.fn();
  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback;
    MockIntersectionObserver.latest = this;
  }
  callback: IntersectionObserverCallback;
  static triggerIntersecting() {
    MockIntersectionObserver.latest?.callback(
      [{ isIntersecting: true } as unknown as IntersectionObserverEntry],
      MockIntersectionObserver.latest as unknown as IntersectionObserver
    );
  }
}
vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);

const mockExplore = vi.mocked(explorePostings);

function posting(overrides: Partial<PostingOut> = {}): PostingOut {
  return {
    id: "p1",
    ref: "REF00001",
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
    facets: {},
    ...overrides,
  };
}

function renderExplore(entry = "/postings") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Explore />
    </MemoryRouter>
  );
}

function PushProbe() {
  const navigate = useNavigate();
  return <button onClick={() => navigate("/postings")}>open-postings</button>;
}

describe("Explore list restore (plan 172)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetExploreListCache();
  });

  it("restores the loaded pages without refetching on return", async () => {
    mockExplore
      .mockResolvedValueOnce(
        exploreResponse({
          items: [posting({ id: "p1", ref: "REF00001", title: "Page one" })],
          total: 2,
          next_cursor: "c1",
        })
      )
      .mockResolvedValueOnce(
        exploreResponse({
          items: [posting({ id: "p2", ref: "REF00002", title: "Page two" })],
          total: 2,
          next_cursor: null,
        })
      );

    const firstView = renderExplore();
    expect(await screen.findByText("Page one")).toBeInTheDocument();
    expect(mockExplore).toHaveBeenCalledTimes(1);

    MockIntersectionObserver.triggerIntersecting();
    expect(await screen.findByText("Page two")).toBeInTheDocument();
    expect(mockExplore).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Page one")).toBeInTheDocument();

    firstView.unmount();
    const callsBeforeReturn = mockExplore.mock.calls.length;

    renderExplore();
    expect(screen.getByText("Page one")).toBeInTheDocument();
    expect(screen.getByText("Page two")).toBeInTheDocument();
    expect(mockExplore.mock.calls.length).toBe(callsBeforeReturn);

    await waitFor(() => {
      expect(mockExplore.mock.calls.length).toBe(callsBeforeReturn);
    });
  });

  it("a filter change refetches page one and drops the restored snapshot", async () => {
    const user = userEvent.setup();
    mockExplore.mockResolvedValue(
      exploreResponse({
        items: [posting({ id: "p1", ref: "REF00001", title: "Fresh" })],
        total: 1,
        next_cursor: null,
      })
    );

    const firstView = renderExplore();
    expect(await screen.findByText("Fresh")).toBeInTheDocument();
    firstView.unmount();

    renderExplore();
    expect(screen.getByText("Fresh")).toBeInTheDocument();
    const calls = mockExplore.mock.calls.length;

    await user.type(screen.getByTestId("explore-q"), "rust");
    await waitFor(() => {
      expect(mockExplore.mock.calls.length).toBeGreaterThan(calls);
    });
    const lastCall = mockExplore.mock.calls[mockExplore.mock.calls.length - 1][0];
    expect(lastCall.q).toBe("rust");
  });

  it("a restored cursor keeps paginating where the session left off", async () => {
    mockExplore
      .mockResolvedValueOnce(
        exploreResponse({
          items: [posting({ id: "p1", ref: "REF00001", title: "Page one" })],
          total: 3,
          next_cursor: "c1",
        })
      )
      .mockResolvedValueOnce(
        exploreResponse({
          items: [posting({ id: "p2", ref: "REF00002", title: "Page two" })],
          total: 3,
          next_cursor: "c2",
        })
      )
      .mockResolvedValueOnce(
        exploreResponse({
          items: [posting({ id: "p3", ref: "REF00003", title: "Page three" })],
          total: 3,
          next_cursor: null,
        })
      );

    const firstView = renderExplore();
    expect(await screen.findByText("Page one")).toBeInTheDocument();
    MockIntersectionObserver.triggerIntersecting();
    expect(await screen.findByText("Page two")).toBeInTheDocument();
    expect(mockExplore).toHaveBeenCalledTimes(2);

    firstView.unmount();

    renderExplore();
    expect(screen.getByText("Page one")).toBeInTheDocument();
    expect(screen.getByText("Page two")).toBeInTheDocument();
    expect(mockExplore).toHaveBeenCalledTimes(2);

    MockIntersectionObserver.triggerIntersecting();
    expect(await screen.findByText("Page three")).toBeInTheDocument();
    expect(mockExplore).toHaveBeenCalledTimes(3);
    expect(mockExplore.mock.calls[2][0].cursor).toBe("c2");
  });

  it("a fresh navigation refetches instead of serving the session snapshot", async () => {
    rememberExploreList("0|", {
      items: [posting({ id: "p9", ref: "REF00009", title: "Stale snapshot" })],
      total: 1,
      facets: {},
      nextCursor: null,
    });
    mockExplore.mockResolvedValue(
      exploreResponse({
        items: [posting({ id: "p1", ref: "REF00001", title: "Fresh fetch" })],
      })
    );

    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<PushProbe />} />
          <Route path="/postings" element={<Explore />} />
        </Routes>
      </MemoryRouter>
    );
    fireEvent.click(screen.getByText("open-postings"));

    expect(await screen.findByText("Fresh fetch")).toBeInTheDocument();
    expect(screen.queryByText("Stale snapshot")).not.toBeInTheDocument();
    expect(mockExplore).toHaveBeenCalledTimes(1);
  });

  it("cache mutators keep the snapshot honest (drop + patch)", () => {
    rememberExploreList("0|", {
      items: [posting({ id: "p1" }), posting({ id: "p2" })],
      total: 5,
      facets: {},
      nextCursor: "c9",
    });

    patchExploreListPosting("p1", { seen: true, saved: true });
    const snapshot = peekExploreList("0|");
    expect(snapshot?.items[0].seen).toBe(true);
    expect(snapshot?.items[0].saved).toBe(true);
    expect(snapshot?.items[1].seen).toBe(false);

    dropExploreListPosting("p2");
    expect(peekExploreList("0|")?.items.map((item) => item.id)).toEqual(["p1"]);
    expect(peekExploreList("0|")?.total).toBe(4);
  });
});
