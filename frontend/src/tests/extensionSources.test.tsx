import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as extApi from "@/api/extensionSources";
import { ExtensionSourcesSection } from "@/components/settings/ExtensionSourcesSection";

vi.mock("@/api/extensionSources", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/extensionSources")>();
  return {
    ...actual,
    fetchExtensionSources: vi.fn(),
    addExtensionSource: vi.fn(),
    syncExtensionSource: vi.fn(),
    removeExtensionSource: vi.fn(),
    installExtension: vi.fn(),
    applyExtensionUpdate: vi.fn(),
    setExtensionEnabled: vi.fn(),
    parkExtensionInstall: vi.fn(),
    tombstoneExtensionInstall: vi.fn(),
  };
});

const mocked = vi.mocked(extApi);

const T3_DISCLOSURE =
  "This extension runs as a separate process outside the app's network perimeter. It opens its own network connections, with no SSRF guard, robots.txt check or rate limiting by the app. The app governs only what it returns: outputs are validated and capped.";

const CANDIDATE = {
  extensionId: "example-posting-fetcher",
  subpath: ".",
  digest: "3af53a1ef0ece88bdce9469f83db5f584d17fc18b56634578688a9a8794ec75e",
  ref: "23a189e9aa1e536e51eb5ab4cb4630cf4718c8df",
  compatible: true,
  reason: null,
  hasEntry: true,
  consent: {
    extensionId: "example-posting-fetcher",
    version: "1.0.0",
    subpath: ".",
    digest: "3af53a1ef0ece88bdce9469f83db5f584d17fc18b56634578688a9a8794ec75e",
    tier: "T3",
    importClass: "imported",
    capabilities: ["sync"],
    provenance: {
      author: "Neuronection",
      license: "MIT",
      repository: "https://example.com/your-fork/career-connector-template",
      description: "Reference posting fetcher",
    },
    disclosureKey: "t3PerimeterDisclosure",
    disclosure: T3_DISCLOSURE,
  },
};

const SOURCE = {
  id: "src-1",
  kind: "local" as const,
  origin: "/tmp/ext-repo",
  descriptor: {
    url: null,
    local: { path: "/tmp/ext-repo" },
    ref: { strategy: "branch" as const, value: "main" },
    credentialSlots: [],
  },
  status: "ok" as const,
  error: "",
  last_checked_at: null,
  last_success_at: null,
  consecutive_failures: 0,
  candidates: [CANDIDATE],
  installs: [],
};

const INSTALL = {
  id: "inst-1",
  extensionId: "example-posting-fetcher",
  version: "1.0.0",
  digest: CANDIDATE.digest,
  pinRef: "v1.0.0",
  tier: "T3" as const,
  originClass: "imported" as const,
  state: "installed" as const,
  enabled: false,
  managedBy: "manual" as const,
  parked: false,
  sourceKey: "example-posting-fetcher",
  contentPath: "/data/extensions/example-posting-fetcher/abc",
  provenance: CANDIDATE.consent.provenance,
  consentedAt: "2026-10-16T00:00:00Z",
  update: {},
  tombstonedAt: null,
};

function renderSection() {
  return render(<ExtensionSourcesSection />);
}

