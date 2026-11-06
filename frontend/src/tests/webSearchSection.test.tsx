import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WebSearchSection } from "@/components/settings/WebSearchSection";
import * as aiApi from "@/api/ai";

// The section is library composition (family web-search-providers module):
// ProviderCards with a ⋯ management menu, add = tiles → settings-form
// wizard in a modal, edit = the catalog-driven settings form. These tests
// pin the app-side contract: the mapping (stored google_pse ↔ catalog
// google-pse), the save body (base-URL deviation rule, apiKey null keeps
// the stored key, tuning fields ride the fields bag) and the gated
// delete. Labels assert on i18n keys (the mock returns the key).

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
      keyUrl: "https://app.tavily.com/app/api-key",
      baseUrl: "https://api.tavily.com",
      baseUrlRequired: false,
    },
    "google-pse": {
      label: "Google Programmable Search",
      requiresKey: true,
      keyUrl: "https://programmablesearchengine.google.com/controlpanel/create",
      baseUrl: "https://www.googleapis.com/customsearch/v1",
      baseUrlRequired: false,
      fields: [{ id: "google_cx", label: "Engine id (cx)", required: true }],
    },
  },
  limits: {
    maxResults: { default: 5, min: 1, max: 10 },
    timeoutMs: { default: 8000, min: 500, max: 30000 },
  },
};

const storedGoogle = {
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
};

function mockCatalog() {
  vi.mocked(aiApi.getSearchProviderCatalog).mockResolvedValue(catalog as never);
}

async function openMenu(index = 0) {
  const { userEvent } = await import("@testing-library/user-event");
  const user = userEvent.setup();
  const triggers = screen.getAllByRole("button", {
    name: "toolsSettings.webSearch.actionsAria",
  });
  await user.click(triggers[index]);
  return user;
}

