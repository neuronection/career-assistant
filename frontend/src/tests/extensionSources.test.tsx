import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as extApi from "@/api/extensionSources";
import { ExtensionSourcesSection } from "@/components/settings/ExtensionSourcesSection";

// plan 33 Phase B: the sources surface renders through the family kit
// (IntegrationSourcesList + AddIntegrationSourceDialog + ConsentDialog) —
// these tests pin the app glue: api mapping, the VERBATIM consent payload
// hand-off, and every mutation as an explicit api call.

vi.mock("@/api/extensionSources", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/extensionSources")>();
  return {
    ...actual,
    fetchExtensionSources: vi.fn(),
    addExtensionSource: vi.fn(),
    syncExtensionSource: vi.fn(),
    removeExtensionSource: vi.fn(),
    fetchInstallPreview: vi.fn(),
    fetchUpdatePreview: vi.fn(),
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

const ECHO = {
  digest: CANDIDATE.digest,
  capabilities: ["sync"],
  version: "1.0.0",
};

const PREVIEW = {
  extensionId: CANDIDATE.extensionId,
  version: "1.0.0",
  subpath: ".",
  digest: CANDIDATE.digest,
  tier: "T3",
  capabilities: ["sync"],
  ref: CANDIDATE.ref,
  consent: CANDIDATE.consent,
  echo: ECHO,
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

describe("ExtensionSourcesSection (kit surfaces)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.fetchExtensionSources.mockResolvedValue([]);
    mocked.fetchInstallPreview.mockResolvedValue(PREVIEW);
    mocked.fetchUpdatePreview.mockResolvedValue(PREVIEW);
  });

  it("renders the empty kit list and the add-source affordance", async () => {
    renderSection();
    await waitFor(() => expect(mocked.fetchExtensionSources).toHaveBeenCalled());
    expect(screen.getByTestId("extension-sources-block")).toBeTruthy();
    expect(screen.getByTestId("integration-sources-empty")).toBeTruthy();
    expect(screen.getByTestId("add-extension-source")).toBeTruthy();
  });

  it("renders a candidate whose consent opens with the VERBATIM disclosure", async () => {
    const { userEvent } = await import("@testing-library/user-event");
    mocked.fetchExtensionSources.mockResolvedValue([SOURCE]);
    renderSection();
    fireEvent.click(await screen.findByTestId("integration-candidate-example-posting-fetcher"));
    const install = screen.getByRole("button", { name: "Install with consent…" });
    await userEvent.click(install);
    const dialog = await screen.findByTestId("integration-consent");
    expect(screen.getByTestId("integration-consent-disclosure").textContent).toBe(T3_DISCLOSURE);
    expect(screen.getByTestId("integration-consent-digest").textContent).toBe(CANDIDATE.digest);
    expect(dialog.textContent).toContain("Neuronection");
    expect(dialog.textContent).toContain("MIT");
  });

  it("installs only through the explicit consent confirmation", async () => {
    const { userEvent } = await import("@testing-library/user-event");
    mocked.fetchExtensionSources.mockResolvedValue([SOURCE]);
    mocked.installExtension.mockResolvedValue(INSTALL);
    renderSection();
    fireEvent.click(await screen.findByTestId("integration-candidate-example-posting-fetcher"));
    await userEvent.click(await screen.findByRole("button", { name: "Install with consent…" }));
    expect(mocked.installExtension).not.toHaveBeenCalled();
    await userEvent.click(await screen.findByRole("button", { name: "I consent — install" }));
    await waitFor(() =>
      expect(mocked.installExtension).toHaveBeenCalledWith(
        "src-1",
        "example-posting-fetcher",
        ECHO,
      ),
    );
  });

  it("marks incompatible candidates with the reason, no install affordance", async () => {
    mocked.fetchExtensionSources.mockResolvedValue([
      {
        ...SOURCE,
        candidates: [{ ...CANDIDATE, compatible: false, reason: "kind 'mini-app' is not hosted" }],
      },
    ]);
    renderSection();
    const row = await screen.findByTestId("integration-candidate-example-posting-fetcher");
    expect(row.textContent).toContain("kind 'mini-app' is not hosted");
    expect(screen.queryByRole("button", { name: "Install with consent…" })).toBeNull();
  });

  it("renders installs with the imported origin chip and update affordances", async () => {
    const { userEvent } = await import("@testing-library/user-event");
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
    mocked.applyExtensionUpdate.mockResolvedValue(INSTALL);
    renderSection();
    const row = await screen.findByTestId("integration-instance-inst-1");
    expect(row.querySelector('[data-origin-class="imported"]')?.textContent).toBe("imported");
    expect(screen.getByTestId("integration-update-inst-1").textContent).toContain("1.1.0");
    expect(screen.getByTestId("integration-update-inst-1").textContent).toContain(
      "re-consent required",
    );
    await userEvent.click(screen.getByRole("button", { name: /Apply update/ }));
    await waitFor(() =>
      expect(mocked.applyExtensionUpdate).toHaveBeenCalledWith("inst-1", ECHO),
    );
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
    expect(await screen.findByTestId("integration-drift-inst-1")).toBeTruthy();
  });

  it("parks an install without deleting anything", async () => {
    const { userEvent } = await import("@testing-library/user-event");
    mocked.fetchExtensionSources.mockResolvedValue([
      { ...SOURCE, candidates: [], installs: [INSTALL] },
    ]);
    mocked.parkExtensionInstall.mockResolvedValue({ ...INSTALL, parked: true });
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Park" }));
    await waitFor(() => expect(mocked.parkExtensionInstall).toHaveBeenCalledWith("inst-1"));
  });

  it("adds an https source with a tag-pattern ref and syncs it", async () => {
    const { userEvent } = await import("@testing-library/user-event");
    mocked.fetchExtensionSources.mockResolvedValue([]);
    mocked.addExtensionSource.mockResolvedValue(SOURCE);
    mocked.syncExtensionSource.mockResolvedValue({ ok: true });
    renderSection();
    await userEvent.click(await screen.findByTestId("add-extension-source"));
    await userEvent.type(await screen.findByLabelText("https git URL"), "https://git.example.com/ext/repo");
    await userEvent.selectOptions(screen.getByLabelText("Ref strategy"), "tag-pattern");
    await userEvent.type(
      screen.getByLabelText("Tag pattern / branch / commit sha"),
      "v*",
    );
    await userEvent.click(screen.getByRole("button", { name: "Add source" }));
    await waitFor(() => expect(mocked.addExtensionSource).toHaveBeenCalled());
    const payload = mocked.addExtensionSource.mock.calls[0]![0];
    expect(payload.descriptor).toEqual({
      url: "https://git.example.com/ext/repo",
      ref: { strategy: "tag-pattern", value: "v*" },
    });
    await waitFor(() => expect(mocked.syncExtensionSource).toHaveBeenCalledWith("src-1"));
  });

  it("passes source errors through as alerts", async () => {
    mocked.fetchExtensionSources.mockResolvedValue([
      { ...SOURCE, candidates: [], installs: [], error: "sync failed: unreachable" },
    ]);
    renderSection();
    expect((await screen.findByRole("alert")).textContent).toBe(
      "sync failed: unreachable",
    );
  });
});
