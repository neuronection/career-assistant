import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import { TranslationsPanel } from "@/components/settings/TranslationsPanel";

const approve = vi.fn(async (id: string) => ({ id, status: "approved" }));
const reject = vi.fn(async (id: string) => ({ id, status: "rejected" }));
const update = vi.fn(async (id: string, value: string) => ({ id, value }));
const draft = vi.fn(async (locale: string) => ({ locale, drafted: { job: 2, skill: 1, family: 0 } }));
const queue = vi.fn(async (locale: string, status: string) => [
  {
    id: `overlay-${locale}-${status}`,
    entity_kind: "job" as const,
    entity_id: "11111111-1111-1111-1111-111111111111",
    locale,
    field: "label" as const,
    value: "Berufsbild",
    base_value: "Job",
    source: "ai_draft" as const,
    status: status as "draft",
    created_at: "2026-10-22T10:00:00Z",
    updated_at: "2026-10-22T10:00:00Z",
  },
]);

vi.mock("@/api/i18n", () => ({
  fetchOverlayQueue: (locale: string, status: string) => queue(locale, status),
  draftOverlays: (locale: string) => draft(locale),
  approveOverlay: (id: string) => approve(id),
  rejectOverlay: (id: string) => reject(id),
  updateOverlay: (id: string, value: string) => update(id, value),
}));

describe("catalog translations panel", () => {
  test("drafts, edits, approves and rejects overlays", async () => {
    render(<TranslationsPanel />);
    await screen.findByTestId("overlay-row-overlay-de-draft");

    await userEvent.click(screen.getByTestId("draft-overlays"));
    await waitFor(() => expect(draft).toHaveBeenCalledWith("de"));

    const input = screen.getByTestId("overlay-value-overlay-de-draft");
    await userEvent.clear(input);
    await userEvent.type(input, "Beruf");
    await userEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(update).toHaveBeenCalledWith("overlay-de-draft", "Beruf"));

    await userEvent.click(screen.getByTestId("overlay-approve-overlay-de-draft"));
    await waitFor(() => expect(approve).toHaveBeenCalledWith("overlay-de-draft"));

    await userEvent.click(screen.getByTestId("overlay-reject-overlay-de-draft"));
    await waitFor(() => expect(reject).toHaveBeenCalledWith("overlay-de-draft"));

    await userEvent.click(screen.getByTestId("overlay-locale-el"));
    await waitFor(() => expect(queue).toHaveBeenCalledWith("el", "draft"));

    await userEvent.click(screen.getByTestId("overlay-status-approved"));
    await waitFor(() => expect(queue).toHaveBeenCalledWith("el", "approved"));
  });
});
