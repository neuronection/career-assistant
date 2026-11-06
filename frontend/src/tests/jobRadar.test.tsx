import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { JobRadarSettings } from "@/pages/settings/JobRadar";
import * as radarApi from "@/api/radar";
import * as schedulerApi from "@/api/scheduler";
import * as sourcesApi from "@/api/sources";

vi.mock("@/api/radar", () => ({
  fetchRadar: vi.fn(),
  updateRadar: vi.fn(),
  previewRadar: vi.fn(),
}));

vi.mock("@/api/scheduler", () => ({
  fetchMySchedules: vi.fn(),
  setMyScheduleEnabled: vi.fn(),
  runMyScheduleNow: vi.fn(),
}));

vi.mock("@/api/sources", () => ({
  fetchUserSources: vi.fn(),
}));

const radar = {
  keywords: ["data engineer"],
  locations: [{ city: "Hamburg", country: "Germany", remote: false }],
  seniority: ["mid"],
  onsite_policy: "hybrid",
  salary_min_annual: "50000",
  salary_currency: "EUR",
  source_keys: [],
  cadence: "daily",
  enabled: true,
  updated_at: "2026-10-28T10:00:00Z",
};

const schedule = {
  id: "sched-radar",
  kind: "user_radar_digest",
  enabled: true,
  next_run_at: "2026-10-29T08:00:00Z",
  last_run_at: "2026-10-28T08:00:00Z",
  last_status: "ok",
  task: "radar_digest",
};

const userSources = [
  { key: "board-postings", connector_key: "mcp", open_postings: 12 },
  { key: "market-demand", connector_key: "mcp", open_postings: 0 },
];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(radarApi.fetchRadar).mockResolvedValue(radar as never);
  vi.mocked(radarApi.updateRadar).mockResolvedValue({
    ...radar,
    updated_at: "2026-10-29T10:00:00Z",
  } as never);
  vi.mocked(radarApi.previewRadar).mockResolvedValue({
    items: [
      {
        id: "p1",
        title: "Data Engineer",
        org: "Acme",
        location: "Hamburg, Germany",
      },
    ],
    total: 1,
    facets: {},
    next_cursor: null,
  } as never);
  vi.mocked(schedulerApi.fetchMySchedules).mockResolvedValue([schedule] as never);
  vi.mocked(schedulerApi.runMyScheduleNow).mockResolvedValue({
    id: "sched-radar",
    next_run_at: "2026-10-29T09:00:00Z",
  });
  vi.mocked(schedulerApi.setMyScheduleEnabled).mockResolvedValue({
    ...schedule,
    enabled: false,
  } as never);
  vi.mocked(sourcesApi.fetchUserSources).mockResolvedValue(userSources);
});

function renderPage() {
  return render(
    <MemoryRouter>
      <JobRadarSettings />
    </MemoryRouter>
  );
}

describe("job radar settings (plan 148 phase 3)", () => {
  it("renders the hero with the loaded config, cadence chips and schedule facts", async () => {
    renderPage();
    const chip = await screen.findByTestId("radar-status-chip");
    await waitFor(() => expect(chip).toHaveTextContent("On · Daily"));
    await waitFor(() =>
      expect(screen.getByTestId("radar-enabled")).toHaveAttribute(
        "aria-checked",
        "true"
      )
    );
    expect(screen.getByTestId("radar-schedule")).toHaveTextContent("Last scan");
    expect(screen.getByTestId("radar-scan-status")).toHaveTextContent("ok");
    expect(screen.getByTestId("radar-updated")).toHaveTextContent("Saved");
    expect(screen.getByTestId("radar-cadence-daily")).toHaveAttribute(
      "aria-checked",
      "true"
    );
  });

  it("runs scan-now over the user schedule endpoint", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByTestId("radar-scan-now"));
    await waitFor(() =>
      expect(schedulerApi.runMyScheduleNow).toHaveBeenCalledWith("sched-radar")
    );
    expect(schedulerApi.fetchMySchedules).toHaveBeenCalledTimes(2);
  });

  it("pauses and resumes scans without touching the radar payload", async () => {
    const user = userEvent.setup();
    renderPage();
    const paused = await screen.findByTestId("radar-scan-paused");
    expect(paused).toHaveAttribute("aria-checked", "false");
    await user.click(paused);
    await waitFor(() =>
      expect(schedulerApi.setMyScheduleEnabled).toHaveBeenCalledWith(
        "sched-radar",
        false
      )
    );
    expect(radarApi.updateRadar).not.toHaveBeenCalled();
  });

  it("adds a keyword chip and saves the replace-all payload", async () => {
    const user = userEvent.setup();
    renderPage();
    const chipInput = await screen.findByLabelText("Keywords");
    await user.type(chipInput, "python{Enter}");
    await user.click(screen.getByTestId("radar-save"));
    await waitFor(() => expect(radarApi.updateRadar).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(radarApi.updateRadar).mock.calls[0]![0];
    expect(payload.keywords).toEqual(["data engineer", "python"]);
    expect(payload.enabled).toBe(true);
    expect(payload.cadence).toBe("daily");
    expect(payload.locations).toEqual([
      { city: "Hamburg", country: "Germany", remote: false },
    ]);
    expect(payload.salary_min_annual).toBe(50000);
    expect(payload.salary_currency).toBe("EUR");
  });

  it("picks connector sources into the payload", async () => {
    const user = userEvent.setup();
    renderPage();
    const row = await screen.findByTestId("settings-section-sources");
    await user.click(
      within(row).getByRole("button", { name: /board-postings/ })
    );
    await user.click(screen.getByTestId("radar-save"));
    await waitFor(() => expect(radarApi.updateRadar).toHaveBeenCalled());
    const payload = vi.mocked(radarApi.updateRadar).mock.calls[0]![0];
    expect(payload.source_keys).toEqual(["board-postings"]);
  });

  it("previews the current draft without saving", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByTestId("radar-test"));
    await waitFor(() => expect(radarApi.previewRadar).toHaveBeenCalledTimes(1));
    const previewed = vi.mocked(radarApi.previewRadar).mock.calls[0]![0];
    expect(previewed.keywords).toEqual(["data engineer"]);
    expect(radarApi.updateRadar).not.toHaveBeenCalled();
    expect(await screen.findByTestId("radar-preview")).toHaveTextContent(
      "Data Engineer"
    );
    expect(screen.getByText("Open these matches in Explore")).toBeInTheDocument();
  });

  it("keeps an untouched draft from PUTting", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("radar-schedule");
    await user.click(screen.getByTestId("radar-save"));
    expect(radarApi.updateRadar).not.toHaveBeenCalled();
  });
});
