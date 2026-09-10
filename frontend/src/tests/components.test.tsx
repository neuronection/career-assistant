import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { ScoreRing } from "@/components/ScoreRing";
import { JobCard } from "@/components/JobCard";
import { AiButton } from "@/components/AiButton";
import { DemandBadge } from "@/components/DemandBadge";
import { quickAssist } from "@/api/universities";
import type { Job } from "@/types";

vi.mock("@/api/universities");

vi.mocked(quickAssist).mockResolvedValue({
  answer: "It matches your interests in software.",
  referenced_job_codes: [],
});

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "1",
    code: "software-developer",
    title: "Software Developer",
    family_key: "technology-software",
    short_description: "Writes code for a living.",
    status: "published",
    source: "seed",
    attributes: {
      subjects: ["mathematics"],
      work_style: { teamwork: 3, environment: 3, structure: 3, pace: 3, leadership: 3, physical_activity: "light" },
      education: { level: "bachelor", fields: [] },
      physical: { activity: "light", requirements: [] },
      salary: { currency: "USD", entry: null, median: [60000, 95000], senior: null },
      demand: { outlook: "hot", note: "", sources: {} },
      environments: ["office", "remote"],
      typical_positives: [],
      typical_negatives: [],
    },
    interests: [{ key: "technology-software", label: "Software & Apps" }],
    skills: [],
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("ScoreRing", () => {
  it("renders the numeric score", () => {
    render(<ScoreRing score={8.4} />);
    expect(screen.getByRole("img", { name: /8\.4 of 10/i })).toBeInTheDocument();
    expect(screen.getByText("8.4")).toBeInTheDocument();
  });
});

describe("DemandBadge", () => {
  it("shows the outlook", () => {
    render(<DemandBadge outlook="hot" />);
    expect(screen.getByTestId("demand-badge")).toHaveTextContent("hot");
  });
  it("renders nothing without outlook", () => {
    render(<DemandBadge outlook={null} />);
    expect(screen.queryByTestId("demand-badge")).toBeNull();
  });
});

describe("JobCard", () => {
  it("shows title, description and demand badge", () => {
    render(<JobCard job={makeJob()} />);
    expect(screen.getByText("Software Developer")).toBeInTheDocument();
    expect(screen.getByText(/Writes code/)).toBeInTheDocument();
    expect(screen.getByTestId("demand-badge")).toHaveTextContent("hot");
  });
  it("calls onSelect on click", () => {
    const onSelect = vi.fn();
    render(<JobCard job={makeJob()} onSelect={onSelect} />);
    fireEvent.click(screen.getByTestId("job-card"));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ code: "software-developer" }));
  });
});

describe("AiButton", () => {
  it("opens popup and fetches an answer", async () => {
    render(<AiButton page="job_detail" jobCode="software-developer" question="Why me?" label="Why me?" />);
    fireEvent.click(screen.getByRole("button", { name: "Why me?" }));
    const panel = await screen.findByRole("dialog");
    fireEvent.click(within(panel).getByRole("button", { name: "Why me?" }));
    expect(await screen.findByText(/matches your interests/i)).toBeInTheDocument();
    expect(quickAssist).toHaveBeenCalledWith({
      question: "Why me?",
      page: "job_detail",
      job_code: "software-developer",
    });
  });
});
