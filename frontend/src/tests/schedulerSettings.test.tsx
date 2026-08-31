import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { SchedulerSettings } from "@/pages/settings/SchedulerSettings";
import {
  fetchMySchedules,
  fetchSavedSearches,
  fetchSystemSchedules,
  runScheduleNow,
  setSavedSearchSchedule,
  setSystemScheduleEnabled,
} from "@/api/scheduler";
import { useAuthStore } from "@/stores/authStore";
import type { ScheduleItem } from "@/types";

vi.mock("@/api/scheduler", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/scheduler")>();
  return {
    ...mod,
    fetchMySchedules: vi.fn(),
    fetchSavedSearches: vi.fn(),
    fetchSystemSchedules: vi.fn(),
    setSavedSearchSchedule: vi.fn().mockResolvedValue({}),
    setSystemScheduleEnabled: vi.fn().mockResolvedValue(undefined),
    runScheduleNow: vi.fn().mockResolvedValue(undefined),
  };
});

const mySchedules: ScheduleItem[] = [
  {
    id: "sch-checkin",
    kind: "user_checkin",
    task: null,
    trigger: { type: "interval", params: { every_minutes: 129600 } },
    payload: {},
    enabled: true,
    next_run_at: "2026-11-29T00:00:00Z",
    last_status: "ok",
    consecutive_failures: 0,
  },
  {
    id: "sch-search",
    kind: "user_saved_search",
    task: "saved_search_run",
    trigger: { type: "interval", params: { every_minutes: 360 } },
    payload: { search_id: "sr1" },
    enabled: true,
    next_run_at: "2026-08-31T12:00:00Z",
    last_status: "queued",
    consecutive_failures: 0,
  },
];

describe("Scheduler settings", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: { email: "a@b.c", is_admin: true } as never });
    vi.mocked(fetchMySchedules).mockResolvedValue(mySchedules);
    vi.mocked(fetchSavedSearches).mockResolvedValue([
      { id: "sr1", query: "qa remote", scope: "postings", saved: true },
    ]);
    vi.mocked(fetchSystemSchedules).mockResolvedValue([
      {
        id: "sys1",
        kind: "system_source_sync",
        task: "posting_sync",
        trigger: { type: "interval", params: { every_minutes: 360, jitter_minutes: 30 } },
        payload: {},
        enabled: true,
        next_run_at: "2026-08-31T12:00:00Z",
        last_status: "ok",
        consecutive_failures: 0,
      },
    ]);
  });

  it("renders saved-search schedules and system schedules for admins", async () => {
    render(<SchedulerSettings />);
    expect(await screen.findByTestId("scheduler-settings")).toBeInTheDocument();
    expect(screen.getByTestId("saved-search-schedule")).toHaveTextContent(
      /every 360 min/
    );
    expect(screen.getByTestId("system-schedule")).toHaveTextContent(
      /system source sync/
    );
  });

  it("changes a saved search schedule", async () => {
    render(<SchedulerSettings />);
    fireEvent.change(await screen.findByRole("combobox"), {
      target: { value: "3" },
    });
    await waitFor(() =>
      expect(setSavedSearchSchedule).toHaveBeenCalledWith("sr1", {
        type: "daily_at",
        params: { time: "08:00", timezone: "UTC" },
      })
    );
  });

  it("pauses and runs system schedules", async () => {
    render(<SchedulerSettings />);
    fireEvent.click(await screen.findByText("pause"));
    await waitFor(() => expect(setSystemScheduleEnabled).toHaveBeenCalledWith("sys1", false));
    fireEvent.click(screen.getByText("run now"));
    await waitFor(() => expect(runScheduleNow).toHaveBeenCalledWith("sys1"));
  });
});
