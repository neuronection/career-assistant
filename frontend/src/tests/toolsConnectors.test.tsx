import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { SourcesSection } from "@/components/settings/SourcesSection";
import { JOB_SOURCE_PRESETS } from "@/config/jobSourcePresets";
import * as aiApi from "@/api/ai";
import * as sourcesApi from "@/api/sources";

// plan 32 Phase 1: the connectors section broadened to job-source
// connector instances — catalog-driven form, sealed-secret hints (never
// values), probe button with typed outcomes.

vi.mock("@/api/ai", () => ({
  fetchWebSettings: vi.fn().mockResolvedValue({ github_token_set: false }),
  updateWebSettings: vi.fn(),
}));

vi.mock("@/api/mcp", () => ({
  fetchMcpStatus: vi.fn().mockResolvedValue({
    endpoint: "http://test/mcp",
    transport: "streamable-http",
    write_enabled: false,
    tools: [],
    read_tools: [],
    write_tools: [],
    active_tokens: 0,
  }),
  fetchMcpTokens: vi.fn().mockResolvedValue([]),
  fetchMcpAudit: vi.fn().mockResolvedValue([]),
  mintMcpToken: vi.fn(),
  rotateMcpToken: vi.fn(),
  revokeMcpToken: vi.fn(),
  setMcpWriteEnabled: vi.fn(),
}));

vi.mock("@/api/profileProposals", () => ({
  fetchProfileProposals: vi.fn().mockResolvedValue({ proposals: [], pending_count: 0 }),
  approveProfileProposal: vi.fn(),
  rejectProfileProposal: vi.fn(),
}));

vi.mock("@/api/sources", () => ({
  fetchAdminSources: vi.fn(),
  fetchConnectorCatalog: vi.fn(),
  createSource: vi.fn(),
  updateSource: vi.fn(),
  probeSource: vi.fn(),
  syncSource: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    i18n: { language: "en" },
    t: (key: string, params?: Record<string, string | number>) => {
      const templates: Record<string, string> = {
        "toolsSettings.connectors.sources.secretSet": "{{slot}}: {{hint}}",
        "toolsSettings.connectors.sources.secretMissing": "{{slot}}: not set",
        "toolsSettings.connectors.sources.needsSecret": "needs secret",
        "toolsSettings.connectors.sources.probeOk": "OK · {{items}} item(s) · {{latency}} ms",
        "toolsSettings.connectors.sources.probeError": "{{code}}: {{detail}}",
        "toolsSettings.connectors.sources.test": "Test",
        "toolsSettings.connectors.sources.secret": "{{name}} (secret — leave empty to keep)",
        "toolsSettings.connectors.sources.save": "Save source",
        "toolsSettings.connectors.sources.cancel": "Cancel",
        "toolsSettings.connectors.sources.select": "Select…",
        "toolsSettings.connectors.sources.secretSetShort": "set — leave empty to keep",
        "toolsSettings.connectors.sources.secretMissingShort": "not set",
        "toolsSettings.connectors.sources.needsConfig": "needs config",
        "toolsSettings.connectors.sources.edit": "Edit",
        "toolsSettings.connectors.presets.addSelected": "Add {{count}} selected",
        "toolsSettings.connectors.sources.countryFilterAria": "Filter sources by country",
        "toolsSettings.connectors.sources.countryAll": "All sources",
        "toolsSettings.connectors.sources.countryCustom": "Custom",
        "toolsSettings.connectors.sources.worldwide": "Worldwide",
        "toolsSettings.connectors.sources.problemsOnly": "Problems only",
      };
      let out = templates[key] ?? key;
      for (const [name, value] of Object.entries(params ?? {})) {
        out = out.split(`{{${name}}}`).join(String(value));
      }
      return out;
    },
  }),
}));

const catalog = [
  {
    key: "ats_api",
    title: "ATS public API (Greenhouse / Lever / Ashby)",
    docs_url: "",
    builtin: true,
    secret_fields: ["api_token"],
    capabilities: { requires_credentials: true },
    config_schema: {
      type: "object" as const,
      properties: {
        provider: { type: "string" as const, title: "ATS provider", enum: ["greenhouse"] },
        org: { type: "string" as const, title: "Board org slug" },
        api_token: { type: "string" as const, title: "Partner API token", "x-secret": true },
      },
      required: ["provider", "org"],
    },
    manifest: {
      id: "career-ats-api",
      description: "Ingest a Greenhouse-style public board.",
      capabilities: ["net", "sync"],
      supportsIncremental: true,
      docs: "connectors/ats",
    },
  },
];

