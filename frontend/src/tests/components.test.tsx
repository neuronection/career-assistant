import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ScoreBubble } from "@/components/score/ScoreBubble";
import { JobCard } from "@/features/catalog/components/JobCard";
import { AiButton } from "@/components/AiButton";
import { DemandBadge } from "@/features/postings/components/DemandBadge";
import { quickAssist } from "@/api/universities";
import type { Job } from "@/types/wire";

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
    family_label: "",
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

describe("ScoreBubble", () => {
  it("renders the numeric score", () => {
    render(<ScoreBubble score={8.4} />);
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
  const renderJob = (job: Job, props: Partial<Parameters<typeof JobCard>[0]> = {}) =>
    render(
      <MemoryRouter>
        <JobCard job={job} {...props} />
      </MemoryRouter>
    );

  const richJob = (): Job =>
    makeJob({
      open_roles: 3,
      attributes: {
        ...makeJob().attributes,
        salary: { currency: "USD", entry: null, median: [60000, 95000], senior: null },
        experience_typical_years: [1, 3],
        contract_type: "permanent",
        schedule_cues: ["shift_work"],
        travel_required: { level: "frequent", days_per_month: null },
        work_hours: { pattern: "full_time", hours_per_week_min: 20, hours_per_week_max: 30 },
        physical: { activity: "light", requirements: [] },
        work_style: {
          teamwork: 4,
          environment: 3,
          structure: 2,
          pace: 3,
          leadership: 3,
          physical_activity: "light",
        },
      },
      skills: [
        {
          skill_id: "s1",
          key: "typescript",
          label: "TypeScript",
          required_level: 8,
          importance: "important",
          rationale: "",
        },
      ],
      interests: [{ key: "technology-software", label: "Software" }],
    });

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

  it("renders every metric only when its attribute exists", () => {
    renderJob(richJob());
    expect(screen.getByTestId("job-open-roles")).toHaveTextContent("3");
    expect(screen.getByTestId("job-salary-band")).toHaveTextContent("USD 60k–95k");
    expect(screen.getByTestId("job-experience")).toHaveTextContent("1–3 yrs");
    expect(screen.getByTestId("job-contract")).toHaveTextContent("Permanent");
    expect(screen.getByTestId("job-travel")).toHaveTextContent("Frequent");
    expect(screen.getByTestId("job-schedule")).toHaveTextContent("Shift work");
    expect(screen.getByTestId("job-hours")).toHaveTextContent("Full time · 20–30 h");
    expect(screen.getByTestId("job-spec")).toHaveTextContent("Light");
    expect(screen.getByTestId("job-spec")).toHaveTextContent("4/5");
  });

  it("hides absent metrics instead of rendering empty slots", () => {
    const base = makeJob();
    renderJob(
      makeJob({
        open_roles: null,
        attributes: {
          ...base.attributes,
          salary: { currency: "USD", entry: null, median: null, senior: null },
          experience_typical_years: null,
          contract_type: null,
          schedule_cues: [],
          travel_required: null,
          work_hours: null,
        },
      })
    );
    expect(screen.queryByTestId("job-metric-rail")).not.toBeInTheDocument();
    expect(screen.queryByTestId("job-salary-band")).not.toBeInTheDocument();
    expect(screen.queryByTestId("job-experience")).not.toBeInTheDocument();
    expect(screen.queryByTestId("job-contract")).not.toBeInTheDocument();
    expect(screen.queryByTestId("job-schedule")).not.toBeInTheDocument();
    expect(screen.queryByTestId("job-hours")).not.toBeInTheDocument();
    expect(screen.queryByTestId("job-open-roles-link")).not.toBeInTheDocument();
  });

  it("links open roles to the postings job axis and shows skill levels", () => {
    renderJob(richJob());
    expect(screen.getByTestId("job-open-roles-link")).toHaveAttribute(
      "href",
      "/postings?job=software-developer"
    );
    const skill = screen.getByTestId("skill-tag");
    expect(skill).toHaveTextContent("TypeScript");
    expect(skill).toHaveTextContent("8");
    expect(skill).toHaveAttribute("title", "requires level 8 of 10");
  });

  it("keeps the metric rail compactly and drops the description, spec and interests in compact density", () => {
    renderJob(richJob(), { density: "compact" });
    expect(screen.getByTestId("job-card")).toHaveAttribute("data-density", "compact");
    expect(screen.getByTestId("job-metric-rail")).toBeInTheDocument();
    expect(screen.getByTestId("job-open-roles")).toHaveTextContent("3");
    expect(screen.getByTestId("job-salary-band")).toHaveTextContent("USD 60k–95k");
    expect(screen.queryByText(/Writes code/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("job-spec")).not.toBeInTheDocument();
    expect(screen.queryByTestId("job-interests")).not.toBeInTheDocument();
    expect(screen.getByTestId("job-skills")).toBeInTheDocument();
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
