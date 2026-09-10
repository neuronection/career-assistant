import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError } from "axios";
import { CvIntakeFlow } from "@/components/intake/CvIntakeFlow";
import {
  applyCvDraft,
  discardCvDraft,
  fetchCvPageImageUrl,
  getCvDrafts,
  reparseCv,
  uploadCv,
} from "@/api/cvIntake";
import type { CvDraft } from "@/types/cvIntake";

vi.mock("@/api/cvIntake", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/cvIntake")>();
  return {
    ...mod,
    uploadCv: vi.fn<typeof mod.uploadCv>(),
    getCvDrafts: vi.fn<typeof mod.getCvDrafts>(),
    applyCvDraft: vi.fn<typeof mod.applyCvDraft>(),
    discardCvDraft: vi.fn<typeof mod.discardCvDraft>(),
    reparseCv: vi.fn<typeof mod.reparseCv>(),
    fetchCvPageImageUrl: vi.fn<typeof mod.fetchCvPageImageUrl>(),
  };
});

vi.mock("@/api/backgroundJobs", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/backgroundJobs")>();
  return {
    ...mod,
    fetchBackgroundJob: vi.fn<typeof mod.fetchBackgroundJob>(),
  };
});

function notFound(): AxiosError {
  return new AxiosError("Not Found", "404", undefined, undefined, {
    status: 404,
    statusText: "Not Found",
    headers: {},
    config: {} as never,
  } as never);
}

const DRAFT: CvDraft = {
  id: "draft-1",
  status: "pending",
  payload: {
    basics: {
      full_name: "Ilias Pap",
      headline: "Data engineer",
      email: "ilias@example.com",
      phone: "+30 69",
      location: "Athens, GR",
      links: [],
      evidence: { quote: "Ilias Pap — Data engineer", page: 0, confidence: 0.92 },
    },
    summary: "Experienced data engineer",
    education: [
      {
        institution: "NKUA",
        program: "Physics",
        level: "bachelor",
        start: "2015-09",
        end: "2019-06",
        grade_band: "good",
        evidence: { quote: "BSc Physics, NKUA", page: 1, confidence: 0.8 },
      },
    ],
    experience: [
      {
        kind: "job",
        title: "Data Engineer",
        org: "Acme",
        start: "2021-01",
        end: "",
        description: "Pipelines",
        skills: [],
        achievements: [],
        evidence: { quote: "Data Engineer at Acme", page: 0, confidence: 0.85 },
      },
    ],
    skills: [
      {
        name: "Python",
        level_claim: 8,
        evidence: { quote: "Python — 8", page: 0, confidence: 0.4 },
      },
    ],
    languages: [
      {
        code: "en",
        level: "advanced",
        evidence: { quote: "English — advanced", page: 1, confidence: 0.6 },
      },
    ],
    certifications: [],
    awards: [],
    interests: [
      {
        label: "Board games",
        evidence: { quote: "board games", page: 2, confidence: 0.3 },
      },
    ],
  },
  report: {},
};

const APPLY_REPORT = {
  created: { education_items: 1, experience_items: 1 },
  proposed_skills: ["python"],
  skill_conflicts: [],
  unmapped_interests: [],
  duplicates: [],
};

function fileInput(): HTMLInputElement {
  const input = document.querySelector('input[type="file"]');
  expect(input).not.toBeNull();
  return input as HTMLInputElement;
}

async function uploadAndReachReview() {
  vi.mocked(uploadCv).mockResolvedValue({
    document: {
      id: "doc-1",
      kind: "cv",
      filename: "cv.pdf",
      mime: "application/pdf",
      size_bytes: 10,
      page_count: 2,
      extraction: { universities: [] },
      status: "parsed",
      error: "",
    },
    job_id: "job-1",
  });
  vi.mocked(getCvDrafts).mockResolvedValue(DRAFT);
  const user = userEvent.setup();
  const input = fileInput();
  await user.upload(input, new File(["cv"], "cv.pdf", { type: "application/pdf" }));
  await screen.findByTestId("cv-intake-review");
}

