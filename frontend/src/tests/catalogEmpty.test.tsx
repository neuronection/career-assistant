import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { Catalog } from "@/features/catalog/pages/Catalog";
import { CatalogTree } from "@/features/catalog/components/catalog/CatalogTree";
import { useCatalogStore } from "@/stores/catalogStore";
import { useAuthStore } from "@/stores/authStore";
import * as jobsApi from "@/api/jobs";
import * as providersApi from "@/api/providers";
import { fetchSearches } from "@/api/engagement";
import type { User } from "@/api/auth";

vi.mock("@/api/jobs", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/jobs")>();
  return { ...mod, fetchFamilyTree: vi.fn(), fetchJobs: vi.fn(), fetchGraph: vi.fn() };
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

vi.mock("@/api/providers", () => ({
  listAdminProviders: vi.fn(),
  installOfficialProvider: vi.fn(),
}));

const ADMIN = {
  id: "user-1",
  email: "admin@example.com",
  full_name: "Admin",
  is_active: true,
  is_admin: true,
} as User;

const COMMENTATOR = { ...ADMIN, id: "user-2", is_admin: false } as User;

const TILE = {
  id: "official-1",
  name: "Neuronection official — Job catalog",
  kind: "git",
  uri: "https://github.com/neuronection/career-assistant-seeds.git",
  ref: "v2026.11.25.3",
  subpath: "packs/neuronection/job-catalog",
  priority: 100,
  scope: "system",
  trust_tier: "official",
  refresh_minutes: 0,
  enabled: false,
  current_version: null,
  latest_version: null,
  pending_count: 0,
  item_counts: {},
  last_check_at: null,
  last_error: "",
  policy: {},
} as providersApi.AdminProvider;

function renderCatalog() {
  return render(
    <MemoryRouter initialEntries={["/catalog"]}>
      <Routes>
        <Route path="/catalog" element={<Catalog />}>
          <Route index element={<CatalogTree />} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useCatalogStore.setState({
    families: [],
    jobs: [],
    total: 0,
    facets: {},
    loading: false,
    filters: {},
  });
  useAuthStore.setState({ user: ADMIN, loading: false, status: "authenticated", error: null });
  vi.mocked(jobsApi.fetchFamilyTree).mockResolvedValue([]);
  vi.mocked(jobsApi.fetchJobs).mockResolvedValue({ items: [], total: 0, facets: {} });
  vi.mocked(fetchSearches).mockResolvedValue([]);
  vi.mocked(providersApi.listAdminProviders).mockResolvedValue([TILE]);
  vi.mocked(providersApi.installOfficialProvider).mockResolvedValue({
    status: "applied",
    run_id: "run-1",
    counts: { create: 45 },
    error: "",
    plan: null,
  } as providersApi.ProviderApply);
});

describe("empty catalog", () => {
  it("offers admins the one-click official catalog install", async () => {
    const user = userEvent.setup();
    renderCatalog();

    expect(await screen.findByTestId("catalog-empty")).toBeInTheDocument();
    await user.click(screen.getByTestId("catalog-load-official"));

    await waitFor(() =>
      expect(providersApi.installOfficialProvider).toHaveBeenCalledWith("official-1")
    );
    expect(jobsApi.fetchJobs).toHaveBeenCalledTimes(2);
  });

  it("tells non-admins to ask an administrator", async () => {
    useAuthStore.setState({
      user: COMMENTATOR,
      loading: false,
      status: "authenticated",
      error: null,
    });
    renderCatalog();

    expect(await screen.findByTestId("catalog-empty")).toBeInTheDocument();
    expect(screen.getByText(/Ask your administrator/i)).toBeInTheDocument();
    expect(screen.queryByTestId("catalog-load-official")).toBeNull();
  });
});
