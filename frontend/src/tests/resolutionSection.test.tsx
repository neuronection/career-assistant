import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import * as resolutionApi from "@/api/postingResolution";
import type { ResolutionStats, ResolutionThresholds } from "@/api/postingResolution";
import { ResolutionSection } from "@/components/settings/ResolutionSection";

vi.mock("@/api/postingResolution", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/postingResolution")>();
  return {
    ...actual,
    fetchResolutionThresholds: vi.fn(),
    saveResolutionThresholds: vi.fn(),
    fetchResolutionStats: vi.fn(),
    replayPostingResolution: vi.fn(),
    reconcileSkillEmbeddings: vi.fn(),
  };
});

const mocked = vi.mocked(resolutionApi);

const THRESHOLDS: ResolutionThresholds = {
  candidate_trigram_floor: 0,
  candidate_cosine_floor: 0,
  candidate_top_k: 5,
  dedup_trigram_bar: 0.75,
  dedup_cosine_bar: 0.9,
  corroboration_min_postings: 2,
  corroboration_cap: 20,
};

const STATS: ResolutionStats = {
  last_run: {
    job_id: "job-1",
    status: "succeeded",
    created_at: "2026-11-02T00:00:00Z",
    finished_at: "2026-11-02T00:00:01Z",
    labels: 3,
    exact_hits: 2,
    pass2_matches: 1,
    new_proposals: 0,
    gate_blocks: 0,
    degraded: false,
    replay: false,
  },
  rolling: {
    window: "7d",
    runs: 4,
    replay_runs: 1,
    degraded_runs: 0,
    labels: 9,
    exact_hits: 5,
    pass2_matches: 3,
    new_proposals: 1,
    gate_blocks: 1,
    match_rate: 0.8889,
    new_rate: 0.1111,
    block_rate: 0.5,
    replay_rate: 0.25,
    degrade_rate: 0,
  },
  failing_schedules: 1,
};

function renderSection() {
  return render(
    <MemoryRouter>
      <ResolutionSection />
    </MemoryRouter>,
  );
}

describe("ResolutionSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.fetchResolutionThresholds.mockResolvedValue(THRESHOLDS);
    mocked.fetchResolutionStats.mockResolvedValue(STATS);
  });

  it("renders the stats strip with last-run counters and rolling rates", async () => {
    renderSection();
    expect(await screen.findByTestId("resolution-stats")).toBeTruthy();
    expect(mocked.fetchResolutionStats).toHaveBeenCalledWith("7d");
    expect(screen.getByTestId("resolution-stats-last-run")).toBeTruthy();
    expect(screen.getByTestId("resolution-stats-rolling")).toBeTruthy();
    expect(screen.getByText("89%")).toBeTruthy();
    expect(screen.getByText("25%")).toBeTruthy();
  });

  it("deep-links failing schedules into /settings/automations", async () => {
    renderSection();
    const link = await screen.findByTestId(
      "resolution-schedules-link",
    ) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/settings/automations");
    expect(link.textContent).toMatch(/automations/i);
  });

  it("switches the rolling window and refetches", async () => {
    const user = fireEvent;
    renderSection();
    await screen.findByTestId("resolution-stats");
    const tab = screen.getByRole("tab", { name: "30 days" });
    user.click(tab);
    await waitFor(() => expect(mocked.fetchResolutionStats).toHaveBeenCalledWith("30d"));
  });

  it("edits a threshold and saves the payload", async () => {
    mocked.saveResolutionThresholds.mockResolvedValue({
      ...THRESHOLDS,
      dedup_trigram_bar: 0.8,
    });
    renderSection();
    const input = (await screen.findByTestId(
      "threshold-dedup_trigram_bar",
    )) as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe("0.75"));
    fireEvent.change(input, { target: { value: "0.8" } });
    fireEvent.click(screen.getByTestId("resolution-thresholds-save"));
    await waitFor(() =>
      expect(mocked.saveResolutionThresholds).toHaveBeenCalledWith({
        ...THRESHOLDS,
        dedup_trigram_bar: 0.8,
      }),
    );
    expect(screen.getByTestId("resolution-thresholds-save")).toBeTruthy();
  });

  it("parses the replay id list and reports the wave outcome", async () => {
    mocked.replayPostingResolution.mockResolvedValue({
      queued: 2,
      skipped: 1,
      missing: ["gone"],
      requested: 4,
    });
    renderSection();
    const input = await screen.findByTestId("resolution-replay-ids");
    fireEvent.change(input, {
      target: { value: "id-1, id-2\nid-3\ngone" },
    });
    fireEvent.click(screen.getByTestId("resolution-replay-run"));
    await waitFor(() =>
      expect(mocked.replayPostingResolution).toHaveBeenCalledWith([
        "id-1",
        "id-2",
        "id-3",
        "gone",
      ]),
    );
    expect(await screen.findByTestId("resolution-replay-report")).toBeTruthy();
  });

  it("fires the skill-embedding reconcile and renders the report", async () => {
    mocked.reconcileSkillEmbeddings.mockResolvedValue({
      candidates: 12,
      embedded: 3,
    });
    renderSection();
    fireEvent.click(await screen.findByTestId("resolution-reconcile"));
    await waitFor(() =>
      expect(mocked.reconcileSkillEmbeddings).toHaveBeenCalledWith(200),
    );
    expect(await screen.findByTestId("resolution-reconcile-report")).toBeTruthy();
  });

  it("stays silent about schedules while none are failing", async () => {
    mocked.fetchResolutionStats.mockResolvedValue({ ...STATS, failing_schedules: 0 });
    renderSection();
    await screen.findByTestId("resolution-stats");
    expect(screen.queryByTestId("resolution-failing-schedules")).toBeNull();
  });
});
