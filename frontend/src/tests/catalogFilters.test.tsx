import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useSearchParams } from "react-router-dom";

import { Catalog } from "@/features/catalog/pages/Catalog";
import { CatalogTree } from "@/features/catalog/components/catalog/CatalogTree";
import { useCatalogStore } from "@/stores/catalogStore";
import * as jobsApi from "@/api/jobs";
import type { Job } from "@/types/wire";
import type { JobFamilyNode } from "@/types";

vi.mock("@/api/jobs", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/jobs")>();
  return {
    ...mod,
    fetchFamilyTree: vi.fn(),
    fetchJobs: vi.fn(),
    fetchGraph: vi.fn(),
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

vi.mock("@/api/skills", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/skills")>();
  return { ...mod, fetchSkillOntology: vi.fn().mockResolvedValue([]) };
});

const FACETS = {
  family: { technology: 2, "creative-arts": 0 },
  skills: { programming: 2, design: 1 },
  interests: { "technology-software": 2 },
  education: { bachelor: 2, master: 1, high_school: 0 },
  demand: { hot: 2, growing: 1, stable: 0, declining: 0 },
  contract: { permanent: 2, contract: 1, internship: 0 },
  schedule: { shift_work: 1, flexible: 1, nights: 0 },
  travel: { none: 2, occasional: 1, frequent: 0 },
  environment: { office: 2, remote: 1, lab: 0 },
  source: { seed: 2, ai: 1, user: 0 },
};

const job = (over: Partial<Job> = {}): Job => ({
  id: "job-1",
  code: "software-developer",
  title: "Software Developer",
  family_key: "technology",
  family_label: "",
  short_description: "Builds software systems.",
  status: "published",
  source: "seed",
  attributes: {} as Job["attributes"],
  interests: [],
  skills: [],
  created_at: "2026-01-01T00:00:00Z",
  open_roles: 2,
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

function SearchProbe() {
  const [params] = useSearchParams();
  return <output data-testid="search-probe">{params.toString()}</output>;
}

function renderCatalog(initialEntries: string[] = ["/catalog"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Routes>
        <Route
          path="/catalog"
          element={
            <>
              <Catalog />
              <SearchProbe />
            </>
          }
        >
          <Route index element={<CatalogTree />} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  useCatalogStore.setState({
    families: [],
    jobs: [],
    total: 0,
    facets: {},
    loading: false,
    filters: {},
  });
  vi.mocked(jobsApi.fetchFamilyTree).mockResolvedValue(families);
  vi.mocked(jobsApi.fetchJobs).mockResolvedValue({
    items: [job()],
    total: 1,
    facets: FACETS,
  });
});

describe("catalog filter rail", () => {
  it("cycles a tri-state facet include → exclude → clear through the URL", async () => {
    const user = userEvent.setup();
    renderCatalog();

    await user.click(await screen.findByRole("button", { name: "Demand" }));
    const hot = await screen.findByTestId("catalog-demand-hot");

    await user.click(hot);
    await waitFor(() => expect(screen.getByTestId("search-probe")).toHaveTextContent("demand=hot"));
    expect(hot).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByTestId("catalog-demand-hot"));
    await waitFor(() =>
      expect(screen.getByTestId("search-probe")).toHaveTextContent("demand_exclude=hot")
    );

    await user.click(screen.getByTestId("catalog-demand-hot-clear"));
    await waitFor(() => expect(screen.getByTestId("search-probe")).toHaveTextContent(""));
  });

  it("disables a zero-count facet value", async () => {
    const user = userEvent.setup();
    renderCatalog();

    await user.click(await screen.findByRole("button", { name: "Demand" }));
    expect(await screen.findByTestId("catalog-demand-stable")).toBeDisabled();
    expect(screen.getByTestId("catalog-demand-hot")).not.toBeDisabled();
  });

  it("keeps the family chip and the URL in sync", async () => {
    const user = userEvent.setup();
    renderCatalog();

    const chip = await screen.findByTestId("catalog-family-technology");
    await user.click(chip);
    await waitFor(() =>
      expect(jobsApi.fetchJobs).toHaveBeenCalledWith(
        expect.objectContaining({ family_key: "technology" })
      )
    );
    await waitFor(() =>
      expect(screen.getByTestId("search-probe")).toHaveTextContent("family=technology")
    );
    expect(screen.getByTestId("catalog-family-technology")).toHaveAttribute(
      "aria-pressed",
      "true"
    );

    await user.click(screen.getByTestId("catalog-family-technology"));
    await waitFor(() => expect(screen.getByTestId("search-probe")).toHaveTextContent(""));
  });

  it("swaps the sort and clears every active chip", async () => {
    const user = userEvent.setup();
    renderCatalog();

    await user.selectOptions(screen.getByTestId("catalog-sort"), "open_roles");
    await waitFor(() =>
      expect(jobsApi.fetchJobs).toHaveBeenCalledWith(
        expect.objectContaining({ sort: "open_roles" })
      )
    );
    expect(screen.getByTestId("search-probe")).toHaveTextContent("sort=open_roles");

    await user.click(await screen.findByRole("button", { name: "Demand" }));
    await user.click(await screen.findByTestId("catalog-demand-hot"));
    await user.click(await screen.findByRole("button", { name: "Education" }));
    await user.click(await screen.findByTestId("catalog-education-bachelor"));

    expect(await screen.findByTestId("catalog-chip-demand-hot")).toBeInTheDocument();
    expect(await screen.findByTestId("catalog-chip-education-bachelor")).toBeInTheDocument();

    await user.click(screen.getByTestId("catalog-clear-all"));
    await waitFor(() => expect(screen.getByTestId("search-probe")).toHaveTextContent(""));
    expect(screen.queryByTestId("catalog-chip-demand-hot")).not.toBeInTheDocument();
    expect(screen.queryByTestId("catalog-chip-education-bachelor")).not.toBeInTheDocument();
  });

  it("removes one summary chip without touching the others", async () => {
    const user = userEvent.setup();
    renderCatalog(["/catalog?demand=hot&education=bachelor"]);

    expect(await screen.findByTestId("catalog-chip-demand-hot")).toBeInTheDocument();
    await user.click(screen.getByTestId("catalog-chip-demand-hot"));
    await waitFor(() =>
      expect(screen.getByTestId("search-probe")).toHaveTextContent("education=bachelor")
    );
    expect(screen.getByTestId("catalog-chip-education-bachelor")).toBeInTheDocument();
  });

  it("canonicalizes an unknown parameter on mount", async () => {
    renderCatalog(["/catalog?nonsense=1&sort=fit"]);
    await waitFor(() => expect(screen.getByTestId("search-probe")).toHaveTextContent(""));
  });
});
