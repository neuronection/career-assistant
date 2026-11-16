import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { EligibilityCard } from "@/features/postings/components/posting-detail/EligibilityCard";
import { setPostingGateOverride } from "@/api/postings";
import type { PostingDetailOut } from "@/types/wire";

vi.mock("@/api/postings", () => ({
  setPostingGateOverride: vi.fn(),
}));

const posting = {
  ref: "ABC12345",
  title: "Data Analyst",
  org: "Acme",
  opportunity_type: "graduate_scheme",
  application_deadline: "2026-12-01",
  work_authorization: "none",
  gate_overrides: {},
  match: { score: 7, breakdown: {}, extracted: true, estimate: false, gates: ["visa"] },
  extract: {
    work_authorization: {
      status: "none",
      evidence_quote: "We are unable to sponsor visas.",
      confidence: 0.9,
    },
    language_requirements: [
      {
        code: "de",
        level: "advanced",
        evidence_quote: "Fluent German required",
        confidence: 0.9,
      },
    ],
    grade_requirement: null,
  },
} as unknown as PostingDetailOut;

describe("EligibilityCard", () => {
  beforeEach(() => {
    vi.mocked(setPostingGateOverride).mockReset();
  });

  it("renders the extracted eligibility facts with quotes", () => {
    render(<EligibilityCard posting={posting} />);
    expect(screen.getByTestId("eligibility-card")).toBeInTheDocument();
    expect(screen.getByTestId("eligibility-work-authorization")).toHaveTextContent(
      "Cannot sponsor",
    );
    expect(screen.getByTestId("eligibility-work-authorization")).toHaveTextContent(
      "We are unable to sponsor visas.",
    );
    expect(screen.getByTestId("eligibility-languages")).toHaveTextContent(
      "Fluent German required",
    );
    expect(screen.getByTestId("eligibility-opportunity-type")).toHaveTextContent(
      "Graduate scheme",
    );
    expect(screen.getByTestId("eligibility-deadline")).toHaveTextContent("2026-12-01");
  });

  it("records an apply-anyway override and shows the undo state", async () => {
    vi.mocked(setPostingGateOverride).mockResolvedValue({
      gate_overrides: { visa: true },
    });
    render(<EligibilityCard posting={posting} />);
    fireEvent.click(screen.getByTestId("eligibility-override-visa"));
    await waitFor(() =>
      expect(setPostingGateOverride).toHaveBeenCalledWith("ABC12345", "visa", true),
    );
    expect(await screen.findByTestId("eligibility-undo-visa")).toBeInTheDocument();
  });

  it("starts in the overridden state when the posting carries it", () => {
    render(
      <EligibilityCard
        posting={
          {
            ...posting,
            gate_overrides: { visa: true },
            match: { ...posting.match, gates: [] },
          } as PostingDetailOut
        }
      />,
    );
    expect(screen.getByTestId("eligibility-undo-visa")).toBeInTheDocument();
    expect(screen.queryByTestId("eligibility-override-visa")).toBeNull();
  });

  it("renders nothing when there are no facts and no gates", () => {
    render(
      <EligibilityCard
        posting={
          {
            ...posting,
            work_authorization: null,
            opportunity_type: null,
            application_deadline: null,
            gate_overrides: {},
            match: { ...posting.match, gates: [] },
            extract: {},
          } as PostingDetailOut
        }
      />,
    );
    expect(screen.queryByTestId("eligibility-card")).toBeNull();
  });

  it("ignores lifestyle gates that are not eligibility gates", () => {
    render(
      <EligibilityCard
        posting={
          {
            ...posting,
            match: { ...posting.match, gates: ["travel", "shift"] },
          } as PostingDetailOut
        }
      />,
    );
    expect(screen.queryByTestId("eligibility-gate-travel")).toBeNull();
    expect(screen.queryByTestId("eligibility-gate-shift")).toBeNull();
  });
});
