import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { SourcesSection } from "@/components/settings/SourcesSection";
import * as catalogsApi from "@/api/sourcesCatalogs";
import * as sourcesApi from "@/api/sources";
import { validateCatalog, type SourcesCatalog } from "@/config/sourcesCatalogs";

import liveDocument from "./fixtures/ats-catalog-greece.json";

vi.mock("@/api/sources", () => ({
  fetchAdminSources: vi.fn(),
  fetchConnectorCatalog: vi.fn(),
  createSource: vi.fn(),
  updateSource: vi.fn(),
  deleteSource: vi.fn(),
  probeSource: vi.fn(),
  syncSource: vi.fn(),
}));

vi.mock("@/api/sourcesCatalogs", () => ({
  fetchCatalogs: vi.fn(),
  putCatalog: vi.fn(),
  deleteCatalog: vi.fn(),
}));

const CANONICAL_URL = "https://neuronection.com/api/v1/career/ats-catalogs/greece.json";
const CONTENT_HASH =
  "sha256:7007ba75b97b5b20c8f7120397e4888ed6e6d312367bf969765be68c16643d23";

const parsedLive = validateCatalog(liveDocument);
if (!parsedLive.ok) throw new Error(parsedLive.error);
const live = parsedLive.document;

const storedCatalog: SourcesCatalog = {
  id: "neuronection-greece",
  kind: "url",
  url: CANONICAL_URL,
  name: live.name,
  license: live.license ?? null,
  tier: "operator",
  fetchedAt: "2026-11-23T00:00:00Z",
  updatedAt: live.updatedAt,
  revision: live.revision,
  contentHash: live.contentHash,
  etag: null,
  lastModified: null,
  presets: live.presets,
  providers: live.providers,
};

const fetchMock = vi.fn();

function jsonResponse(body: unknown, status = 200): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: new Headers({ "content-type": "application/json" }),
    text: async () => JSON.stringify(body),
  } as Response;
}

function renderSection() {
  return render(
    <MemoryRouter>
      <SourcesSection />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("fetch", fetchMock);
  vi.mocked(sourcesApi.fetchAdminSources).mockResolvedValue([]);
  vi.mocked(sourcesApi.fetchConnectorCatalog).mockResolvedValue([]);
  vi.mocked(catalogsApi.deleteCatalog).mockResolvedValue({
    id: "neuronection-greece",
    deleted: true,
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("featured operator catalog", () => {
  it("imports in one click through the browser fetch + PUT rail", async () => {
    vi.mocked(catalogsApi.fetchCatalogs)
      .mockResolvedValueOnce([])
      .mockResolvedValue([storedCatalog]);
    vi.mocked(catalogsApi.putCatalog).mockResolvedValue(storedCatalog);
    fetchMock.mockResolvedValue(jsonResponse(liveDocument));

    renderSection();

    const importButton = await screen.findByTestId(
      "catalog-featured-import-neuronection-greece",
    );
    expect(screen.getByTestId("catalog-featured-neuronection-greece").textContent).toContain(
      "Neuronection verified — Greece",
    );
    expect(screen.getByTestId("catalog-featured-neuronection-greece").textContent).toContain(
      CANONICAL_URL,
    );

    await userEvent.click(importButton);

    await waitFor(() => expect(catalogsApi.putCatalog).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(CANONICAL_URL, {
      headers: {},
      redirect: "follow",
    });
    const [catalogId, payload] = vi.mocked(catalogsApi.putCatalog).mock.calls[0]!;
    expect(typeof catalogId).toBe("string");
    expect(payload).toMatchObject({
      tier: "operator",
      url: CANONICAL_URL,
      name: "Neuronection verified — Greece",
      revision: 2,
      contentHash: CONTENT_HASH,
      signature: null,
    });
    expect(payload.presets).toHaveLength(17);
    expect(payload.providers).toEqual([]);

    await waitFor(() =>
      expect(screen.getByTestId("catalog-report-line-1").textContent).toContain(
        "sha256:7007ba75",
      ),
    );
    expect(screen.getByTestId("catalog-report-line-0").textContent).toContain(
      "Neuronection verified — Greece",
    );
    expect(
      (screen.getByTestId("catalog-url-input") as HTMLInputElement).value,
    ).toBe(CANONICAL_URL);
    expect(screen.getByTestId("catalog-featured-state-neuronection-greece").textContent).toContain(
      "Imported — revision 2",
    );
    expect(screen.getByTestId("catalog-featured-hash-neuronection-greece").textContent).toBe(
      "sha256:7007ba75…",
    );
  });

  it("shows the imported revision and hash, and refreshing at the same revision never re-PUTs", async () => {
    vi.mocked(catalogsApi.fetchCatalogs).mockResolvedValue([storedCatalog]);
    fetchMock.mockResolvedValue(jsonResponse(liveDocument));

    renderSection();

    expect(
      (await screen.findByTestId("catalog-featured-state-neuronection-greece")).textContent,
    ).toContain("Imported — revision 2");
    expect(screen.getByTestId("catalog-hash-neuronection-greece").textContent).toBe(
      "sha256:7007ba75…",
    );

    await userEvent.click(
      screen.getByTestId("catalog-featured-refresh-neuronection-greece"),
    );

    await waitFor(() =>
      expect(screen.getByTestId("catalog-report-line-0").textContent).toContain(
        "Already at revision 2.",
      ),
    );
    expect(fetchMock).toHaveBeenCalledWith(CANONICAL_URL, {
      headers: {},
      redirect: "follow",
    });
    expect(catalogsApi.putCatalog).not.toHaveBeenCalled();
  });

  it("refreshes a newer revision through the same PUT rail", async () => {
    const newer = { ...liveDocument, revision: 3 };
    vi.mocked(catalogsApi.fetchCatalogs).mockResolvedValue([storedCatalog]);
    vi.mocked(catalogsApi.putCatalog).mockResolvedValue({
      ...storedCatalog,
      revision: 3,
    });
    fetchMock.mockResolvedValue(jsonResponse(newer));

    renderSection();

    await userEvent.click(
      await screen.findByTestId("catalog-featured-refresh-neuronection-greece"),
    );

    await waitFor(() => expect(catalogsApi.putCatalog).toHaveBeenCalledTimes(1));
    const [catalogId, payload] = vi.mocked(catalogsApi.putCatalog).mock.calls[0]!;
    expect(catalogId).toBe("neuronection-greece");
    expect(payload).toMatchObject({
      tier: "operator",
      url: CANONICAL_URL,
      revision: 3,
      contentHash: CONTENT_HASH,
    });
    await waitFor(() =>
      expect(screen.getByTestId("catalog-report-line-0").textContent).toContain(
        "revision bumped to 3",
      ),
    );
  });
});
