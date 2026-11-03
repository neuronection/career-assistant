import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { JobMatchRails } from "@/features/catalog/components/JobMatchRails";
import type { JobPostings, SimilarJobs } from "@/types/wire";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      const templates: Record<string, string> = {
        "jobDetail.matchDegraded": "Showing the lexical fallback ({{reason}}).",
        "jobDetail.degradedReason.index_missing": "the vector index is not built yet",
      };
      let out = templates[key] ?? key;
      for (const [name, value] of Object.entries(params ?? {})) {
        out = out.split(`{{${name}}}`).join(String(value));
      }
      return out;
    },
    i18n: { language: "en" },
  }),
}));

vi.mock("@/api/jobs", () => ({
  fetchSimilarJobs: vi.fn(),
  fetchJobLivePostings: vi.fn(),
}));

const { fetchSimilarJobs, fetchJobLivePostings } = await import("@/api/jobs");
const similarMock = vi.mocked(fetchSimilarJobs);
const liveMock = vi.mocked(fetchJobLivePostings);

const similar: SimilarJobs = {
  items: [
    {
      code: "data-analyst",
      title: "Data Analyst",
      family_key: "data",
      family_label: "Data & Analytics",
      score: 0.82,
      per_view: {
        summary: 0.9,
        requirements: 0.75,
        responsibilities: 0.6,
        skills: 0.8,
      },
      source: "semantic",
    },
  ],
  source: "semantic",
  degraded: null,
  space_key: "content",
};

const live: JobPostings = {
  items: [
    {
      id: "00000000-0000-0000-0000-000000000001",
      ref: "ABC123",
      title: "Data Analyst",
      org: "Acme",
      posted_at: new Date().toISOString(),
      status: "new",
      catalog_job_id: null,
      score: 0.77,
      per_view: { summary: 0.7, requirements: 0.8 },
      source: "semantic",
    },
  ],
  source: "semantic",
  degraded: null,
};

const similarItem = similar.items![0]!;
const liveItem = live.items![0]!;

function renderRails() {
  return render(
    <MemoryRouter>
      <JobMatchRails jobCode="software-developer" />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  similarMock.mockResolvedValue(similar);
  liveMock.mockResolvedValue(live);
});

afterEach(() => {
  similarMock.mockReset();
  liveMock.mockReset();
});

describe("JobMatchRails", () => {
  it("renders the similar-jobs and live-postings cards", async () => {
    renderRails();
    await waitFor(() => expect(screen.getByTestId("job-similar-jobs")).toBeTruthy());
    await waitFor(() => expect(screen.getByTestId("job-live-postings")).toBeTruthy());
    expect(similarMock).toHaveBeenCalledWith("software-developer", { limit: 6 });
    expect(liveMock).toHaveBeenCalledWith("software-developer", { limit: 6 });
    expect(screen.getByTestId("similar-job-data-analyst").textContent).toContain(
      "Data Analyst",
    );
    expect(screen.getByTestId("similar-job-data-analyst").textContent).toContain(
      "data-analyst",
    );
    expect(screen.getByTestId("similar-job-data-analyst").textContent).toContain(
      "Data & Analytics",
    );
    expect(screen.getByTestId("live-posting-ABC123").textContent).toContain(
      "Data Analyst",
    );
    expect(screen.getByTestId("live-posting-ABC123").textContent).toContain("Acme");
    expect(screen.queryByTestId("similar-jobs-degraded")).toBeNull();
    expect(screen.queryByTestId("live-postings-degraded")).toBeNull();
  });

  it("labels the lexical fallback with the structured degraded reason", async () => {
    similarMock.mockResolvedValue({
      ...similar,
      source: "skill_overlap",
      degraded: "index_missing",
      items: [{ ...similarItem, source: "skill_overlap", per_view: {} }],
    });
    liveMock.mockResolvedValue({
      ...live,
      source: "catalog",
      degraded: "index_missing",
      items: [{ ...liveItem, source: "catalog", per_view: {} }],
    });
    renderRails();
    await waitFor(() =>
      expect(screen.getByTestId("similar-jobs-degraded").textContent).toContain(
        "the vector index is not built yet",
      ),
    );
    expect(screen.getByTestId("live-postings-degraded").textContent).toContain(
      "Showing the lexical fallback",
    );
  });

  it("opens a similar job drawer with the per-view cosine values", async () => {
    const user = userEvent.setup();
    renderRails();
    await user.click(await screen.findByTestId("similar-job-data-analyst"));
    await waitFor(() => expect(screen.getByTestId("job-match-drawer")).toBeTruthy());
    expect(screen.getByTestId("match-drawer-per-view")).toBeTruthy();
    expect(screen.getByTestId("match-view-summary").textContent).toContain("0.900");
    expect(screen.getByTestId("match-view-requirements").textContent).toContain(
      "0.750",
    );
    expect(screen.getByTestId("job-match-drawer-open").getAttribute("href")).toBe(
      "/jobs/data-analyst",
    );
  });

  it("opens a live posting drawer and links to the posting page", async () => {
    const user = userEvent.setup();
    renderRails();
    await user.click(await screen.findByTestId("live-posting-ABC123"));
    await waitFor(() => expect(screen.getByTestId("job-match-drawer")).toBeTruthy());
    expect(screen.getByTestId("match-view-summary").textContent).toContain("0.700");
    expect(screen.getByTestId("job-match-drawer-open").getAttribute("href")).toBe(
      "/postings/ABC123",
    );
  });

  it("shows the no-per-view note for a lexical item", async () => {
    const user = userEvent.setup();
    liveMock.mockResolvedValue({
      ...live,
      source: "catalog",
      degraded: null,
      items: [{ ...liveItem, source: "catalog", per_view: {} }],
    });
    renderRails();
    await user.click(await screen.findByTestId("live-posting-ABC123"));
    await waitFor(() =>
      expect(screen.getByTestId("match-drawer-no-per-view")).toBeTruthy(),
    );
  });

  it("exposes direct navigation links for both rails", async () => {
    renderRails();
    await waitFor(() => expect(screen.getByTestId("job-similar-jobs")).toBeTruthy());
    expect(screen.getByTestId("similar-job-open-data-analyst").getAttribute("href")).toBe(
      "/jobs/data-analyst",
    );
    expect(screen.getByTestId("live-posting-open-ABC123").getAttribute("href")).toBe(
      "/postings/ABC123",
    );
  });

  it("hides an empty rail", async () => {
    similarMock.mockResolvedValue({
      ...similar,
      items: [],
      source: "skill_overlap",
      degraded: "index_missing",
    });
    renderRails();
    await waitFor(() => expect(screen.getByTestId("job-live-postings")).toBeTruthy());
    expect(screen.queryByTestId("job-similar-jobs")).toBeNull();
  });

  it("hides a failed rail without breaking the other one", async () => {
    similarMock.mockRejectedValue(new Error("network"));
    renderRails();
    await waitFor(() => expect(screen.getByTestId("job-live-postings")).toBeTruthy());
    expect(screen.queryByTestId("job-similar-jobs")).toBeNull();
    expect(screen.queryByTestId("similar-jobs-degraded")).toBeNull();
  });
});
