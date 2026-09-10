import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";

import { Compare } from "@/pages/Compare";
import { CompareTray } from "@/components/CompareTray";
import { compareJobs } from "@/api/matching";
import { COMPARE_LIMIT, useCompareStore } from "@/stores/compareStore";
import type { RankedJob } from "@/types";

vi.mock("@/api/matching", () => ({
  compareJobs: vi.fn(),
}));

const mockCompare = vi.mocked(compareJobs);

function row(overrides: Partial<RankedJob> & { job: RankedJob["job"] }): RankedJob {
  return {
    score: 7,
    fit_score: 7,
    ai_score: null,
    user_score: null,
    status: null,
    specialist_dimension: null,
    gated: false,
    gate_reasons: [],
    insight: null,
    breakdown: {
      dimensions: {
        skills: { score: 6, weight: 3, detail: "" },
        interests: { score: 5, weight: 3, detail: "" },
      },
      gates: [],
      specialist_dimension: null,
    },
    ...overrides,
  };
}

function job(id: string, code: string, title: string): RankedJob["job"] {
  return {
    id,
    code,
    title,
    family_key: "technology",
    short_description: "",
    status: "published",
    source: "seed",
    attributes: {
      subjects: [],
      work_style: {
        teamwork: 3,
        environment: 3,
        structure: 3,
        pace: 3,
        leadership: 3,
        physical_activity: "moderate",
      },
      education: { level: "bachelor", fields: [] },
      physical: { activity: "moderate", requirements: [] },
      salary: { currency: "USD", median: [40000, 60000], entry: null, senior: null },
      demand: { outlook: "growing", note: "", sources: {} },
      environments: ["office"],
      typical_positives: [],
      typical_negatives: [],
    } as RankedJob["job"]["attributes"],
    interests: [],
    skills: [],
    created_at: "2026-09-01T00:00:00Z",
  };
}

const rows: RankedJob[] = [
  row({
    job: job("id-a", "data-analyst", "Data Analyst"),
    fit_score: 7.2,
    breakdown: {
      dimensions: {
        skills: { score: 8, weight: 3, detail: "" },
        interests: { score: 5, weight: 3, detail: "" },
      },
      gates: [],
      specialist_dimension: null,
    },
  }),
  row({
    job: job("id-b", "nurse", "Nurse"),
    fit_score: 5.1,
    gated: true,
    gate_reasons: ["education_years"],
    breakdown: {
      dimensions: {
        skills: { score: 3, weight: 3, detail: "" },
        interests: { score: 6, weight: 3, detail: "" },
      },
      gates: ["education_years"],
      specialist_dimension: null,
    },
  }),
];

beforeEach(() => {
  useCompareStore.setState({ items: [] });
  vi.clearAllMocks();
});

describe("compareStore", () => {
  it("caps the tray at the limit, dropping the oldest pick", () => {
    const { toggle } = useCompareStore.getState();
    for (let i = 0; i < COMPARE_LIMIT + 1; i++) {
      toggle({ id: `job-${i}`, title: `Job ${i}` });
    }
    const items = useCompareStore.getState().items;
    expect(items).toHaveLength(COMPARE_LIMIT);
    expect(items[0].id).toBe("job-1");
    expect(items.some((i) => i.id === "job-0")).toBe(false);
  });

  it("toggle removes an already-picked job", () => {
    const { toggle } = useCompareStore.getState();
    toggle({ id: "a", title: "A" });
    toggle({ id: "a", title: "A" });
    expect(useCompareStore.getState().items).toHaveLength(0);
  });
});

describe("CompareTray", () => {
  function LocationProbe() {
    const location = useLocation();
    return <span data-testid="probe">{location.pathname + location.search}</span>;
  }

  it("renders chips and navigates to the compare page", () => {
    useCompareStore.setState({
      items: [
        { id: "id-a", title: "Data Analyst" },
        { id: "id-b", title: "Nurse" },
      ],
    });
    render(
      <MemoryRouter initialEntries={["/rankings"]}>
        <CompareTray />
        <Routes>
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    );
    expect(screen.getByTestId("compare-tray")).toBeTruthy();
    expect(screen.getByText("Data Analyst")).toBeTruthy();
    fireEvent.click(screen.getByTestId("compare-open"));
    expect(screen.getByTestId("probe")).toHaveTextContent("/compare?jobs=id-a,id-b");
  });

  it("hides the tray on the compare page itself", () => {
    useCompareStore.setState({ items: [{ id: "id-a", title: "Data Analyst" }] });
    render(
      <MemoryRouter initialEntries={["/compare?jobs=id-a"]}>
        <CompareTray />
      </MemoryRouter>
    );
    expect(screen.queryByTestId("compare-tray")).toBeNull();
  });
});

describe("Compare page", () => {
  it("renders one column per job with request order, dimension rows and gate chips", async () => {
    mockCompare.mockResolvedValue(rows);
    render(
      <MemoryRouter initialEntries={["/compare?jobs=id-a,id-b"]}>
        <Compare />
      </MemoryRouter>
    );
    await waitFor(() => expect(screen.getByTestId("compare-table")).toBeTruthy());

    const cols = screen.getByTestId("compare-table").querySelectorAll("[data-testid^='compare-col-']");
    expect(cols).toHaveLength(2);
    expect(cols[0]).toHaveTextContent("Data Analyst");
    expect(cols[1]).toHaveTextContent("Nurse");
    expect(screen.getByText("education_years")).toBeTruthy();

    expect(screen.getByTestId("compare-cell-skills-id-a").getAttribute("data-best")).toBe("true");
    expect(screen.getByTestId("compare-cell-skills-id-b").getAttribute("data-best")).toBe("false");
    expect(screen.getByTestId("compare-cell-interests-id-b").getAttribute("data-best")).toBe("true");

    expect(screen.getByTestId("compare-overall-id-a").getAttribute("data-best")).toBe("true");
    expect(screen.getByTestId("compare-overall-id-b").getAttribute("data-best")).toBe("false");
    expect(mockCompare).toHaveBeenCalledWith(["id-a", "id-b"]);
  });

  it("shows the empty state for fewer than two ids and never calls the API", () => {
    render(
      <MemoryRouter initialEntries={["/compare?jobs=id-a"]}>
        <Compare />
      </MemoryRouter>
    );
    expect(screen.getByText("Nothing to compare")).toBeTruthy();
    expect(mockCompare).not.toHaveBeenCalled();
  });
});