describe("WebSearchSection (family web-search-providers module)", () => {
  it("adds a keyed provider through the tiles → form wizard", async () => {
    vi.mocked(aiApi.listSearchProviders).mockResolvedValue([]);
    vi.mocked(aiApi.createSearchProvider).mockResolvedValue(storedGoogle as never);
    mockCatalog();
    const { userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    render(<WebSearchSection />);

    await user.click(await screen.findByText("toolsSettings.webSearch.add"));
    await user.click(
      await screen.findByRole("button", { name: /^Google Programmable Search/ }),
    );
    await user.type(
      await screen.findByLabelText("Engine id (cx)"),
      "a1b2c3d4e5f6g7h8j",
    );
    await user.type(
      screen.getByLabelText("toolsSettings.webSearch.key"),
      "AIza-secret",
    );
    await user.click(screen.getByText("toolsSettings.webSearch.save"));

    await waitFor(() => expect(aiApi.createSearchProvider).toHaveBeenCalled());
    expect(aiApi.createSearchProvider).toHaveBeenCalledWith({
      type: "google-pse",
      name: "Google Programmable Search",
      base_url: null,
      google_cx: "a1b2c3d4e5f6g7h8j",
      max_results: null,
      timeout_ms: null,
      api_key: "AIza-secret",
    });
  });

  it("numbers the seeded connection name when the label is taken", async () => {
    vi.mocked(aiApi.listSearchProviders).mockResolvedValue([
      { ...storedGoogle, id: "p2", name: "Tavily", type: "tavily" },
    ]);
    mockCatalog();
    const { userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    render(<WebSearchSection />);

    await user.click(await screen.findByText("toolsSettings.webSearch.add"));
    await user.click(await screen.findByRole("button", { name: /^Tavily/ }));
    const name = await screen.findByLabelText("toolsSettings.webSearch.nameLabel");
    expect(name).toHaveValue("Tavily 2");
  });

  it("edits a stored google_pse row through the settings form", async () => {
    vi.mocked(aiApi.listSearchProviders).mockResolvedValue([storedGoogle]);
    vi.mocked(aiApi.updateSearchProvider).mockResolvedValue(storedGoogle as never);
    mockCatalog();
    render(<WebSearchSection />);
    await screen.findByTestId("wsp-row-p1");
    const user = await openMenu();
    await user.click(screen.getByRole("menuitem", { name: "toolsSettings.webSearch.edit" }));

    const cx = await screen.findByLabelText("Engine id (cx)");
    expect(cx).toHaveValue("cx-123");
    expect(screen.getAllByText("••••cret").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("toolsSettings.webSearch.baseUrl")).toHaveValue(
      "https://www.googleapis.com/customsearch/v1",
    );

    await user.clear(cx);
    await user.type(cx, "cx-999");
    await user.click(screen.getByText("toolsSettings.webSearch.save"));

    await waitFor(() => expect(aiApi.updateSearchProvider).toHaveBeenCalled());
    expect(aiApi.updateSearchProvider).toHaveBeenCalledWith("p1", {
      type: "google-pse",
      name: "Google",
      base_url: "https://www.googleapis.com/customsearch/v1",
      google_cx: "cx-999",
      max_results: 5,
      timeout_ms: 8000,
      api_key: null,
    });
  });

  it("restores a stored base-URL override to the catalog default on edit", async () => {
    vi.mocked(aiApi.listSearchProviders).mockResolvedValue([
      {
        ...storedGoogle,
        id: "p3",
        name: "Tavily proxy",
        type: "tavily",
        base_url: "https://tavily.internal.example",
        google_cx: null,
        key_hint: null,
        key_set: false,
      },
    ]);
    vi.mocked(aiApi.updateSearchProvider).mockResolvedValue(storedGoogle as never);
    mockCatalog();
    render(<WebSearchSection />);
    await screen.findByTestId("wsp-row-p3");
    const user = await openMenu();
    await user.click(screen.getByRole("menuitem", { name: "toolsSettings.webSearch.edit" }));

    const url = await screen.findByLabelText("toolsSettings.webSearch.baseUrl");
    expect(url).toHaveValue("https://tavily.internal.example");
    await user.clear(url);
    await user.type(url, "https://api.tavily.com");
    await user.click(screen.getByText("toolsSettings.webSearch.save"));

    await waitFor(() => expect(aiApi.updateSearchProvider).toHaveBeenCalled());
    expect(aiApi.updateSearchProvider).toHaveBeenCalledWith(
      "p3",
      expect.objectContaining({ base_url: "https://api.tavily.com" }),
    );
  });

  it("keeps the edit modal open and shows the error when the save fails", async () => {
    vi.mocked(aiApi.listSearchProviders).mockResolvedValue([storedGoogle]);
    vi.mocked(aiApi.updateSearchProvider).mockRejectedValue(new Error("nope"));
    mockCatalog();
    render(<WebSearchSection />);
    await screen.findByTestId("wsp-row-p1");
    const user = await openMenu();
    await user.click(screen.getByRole("menuitem", { name: "toolsSettings.webSearch.edit" }));

    await user.click(await screen.findByText("toolsSettings.webSearch.save"));
    expect(await screen.findByRole("alert")).toHaveTextContent("nope");
    expect(screen.getByLabelText("Engine id (cx)")).toBeInTheDocument();
  });

  it("gates delete behind the confirmation modal", async () => {
    vi.mocked(aiApi.listSearchProviders).mockResolvedValue([storedGoogle]);
    vi.mocked(aiApi.deleteSearchProvider).mockResolvedValue(undefined);
    mockCatalog();
    render(<WebSearchSection />);
    await screen.findByTestId("wsp-row-p1");
    const user = await openMenu();
    await user.click(screen.getByRole("menuitem", { name: "toolsSettings.webSearch.delete" }));

    expect(screen.getByText("toolsSettings.webSearch.deleteTitle")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "toolsSettings.webSearch.delete" }));
    await waitFor(() => expect(aiApi.deleteSearchProvider).toHaveBeenCalledWith("p1"));
  });

  it("toggles and reorders from the management menu", async () => {
    vi.mocked(aiApi.listSearchProviders).mockResolvedValue([
      storedGoogle,
      { ...storedGoogle, id: "p2", name: "Tavily", type: "tavily", google_cx: null },
    ]);
    vi.mocked(aiApi.updateSearchProvider).mockResolvedValue(storedGoogle as never);
    vi.mocked(aiApi.moveSearchProvider).mockResolvedValue([]);
    mockCatalog();
    render(<WebSearchSection />);
    await screen.findByTestId("wsp-row-p1");
    const user = await openMenu();
    await user.click(screen.getByRole("menuitem", { name: "toolsSettings.webSearch.disable" }));
    await waitFor(() =>
      expect(aiApi.updateSearchProvider).toHaveBeenCalledWith("p1", { enabled: false }),
    );

    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "toolsSettings.webSearch.actionsAria" })).toHaveLength(2),
    );
    const secondMenu = screen.getAllByRole("button", {
      name: "toolsSettings.webSearch.actionsAria",
    })[1];
    await user.click(secondMenu);
    await user.click(screen.getByRole("menuitem", { name: "toolsSettings.webSearch.moveUp" }));
    await waitFor(() =>
      expect(aiApi.moveSearchProvider).toHaveBeenCalledWith("p2", "up"),
    );
  });

  it("renders the probe result on the card connection line", async () => {
    vi.mocked(aiApi.listSearchProviders).mockResolvedValue([storedGoogle]);
    vi.mocked(aiApi.testSearchProvider).mockResolvedValue({
      status: "ok",
      latency_ms: 234,
      result_count: 5,
      error: null,
    });
    mockCatalog();
    render(<WebSearchSection />);
    await screen.findByTestId("wsp-row-p1");
    const user = await openMenu();
    await user.click(screen.getByRole("menuitem", { name: "toolsSettings.webSearch.test" }));

    await waitFor(() =>
      expect(screen.getByText("toolsSettings.webSearch.probeOk")).toBeInTheDocument(),
    );
    expect(screen.getByText(/234/)).toBeInTheDocument();
  });

  it("keeps the wizard open and shows the error when the save fails", async () => {
    vi.mocked(aiApi.listSearchProviders).mockResolvedValue([]);
    vi.mocked(aiApi.createSearchProvider).mockRejectedValue(new Error("boom"));
    mockCatalog();
    const { userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    render(<WebSearchSection />);

    await user.click(await screen.findByText("toolsSettings.webSearch.add"));
    await user.click(await screen.findByRole("button", { name: /^SearXNG/ }));
    await user.type(
      await screen.findByLabelText("toolsSettings.webSearch.baseUrlRequired"),
      "https://searx.example.org",
    );
    await user.click(screen.getByText("toolsSettings.webSearch.save"));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("boom"));
    expect(aiApi.createSearchProvider).toHaveBeenCalledWith({
      type: "searxng",
      name: "SearXNG",
      base_url: "https://searx.example.org",
      google_cx: null,
      max_results: null,
      timeout_ms: null,
      api_key: null,
    });
  });
});