describe("ExtensionSourcesSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.fetchExtensionSources.mockResolvedValue([]);
  });

  it("renders an empty state and the add form affordance", async () => {
    renderSection();
    await waitFor(() => expect(mocked.fetchExtensionSources).toHaveBeenCalled());
    expect(screen.getByTestId("extension-sources-block")).toBeTruthy();
    expect(screen.getByTestId("add-extension-source")).toBeTruthy();
  });

  it("renders a candidate with the VERBATIM consent disclosure", async () => {
    mocked.fetchExtensionSources.mockResolvedValue([SOURCE]);
    renderSection();
    const disclosure = await screen.findByTestId("consent-disclosure");
    expect(disclosure.textContent).toContain(T3_DISCLOSURE);
    expect(screen.getByTestId("consent-digest").textContent).toBe(CANDIDATE.digest);
    expect(disclosure.textContent).toContain("Neuronection");
    expect(disclosure.textContent).toContain("MIT");
    expect(screen.getByTestId("consent-install-example-posting-fetcher")).toBeTruthy();
  });

  it("marks incompatible candidates with the reason, no install affordance", async () => {
    mocked.fetchExtensionSources.mockResolvedValue([
      {
        ...SOURCE,
        candidates: [{ ...CANDIDATE, compatible: false, reason: "kind 'mini-app' is not hosted" }],
      },
    ]);
    renderSection();
    await screen.findByTestId("extension-candidate-example-posting-fetcher");
    expect(screen.queryByTestId("consent-install-example-posting-fetcher")).toBeNull();
  });

  it("installs only through the explicit consent confirmation", async () => {
    mocked.fetchExtensionSources.mockResolvedValue([SOURCE]);
    mocked.installExtension.mockResolvedValue(INSTALL);
    renderSection();
    fireEvent.click(await screen.findByTestId("consent-install-example-posting-fetcher"));
    expect(mocked.installExtension).not.toHaveBeenCalled();
    expect(screen.getByTestId("consent-confirm")).toBeTruthy();
    fireEvent.click(screen.getByTestId("confirm-consent"));
    await waitFor(() =>
      expect(mocked.installExtension).toHaveBeenCalledWith(
        "src-1",
        "example-posting-fetcher",
        true,
      ),
    );
  });

  it("renders installs with the imported origin chip and update affordances", async () => {
    mocked.fetchExtensionSources.mockResolvedValue([
      {
        ...SOURCE,
        candidates: [],
        installs: [
          {
            ...INSTALL,
            update: {
              state: "available",
              digest: "9".repeat(64),
              requiresReconsent: true,
              manifestDiff: {
                capabilitiesAdded: ["secrets"],
                configSchemaChanged: false,
                version: { from: "1.0.0", to: "1.1.0" },
              },
            },
          },
        ],
      },
    ]);
    renderSection();
    const row = await screen.findByTestId("extension-install-example-posting-fetcher");
    expect(row.querySelector('[data-testid="origin-chip"]')?.textContent).toBe("imported");
    expect(screen.getByTestId("update-available").textContent).toContain("1.1.0");
    expect(screen.getByTestId("update-available").textContent).toContain(
      "re-consent required",
    );
    expect(screen.getByTestId("apply-update-example-posting-fetcher")).toBeTruthy();

    fireEvent.click(screen.getByTestId("apply-update-example-posting-fetcher"));
    await waitFor(() => expect(mocked.applyExtensionUpdate).toHaveBeenCalledWith("inst-1", true));
  });

  it("surfaces digest drift loudly", async () => {
    mocked.fetchExtensionSources.mockResolvedValue([
      {
        ...SOURCE,
        candidates: [],
        installs: [
          {
            ...INSTALL,
            update: {
              state: "digest-drift",
              ref: "v1.0.0",
              detail: "pinned ref content changed",
            },
          },
        ],
      },
    ]);
    renderSection();
    expect(await screen.findByTestId("digest-drift")).toBeTruthy();
  });

  it("parks an install without deleting anything", async () => {
    mocked.fetchExtensionSources.mockResolvedValue([
      { ...SOURCE, candidates: [], installs: [INSTALL] },
    ]);
    mocked.parkExtensionInstall.mockResolvedValue({ ...INSTALL, parked: true });
    renderSection();
    fireEvent.click(await screen.findByTestId("park-example-posting-fetcher"));
    await waitFor(() => expect(mocked.parkExtensionInstall).toHaveBeenCalledWith("inst-1"));
  });

  it("adds an https source with a tag-pattern ref and syncs it", async () => {
    mocked.fetchExtensionSources.mockResolvedValue([]);
    mocked.addExtensionSource.mockResolvedValue(SOURCE);
    mocked.syncExtensionSource.mockResolvedValue({ ok: true });
    renderSection();
    fireEvent.click(await screen.findByTestId("add-extension-source"));
    fireEvent.change(screen.getByLabelText("https git URL"), {
      target: { value: "https://git.example.com/ext/repo" },
    });
    fireEvent.change(screen.getByLabelText("Ref strategy"), {
      target: { value: "tag-pattern" },
    });
    fireEvent.change(
      screen.getByLabelText("Tag pattern / branch / commit sha"),
      { target: { value: "v*" } },
    );
    fireEvent.submit(screen.getByTestId("extension-source-form"));
    await waitFor(() => expect(mocked.addExtensionSource).toHaveBeenCalled());
    const payload = mocked.addExtensionSource.mock.calls[0][0];
    expect(payload.descriptor).toEqual({
      url: "https://git.example.com/ext/repo",
      ref: { strategy: "tag-pattern", value: "v*" },
    });
    await waitFor(() => expect(mocked.syncExtensionSource).toHaveBeenCalledWith("src-1"));
  });
});
