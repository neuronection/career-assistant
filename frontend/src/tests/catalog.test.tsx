import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Navigate, Route, Routes } from "react-router-dom";

import { Catalog } from "@/pages/Catalog";
import { CatalogGraph } from "@/components/catalog/CatalogGraph";
import { CatalogTree } from "@/components/catalog/CatalogTree";
import { Generate } from "@/pages/Generate";
import { Universities } from "@/pages/Universities";
import { useCatalogStore } from "@/stores/catalogStore";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import * as jobsApi from "@/api/jobs";
import type { Job, JobFamilyNode } from "@/types";

vi.mock("@/api/jobs", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/jobs")>();
  return {
    ...mod,
    fetchFamilyTree: vi.fn(),
    fetchJobs: vi.fn(),
    fetchGraph: vi.fn(),
    generateJobs: vi.fn(),
    publishJob: vi.fn(),
  };
});

vi.mock("@/api/engagement", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/engagement")>();
  return {
    ...mod,
    recordSearch: vi.fn().mockResolvedValue(undefined),
    fetchSearches: vi.fn().mockResolvedValue([]),
    deleteSearch: vi.fn().mockResolvedValue(undefined),
  };
});

vi.mock("@/api/admin", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/admin")>();
  return {
    ...mod,
    fetchModerationQueue: vi.fn().mockResolvedValue([]),
  };
});

vi.mock("@/api/universities", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/universities")>();
  return {
    ...mod,
    fetchDocuments: vi.fn().mockResolvedValue([]),
    fetchUniversities: vi.fn().mockResolvedValue([]),
  };
});

const job = (over: Partial<Job> = {}): Job => ({
  id: "job-1",
  code: "software-developer",
  title: "Software Developer",
  family_key: "technology",
  short_description: "Builds software systems.",
  status: "published",
  source: "seed",
  attributes: {} as Job["attributes"],
  interests: [],
  skills: [],
  created_at: "2026-01-01T00:00:00Z",
  ...over,
});

const families: JobFamilyNode[] = [
  {
    id: "f1",
    key: "technology",
    label: "Technology",
    parent_id: null,
    path: "technology",
    level: 0,
    description: "",
    job_count: 2,
    children: [],
  },
  {
    id: "f2",
    key: "creative-arts",
    label: "Creative & Arts",
    parent_id: null,
    path: "creative-arts",
    level: 0,
    description: "",
    job_count: 1,
    children: [],
  },
];

function renderCatalog(initialEntries: string[] = ["/catalog"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Routes>
        <Route path="/catalog" element={<Catalog />}>
          <Route index element={<CatalogTree />} />
          <Route path="graph" element={<CatalogGraph />} />
          <Route path="generate" element={<Generate />} />
          <Route path="universities" element={<Universities />} />
        </Route>
        <Route path="/generate" element={<Navigate to="/catalog/generate" replace />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("Catalog subtabs", () => {
  beforeEach(() => {
    useCatalogStore.setState({ families: [], jobs: [], total: 0, loading: false, filters: {} });
    vi.mocked(jobsApi.fetchFamilyTree).mockResolvedValue(families);
    vi.mocked(jobsApi.fetchJobs).mockResolvedValue([
      job(),
      job({ id: "job-2", code: "ui-designer", title: "UI Designer", family_key: "creative-arts" }),
    ]);
    vi.mocked(jobsApi.fetchGraph).mockResolvedValue({
      nodes: [
        { id: "n1", code: "software-developer", title: "Software Developer", family_key: "technology", demand: "high" },
      ],
      edges: [],
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders the three subtabs with Tree active by default", async () => {
    renderCatalog();

    expect(screen.getByTestId("catalog-tab-tree")).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("catalog-tab-graph")).toBeInTheDocument();
    expect(screen.getByTestId("catalog-tab-generate")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Software Developer")).toBeInTheDocument());
  });

  it("shows the relation graph on the graph subtab", async () => {
    const user = userEvent.setup();
    renderCatalog();

    await user.click(screen.getByTestId("catalog-tab-graph"));

    await waitFor(() => expect(screen.getByTestId("relation-graph")).toBeInTheDocument());
    expect(jobsApi.fetchGraph).toHaveBeenCalled();
  });

  it("shows the AI generation UI on the generate subtab", async () => {
    const user = userEvent.setup();
    renderCatalog();

    await user.click(screen.getByTestId("catalog-tab-generate"));

    expect(await screen.findByTestId("generate")).toBeInTheDocument();
    expect(screen.getByText(/Invent it/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate" })).toBeInTheDocument();
  });

  it("redirects /generate into the catalog subtab", async () => {
    renderCatalog(["/generate"]);

    expect(await screen.findByTestId("generate")).toBeInTheDocument();
  });

  it("deep-links /catalog?family= to the filtered family", async () => {
    renderCatalog(["/catalog?family=creative-arts"]);

    await waitFor(() =>
      expect(jobsApi.fetchJobs).toHaveBeenCalledWith(expect.objectContaining({ family_key: "creative-arts" }))
    );
    await waitFor(() => expect(screen.getByText("Creative & Arts")).toBeInTheDocument());
    const familyButton = screen.getByRole("button", { name: /Creative & Arts/ });
    expect(familyButton).toHaveClass("font-medium");
  });

  it("shows the universities subtab (visible before bootstrap loads)", async () => {
    renderCatalog(["/catalog/universities"]);

    expect(screen.getByTestId("catalog-tab-universities")).toHaveAttribute("aria-current", "page");
    expect(await screen.findByTestId("universities")).toBeInTheDocument();
  });

  it("hides the universities subtab when the feature is off", () => {
    useBootstrapStore.getState().apply({
      career_stage: "student",
      stage_source: "derived",
      features: { universities: false, grade_fields: true, education_step: true },
    } as never);

    renderCatalog();

    expect(screen.queryByTestId("catalog-tab-universities")).not.toBeInTheDocument();
    useBootstrapStore.setState({ bootstrap: null });
  });
});
