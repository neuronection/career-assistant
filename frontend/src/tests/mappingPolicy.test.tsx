import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import {
  dryRunMappingsPolicy,
  fetchMappingsPolicy,
  mappingsResolve,
  saveMappingsPolicy,
  type MappingDryRunResult,
  type MappingPolicy,
} from "@/api/mappings";
import { MappingRunsView } from "@/components/settings/MappingRunsView";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      let out = key;
      for (const [name, value] of Object.entries(params ?? {})) {
        out = out.split(`{{${name}}}`).join(String(value));
      }
      return out;
    },
    i18n: { language: "en" },
  }),
}));

vi.mock("@/api/mappings", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/mappings")>();
  return {
    ...actual,
    fetchMappingsOverview: vi.fn().mockResolvedValue({
      active: 2,
      described: 2,
      extracted: 2,
      mapped: 1,
      accounted: { mapped: 1, machine_terminal: 1, human_terminal: 0, total: 2 },
      states: { mapped: 1, below_threshold: 1 },
      gate: { floor: 0.95, rate: 1, pass: true },
      methods: {},
      reasons: {},
      proposals_pending: 0,
      switches: { job_proposals: true, semantic_rescue: true, semantic_rerank: false },
      last_remap: {
        job_id: "job-1",
        status: "succeeded",
        created_at: "2026-11-05T10:00:00Z",
        error: null,
      },
      health: {},
      legacy_outcome_count: 0,
    }),
    fetchMappingsPolicy: vi.fn(),
    saveMappingsPolicy: vi.fn(),
    dryRunMappingsPolicy: vi.fn(),
    mappingsResolve: vi.fn(),
    fetchMappingsQueue: vi.fn().mockResolvedValue({
      items: [
        { id: "p-1", ref: "AAAA1111" },
        { id: "p-2", ref: "BBBB2222" },
      ],
      total: 2,
      states: {},
    }),
  };
});

function policy(overrides: Partial<MappingPolicy> = {}): MappingPolicy {
  return {
    tau_job: 0.34,
    delta: 0.08,
    semantic_threshold: 0.6,
    semantic_min_shared_skills: 1,
    blend_deterministic: 0.75,
    blend_semantic: 0.25,
    k: 25,
    policy_hash: "abc123def4567890",
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(fetchMappingsPolicy).mockResolvedValue(policy());
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("mapping policy card (plan 205 S8)", () => {
  it("renders the editable thresholds and the read-only blend/k line", async () => {
    render(
      <MemoryRouter>
        <MappingRunsView />
      </MemoryRouter>,
    );
    await screen.findByTestId("mappings-policy");
    expect(screen.getByTestId("mappings-policy-tau")).toBeTruthy();
    expect(screen.getByTestId("mappings-policy-semantic-min-shared")).toBeTruthy();
    const readonly = screen.getByTestId("mappings-policy-readonly").textContent ?? "";
    expect(readonly).toContain("mappingsConsole.policy.readonlyLine");
  });

  it("saves the policy after confirmation and audits server-side", async () => {
    const user = userEvent.setup();
    vi.mocked(saveMappingsPolicy).mockResolvedValue({ policy_hash: "newhash" });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(
      <MemoryRouter>
        <MappingRunsView />
      </MemoryRouter>,
    );
    await screen.findByTestId("mappings-policy-save");
    await user.click(screen.getByTestId("mappings-policy-save"));
    await waitFor(() => expect(saveMappingsPolicy).toHaveBeenCalled());
    expect(confirmSpy).toHaveBeenCalled();
    expect(await screen.findByTestId("mappings-policy-note")).toBeTruthy();
  });

  it("runs the bounded dry-run and reports the would-change diff", async () => {
    const user = userEvent.setup();
    vi.mocked(dryRunMappingsPolicy).mockResolvedValue({
      policy: { tau_job: 0.05 },
      policy_hash: "dryhash",
      degraded_semantic: true,
      scanned: 2,
      results: [
        {
          posting_id: "p-1",
          before: { state: "unmapped", reason: "below_threshold" },
          after: {
            state: "mapped",
            reason: "overlap 0.10 above 0.05",
            confidence: 0.1,
            catalog_job_id: "j-1",
          },
          changed: true,
        },
        {
          posting_id: "p-2",
          before: { state: "unmapped", reason: "below_threshold" },
          after: { state: "unmapped", reason: "below_threshold", confidence: null, catalog_job_id: null },
          changed: false,
        },
      ],
    } as MappingDryRunResult);
    render(
      <MemoryRouter>
        <MappingRunsView />
      </MemoryRouter>,
    );
    await screen.findByTestId("mappings-policy-dry-run");
    await user.click(screen.getByTestId("mappings-policy-dry-run"));
    await waitFor(() =>
      expect(dryRunMappingsPolicy).toHaveBeenCalledWith(expect.anything(), ["p-1", "p-2"]),
    );
    const report = await screen.findByTestId("mappings-dry-run");
    expect(report.textContent).toContain("mappingsConsole.policy.dryRunDegraded");
    expect(screen.queryByTestId("mappings-policy-note")).toBeNull();
  });

  it("never couples the dry-run to a write (no resolve call happens)", async () => {
    const user = userEvent.setup();
    vi.mocked(mappingsResolve).mockResolvedValue({ id: "x", status: "approved" });
    vi.mocked(dryRunMappingsPolicy).mockResolvedValue({
      policy: {},
      policy_hash: "h",
      degraded_semantic: false,
      scanned: 0,
      results: [],
    } as MappingDryRunResult);
    render(
      <MemoryRouter>
        <MappingRunsView />
      </MemoryRouter>,
    );
    await screen.findByTestId("mappings-policy-dry-run");
    await user.click(screen.getByTestId("mappings-policy-dry-run"));
    await waitFor(() => expect(dryRunMappingsPolicy).toHaveBeenCalled());
    expect(mappingsResolve).not.toHaveBeenCalled();
  });
});
