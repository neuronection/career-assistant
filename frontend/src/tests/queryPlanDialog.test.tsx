import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { QueryPlanDialog } from "@/components/settings/QueryPlanDialog";
import type { PostingSource } from "@/api/sources";

vi.mock("@/api/scheduler", () => ({
  fetchSystemSchedules: vi.fn(async () => [
    {
      id: "sched-1",
      kind: "system_source_sync",
      task: "posting_sync",
      trigger: { type: "interval", params: { every_minutes: 60, jitter_minutes: 10 } },
    },
  ]),
}));

const SOURCE: PostingSource = {
  id: "src-1",
  key: "board-postings",
  connector_key: "mcp",
  kind: "posting",
  schedule_kind: null,
  config: {
    transport: "stdio",
    command: "python server.py",
    options: JSON.stringify({
      max_pages: 2,
      query_interval_seconds: 30,
      nav_delay_seconds: 2.5,
      budget_seconds: 80,
    }),
  },
  query_mode: "radar",
  query_batch_size: 2,
  query_info: {
    keywords: '"ai engineer" OR "agentic engineer"',
    location: "Berlin, Germany",
    rotation: "1-2/3",
    rotation_index: 0,
    groups: [
      { terms: ["ai engineer", "agentic engineer"], keywords: '"ai engineer" OR "agentic engineer"' },
      { terms: ["devops"], keywords: "devops" },
      { terms: ["software engineer"], keywords: '"software engineer"' },
    ],
    provenance: { "ai engineer": ["radar-1"] },
    group_terms: ["ai engineer", "agentic engineer"],
    curated: true,
    radar_ids: ["radar-1"],
    computed_at: "2026-10-26T12:00:00+00:00",
  },
  secret_hints: {},
  enabled: true,
  paused_at: null,
  last_status: "ok",
  last_run_at: null,
  sync_state: {},
  error: "",
};

vi.mock("@/api/sources", () => ({
  fetchAdminSources: vi.fn(async () => [SOURCE]),
}));

afterEach(() => cleanup());

describe("QueryPlanDialog", () => {
  it("fetches the live plan on open and shows groups, args and cadence", async () => {
    render(<QueryPlanDialog sourceId="src-1" onClose={() => {}} />);
    expect(await screen.findByTestId("query-plan")).toBeTruthy();
    const groups = [
      await screen.findByTestId("query-plan-group-0"),
      await screen.findByTestId("query-plan-group-1"),
      await screen.findByTestId("query-plan-group-2"),
    ];
    expect(groups[0].getAttribute("data-current")).toBe("true");
    expect(groups[1].getAttribute("data-current")).toBe("false");
    expect(screen.getAllByText(/searching next/)).toHaveLength(1);
    expect(screen.getByText(/AI-curated grouping/)).toBeTruthy();
    expect(screen.getByText(/2 queries per sync/)).toBeTruthy();
    expect(screen.getByText(/pages 2/)).toBeTruthy();
    expect(await screen.findByText(/every 60 min/)).toBeTruthy();
  });

  it("radar-mode sources with no plan yet point at Sync now", async () => {
    const empty: PostingSource = {
      ...SOURCE,
      query_info: { ...SOURCE.query_info, groups: [], rotation: "", keywords: "" },
    };
    vi.mocked(
      (await import("@/api/sources")).fetchAdminSources,
    ).mockResolvedValueOnce([empty]);
    render(<QueryPlanDialog sourceId="src-1" onClose={() => {}} />);
    expect(await screen.findByTestId("query-plan-empty")).toBeTruthy();
    expect(screen.getByText(/first radar-mode sync/)).toBeTruthy();
  });

  it("static sources explain Follow my radar instead", async () => {
    const staticSource: PostingSource = {
      ...SOURCE,
      query_mode: "static",
      query_info: { ...SOURCE.query_info, groups: [], rotation: "", keywords: "" },
    };
    vi.mocked(
      (await import("@/api/sources")).fetchAdminSources,
    ).mockResolvedValueOnce([staticSource]);
    render(<QueryPlanDialog sourceId="src-1" onClose={() => {}} />);
    expect(await screen.findByTestId("query-plan-empty")).toBeTruthy();
    expect(screen.getByText(/Follow my radar is off/)).toBeTruthy();
  });
});
