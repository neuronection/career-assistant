import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { TaxonomyEmbeddingsCard } from "@/components/settings/TaxonomyEmbeddingsCard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      const templates: Record<string, string> = {
        "taxonomy.embeddings.switchNote": "Saved — effective on the next decision.",
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

function setup(proposals = true) {
  apiGet.mockImplementation((url: string) => {
    if (url === "/admin/catalog-mapping/settings") {
      return Promise.resolve({ data: { job_proposals: proposals } });
    }
    return Promise.reject(new Error(`unexpected GET ${url}`));
  });
}

describe("TaxonomyEmbeddingsCard", () => {
  it("renders the mapping run switch", async () => {
    setup();
    render(<TaxonomyEmbeddingsCard />);
    await waitFor(() => expect(screen.getByTestId("embeddings-switch-proposals")).toBeTruthy());
    expect(
      screen.getByTestId("embeddings-switch-proposals").getAttribute("aria-checked"),
    ).toBe("true");
    expect(screen.queryByTestId("embeddings-buckets")).toBeNull();
    expect(screen.queryByTestId("embeddings-switch-semantic")).toBeNull();
  });

  it("flips the switch through the settings endpoint", async () => {
    setup();
    apiPut.mockResolvedValue({ data: { job_proposals: false } });
    render(<TaxonomyEmbeddingsCard />);
    await waitFor(() => expect(screen.getByTestId("embeddings-switch-proposals")).toBeTruthy());
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
});