const sources = [
  {
    id: "src-1",
    key: "acme-board",
    connector_key: "ats_api",
    config: { provider: "greenhouse", org: "acme" },
    secret_hints: { api_token: { set: true, hint: "…9876" } },
    enabled: true,
    last_run_at: null,
    sync_state: {},
    error: "",
  },
  {
    id: "src-2",
    key: "tokenless",
    connector_key: "ats_api",
    config: { provider: "greenhouse", org: "beta" },
    secret_hints: { api_token: { set: false, hint: null } },
    enabled: true,
    last_run_at: null,
    sync_state: {},
    error: "",
  },
];

function renderSection() {
  return render(
    <MemoryRouter>
      <SourcesSection />
    </MemoryRouter>,
  );
}

function renderSectionWithRoutes() {
  return render(
    <MemoryRouter initialEntries={["/settings/tools?section=sources"]}>
      <Routes>
        <Route path="/settings/tools" element={<SourcesSection />} />
        <Route path="/sources/:sourceId" element={<div data-testid="source-manage-page" />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("SourcesSection job sources", () => {
  it("lists sources as kit instance rows with the sealed-secret condition badge, never values", async () => {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue(sources as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    renderSection();

    expect(await screen.findByTestId("integration-instance-src-1")).toBeTruthy();
    expect(
      screen.getByTestId("integration-condition-src-2-needs-secret").textContent,
    ).toContain("needs secret");
    expect(screen.queryByText(/enc::/)).toBeNull();
    expect(screen.getByTestId("job-sources-block")).toBeTruthy();
  });

  it("groups sources by kind and pauses a source", async () => {
    const withKinds = [
      { ...sources[0], kind: "posting", last_status: "ok", paused_at: null },
      {
        ...sources[1],
        id: "src-3",
        key: "market-demand",
        connector_key: "demand_data",
        kind: "market",
        last_status: "degraded",
        paused_at: null,
      },
    ];
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue(withKinds as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    vi.mocked(sourcesApi.updateSource).mockResolvedValue({} as never);
    const { userEvent } = await import("@testing-library/user-event");
    renderSection();

    expect(
      await screen.findByText("toolsSettings.connectors.sources.kind.posting"),
    ).toBeTruthy();
    await userEvent.click(screen.getByRole("switch", { name: /market-demand/ }));
    await waitFor(() => {
      expect(sourcesApi.updateSource).toHaveBeenCalledWith("src-3", { paused: true });
    });
  });

  it("runs a typed probe and renders the outcome", async () => {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue(sources.slice(0, 1) as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    vi.mocked(sourcesApi.probeSource).mockResolvedValue({
      ok: false,
      error: {
        code: "needs-secret",
        detail: { message: "missing secret slot(s): api_token" },
        retryable: "after-config-change",
      },
    });
    const { userEvent } = await import("@testing-library/user-event");
    renderSection();

    const testButton = await screen.findByRole("button", {
      name: "Test",
    });
    await userEvent.click(testButton);
    await waitFor(() => {
      expect(screen.getByTestId("job-source-probe-acme-board").textContent).toContain(
        "needs-secret",
      );
    });
    expect(sourcesApi.probeSource).toHaveBeenCalledWith("src-1");
  });

  it("renders the connector description on the setup tiles", async () => {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue([] as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    const { userEvent } = await import("@testing-library/user-event");
    renderSection();

    await userEvent.click(await screen.findByTestId("add-job-source"));
    await userEvent.click(await screen.findByTestId("preset-custom"));
    const tile = await screen.findByTestId("source-tile-ats_api");
    expect(tile.textContent).toContain("Ingest a Greenhouse-style public board");
  });

  it("opens a kit config form with a password field for x-secret slots", async () => {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue([] as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    vi.mocked(aiApi.fetchWebSettings).mockResolvedValue({ github_token_set: false });
    const { userEvent } = await import("@testing-library/user-event");
    renderSection();

    const add = await screen.findByTestId("add-job-source");
    await userEvent.click(add);
    await userEvent.click(await screen.findByTestId("preset-custom"));
    await screen.findByTestId("source-tiles");
    await userEvent.click(await screen.findByTestId("source-tile-ats_api"));
    const form = await screen.findByTestId("integration-config-form");
    expect(form).toBeTruthy();
    const secretInput = form.querySelector("input[type='password']");
    expect(secretInput).toBeTruthy();
    expect(secretInput!.getAttribute("autocomplete")).toBe("off");
  });

  it("emits values and secrets separately at save", async () => {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue([] as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    vi.mocked(sourcesApi.createSource).mockResolvedValue(sources[0] as never);
    vi.mocked(aiApi.fetchWebSettings).mockResolvedValue({ github_token_set: false });
    const { userEvent } = await import("@testing-library/user-event");
    renderSection();

    await userEvent.click(await screen.findByTestId("add-job-source"));
    await userEvent.click(await screen.findByTestId("preset-custom"));
    await userEvent.click(await screen.findByTestId("source-tile-ats_api"));
    const form = await screen.findByTestId("integration-config-form");
    await userEvent.type(form.querySelector("input[type='password']")!, "tok");
    await userEvent.click(screen.getByRole("button", { name: "Save source" }));
    await waitFor(() => expect(sourcesApi.createSource).toHaveBeenCalled());
    const payload = vi.mocked(sourcesApi.createSource).mock.calls[0]![0];
    expect(payload.secrets).toEqual({ api_token: "tok" });
    expect(JSON.stringify(payload.config)).not.toContain("tok");
  });

  it("bulk-adds a preset with the connector, config and title prefilled", async () => {
    const withRecruitee = [
      ...catalog,
      {
        key: "recruitee",
        title: "Recruitee",
        docs_url: "",
        builtin: true,
        secret_fields: [],
        config_schema: {
          type: "object" as const,
          properties: { company: { type: "string" as const, title: "Recruitee company" } },
          required: ["company"],
        },
        manifest: { id: "recruitee", capabilities: ["net", "sync"], supportsIncremental: true },
      },
    ];
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue([] as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(withRecruitee as never);
    vi.mocked(sourcesApi.createSource).mockResolvedValue({
      id: "src-9",
      key: "ballysintralotsa",
      connector_key: "recruitee",
    } as never);
    vi.mocked(aiApi.fetchWebSettings).mockResolvedValue({ github_token_set: false });
    const { userEvent } = await import("@testing-library/user-event");
    renderSection();

    await userEvent.click(await screen.findByTestId("add-job-source"));
    await userEvent.click(await screen.findByTestId("preset-ballysintralotsa"));
    await userEvent.click(await screen.findByTestId("presets-add"));
    await waitFor(() => expect(sourcesApi.createSource).toHaveBeenCalled());
    const calls = vi.mocked(sourcesApi.createSource).mock.calls;
    const payload = calls[calls.length - 1]![0];
    expect(payload.connector_key).toBe("recruitee");
    expect(payload.key).toBe("ballysintralotsa");
    expect(payload.title).toBe("Bally's Intralot");
    expect(payload.config).toMatchObject({ company: "ballysintralotsa" });
    expect(payload.query_mode).toBe("static");
  });

  it("bulk-adds several zero-config presets at once", async () => {
    const withWorkable = [
      ...catalog,
      {
        key: "workable",
        title: "Workable",
        docs_url: "",
        builtin: true,
        secret_fields: [],
        config_schema: {
          type: "object" as const,
          properties: { account: { type: "string" as const, title: "Workable account" } },
          required: ["account"],
        },
        manifest: { id: "workable", capabilities: ["net", "sync"], supportsIncremental: true },
      },
    ];
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue([] as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(withWorkable as never);
    vi.mocked(
      sourcesApi.createSource,
    ).mockImplementation(async (payload) => ({
      id: `src-${payload.key}`,
      key: payload.key,
      connector_key: payload.connector_key,
    }) as never);
    vi.mocked(aiApi.fetchWebSettings).mockResolvedValue({ github_token_set: false });
    const { userEvent } = await import("@testing-library/user-event");
    renderSection();

    await userEvent.click(await screen.findByTestId("add-job-source"));
    await userEvent.click(await screen.findByTestId("preset-jobicy"));
    await userEvent.click(await screen.findByTestId("preset-remotive"));
    await userEvent.click(await screen.findByTestId("preset-arbeitnow"));
    const before = vi.mocked(sourcesApi.createSource).mock.calls.length;
    await userEvent.click(await screen.findByTestId("presets-add"));
    await waitFor(() =>
      expect(vi.mocked(sourcesApi.createSource).mock.calls.length).toBe(before + 3),
    );
    const payloads = vi
      .mocked(sourcesApi.createSource)
      .mock.calls.slice(before)
      .map(([payload]) => payload);
    expect(payloads.map((payload) => payload.key)).toEqual(["jobicy", "remotive", "arbeitnow"]);
    for (const payload of payloads) {
      expect(payload.config).toEqual({});
      expect(payload.title).toBeTruthy();
    }
  });

  it("edits an existing source through the wizard (update, never create)", async () => {
    const createBefore = vi.mocked(sourcesApi.createSource).mock.calls.length;
    const updateBefore = vi.mocked(sourcesApi.updateSource).mock.calls.length;
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue(sources as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    vi.mocked(sourcesApi.updateSource).mockResolvedValue(sources[0] as never);
    const { userEvent } = await import("@testing-library/user-event");
    renderSection();

    await userEvent.click(await screen.findByTestId("source-actions-acme-board"));
    await userEvent.click(await screen.findByTestId("edit-source-acme-board"));
    const form = await screen.findByTestId("integration-config-form");
    expect(form).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Save source" }));
    await waitFor(() =>
      expect(vi.mocked(sourcesApi.updateSource).mock.calls.length).toBe(updateBefore + 1),
    );
    expect(vi.mocked(sourcesApi.createSource).mock.calls.length).toBe(createBefore);
  });

  it("hides the needs-secret badge for connectors without required credentials", async () => {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue([
      {
        id: "src-mcp",
        key: "board-optional",
        connector_key: "mcp",
        config: { transport: "stdio", command: "python serve.py" },
        secret_hints: { token: { set: false, hint: null } },
        enabled: true,
        last_run_at: null,
        sync_state: {},
        error: "",
      },
    ] as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue([
      ...catalog,
      {
        key: "mcp",
        title: "MCP script (external process)",
        docs_url: "",
        builtin: true,
        secret_fields: ["token"],
        capabilities: {},
        config_schema: {
          type: "object" as const,
          properties: {
            transport: { type: "string" as const, title: "Transport" },
            command: { type: "string" as const, title: "Command" },
            token: { type: "string" as const, title: "Token", "x-secret": true },
          },
        },
        manifest: { id: "mcp", capabilities: ["sync"], supportsIncremental: true },
      },
    ] as never);
    renderSection();

    expect(await screen.findByTestId("integration-instance-src-mcp")).toBeTruthy();
    expect(
      screen.queryByTestId("integration-condition-src-mcp-needs-secret"),
    ).toBeNull();
  });

  it("filters the sources list through the search field", async () => {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue(sources as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    const { userEvent } = await import("@testing-library/user-event");
    renderSection();

    expect(await screen.findByTestId("integration-instance-src-1")).toBeTruthy();
    expect(screen.getByTestId("integration-instance-src-2")).toBeTruthy();
    await userEvent.type(
      screen.getByTestId("job-sources-search").querySelector("input")!,
      "acme",
    );
    expect(screen.getByTestId("integration-instance-src-1")).toBeTruthy();
    expect(screen.queryByTestId("integration-instance-src-2")).toBeNull();
  });

  it("bulk-pauses selected sources from the selection bar", async () => {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue(sources as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    vi.mocked(sourcesApi.updateSource).mockResolvedValue(sources[0] as never);
    const { userEvent } = await import("@testing-library/user-event");
    renderSection();

    const select = (key: string) =>
      screen.getByRole("checkbox", {
        name: `toolsSettings.connectors.sources.selectAria: ${key}`,
      });
    await screen.findByTestId("integration-instance-src-1");
    const pausedBefore = vi
      .mocked(sourcesApi.updateSource)
      .mock.calls.filter(([, payload]) => (payload as { paused?: boolean }).paused === true).length;
    await userEvent.click(select("acme-board"));
    await userEvent.click(select("tokenless"));
    expect(await screen.findByTestId("job-sources-bulk")).toBeTruthy();
    await userEvent.click(screen.getByTestId("bulk-pause"));
    await waitFor(() => {
      const pausedCalls = vi
        .mocked(sourcesApi.updateSource)
        .mock.calls.filter(([, payload]) => (payload as { paused?: boolean }).paused === true);
      expect(pausedCalls.length).toBe(pausedBefore + 2);
    });
  });

  it("shows the preset logo (monogram fallback) for preset-created sources", async () => {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue([
      {
        id: "src-ballys",
        key: "ballysintralotsa",
        connector_key: "recruitee",
        config: { company: "ballysintralotsa" },
        secret_hints: {},
        enabled: true,
        last_run_at: null,
        sync_state: {},
        error: "",
      },
    ] as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    renderSection();

    const card = await screen.findByTestId("integration-instance-src-ballys");
    const logo = card.querySelector("img");
    expect(logo?.getAttribute("src")).toBe("/presets/ballysintralotsa.svg");
    fireEvent.error(logo!);
    expect(screen.getByText("BI")).toBeTruthy();
  });

  it("shows a health strip (active count + failing badge) over the rows", async () => {
    const withHealth = [
      { ...sources[0], kind: "posting", last_status: "ok", paused_at: null },
      {
        ...sources[1],
        id: "src-3",
        key: "broken",
        kind: "posting",
        last_status: "failed",
        paused_at: null,
      },
    ];
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue(withHealth as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    renderSection();

    expect(await screen.findByTestId("job-sources-count")).toBeInTheDocument();
    expect(await screen.findByTestId("job-sources-failing")).toBeInTheDocument();
  });

  it("moves Sync/Docs/Query plan/Manage/Remove into the row overflow menu", async () => {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue(
      [{ ...sources[0], kind: "posting", last_status: "ok", paused_at: null }] as never
    );
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    const { userEvent } = await import("@testing-library/user-event");
    renderSection();

    await screen.findByTestId("integration-instance-src-1");
    expect(screen.queryByTestId("manage-source-acme-board")).toBeNull();
    await userEvent.click(await screen.findByTestId("source-actions-acme-board"));
    expect(await screen.findByTestId("sync-source-acme-board")).toBeInTheDocument();
    expect(screen.getByTestId("connector-docs-ats_api")).toBeInTheDocument();
    expect(screen.getByTestId("query-plan-acme-board")).toBeInTheDocument();
    expect(screen.getByTestId("manage-source-acme-board")).toBeInTheDocument();
    expect(screen.getByTestId("remove-source-acme-board")).toBeInTheDocument();
  });

  it("opens the source manage page when the card is clicked", async () => {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue(
      [{ ...sources[0], kind: "posting", last_status: "ok", paused_at: null }] as never,
    );
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    const { userEvent } = await import("@testing-library/user-event");
    renderSectionWithRoutes();

    const card = await screen.findByTestId("integration-instance-src-1");
    expect(card.className).toContain("cursor-pointer");
    await userEvent.click(card);
    expect(await screen.findByTestId("source-manage-page")).toBeInTheDocument();
  });

  it("the title is a keyboard-reachable open affordance", async () => {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue(
      [{ ...sources[0], kind: "posting", last_status: "ok", paused_at: null }] as never,
    );
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    const { userEvent } = await import("@testing-library/user-event");
    renderSectionWithRoutes();

    const name = await screen.findByTestId("job-source-name-acme-board");
    name.focus();
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByTestId("source-manage-page")).toBeInTheDocument();
  });

  it("the enable toggle never opens the manage page", async () => {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue(
      [{ ...sources[0], kind: "posting", last_status: "ok", paused_at: null }] as never,
    );
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    vi.mocked(sourcesApi.updateSource).mockResolvedValue({} as never);
    const { userEvent } = await import("@testing-library/user-event");
    renderSectionWithRoutes();

    await userEvent.click(await screen.findByTestId("job-source-toggle-acme-board"));
    await waitFor(() => expect(sourcesApi.updateSource).toHaveBeenCalled());
    expect(screen.queryByTestId("source-manage-page")).toBeNull();
  });
});

describe("SourcesSection country lens + problems-only", () => {
  const grPreset = JOB_SOURCE_PRESETS.find((entry) => entry.country === "GR")!;
  const wwPreset = JOB_SOURCE_PRESETS.find((entry) => !entry.country)!;
  const lensSources = [
    {
      id: "src-gr",
      key: grPreset.slug,
      connector_key: grPreset.connectorKey,
      config: grPreset.config,
      secret_hints: {},
      enabled: true,
      last_run_at: null,
      sync_state: {},
      error: "",
    },
    {
      id: "src-ww",
      key: wwPreset.slug,
      connector_key: wwPreset.connectorKey,
      config: wwPreset.config,
      secret_hints: {},
      enabled: true,
      last_run_at: null,
      sync_state: {},
      error: "",
    },
    {
      id: "src-custom",
      key: "acme-board",
      connector_key: "ats_api",
      config: { provider: "greenhouse", org: "acme" },
      secret_hints: { api_token: { set: true, hint: "…9876" } },
      enabled: true,
      last_run_at: null,
      sync_state: {},
      error: "",
    },
    {
      id: "src-broken",
      key: "broken-board",
      connector_key: "ats_api",
      config: { provider: "greenhouse", org: "beta" },
      secret_hints: { api_token: { set: true, hint: "…1234" } },
      enabled: true,
      last_run_at: null,
      sync_state: {},
      error: "net-denied: robots.txt disallows the path",
    },
  ];

  function renderLens() {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue(lensSources as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    render(
      <MemoryRouter>
        <SourcesSection />
      </MemoryRouter>,
    );
  }

  it("derives country chips with counts from the preset catalog", async () => {
    renderLens();
    const greece = await screen.findByTestId("job-sources-country-GR");
    expect(greece.getAttribute("aria-pressed")).toBe("false");
    expect(greece.textContent).toContain("1");
    expect(screen.getByTestId("job-sources-country-WW").textContent).toContain("1");
    expect(screen.getByTestId("job-sources-country-custom").textContent).toContain("2");
    expect(screen.getByTestId("job-sources-country-all").getAttribute("aria-pressed")).toBe("true");
  });

  it("flags preset rows with their country", async () => {
    renderLens();
    expect(
      (await screen.findByTestId(`source-country-${grPreset.slug}`)).textContent,
    ).toContain("🇬🇷");
    expect(screen.queryByTestId("source-country-acme-board")).toBeNull();
  });

  it("filters by a country chip and restores with all", async () => {
    const { userEvent } = await import("@testing-library/user-event");
    renderLens();
    await screen.findByTestId("job-sources-country-GR");
    await userEvent.click(screen.getByTestId("job-sources-country-GR"));
    expect(screen.getByTestId("integration-instance-src-gr")).toBeTruthy();
    expect(screen.queryByTestId("integration-instance-src-ww")).toBeNull();
    expect(screen.queryByTestId("integration-instance-src-custom")).toBeNull();
    await userEvent.click(screen.getByTestId("job-sources-country-all"));
    expect(screen.getByTestId("integration-instance-src-ww")).toBeTruthy();
  });

  it("problems-only keeps failing and paused sources", async () => {
    const { userEvent } = await import("@testing-library/user-event");
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue([
      ...lensSources,
      {
        id: "src-paused",
        key: "paused-board",
        connector_key: "ats_api",
        config: { provider: "greenhouse", org: "gamma" },
        secret_hints: { api_token: { set: true, hint: "…5555" } },
        enabled: true,
        paused_at: "2026-11-02T10:00:00Z",
        last_run_at: null,
        sync_state: {},
        error: "",
      },
    ] as never);
    render(
      <MemoryRouter>
        <SourcesSection />
      </MemoryRouter>,
    );
    await screen.findByTestId("integration-instance-src-gr");
    expect(screen.getByTestId("job-sources-problems").textContent).toContain("2");
    await userEvent.click(screen.getByTestId("job-sources-problems"));
    expect(screen.getByTestId("integration-instance-src-broken")).toBeTruthy();
    expect(screen.getByTestId("integration-instance-src-paused")).toBeTruthy();
    expect(screen.queryByTestId("integration-instance-src-gr")).toBeNull();
    expect(screen.getByTestId("job-sources-problems").getAttribute("aria-pressed")).toBe("true");
  });
});
