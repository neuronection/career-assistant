import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { TaxonomyEmbeddingsCard } from "@/components/settings/TaxonomyEmbeddingsCard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      const templates: Record<string, string> = {
        "taxonomy.embeddings.bucket": "dim {{dim}} · {{count}} vectors",
        "taxonomy.embeddings.recomputeDone": "{{kind}} recompute embedded {{count}} rows.",
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
const apiPost = vi.fn();
const apiPut = vi.fn();

vi.mock("@/api/client", () => ({
  api: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
    put: (...args: unknown[]) => apiPut(...args),
  },
}));

const buckets = [
  { entity_kind: "posting", dim: 1024, count: 12 },
  { entity_kind: "job", dim: 1024, count: 3 },
];

afterEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  apiPut.mockReset();
});

function setup() {
  apiGet.mockImplementation((url: string) => {
    if (url === "/ai/embeddings/status") {
      return Promise.resolve({ data: buckets });
    }
    if (url === "/admin/catalog-mapping/settings") {
      return Promise.resolve({ data: { semantic_rescue: true, job_proposals: true } });
    }
    return Promise.reject(new Error(`unexpected GET ${url}`));
  });
}

describe("TaxonomyEmbeddingsCard", () => {
  it("renders the per-kind buckets and the run switches", async () => {
    setup();
    render(<TaxonomyEmbeddingsCard />);
    await waitFor(() => expect(screen.getByTestId("embeddings-buckets")).toBeTruthy());
    expect(screen.getByTestId("embeddings-bucket-posting").textContent).toContain("12");
    expect(screen.getByTestId("embeddings-bucket-job").textContent).toContain("3");
    expect(
      (screen.getByTestId("embeddings-switch-semantic").getAttribute("aria-checked")) === "true",
    ).toBe(true);
  });

  it("fires the recompute buttons with the right kind and reloads the buckets", async () => {
    setup();
    apiPost.mockResolvedValue({ data: { candidates: 5, embedded: 4, kind: "job" } });
    render(<TaxonomyEmbeddingsCard />);
    await waitFor(() => expect(screen.getByTestId("embeddings-recompute-job")).toBeTruthy());
    fireEvent.click(screen.getByTestId("embeddings-recompute-job"));
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1));
    expect(apiPost.mock.calls[0][0]).toBe("/ai/embeddings/recompute");
    expect((apiPost.mock.calls[0][2] as { params: { kind: string } }).params.kind).toBe("job");
    await waitFor(() =>
      expect(screen.getByTestId("embeddings-note").textContent).toContain("4"),
    );
  });

  it("flips a run switch through the settings endpoint", async () => {
    setup();
    apiPut.mockResolvedValue({
      data: { semantic_rescue: false, job_proposals: true },
    });
    render(<TaxonomyEmbeddingsCard />);
    await waitFor(() => expect(screen.getByTestId("embeddings-switch-semantic")).toBeTruthy());
    fireEvent.click(screen.getByTestId("embeddings-switch-semantic"));
    await waitFor(() => expect(apiPut).toHaveBeenCalledTimes(1));
    expect(apiPut.mock.calls[0][1]).toEqual({ semantic_rescue: false });
    await waitFor(() =>
      expect(
        (screen.getByTestId("embeddings-switch-semantic").getAttribute("aria-checked")) === "false",
      ).toBe(true),
    );
  });
});
