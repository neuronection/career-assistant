import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProviderHub } from "@/components/settings/providers/ProviderHub";
import * as providersApi from "@/api/providers";

const PROVIDER = {
  id: "provider-1",
  name: "Neuronection official",
  kind: "git",
  uri: "https://github.com/neuronection/career-assistant-seeds.git",
  ref: "v2026.11.25.2",
  subpath: "packs/neuronection/greece-ats",
  priority: 100,
  scope: "system",
  trust_tier: "official",
  refresh_minutes: 0,
  enabled: true,
  current_version: {
    id: "version-1",
    pack_version: "1.2.0",
    status: "approved",
    digest: `sha256:${"a".repeat(64)}`,
    commit_sha: "e2f489cf10f9",
    created_at: "2026-11-24T20:00:00Z",
    approved_at: "2026-11-24T20:00:00Z",
  },
  latest_version: {
    id: "version-1",
    pack_version: "1.2.0",
    status: "approved",
    digest: `sha256:${"a".repeat(64)}`,
    commit_sha: "e2f489cf10f9",
    created_at: "2026-11-24T20:00:00Z",
    approved_at: "2026-11-24T20:00:00Z",
  },
  pending_count: 1,
  item_counts: { presets: 17, endpoints: 8 },
  last_check_at: "2026-11-24T20:00:00Z",
  last_error: "",
  policy: {},
} as providersApi.AdminProvider;

const PENDING = {
  id: "version-2",
  source_id: "provider-1",
  pack_version: "1.3.0",
  status: "pending",
  digest: `sha256:${"b".repeat(64)}`,
  commit_sha: "f".repeat(40),
  etag: "",
  schema_version: "1.0",
  reason: "",
  contract_version: "1.0",
  created_at: "2026-11-25T08:00:00Z",
  approved_at: null,
} as providersApi.ProviderVersion;

const CURRENT_VERSION = {
  id: "version-1",
  source_id: "provider-1",
  pack_version: "1.2.0",
  status: "approved",
  digest: `sha256:${"a".repeat(64)}`,
  commit_sha: "e2f489cf10f9",
  etag: "",
  schema_version: "1.0",
  reason: "",
  contract_version: "1.0",
  created_at: "2026-11-24T20:00:00Z",
  approved_at: "2026-11-24T20:00:00Z",
} as providersApi.ProviderVersion;

const APPROVED = { ...PENDING, status: "approved" } as providersApi.ProviderVersion;

const DETAIL = {
  ...PROVIDER,
  versions: [PROVIDER.current_version],
  presets: [
    {
      seed_key: "ats-preset:acme",
      slug: "acme",
      name: "Acme",
      connector_key: "recruitee",
      platform: "Recruitee",
      category: "ats",
      country: "GR",
      countries: ["GR"],
      regions: [],
      worldwide: false,
      languages: [],
      work_modes: [],
      homepage: null,
      openings: 3,
      verified_at: "2026-11-23",
      config: { company: "acme" },
      enabled: true,
      state: "active",
      seed_source_version_id: "version-1",
      updated_at: "2026-11-24T20:00:00Z",
    },
  ],
  endpoints: [
    {
      seed_key: "endpoint:recruitee-offers",
      label: "Recruitee offers",
      connector_key: "recruitee",
      platform: "",
      server: "https://acme.recruitee.com",
      method: "GET",
      path: "/api/offers/",
      auth: "none",
      params: [],
      countries: ["GR"],
      regions: [],
      worldwide: false,
      languages: [],
      docs_url: "https://docs.recruitee.com/",
      state: "active",
      seed_source_version_id: "version-1",
      updated_at: "2026-11-24T20:00:00Z",
    },
  ],
} as providersApi.AdminProviderDetail;

const PLAN = {
  status: "ok",
  candidate_source_id: "provider-1",
  candidate_version_id: "version-2",
  counts: { create: 1, update: 2, noop: 14, retire: 0, skip: 0, conflict: 0, override: 0 },
  conflicts: [],
  items: [
    {
      entity_type: "job_source_preset",
      seed_key: "ats-preset:acme",
      action: "update",
      content_hash: "hash",
      source_id: "provider-1",
      version_id: "version-2",
      priority: 100,
      current_id: "entity-1",
      reason: "content changed",
    },
  ],
} as providersApi.ProviderPlan;

