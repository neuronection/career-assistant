import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ConnectorsSection } from "@/components/settings/ConnectorsSection";
import * as aiApi from "@/api/ai";
import * as sourcesApi from "@/api/sources";

// plan 32 Phase 1: the connectors section broadened to job-source
// connector instances — catalog-driven form, sealed-secret hints (never
// values), probe button with typed outcomes.

vi.mock("@/api/ai", () => ({
  fetchWebSettings: vi.fn().mockResolvedValue({ github_token_set: false }),
  updateWebSettings: vi.fn(),
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
    t: (key: string, params?: Record<string, string | number>) => {
      const templates: Record<string, string> = {
        "toolsSettings.connectors.sources.secretSet": "{{slot}}: {{hint}}",
        "toolsSettings.connectors.sources.secretMissing": "{{slot}}: not set",
        "toolsSettings.connectors.sources.needsSecret": "needs secret",
        "toolsSettings.connectors.sources.probeOk": "OK · {{items}} item(s) · {{latency}} ms",
        "toolsSettings.connectors.sources.probeError": "{{code}}: {{detail}}",
        "toolsSettings.connectors.sources.test": "Test",
        "toolsSettings.connectors.sources.secret": "{{name}} (secret — leave empty to keep)",
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
    config_schema: {
      type: "object" as const,
      properties: {
        provider: { type: "string" as const, title: "ATS provider", enum: ["greenhouse"] },
        org: { type: "string" as const, title: "Board org slug" },
        api_token: { type: "string" as const, title: "Partner API token", "x-secret": true },
      },
      required: ["provider", "org"],
    },
    manifest: { id: "career-ats-api", capabilities: ["net", "sync"], supportsIncremental: true },
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
      <ConnectorsSection />
    </MemoryRouter>,
  );
}

describe("ConnectorsSection job sources", () => {
  it("lists sources with sealed-secret hints, never values", async () => {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue(sources as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    renderSection();

    const hint = await screen.findByTestId("secret-hint-acme-board-api_token");
    expect(hint.textContent).toContain("…9876");
    expect(screen.queryByText(/enc::/)).toBeNull();
    expect(screen.getByTestId("job-sources-block")).toBeTruthy();
  });

  it("flags a missing required secret slot with the needs-secret badge", async () => {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue(sources as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    renderSection();

    expect(await screen.findByText("needs secret")).toBeTruthy();
  });

  it("runs a typed probe and renders the outcome", async () => {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue(sources.slice(0, 1) as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    vi.mocked(sourcesApi.probeSource).mockResolvedValue({
      ok: false,
      error: { code: "needs-secret", detail: "missing secret slot(s): api_token", retryable: "after-config-change" },
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

  it("opens a catalog-driven form with a password field for x-secret slots", async () => {
    vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue([] as never);
    vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue(catalog as never);
    vi.mocked(aiApi.fetchWebSettings).mockResolvedValue({ github_token_set: false });
    const { userEvent } = await import("@testing-library/user-event");
    renderSection();

    const add = await screen.findByTestId("add-job-source");
    await userEvent.click(add);
    const form = await screen.findByTestId("job-source-form");
    expect(form).toBeTruthy();
    const secretInput = form.querySelector("input[type='password']");
    expect(secretInput).toBeTruthy();
    expect(secretInput!.getAttribute("placeholder")).toContain("secret");
  });
});
