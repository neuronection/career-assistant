import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DatastoreQuarantineGate } from "@/components/DatastoreQuarantineDialog";
import {
  FirstRunSetupGate,
} from "@/features/profile/components/onboarding/FirstRunSetupGate";
import {
  QUARANTINE_SEEN_KEY,
  useDatastoreQuarantineStore,
} from "@/stores/datastoreQuarantineStore";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import type { AiStatus, Bootstrap } from "@/types/wire";

import * as instanceApi from "@/api/instance";

vi.mock("@/api/instance", () => ({
  getInstanceConfig: vi.fn(),
}));

const mockedInstance = vi.mocked(instanceApi);

const CONFIG: instanceApi.InstanceConfig = {
  demo_mode: false,
  auth_mode: "open",
  registration_enabled: false,
  identity_mode: "desktop",
};

const NOTICE: instanceApi.DatastoreQuarantine = {
  path: "/home/student/.local/share/CareerAssistant/previous-datastore-20261110-120000",
  reason: "incompatible-schema",
  quarantined_at: "2026-11-10T12:00:00+00:00",
  schema_revision: "0100_previous_line",
  from_version: null,
};

function unconfiguredBootstrap(): Bootstrap {
  const weights = { skills: 3, location: 3, experience: 3, education: 3, interests: 3, values: 3 };
  const ai: AiStatus = {
    configured: false,
    provider_type: null,
    default_model: null,
    task_coverage: { assigned: 0, total: 4, missing: ["text", "vision", "stt", "embeddings"] },
    mock_active: false,
    setup_dismissed: false,
  };
  return {
    career_stage: "student",
    stage_source: "derived",
    features: { universities: true, grade_fields: true, education_step: true },
    suggested_scoring_weights: weights,
    effective_scoring_weights: weights,
    weights_overridden: false,
    catalog_empty: false,
    fit_stale: false,
    target_mode: false,
    ai,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  useDatastoreQuarantineStore.getState().reset();
  useBootstrapStore.getState().reset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("DatastoreQuarantineDialog (family datastore-breaks contract)", () => {
  it("shows the preserved folder and dismisses locally", async () => {
    mockedInstance.getInstanceConfig.mockResolvedValue({
      ...CONFIG,
      datastore_quarantine: NOTICE,
    });
    render(<DatastoreQuarantineGate />);

    expect(await screen.findByTestId("datastore-quarantine")).toBeInTheDocument();
    expect(screen.getByTestId("datastore-quarantine-path")).toHaveTextContent(NOTICE.path);
    expect(screen.getByText(/nothing was deleted/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(screen.queryByTestId("datastore-quarantine")).not.toBeInTheDocument();
    expect(localStorage.getItem(QUARANTINE_SEEN_KEY)).toBe(NOTICE.quarantined_at);
  });

  it("renders nothing on a current datastore", async () => {
    mockedInstance.getInstanceConfig.mockResolvedValue({ ...CONFIG });
    render(<DatastoreQuarantineGate />);

    await waitFor(() => {
      expect(useDatastoreQuarantineStore.getState().pending).toBe(false);
    });
    expect(screen.queryByTestId("datastore-quarantine")).not.toBeInTheDocument();
  });

  it("keeps an already acknowledged notice dismissed", async () => {
    localStorage.setItem(QUARANTINE_SEEN_KEY, NOTICE.quarantined_at);
    mockedInstance.getInstanceConfig.mockResolvedValue({
      ...CONFIG,
      datastore_quarantine: NOTICE,
    });
    render(<DatastoreQuarantineGate />);

    await waitFor(() => {
      expect(useDatastoreQuarantineStore.getState().pending).toBe(false);
    });
    expect(screen.queryByTestId("datastore-quarantine")).not.toBeInTheDocument();
  });

  it("explains an unreadable datastore in its own words", async () => {
    mockedInstance.getInstanceConfig.mockResolvedValue({
      ...CONFIG,
      datastore_quarantine: { ...NOTICE, reason: "unreadable", schema_revision: null },
    });
    render(<DatastoreQuarantineGate />);

    expect(await screen.findByText(/could not be read/i)).toBeInTheDocument();
    expect(screen.queryByText(/cannot read your previous one/i)).not.toBeInTheDocument();
  });

  it("never blocks the boot on a stalled instance-config check", async () => {
    vi.useFakeTimers();
    mockedInstance.getInstanceConfig.mockReturnValue(new Promise(() => {}));
    render(<DatastoreQuarantineGate />);

    await act(async () => {
      vi.advanceTimersByTime(5000);
    });

    expect(useDatastoreQuarantineStore.getState().pending).toBe(false);
    expect(screen.queryByTestId("datastore-quarantine")).not.toBeInTheDocument();
  });

  it("fails closed to the ordinary first run when the config is unreadable", async () => {
    mockedInstance.getInstanceConfig.mockRejectedValue(new Error("offline"));
    render(<DatastoreQuarantineGate />);

    await waitFor(() => {
      expect(useDatastoreQuarantineStore.getState().pending).toBe(false);
    });
    expect(screen.queryByTestId("datastore-quarantine")).not.toBeInTheDocument();
  });
});

describe("FirstRunSetupGate sequencing", () => {
  function renderGate() {
    return render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route
            path="/"
            element={
              <>
                <FirstRunSetupGate />
                <div>dashboard</div>
              </>
            }
          />
          <Route path="/onboarding/setup" element={<div>setup-page</div>} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("waits for the datastore notice before opening the wizard", async () => {
    useBootstrapStore.getState().apply(unconfiguredBootstrap());
    mockedInstance.getInstanceConfig.mockResolvedValue({
      ...CONFIG,
      datastore_quarantine: NOTICE,
    });
    renderGate();

    await waitFor(() => {
      expect(useDatastoreQuarantineStore.getState().pending).toBe(true);
    });
    expect(screen.getByText("dashboard")).toBeInTheDocument();
    expect(screen.queryByText("setup-page")).not.toBeInTheDocument();

    act(() => useDatastoreQuarantineStore.getState().dismiss());

    expect(await screen.findByText("setup-page")).toBeInTheDocument();
  });
});
