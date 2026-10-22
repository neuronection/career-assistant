import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WebSearchSection } from "@/components/settings/WebSearchSection";
import * as aiApi from "@/api/ai";

// plan 122 phase 2: the keyed providers (Tavily/Brave/Exa/Serper/Google
// PSE) are real rows now — the form sends the engine id for Google PSE and
// maps the catalog's hyphenated id onto the stored underscore type.

vi.mock("@/api/ai", () => ({
  listSearchProviders: vi.fn(),
  getSearchProviderCatalog: vi.fn(),
  createSearchProvider: vi.fn(),
  updateSearchProvider: vi.fn(),
  moveSearchProvider: vi.fn(),
  deleteSearchProvider: vi.fn(),
  testSearchProvider: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, string | number>) => {
      let out = key;
      for (const [name, value] of Object.entries(params ?? {})) {
        out = out.split(`{{${name}}}`).join(String(value));
      }
      return out;
    },
  }),
}));

const catalog = {
  providerOrder: ["searxng", "tavily", "brave", "exa", "serper", "google-pse"],
  providers: {
    searxng: {
      label: "SearXNG",
      requiresKey: false,
      keyUrl: null,
      baseUrl: null,
      baseUrlRequired: true,
    },
    tavily: {
      label: "Tavily",
      requiresKey: true,
      keyUrl: null,
      baseUrl: "https://api.tavily.com",
      baseUrlRequired: false,
    },
    "google-pse": {
      label: "Google Programmable Search",
      requiresKey: true,
      keyUrl: null,
      baseUrl: "https://www.googleapis.com/customsearch/v1",
      baseUrlRequired: false,
      fields: [{ id: "google_cx", label: "Engine id (cx)", required: true }],
    },
  },
};

function mockCatalog() {
  vi.mocked(aiApi.getSearchProviderCatalog).mockResolvedValue(catalog as never);
}

describe("WebSearchSection keyed providers", () => {
  it("sends the Google PSE engine id with the catalog type", async () => {
    vi.mocked(aiApi.listSearchProviders).mockResolvedValue([]);
    vi.mocked(aiApi.createSearchProvider).mockResolvedValue({} as never);
    mockCatalog();
    const { userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    render(<WebSearchSection />);

    await waitFor(() => expect(aiApi.getSearchProviderCatalog).toHaveBeenCalled());
    await user.click(await screen.findByText("toolsSettings.webSearch.add"));
    await user.selectOptions(
      screen.getByLabelText("toolsSettings.webSearch.type"),
      "google-pse",
    );
    await user.type(
      screen.getByPlaceholderText("toolsSettings.webSearch.googleCx"),
      "a1b2c3d4e5f6g7h8j",
    );
    await user.type(
      screen.getByPlaceholderText("toolsSettings.webSearch.key"),
      "AIza-secret",
    );
    await user.click(screen.getByText("toolsSettings.webSearch.save"));

    await waitFor(() => expect(aiApi.createSearchProvider).toHaveBeenCalled());
    expect(aiApi.createSearchProvider).toHaveBeenCalledWith({
      type: "google-pse",
      name: null,
      base_url: null,
      google_cx: "a1b2c3d4e5f6g7h8j",
      api_key: "AIza-secret",
    });
  });

  it("maps a stored google_pse row onto the catalog's hyphenated option", async () => {
    vi.mocked(aiApi.listSearchProviders).mockResolvedValue([
      {
        id: "p1",
        name: "Google",
        type: "google_pse",
        enabled: true,
        base_url: "https://www.googleapis.com/customsearch/v1",
        google_cx: "cx-123",
        key_hint: "••••cret",
        max_results: 5,
        timeout_ms: 8000,
        key_set: true,
      },
    ]);
    mockCatalog();
    const { userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    render(<WebSearchSection />);

    await user.click(await screen.findByTitle("toolsSettings.webSearch.edit"));
    expect(screen.getByLabelText("toolsSettings.webSearch.type")).toHaveValue("google-pse");
    expect(screen.getByPlaceholderText("toolsSettings.webSearch.googleCx")).toHaveValue("cx-123");
    expect(screen.getByText("••••cret")).toBeInTheDocument();
  });
});