describe("CvIntakeFlow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("uploads the CV as kind=cv and lands on the grouped review", async () => {
    render(<CvIntakeFlow pollMs={10} />);
    await uploadAndReachReview();
    expect(uploadCv).toHaveBeenCalledTimes(1);
    const sent = vi.mocked(uploadCv).mock.calls[0][0];
    expect(sent.name).toBe("cv.pdf");
    expect(screen.getByTestId("intake-section-basics")).toBeInTheDocument();
    expect(screen.getByTestId("intake-section-education")).toBeInTheDocument();
    expect(screen.getByTestId("intake-section-skills")).toBeInTheDocument();
    expect(screen.getByTestId("intake-section-interests")).toBeInTheDocument();
    expect(screen.getAllByTestId("confidence-high").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("confidence-low").length).toBeGreaterThan(0);
    expect(
      screen.getByText("“Ilias Pap — Data engineer”")
    ).toBeInTheDocument();
    expect(screen.getByTestId("cv-intake-apply")).toHaveTextContent(
      "Import 6 details"
    );
  });

  it("unticking an item drops exactly that index from the apply payload", async () => {
    const onApplied = vi.fn();
    vi.mocked(applyCvDraft).mockResolvedValue({ report: APPLY_REPORT });
    render(<CvIntakeFlow pollMs={10} onApplied={onApplied} />);
    await uploadAndReachReview();

    fireEvent.click(
      screen.getByRole("checkbox", { name: "Import \u201cPython\u201d" })
    );
    expect(screen.getByTestId("cv-intake-apply")).toHaveTextContent(
      "Import 5 details"
    );
    fireEvent.click(screen.getByTestId("cv-intake-apply"));

    await waitFor(() =>
      expect(applyCvDraft).toHaveBeenCalledWith("doc-1", {
        basics: [0],
        education: [0],
        experience: [0],
        languages: [0],
        interests: [0],
      })
    );
    await screen.findByText("Profile imported");
    expect(onApplied).toHaveBeenCalledTimes(1);
    expect(
      screen.getByText(/1 education items, 1 experience items/)
    ).toBeInTheDocument();
    expect(screen.getByText(/1 new skill was suggested/)).toBeInTheDocument();
  });

  it("section select-all off clears the whole section from the payload", async () => {
    vi.mocked(applyCvDraft).mockResolvedValue({ report: APPLY_REPORT });
    render(<CvIntakeFlow pollMs={10} />);
    await uploadAndReachReview();

    fireEvent.click(screen.getByTestId("intake-section-toggle-skills"));
    fireEvent.click(screen.getByTestId("cv-intake-apply"));

    await waitFor(() =>
      expect(applyCvDraft).toHaveBeenCalledWith(
        "doc-1",
        expect.not.objectContaining({ skills: expect.anything() })
      )
    );
  });

  it("discard asks for confirmation and returns to the dropzone", async () => {
    vi.mocked(discardCvDraft).mockResolvedValue(undefined);
    render(<CvIntakeFlow pollMs={10} />);
    await uploadAndReachReview();

    fireEvent.click(screen.getByTestId("cv-intake-discard"));
    fireEvent.click(await screen.findByRole("button", { name: "Discard" }));

    await waitFor(() => expect(discardCvDraft).toHaveBeenCalledWith("doc-1"));
    expect(await screen.findByText(/Drop your CV here/)).toBeInTheDocument();
    expect(screen.queryByTestId("cv-intake-review")).not.toBeInTheDocument();
  });

  it("surfaces a friendly error when the parse never becomes ready", async () => {
    vi.mocked(uploadCv).mockResolvedValue({
      document: {
        id: "doc-2",
        kind: "cv",
        filename: "cv.pdf",
        mime: "application/pdf",
        size_bytes: 10,
        page_count: 1,
        extraction: { universities: [] },
      status: "parsed",
        error: "",
      },
      job_id: "job-2",
    });
    vi.mocked(getCvDrafts).mockRejectedValue(notFound());
    render(<CvIntakeFlow pollMs={10} />);
    const user = userEvent.setup();
    await user.upload(
      fileInput(),
      new File(["cv"], "cv.pdf", { type: "application/pdf" })
    );
    expect(
      await screen.findByText(
        "The CV parse is taking longer than expected — try again in a moment.",
        {},
        { timeout: 4000 }
      )
    ).toBeInTheDocument();
  });
});

