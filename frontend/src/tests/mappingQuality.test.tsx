import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import {
  fetchMappingsQuality,
  mappingsResolve,
  mappingsSample,
  type MappingQuality,
} from "@/api/mappings";
import { MappingQualityView } from "@/components/settings/MappingQualityView";

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
    fetchMappingsQuality: vi.fn(),
    mappingsResolve: vi.fn(),
    mappingsSample: vi.fn(),
  };
});

function quality(overrides: Partial<MappingQuality> = {}): MappingQuality {
  return {
    golden: { resolved: 31, precision: 0.96, recall: 0.9, agreement: 0.94 },
    sample: { resolved: 10, precision: 0.8, recall: 0.8, agreement: 0.8 },
    confusion: [{ predicted: "quality-right", expected: "none", count: 2 }],
    gate: {
      min_golden: 30,
      precision_floor: 0.9,
      pass: true,
      state: "pass",
    },
    pending: [
      {
        id: "rev-1",
        kind: "golden",
        status: "pending",
        expected_job_id: null,
        note: "",
        posting: {
          id: "p-1",
          ref: "AAAA1111",
          title: "Analyst",
          state_kind: "skill_overlap",
          catalog_job_id: "j-9",
        },
        created_at: "2026-11-06T09:00:00Z",
      },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(fetchMappingsQuality).mockResolvedValue(quality());
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("mapping quality view (plan 205 S7)", () => {
  it("renders the metrics, the confusion pairs and the pending rows", async () => {
    render(
      <MemoryRouter>
        <MappingQualityView />
      </MemoryRouter>,
    );
    await screen.findByTestId("mappings-quality-gate");
    expect(screen.getByTestId("mappings-quality-golden").textContent).toContain(
      "mappingsConsole.quality.precision",
    );
    expect(screen.getByTestId("mappings-confusion").textContent).toContain(
      "quality-right",
    );
    const rows = screen.getAllByTestId("mappings-pending-row");
    expect(rows).toHaveLength(1);
    expect(
      screen.getByTestId("mappings-correct-rev-1"),
    ).toBeTruthy();
  });

  it("shows the no-golden state when nothing is resolved", async () => {
    vi.mocked(fetchMappingsQuality).mockResolvedValue(
      quality({
        golden: { resolved: 0, precision: null, recall: null, agreement: null },
        sample: { resolved: 0, precision: null, recall: null, agreement: null },
        confusion: [],
        gate: { min_golden: 30, precision_floor: 0.9, pass: false, state: "no-golden" },
        pending: [],
      }),
    );
    render(
      <MemoryRouter>
        <MappingQualityView />
      </MemoryRouter>,
    );
    expect(await screen.findByText("mappingsConsole.quality.noGolden")).toBeTruthy();
    expect(
      await screen.findByText("mappingsConsole.quality.pendingEmptyTitle"),
    ).toBeTruthy();
  });

  it("resolves a pending row correct and reloads", async () => {
    const user = userEvent.setup();
    vi.mocked(mappingsResolve).mockResolvedValue({ id: "rev-1", status: "approved" });
    render(
      <MemoryRouter>
        <MappingQualityView />
      </MemoryRouter>,
    );
    await screen.findByTestId("mappings-correct-rev-1");
    await user.click(screen.getByTestId("mappings-correct-rev-1"));
    await waitFor(() => expect(mappingsResolve).toHaveBeenCalledWith("rev-1", true));
    await waitFor(() => expect(fetchMappingsQuality).toHaveBeenCalledTimes(2));
  });

  it("creates a sample batch with the chosen size", async () => {
    const user = userEvent.setup();
    vi.mocked(mappingsSample).mockResolvedValue({ created: 5, ids: [] });
    render(
      <MemoryRouter>
        <MappingQualityView />
      </MemoryRouter>,
    );
    await screen.findByTestId("mappings-sample-create");
    await user.click(screen.getByTestId("mappings-sample-create"));
    await waitFor(() => expect(mappingsSample).toHaveBeenCalledWith(20));
    expect(
      await screen.findByText("mappingsConsole.quality.sampleDone"),
    ).toBeTruthy();
  });

  it("never couples the gate to a release wall (advisory note only)", async () => {
    vi.mocked(fetchMappingsQuality).mockResolvedValue(
      quality({ gate: { min_golden: 30, precision_floor: 0.9, pass: false, state: "fail" } }),
    );
    render(
      <MemoryRouter>
        <MappingQualityView />
      </MemoryRouter>,
    );
    const gate = await screen.findByTestId("mappings-quality-gate");
    expect(gate.textContent).toContain("mappingsConsole.quality.gateFail");
    expect(gate.textContent).not.toContain("mappingsConsole.overview.gateFail");
    expect(screen.queryByTestId("mappings-release-block")).toBeNull();
  });
});
