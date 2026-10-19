import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ConnectorsSection } from "@/components/settings/ConnectorsSection";
import * as sourcesApi from "@/api/sources";
import type { ConnectorDocs } from "@/api/sources";

// plan 34 wave 8: per-connector docs — a Docs action on the source rows
// whose connector's manifest carries the docs pointer; absent pointer ⇒
// no affordance. The dialog opens on the landing page (the landing rule)
// and badges the page's audience tag.

vi.mock("@/api/ai", () => ({
  fetchWebSettings: vi.fn().mockResolvedValue({ github_token_set: false }),
  updateWebSettings: vi.fn(),
}));

vi.mock("@/api/sources", () => ({
  fetchAdminSources: vi.fn(),
  fetchConnectorCatalog: vi.fn(),
  fetchConnectorDocs: vi.fn(),
  createSource: vi.fn(),
  updateSource: vi.fn(),
  probeSource: vi.fn(),
  syncSource: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, string | number>) => {
      const templates: Record<string, string> = {
        "toolsSettings.connectors.docs.open": "Docs",
        "toolsSettings.connectors.docs.title": "Documentation",
        "toolsSettings.connectors.docs.tree": "Documentation",
        "toolsSettings.connectors.docs.empty": "No documentation provided.",
        "toolsSettings.connectors.docs.loading": "Loading…",
        "toolsSettings.connectors.docs.error": "Failed to load documentation.",
        "toolsSettings.connectors.docs.audience.user": "For users",
        "toolsSettings.connectors.docs.audience.dev": "For developers",
        "toolsSettings.connectors.sources.test": "Test",
        "toolsSettings.connectors.sources.sync": "Sync",
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

const TREE: NonNullable<ConnectorDocs["tree"]> = {
  version: 1,
  categories: [
    {
      category: "overview",
      items: [
        { id: "overview", file: "overview.md", title: "Overview", audience: "user" as const },
      ],
    },
    {
      category: "usage",
      items: [{ id: "usage", file: "usage.md", title: "Running it" }],
    },
  ],
};

const catalog = [
  {
    key: "arbeitnow",
    title: "Arbeitnow job board",
    docs_url: "",
    builtin: true,
    secret_fields: [],
    config_schema: { type: "object" as const, properties: {} },
    manifest: {
      id: "career-arbeitnow",
      capabilities: ["net", "sync"],
      supportsIncremental: true,
      docs: "docs/docs-tree.json",
    },
  },
  {
    key: "csv",
    title: "CSV upload",
    docs_url: "",
    builtin: true,
    secret_fields: [],
    config_schema: { type: "object" as const, properties: {} },
    manifest: { id: "career-csv", capabilities: ["sync"], supportsIncremental: false },
  },
];

const sources = [
  {
    id: "src-documented",
    key: "board",
    connector_key: "arbeitnow",
    config: {},
    secret_hints: {},
    enabled: true,
    last_run_at: null,
    sync_state: {},
    error: "",
  },
  {
    id: "src-undocumented",
    key: "sheet",
    connector_key: "csv",
    config: {},
    secret_hints: {},
    enabled: true,
    last_run_at: null,
    sync_state: {},
    error: "",
  },
];

function renderSection() {
  return render(
    <MemoryRouter>
      <ConnectorsSection />
    </MemoryRouter>,
  );
}

describe("connector docs affordance", () => {
  it("shows the Docs action only for connectors whose manifest carries the pointer", async () => {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue(sources as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    renderSection();

    expect(await screen.findByTestId("connector-docs-arbeitnow")).toBeTruthy();
    expect(screen.queryByTestId("connector-docs-csv")).toBeNull();
  });

  it("opens the dialog on the landing page and fetches pages by file", async () => {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue(sources.slice(0, 1) as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(
      catalog.slice(0, 1) as never,
    );
    vi.mocked(sourcesApi.fetchConnectorDocs).mockImplementation(
      async (_key: string, file?: string) => {
        if (file && file !== "overview.md") {
          return { markdown: "# Usage\n\nDay-to-day.", tree: null };
        }
        return { markdown: "# Overview\n\nLanding body.", tree: TREE };
      },
    );
    const { userEvent } = await import("@testing-library/user-event");
    renderSection();

    await userEvent.click(await screen.findByTestId("connector-docs-arbeitnow"));
    await waitFor(() => {
      expect(screen.getAllByText("Landing body.").length).toBeGreaterThan(0);
    });
    expect(sourcesApi.fetchConnectorDocs).toHaveBeenCalledWith("arbeitnow");

    await userEvent.click(screen.getAllByText("Running it")[0]);
    await waitFor(() => {
      expect(sourcesApi.fetchConnectorDocs).toHaveBeenCalledWith("arbeitnow", "usage.md");
    });
    await waitFor(() => {
      expect(screen.getAllByText("Day-to-day.").length).toBeGreaterThan(0);
    });
  });

  it("badges the page's audience tag", async () => {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue(sources.slice(0, 1) as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(
      catalog.slice(0, 1) as never,
    );
    vi.mocked(sourcesApi.fetchConnectorDocs).mockResolvedValue({
      markdown: "# Overview\n\nLanding body.",
      tree: TREE,
    });
    const { userEvent } = await import("@testing-library/user-event");
    renderSection();

    await userEvent.click(await screen.findByTestId("connector-docs-arbeitnow"));
    await waitFor(() => {
      expect(screen.getByTestId("connector-docs-audience").textContent).toBe(
        "For users",
      );
    });
  });
});