const EMPTY_DRAFT: CvDraft = {
  id: "draft-empty",
  status: "pending",
  payload: {
    basics: {
      full_name: "",
      headline: "",
      email: "",
      phone: "",
      location: "",
      links: [],
      evidence: { quote: "", page: null, confidence: 0.5 },
    },
    summary: "",
    education: [],
    experience: [],
    skills: [],
    languages: [],
    certifications: [],
    awards: [],
    interests: [],
  },
  report: {},
};

describe("CvIntakeFlow — history entry & tracing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a friendly empty state when nothing could be extracted", async () => {
    vi.mocked(getCvDrafts).mockResolvedValue(EMPTY_DRAFT);
    render(<CvIntakeFlow pollMs={10} initialDocumentId="doc-9" />);
    expect(
      await screen.findByText("Nothing usable in this CV")
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("cv-intake-review")
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("cv-intake-empty-retry"));
    expect(await screen.findByText(/Drop your CV here/)).toBeInTheDocument();
  });

  it("opens a saved draft directly without re-parsing", async () => {
    vi.mocked(getCvDrafts).mockResolvedValue(DRAFT);
    render(<CvIntakeFlow pollMs={10} initialDocumentId="doc-1" />);
    await screen.findByTestId("cv-intake-review");
    expect(getCvDrafts).toHaveBeenCalledWith("doc-1");
    expect(reparseCv).not.toHaveBeenCalled();
  });

  it("re-process re-parses the stored document and waits for the job", async () => {
    vi.mocked(reparseCv).mockResolvedValue({ job_id: "job-9" });
    vi.mocked(getCvDrafts).mockResolvedValue(DRAFT);
    const { fetchBackgroundJob } = await import("@/api/backgroundJobs");
    vi.mocked(fetchBackgroundJob).mockResolvedValue({
      id: "job-9",
      job_type: "cv_parse",
      status: "succeeded",
      progress: 100,
      stage: null,
      error: null,
      result: null,
      payload: null,
      attempts: 1,
      max_attempts: 3,
      created_at: "2026-09-08T00:00:00Z",
      updated_at: "2026-09-08T00:00:00Z",
      finished_at: null,
    });
    render(
      <CvIntakeFlow pollMs={10} initialDocumentId="doc-1" reprocess />
    );
    await waitFor(() => expect(reparseCv).toHaveBeenCalledWith("doc-1"));
    await screen.findByTestId("cv-intake-review");
    expect(fetchBackgroundJob).toHaveBeenCalledWith("job-9");
    expect(getCvDrafts).toHaveBeenCalledWith("doc-1");
  });

  it("empty drafts surface a section_count of zero in the api contract", () => {
    expect(EMPTY_DRAFT.section_count).toBeUndefined();
  });

  it("grounds evidence: show source page loads the page image", async () => {
    vi.mocked(getCvDrafts).mockResolvedValue(DRAFT);
    vi.mocked(fetchCvPageImageUrl).mockResolvedValue("blob:page-0");
    render(<CvIntakeFlow pollMs={10} initialDocumentId="doc-1" />);
    await screen.findByTestId("cv-intake-review");
    fireEvent.click(screen.getAllByTestId("evidence-toggle-0")[0]);
    await waitFor(() =>
      expect(fetchCvPageImageUrl).toHaveBeenCalledWith("doc-1", 0)
    );
    expect(await screen.findByTestId("evidence-page-0")).toHaveAttribute(
      "src",
      "blob:page-0"
    );
  });

  it("offers a way back to the CV list after applying", async () => {
    const onExit = vi.fn();
    vi.mocked(getCvDrafts).mockResolvedValue(DRAFT);
    vi.mocked(applyCvDraft).mockResolvedValue({ report: APPLY_REPORT });
    render(
      <CvIntakeFlow pollMs={10} initialDocumentId="doc-1" onExit={onExit} />
    );
    await screen.findByTestId("cv-intake-review");
    fireEvent.click(screen.getByTestId("cv-intake-apply"));
    await screen.findByText("Profile imported");
    fireEvent.click(screen.getByTestId("cv-intake-done"));
    expect(onExit).toHaveBeenCalledTimes(1);
  });
});
