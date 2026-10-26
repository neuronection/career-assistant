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
  key: "linkedin-postings",
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

afterEach(() => cleanup());

describe("QueryPlanDialog", () => {
  it("shows the merged groups, rotation marker, args and cadence", async () => {
    render(<QueryPlanDialog source={SOURCE} onClose={() => {}} />);
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

  it("explains an empty plan", async () => {
    render(
      <QueryPlanDialog
        source={{
          ...SOURCE,
          query_info: {
            ...SOURCE.query_info,
            groups: [],
            rotation: "",
            keywords: "",
          },
        }}
        onClose={() => {}}
      />,
    );
    expect(await screen.findByTestId("query-plan-empty")).toBeTruthy();
  });
});
