import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { TranslationsBoard } from "@/components/settings/TranslationsBoard";
import type { LabelOverlay } from "@/types/wire";

const approve = vi.fn(async (id: string) => ({ id, status: "approved" }));
const reject = vi.fn(async (id: string) => ({ id, status: "rejected" }));
const update = vi.fn(async (id: string, value: string) => ({ id, value }));
const draft = vi.fn(async (locale: string) => ({
  locale,
  drafted: { job: 2, skill: 1, family: 0 },
}));

function overlay(partial: Partial<LabelOverlay> & { id: string }): LabelOverlay {
  return {
    entity_kind: "job",
    entity_id: "11111111-1111-1111-1111-111111111111",
    locale: "de",
    field: "label",
    value: "Berufsbild",
    base_value: "Job",
    source: "ai_draft",
    status: "draft",
    created_at: "2026-10-22T10:00:00Z",
    updated_at: "2026-10-22T10:00:00Z",
    ...partial,
  };
}

const BASE_ROWS: LabelOverlay[] = [
  overlay({ id: "ov-de-1", entity_kind: "job", value: "Berufsbild" }),
  overlay({ id: "ov-de-2", entity_kind: "skill", value: "Programmierung" }),
  overlay({
    id: "ov-de-3",
    entity_kind: "skill",
    status: "approved",
    base_value: "Database",
    value: "Datenbanken",
  }),
  overlay({
    id: "ov-el-1",
    entity_kind: "family",
    locale: "el",
    base_value: "Family",
    value: "Οικογένεια",
  }),
];

/** The board fetches ONE unfiltered page: no locale, no status. */
const queue = vi.fn(async () => BASE_ROWS);

const bulk = vi.fn(async (ids: string[], action: "approve" | "reject") => {
  const affected: string[] = [];
  const failed: { id: string; reason: string }[] = [];
  for (const id of ids) {
    try {
      await (action === "approve" ? approve(id) : reject(id));
      affected.push(id);
    } catch (err) {
      failed.push({ id, reason: err instanceof Error ? err.message : "failed" });
    }
  }
  return { affected, failed };
});

vi.mock("@/api/i18n", () => ({
  fetchOverlayQueue: () => queue(),
  draftOverlays: (locale: string) => draft(locale),
  approveOverlay: (id: string) => approve(id),
  rejectOverlay: (id: string) => reject(id),
  updateOverlay: (id: string, value: string) => update(id, value),
  bulkOverlayAction: (ids: string[], action: "approve" | "reject") => bulk(ids, action),
}));

function renderBoard() {
  return render(
    <MemoryRouter>
      <TranslationsBoard />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  queue.mockImplementation(async () => BASE_ROWS);
});

