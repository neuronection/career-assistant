import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PostingHistory } from "@/features/postings/components/posting-detail/PostingHistory";
import { api } from "@/api/client";

vi.mock("@/api/client", () => ({
  api: { get: vi.fn() },
}));

const mockGet = vi.mocked(api.get);

const NOW = Date.now();
const iso = (offsetMs: number) => new Date(NOW - offsetMs).toISOString();
const MINUTE = 60_000;

function entry(overrides: Record<string, unknown> = {}) {
  return {
    id: "chg-1",
    occurred_at: iso(5 * MINUTE),
    actor_kind: "sync_run",
    actor_ref: { trigger: "scheduled" },
    operation: { source: "synth" },
    duration_ms: 240,
    diff: { title: { from: "Data Analyst", to: "Senior Data Analyst" } },
    outcome: "ok",
    ...overrides,
  };
}

describe("PostingHistory (plan 142)", () => {
  beforeEach(() => {
    mockGet.mockReset();
  });

  it("renders the day-grouped timeline with kind badges and duration chips", async () => {
    const DAY = 24 * 60 * MINUTE;
    mockGet.mockResolvedValue({
      data: {
        items: [
          entry({
            id: "chg-2",
            actor_kind: "extract_llm",
            duration_ms: 1520,
            occurred_at: iso(MINUTE),
          }),
          entry({ occurred_at: iso(3 * DAY) }),
        ],
        total: 2,
        limit: 50,
        offset: 0,
        posting_id: "p1",
      },
    });
    render(<PostingHistory postingRef="AB12CD34" createdAt={iso(3 * DAY)} />);

    await waitFor(() => {
      expect(screen.getByTestId("posting-history-list")).toBeTruthy();
    });
    expect(screen.getByText("LLM extract")).toBeTruthy();
    expect(screen.getByText("Sync")).toBeTruthy();
    const durations = screen.getAllByTestId("history-duration");
    expect(durations.map((d) => d.textContent)).toEqual(["1.5 s", "240 ms"]);
    expect(mockGet).toHaveBeenCalledWith("/postings/AB12CD34/history", { params: { limit: 50 } });
    const dayHeaders = screen
      .getAllByText((content, element) => element?.tagName === "P" && /\d/.test(content))
      .filter((el) => el.className.includes("tracking-[0.08em]"));
    expect(dayHeaders.length).toBe(2), "one header per day group";
    expect(dayHeaders[0].textContent).not.toBe(dayHeaders[1].textContent);
  });

  it("expands a capped diff on click, including the skills set-diff", async () => {
    mockGet.mockResolvedValue({
      data: {
        items: [
          entry({
            id: "chg-s",
            actor_kind: "retag",
            actor_ref: {},
            duration_ms: null,
            diff: {
              skills: {
                added: ["kubernetes"],
                removed: ["go"],
                changed: { python: { level: { from: 3, to: 5 } } },
              },
            },
          }),
        ],
        total: 1,
        limit: 50,
        offset: 0,
        posting_id: "p1",
      },
    });
    render(<PostingHistory postingRef="AB12CD34" createdAt={null} />);

    const toggle = await screen.findByTestId("history-toggle-chg-s");
    expect(screen.queryByTestId("history-diff-skills")).toBeNull();
    fireEvent.click(toggle);

    const skills = await screen.findByTestId("history-diff-skills");
    expect(skills.textContent).toContain("+ kubernetes");
    expect(skills.textContent).toContain("− go");
    expect(skills.textContent).toContain("python");
    expect(skills.textContent).toContain("level 3 → 5");
  });

  it("shows the honest empty state anchored at the posting's first sighting", async () => {
    mockGet.mockResolvedValue({
      data: { items: [], total: 0, limit: 50, offset: 0, posting_id: "p1" },
    });
    render(<PostingHistory postingRef="AB12CD34" createdAt={iso(90 * 24 * 60 * MINUTE)} />);

    const empty = await screen.findByTestId("posting-history-empty");
    expect(empty.textContent).toContain("history begins");
    expect(empty.textContent).toContain(new Date(NOW - 90 * 24 * 60 * MINUTE).toLocaleDateString());
  });

  it("degrades quietly when the read fails", async () => {
    mockGet.mockRejectedValue(new Error("boom"));
    render(<PostingHistory postingRef="AB12CD34" createdAt={null} />);

    expect(await screen.findByTestId("posting-history-error")).toBeTruthy();
  });
});
