import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { CompetencyEvidenceCard } from "@/features/growth/components/CompetencyEvidenceCard";
import { fetchCompetencies } from "@/api/competencies";

vi.mock("@/api/competencies", () => ({ fetchCompetencies: vi.fn() }));

const DATA = {
  competencies: [
    {
      key: "leadership" as const,
      evidence: [
        {
          id: "experience:1",
          kind: "experience" as const,
          label: "Community volunteer",
          quote: "Led a team of five volunteers.",
        },
      ],
    },
    { key: "intercultural" as const, evidence: [] },
  ],
};

describe("CompetencyEvidenceCard", () => {
  beforeEach(() => {
    vi.mocked(fetchCompetencies).mockResolvedValue(DATA);
  });

  it("shows evidence and an honest empty state without a score", async () => {
    render(<CompetencyEvidenceCard />);
    expect(await screen.findByTestId("competency-evidence")).toHaveTextContent(
      "NACE career-readiness competencies"
    );
    expect(screen.getByTestId("competency-leadership")).toHaveTextContent(
      "Community volunteer"
    );
    expect(screen.getByTestId("competency-leadership")).toHaveTextContent(
      "Led a team of five volunteers."
    );
    expect(screen.getByTestId("competency-intercultural")).toHaveTextContent(
      "No evidence yet"
    );
    expect(screen.getByTestId("competency-evidence")).not.toHaveTextContent(
      /score\s*\d/i
    );
  });

  it("renders nothing when the request fails", async () => {
    vi.mocked(fetchCompetencies).mockRejectedValue(new Error("offline"));
    const { container } = render(<CompetencyEvidenceCard />);
    await vi.waitFor(() => expect(fetchCompetencies).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