describe("catalog translations review board", () => {
  test("fetches one unfiltered page and derives the pill counts", async () => {
    renderBoard();

    await screen.findByTestId("translations-card-ov-de-1");
    expect(queue).toHaveBeenCalledTimes(1);

    // Locale pills count per locale across the whole page.
    expect(screen.getByTestId("translations-locale-de")).toHaveTextContent("3");
    expect(screen.getByTestId("translations-locale-el")).toHaveTextContent("1");
    // Status pills count within the selected locale (de).
    expect(screen.getByTestId("translations-status-draft")).toHaveTextContent("2");
    expect(screen.getByTestId("translations-status-approved")).toHaveTextContent("1");
    expect(screen.getByTestId("translations-status-rejected")).toHaveTextContent("0");
    expect(screen.getByTestId("translations-status-all")).toHaveTextContent("3");
  });

  test("groups cards by entity kind with count pills and collapses a group", async () => {
    const user = userEvent.setup();
    renderBoard();

    await screen.findByTestId("translations-card-ov-de-1");
    // The default status filter is the draft pile: only drafts show.
    expect(screen.getByTestId("translations-group-job")).toBeInTheDocument();
    expect(screen.getByTestId("translations-group-count-job")).toHaveTextContent("1");
    expect(screen.getByTestId("translations-group-count-skill")).toHaveTextContent("1");

    // Widening to all statuses brings the approved skill row into the group.
    await user.click(screen.getByTestId("translations-status-all"));
    expect(screen.getByTestId("translations-group-count-skill")).toHaveTextContent("2");

    await user.click(screen.getByTestId("translations-group-toggle-skill"));
    expect(screen.queryByTestId("translations-card-ov-de-2")).toBeNull();
    await user.click(screen.getByTestId("translations-group-toggle-skill"));
    expect(screen.getByTestId("translations-card-ov-de-2")).toBeInTheDocument();
  });

  test("edits, approves and rejects a draft from its card", async () => {
    const user = userEvent.setup();
    renderBoard();

    await screen.findByTestId("translations-card-ov-de-1");

    await user.clear(screen.getByTestId("translations-value-ov-de-1"));
    await user.type(screen.getByTestId("translations-value-ov-de-1"), "Beruf");
    await user.click(screen.getByTestId("translations-save-ov-de-1"));
    await waitFor(() => expect(update).toHaveBeenCalledWith("ov-de-1", "Beruf"));

    await user.click(screen.getByTestId("translations-approve-ov-de-1"));
    await waitFor(() => expect(approve).toHaveBeenCalledWith("ov-de-1"));

    await user.click(screen.getByTestId("translations-reject-ov-de-1"));
    await waitFor(() => expect(reject).toHaveBeenCalledWith("ov-de-1"));
  });

  test("searches across the base label and the drafted value", async () => {
    const user = userEvent.setup();
    renderBoard();

    await screen.findByTestId("translations-card-ov-de-1");
    // Matches the drafted value.
    await user.type(
      screen.getByPlaceholderText("Search base or translation…"),
      "programmierung",
    );
    await waitFor(() =>
      expect(screen.queryByTestId("translations-card-ov-de-1")).toBeNull(),
    );
    expect(screen.getByTestId("translations-card-ov-de-2")).toBeInTheDocument();

    // Matches the base label too (across statuses — widen first).
    await user.click(screen.getByTestId("translations-status-all"));
    await user.clear(screen.getByPlaceholderText("Search base or translation…"));
    await user.type(
      screen.getByPlaceholderText("Search base or translation…"),
      "database",
    );
    await waitFor(() =>
      expect(screen.getByTestId("translations-card-ov-de-3")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("translations-card-ov-de-2")).toBeNull();
  });

  test("batches approve with per-item results and reloads", async () => {
    const user = userEvent.setup();
    approve.mockRejectedValueOnce(new Error("gone"));
    renderBoard();

    await screen.findByTestId("translations-card-ov-de-1");
    await user.click(screen.getByTestId("translations-select"));
    // Enter the bulk bar by picking one card, then widen to the whole
    // pill-scoped section (the drafts — ov-de-3 is approved already).
    await user.click(
      within(screen.getByTestId("translations-card-ov-de-1")).getByRole("checkbox"),
    );
    await user.click(
      within(screen.getByTestId("translations-bulk-bar-select-all")).getByRole("checkbox"),
    );
    expect(screen.getByTestId("translations-bulk-bar")).toBeInTheDocument();

    await user.click(screen.getByTestId("translations-bulk-approve"));
    await waitFor(() =>
      expect(screen.getByTestId("translations-bulk-note")).toBeInTheDocument(),
    );
    // Both drafts approved (ov-de-3 is approved already — not batchable).
    expect(approve).toHaveBeenCalledTimes(2);
    // The failed one is reported per item, the success summarized.
    expect(screen.getByTestId("translations-bulk-failure-ov-de-1")).toBeInTheDocument();
    expect(screen.getByTestId("translations-bulk-note")).toHaveTextContent(
      "Approved 1 translation.",
    );
    // Selection clears (the mode frame is back) and the queue reloads.
    expect(screen.getByTestId("translations-bulk-mode")).toHaveTextContent(
      "Selection mode",
    );
    expect(queue).toHaveBeenCalledTimes(2);
  });

  test("reports a fully failed batch instead of staying silent", async () => {
    const user = userEvent.setup();
    approve.mockRejectedValue(new Error("gone"));
    renderBoard();

    await screen.findByTestId("translations-card-ov-de-1");
    await user.click(screen.getByTestId("translations-select"));
    await user.click(
      within(screen.getByTestId("translations-bulk-bar-select-all")).getByRole("checkbox"),
    );
    await user.click(screen.getByTestId("translations-bulk-approve"));

    expect(
      await screen.findByTestId("translations-bulk-failure-ov-de-1"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("translations-bulk-failure-ov-de-2")).toBeInTheDocument();
    expect(screen.getByTestId("translations-bulk-failure-ov-de-1")).toHaveTextContent(
      "gone",
    );
  });

  test("batches reject behind a confirmation", async () => {
    const user = userEvent.setup();
    renderBoard();

    await screen.findByTestId("translations-card-ov-de-1");
    await user.click(screen.getByTestId("translations-select"));
    await user.click(
      within(screen.getByTestId("translations-card-ov-de-1")).getByRole("checkbox"),
    );
    await user.click(
      within(screen.getByTestId("translations-bulk-bar-select-all")).getByRole("checkbox"),
    );
    await user.click(screen.getByTestId("translations-bulk-reject"));
    expect(reject).not.toHaveBeenCalled();

    // The confirm modal's Reject is the last "Reject" button in the DOM
    // (the cards carry their own per-row Reject buttons).
    const confirmButtons = await screen.findAllByRole("button", { name: "Reject" });
    await user.click(confirmButtons[confirmButtons.length - 1]);
    await waitFor(() => expect(reject).toHaveBeenCalledWith("ov-de-1"));
    await waitFor(() => expect(reject).toHaveBeenCalledWith("ov-de-2"));
    await waitFor(() =>
      expect(screen.getByTestId("translations-bulk-note")).toHaveTextContent(
        "Rejected 2 translations.",
      ),
    );
  });

  test("load-more pages the render window past the fetch cap", async () => {
    const user = userEvent.setup();
    const page = Array.from({ length: 120 }, (_, index) =>
      overlay({
        id: `ov-paged-${index}`,
        entity_kind: "job",
        base_value: `Base ${index}`,
        value: `Entwurf ${index}`,
      }),
    );
    queue.mockImplementation(async () => page);
    renderBoard();

    await screen.findByTestId("translations-card-ov-paged-0");
    expect(screen.queryByTestId("translations-card-ov-paged-60")).toBeNull();

    await user.click(screen.getByTestId("translations-load-more"));
    expect(screen.getByTestId("translations-card-ov-paged-60")).toBeInTheDocument();
    expect(screen.queryByTestId("translations-card-ov-paged-110")).toBeNull();
  });

  test("keeps the Draft with AI flow and reports its result note", async () => {
    const user = userEvent.setup();
    renderBoard();

    await screen.findByTestId("translations-card-ov-de-1");
    await user.click(screen.getByTestId("translations-draft"));
    await waitFor(() => expect(draft).toHaveBeenCalledWith("de"));
    await waitFor(() =>
      expect(screen.getByTestId("translations-note")).toHaveTextContent(
        "3 overlays drafted for review.",
      ),
    );
    expect(queue).toHaveBeenCalledTimes(2);
  });

  test("switches locale pills and scopes the view", async () => {
    const user = userEvent.setup();
    renderBoard();

    await screen.findByTestId("translations-card-ov-de-1");
    await user.click(screen.getByTestId("translations-locale-el"));
    expect(screen.getByTestId("translations-card-ov-el-1")).toBeInTheDocument();
    expect(screen.queryByTestId("translations-card-ov-de-1")).toBeNull();
    expect(screen.getByTestId("translations-status-all")).toHaveTextContent("1");
  });
});