vi.mock("@/api/providers", () => ({
  listAdminProviders: vi.fn(),
  fetchAdminProvider: vi.fn(),
  createProvider: vi.fn(),
  updateProvider: vi.fn(),
  deleteProvider: vi.fn(),
  discoverProvider: vi.fn(),
  syncProvider: vi.fn(),
  uploadProviderPack: vi.fn(),
  listProviderVersions: vi.fn(),
  planProviderVersion: vi.fn(),
  approveProviderVersion: vi.fn(),
  rejectProviderVersion: vi.fn(),
  revokeProviderVersion: vi.fn(),
  applyProviderVersion: vi.fn(),
  adoptProviderVersion: vi.fn(),
  setProviderItemEnabled: vi.fn(),
  retireProviderItem: vi.fn(),
  listProviderRuns: vi.fn(),
  probeProviderEndpoint: vi.fn(),
  listUserProviders: vi.fn(),
  fetchUserProvider: vi.fn(),
  listUserProviderEndpoints: vi.fn(),
}));

const mocked = vi.mocked(providersApi);

beforeEach(() => {
  vi.clearAllMocks();
  mocked.listAdminProviders.mockResolvedValue([PROVIDER]);
  mocked.fetchAdminProvider.mockResolvedValue(DETAIL);
  mocked.listProviderVersions.mockResolvedValue([PENDING, CURRENT_VERSION]);
  mocked.listProviderRuns.mockResolvedValue([]);
  mocked.planProviderVersion.mockResolvedValue(PLAN);
  mocked.approveProviderVersion.mockResolvedValue(APPROVED);
  mocked.applyProviderVersion.mockResolvedValue({
    status: "applied",
    run_id: "run-1",
    counts: PLAN.counts,
    error: "",
    plan: PLAN,
  });
  mocked.setProviderItemEnabled.mockResolvedValue();
  mocked.createProvider.mockResolvedValue(DETAIL);
  mocked.syncProvider.mockResolvedValue({ status: "ok", commit_sha: "", etag: "", message: "" });
});

describe("ProviderHub", () => {
  it("renders provider cards with versions, counts and pending updates", async () => {
    render(<ProviderHub />);
    expect(await screen.findByText("Neuronection official")).toBeInTheDocument();
    expect(screen.getByText("1.2.0")).toBeInTheDocument();
    expect(screen.getAllByText("25 items").length).toBeGreaterThan(0);
    expect(screen.getByText("1 pending")).toBeInTheDocument();
    expect(screen.getByText(/Official/)).toBeInTheDocument();
  });

  it("opens the detail, previews a plan, approves and applies a version", async () => {
    const user = userEvent.setup();
    render(<ProviderHub />);
    await user.click(await screen.findByTestId("provider-card-provider-1"));
    expect(await screen.findByTestId("provider-detail")).toBeInTheDocument();

    await user.click(screen.getByText("Versions"));
    expect(await screen.findByTestId("provider-version-version-2")).toBeInTheDocument();

    await user.click(screen.getByTestId("provider-plan-version-2"));
    expect(await screen.findByTestId("provider-plan-preview")).toBeInTheDocument();

    await user.click(screen.getByTestId("provider-approve-version-2"));
    await waitFor(() =>
      expect(mocked.approveProviderVersion).toHaveBeenCalledWith("provider-1", "version-2"),
    );
  });

  it("applies an approved version", async () => {
    const user = userEvent.setup();
    mocked.listProviderVersions.mockResolvedValue([
      APPROVED,
      CURRENT_VERSION,
    ]);
    render(<ProviderHub />);
    await user.click(await screen.findByTestId("provider-card-provider-1"));
    await screen.findByTestId("provider-detail");
    await user.click(screen.getByText("Versions"));
    await user.click(await screen.findByTestId("provider-apply-version-2"));
    await waitFor(() =>
      expect(mocked.applyProviderVersion).toHaveBeenCalledWith("provider-1", "version-2"),
    );
  });

  it("enables a preset from the items tab", async () => {
    const user = userEvent.setup();
    render(<ProviderHub />);
    await user.click(await screen.findByTestId("provider-card-provider-1"));
    await user.click(screen.getByText("Items"));
    const toggle = await screen.findByRole("switch", { name: "Enabled" });
    await user.click(toggle);
    await waitFor(() =>
      expect(mocked.setProviderItemEnabled).toHaveBeenCalledWith(
        "provider-1",
        "ats-preset:acme",
        false,
      ),
    );
  });

  it("creates a git provider from the add dialog", async () => {
    const user = userEvent.setup();
    render(<ProviderHub />);
    await user.click(await screen.findByTestId("provider-add"));
    await user.click(screen.getByTestId("provider-kind-git"));
    await user.type(screen.getByTestId("provider-name"), "Neuronection official");
    await user.type(
      screen.getByTestId("provider-uri"),
      "https://github.com/neuronection/career-assistant-seeds.git",
    );
    await user.type(screen.getByTestId("provider-ref"), "v2026.11.25.2");
    await user.click(screen.getByTestId("provider-create"));
    await waitFor(() =>
      expect(mocked.createProvider).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: "git",
          name: "Neuronection official",
          ref: "v2026.11.25.2",
          priority: 100,
        }),
      ),
    );
  });
});
