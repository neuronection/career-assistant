import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { TaxonomyEmbeddingsCard } from "@/components/settings/TaxonomyEmbeddingsCard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      const templates: Record<string, string> = {
        "taxonomy.embeddings.switchNote": "Saved — effective on the next decision.",
        "taxonomy.embeddings.retrievalLink": "Manage retrieval index",
        "taxonomy.embeddings.retrievalHint": "coverage, reindex and space operations.",
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

const apiGet = vi.fn();
const apiPut = vi.fn();

vi.mock("@/api/client", () => ({
  api: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => vi.fn()(...args),
    put: (...args: unknown[]) => apiPut(...args),
  },
}));

afterEach(() => {
  apiGet.mockReset();
  apiPut.mockReset();
});

function settings(overrides: Partial<Record<string, boolean>> = {}) {
  return {
    job_proposals: true,
    semantic_rescue: true,
    semantic_rerank: false,
    ...overrides,
  };
}

function renderCard() {
  return render(
    <MemoryRouter>
      <TaxonomyEmbeddingsCard />
    </MemoryRouter>,
  );
}

function setup(overrides: Partial<Record<string, boolean>> = {}) {
  apiGet.mockImplementation((url: string) => {
    if (url === "/admin/catalog-mapping/settings") {
      return Promise.resolve({ data: settings(overrides) });
    }
    return Promise.reject(new Error(`unexpected GET ${url}`));
  });
}

describe("TaxonomyEmbeddingsCard", () => {
  it("renders the three mapping switches from the API values", async () => {
    setup();
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("embeddings-switch-proposals")).toBeTruthy(),
    );
    expect(
      screen.getByTestId("embeddings-switch-proposals").getAttribute("aria-checked"),
    ).toBe("true");
    expect(
      screen
        .getByTestId("embeddings-switch-semantic-rescue")
        .getAttribute("aria-checked"),
    ).toBe("true");
    expect(
      screen
        .getByTestId("embeddings-switch-semantic-rerank")
        .getAttribute("aria-checked"),
    ).toBe("false");
    expect(screen.queryByTestId("embeddings-switch-semantic")).toBeNull();
  });

  it("links the store operations to Tools → Retrieval and keeps behavior switches here", async () => {
    setup();
    renderCard();
    await waitFor(() => expect(screen.getByTestId("embeddings-card")).toBeTruthy());
    expect(screen.getByTestId("embeddings-retrieval-link").getAttribute("href")).toBe(
      "/settings/tools?section=retrieval",
    );
    expect(screen.getByTestId("embeddings-switch-semantic-rescue")).toBeTruthy();
    expect(screen.getByTestId("embeddings-switch-semantic-rerank")).toBeTruthy();
  });

  it("shows the API's OFF rerank and ON rescue, never local defaults", async () => {
    setup({ semantic_rescue: false, semantic_rerank: true });
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("embeddings-switch-semantic-rerank")).toBeTruthy(),
    );
    expect(
      screen
        .getByTestId("embeddings-switch-semantic-rescue")
        .getAttribute("aria-checked"),
    ).toBe("false");
    expect(
      screen
        .getByTestId("embeddings-switch-semantic-rerank")
        .getAttribute("aria-checked"),
    ).toBe("true");
  });

  it("flips the job proposals switch through the settings endpoint", async () => {
    setup();
    apiPut.mockResolvedValue({ data: settings({ job_proposals: false }) });
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("embeddings-switch-proposals")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("embeddings-switch-proposals"));
    await waitFor(() => expect(apiPut).toHaveBeenCalledTimes(1));
    expect(apiPut.mock.calls[0][1]).toEqual({ job_proposals: false });
    await waitFor(() =>
      expect(
        screen.getByTestId("embeddings-switch-proposals").getAttribute("aria-checked"),
      ).toBe("false"),
    );
    expect(screen.getByTestId("embeddings-note").textContent).toContain("Saved");
  });

  it("flips semantic rescue independently", async () => {
    setup();
    apiPut.mockResolvedValue({ data: settings({ semantic_rescue: false }) });
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("embeddings-switch-semantic-rescue")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("embeddings-switch-semantic-rescue"));
    await waitFor(() => expect(apiPut).toHaveBeenCalledTimes(1));
    expect(apiPut.mock.calls[0][1]).toEqual({ semantic_rescue: false });
    await waitFor(() =>
      expect(
        screen
          .getByTestId("embeddings-switch-semantic-rescue")
          .getAttribute("aria-checked"),
      ).toBe("false"),
    );
    expect(
      screen
        .getByTestId("embeddings-switch-semantic-rerank")
        .getAttribute("aria-checked"),
    ).toBe("false");
  });

  it("flips semantic rerank independently", async () => {
    setup();
    apiPut.mockResolvedValue({ data: settings({ semantic_rerank: true }) });
    renderCard();
    await waitFor(() =>
      expect(screen.getByTestId("embeddings-switch-semantic-rerank")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("embeddings-switch-semantic-rerank"));
    await waitFor(() => expect(apiPut).toHaveBeenCalledTimes(1));
    expect(apiPut.mock.calls[0][1]).toEqual({ semantic_rerank: true });
    await waitFor(() =>
      expect(
        screen
          .getByTestId("embeddings-switch-semantic-rerank")
          .getAttribute("aria-checked"),
      ).toBe("true"),
    );
    expect(
      screen
        .getByTestId("embeddings-switch-semantic-rescue")
        .getAttribute("aria-checked"),
    ).toBe("true");
  });
});
