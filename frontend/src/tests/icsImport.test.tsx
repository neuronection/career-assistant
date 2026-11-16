import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { IcsImportModal } from "@/features/postings/components/applications/IcsImportModal";
import { importApplicationsIcs } from "@/api/applications";

vi.mock("@/api/applications", () => ({
  importApplicationsIcs: vi.fn(),
}));

const REPORT = {
  proposals: [
    {
      uid: "evt-1",
      summary: "Interview with Acme",
      start: "2026-11-12T08:00:00+00:00",
      end: null,
      all_day: false,
      location: "Acme HQ",
      application_id: "a1",
      application_label: "Acme — Data Analyst",
      match_reason: "organisation: Acme",
      duplicate: false,
      writable: true,
    },
  ],
  warnings: [],
  created: 0,
  applied: false,
};

describe("IcsImportModal", () => {
  beforeEach(() => {
    vi.mocked(importApplicationsIcs).mockResolvedValue(REPORT);
  });

  it("previews, flags duplicates and applies", async () => {
    const onApplied = vi.fn();
    render(<IcsImportModal open onClose={vi.fn()} onApplied={onApplied} />);
    const file = new File(["BEGIN:VCALENDAR"], "calendar.ics", { type: "text/calendar" });
    Object.defineProperty(file, "text", {
      value: async () => "BEGIN:VCALENDAR\nEND:VCALENDAR",
    });
    fireEvent.change(screen.getByTestId("import-review-file-input"), { target: { files: [file] } });
    expect(await screen.findByTestId("ics-proposal-evt-1")).toHaveTextContent(
      "Interview with Acme",
    );
    fireEvent.click(screen.getByTestId("import-review-apply"));
    await waitFor(() =>
      expect(importApplicationsIcs).toHaveBeenLastCalledWith(
        "BEGIN:VCALENDAR\nEND:VCALENDAR",
        true,
      ),
    );
    expect(onApplied).toHaveBeenCalled();
  });
});
