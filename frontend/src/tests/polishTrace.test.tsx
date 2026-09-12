import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { PolishPreviewIframe, PolishTraceCard } from "@/components/cv/PolishTrace";
import type { CvPolishTrace, CvVersionOut } from "@/types/cv";

vi.mock("@/lib/i18n", async () => ({ initI18n: vi.fn() }));

const trace: CvPolishTrace = {
  request: {
    notes: "Lead with the internship.",
    length: "standard",
    language: "en",
    max_pages: 1,
  },
  outcome: { status: "completed" },
  iterations: [
    {
      n: 0,
      summary: "One spacing fix + a coverage pass.",
      issues: [
        {
          level: "fail",
          area: "density",
          message: "The sidebar renders empty.",
        },
        {
          level: "info",
          area: "coverage",
          message: "Skills section considered.",
        },
      ],
      ops: [
        { op: "move_block", ok: true, detail: "Languages section moved" },
        { op: "move_block", ok: false, detail: "bounds clamped" },
      ],
      coverage: {
        included: [],
        dropped: [],
        missing: [{ source_key: "skills", item_id: "s1", label: "SQL" }],
      },
    },
  ],
};

function versionWith(polish: CvPolishTrace): CvVersionOut {
  return {
    id: "v-2",
    version: 2,
    content: { polish },
  } as unknown as CvVersionOut;
}

it("renders the request panel, severity groups and applied edits", () => {
  render(<PolishTraceCard version={versionWith(trace)} />);
  expect(screen.getByTestId("polish-request")).toHaveTextContent(
    "Lead with the internship."
  );
  expect(screen.getAllByTestId("polish-iteration")[0]).toHaveTextContent(
    "Polish pass 1"
  );
  expect(screen.getByText("The sidebar renders empty.")).toBeInTheDocument();
  expect(screen.getByText("Languages section moved")).toBeInTheDocument();
  expect(screen.getByText(/Rejected edit/)).toBeInTheDocument();
  expect(screen.getByTestId("polish-outcome")).toHaveTextContent(
    "AI polish finished"
  );
  expect(screen.getByTestId("polish-trace-card")).toHaveTextContent("SQL");
});

it("renders nothing without a trace", () => {
  const { container } = render(
    <PolishTraceCard version={{} as unknown as CvVersionOut} />
  );
  expect(container.querySelector('[data-testid="polish-trace-card"]')).toBeNull();
});

it("renders the live preview iframe with the committed snapshot", () => {
  render(
    <PolishPreviewIframe html="<!DOCTYPE html><html><body>x</body></html>" title="p" testId="preview" />
  );
  expect(document.querySelector('[data-testid="preview"]')).toHaveAttribute(
    "srcdoc",
    expect.stringContaining("DOCTYPE")
  );
});
