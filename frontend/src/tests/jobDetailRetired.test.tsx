import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobDetail } from "@/features/catalog/pages/JobDetail";

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

vi.mock("@/api/jobs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/jobs")>();
  return {
    ...actual,
    fetchJob: vi.fn(),
    fetchJobRelations: vi.fn().mockResolvedValue([]),
    fetchSimilarJobs: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    fetchJobLivePostings: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    publishJob: vi.fn(),
  };
});
vi.mock("@/api/matching", () => ({
  fetchJobMatchDetail: vi.fn().mockResolvedValue({ insight: null, university_pathways: [] }),
  rateJob: vi.fn(),
  scoreJobForMe: vi.fn(),
}));
vi.mock("@/api/paths", () => ({
  fetchJobPathGraph: vi.fn().mockResolvedValue({ nodes: [] }),
  fetchJobPaths: vi.fn().mockResolvedValue([]),
}));
vi.mock("@/api/skills", () => ({ fetchSkillGaps: vi.fn().mockResolvedValue(null) }));
vi.mock("@/api/engagement", () => ({
  hideJob: vi.fn(),
  markSeen: vi.fn().mockResolvedValue(undefined),
  saveJob: vi.fn(),
}));
vi.mock("@/api/growth", () => ({
  fetchMarketSnapshot: vi.fn().mockResolvedValue(null),
  fetchMarketTrend: vi.fn().mockResolvedValue([]),
}));

import { fetchJob } from "@/api/jobs";
import { fetchSkillGaps } from "@/api/skills";

describe("JobDetail retired types", () => {
  beforeEach(() => {
    vi.mocked(fetchJob).mockResolvedValue({
      id: "job-1",
      code: "old-role",
      title: "Old Role",
      family_key: "tech",
      family_label: "Technology",
      short_description: "A retired type.",
      status: "retired",
      source: "seed",
      attributes: {},
      interests: [],
      skills: [],
      links: [],
      created_at: "2026-01-01T00:00:00Z",
      open_roles: 4,
      retired_into: { code: "new-role", title: "New Role" },
    } as never);
  });

  it("shows the retired banner and successor link on a retired type", async () => {
    render(
      <MemoryRouter initialEntries={["/jobs/old-role"]}>
        <Routes>
          <Route path="/jobs/:code" element={<JobDetail />} />
        </Routes>
      </MemoryRouter>,
    );

    const banner = await screen.findByTestId("job-retired-banner");
    expect(banner.textContent).toContain("jobDetail.retiredBanner");
    const successor = screen.getByRole("link", {
      name: "jobDetail.retiredSuccessor",
    });
    expect(successor.getAttribute("href")).toBe("/jobs/new-role");
    expect(screen.getByTestId("job-open-roles").textContent).toContain(
      "jobDetail.openRoles",
    );
    expect(screen.getByTestId("job-browse-postings").getAttribute("href")).toBe(
      "/postings?job=old-role",
    );
  });

  it("pins the warning and success token classes on skill-gap bars", async () => {
    vi.mocked(fetchSkillGaps).mockResolvedValue({
      job_id: "job-1",
      job_code: "old-role",
      job_title: "Old Role",
      gaps: [
        {
          skill_id: "s1",
          key: "sql",
          label: "SQL",
          required_level: 8,
          user_level: 4,
          delta: -4,
          importance: "core",
          suggestion: "Practice more.",
          next_step: null,
        },
        {
          skill_id: "s2",
          key: "python",
          label: "Python",
          required_level: 5,
          user_level: 6,
          delta: 1,
          importance: "important",
          suggestion: "Keep going.",
          next_step: null,
        },
      ],
    });
    render(
      <MemoryRouter initialEntries={["/jobs/old-role"]}>
        <Routes>
          <Route path="/jobs/:code" element={<JobDetail />} />
        </Routes>
      </MemoryRouter>,
    );

    const warning = await screen.findByTestId("job-gap-bar-sql");
    const success = await screen.findByTestId("job-gap-bar-python");
    expect(warning.className).toContain(
      "bg-[color-mix(in_srgb,var(--as-warning)_8%,transparent)]",
    );
    expect(success.className).toContain(
      "bg-[color-mix(in_srgb,var(--as-success)_8%,transparent)]",
    );
    expect(warning.className).not.toContain("transparent)]0");
    expect(success.className).not.toContain("transparent)]0");
  });
});
