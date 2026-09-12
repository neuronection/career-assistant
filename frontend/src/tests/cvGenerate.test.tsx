import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CvStudio } from "@/pages/CvStudio";
import { useChatStore } from "@/stores/chatStore";

const fetchCvs = vi.fn();
const fetchContextSources = vi.fn();
const generateCv = vi.fn();
const fetchGeneratePreview = vi.fn();
const polishCv = vi.fn();
const fetchBackgroundJob = vi.fn();
const cancelBackgroundJob = vi.fn();
const fetchPostings = vi.fn();
const fetchTemplates = vi.fn();
const suggestTemplates = vi.fn();
const previewSynthMatches = vi.fn();

vi.mock("@/api/cv", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/cv")>();
  return {
    ...mod,
    fetchCvs: (...args: unknown[]) => fetchCvs(...args),
    fetchContextSources: (...args: unknown[]) => fetchContextSources(...args),
    generateCv: (...args: unknown[]) => generateCv(...args),
    fetchGeneratePreview: (...args: unknown[]) => fetchGeneratePreview(...args),
    polishCv: (...args: unknown[]) => polishCv(...args),
    previewSynthMatches: (...args: unknown[]) => previewSynthMatches(...args),
  };
});

vi.mock("@/api/postings", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/postings")>();
  return {
    ...mod,
    fetchPostings: (...args: unknown[]) => fetchPostings(...args),
  };
});

vi.mock("@/api/cvTemplates", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/cvTemplates")>();
  return {
    ...mod,
    fetchTemplates: (...args: unknown[]) => fetchTemplates(...args),
    suggestTemplates: (...args: unknown[]) => suggestTemplates(...args),
  };
});

vi.mock("@/api/backgroundJobs", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/backgroundJobs")>();
  return {
    ...mod,
    fetchBackgroundJob: (...args: unknown[]) => fetchBackgroundJob(...args),
    cancelBackgroundJob: (...args: unknown[]) => cancelBackgroundJob(...args),
  };
});

vi.mock("@/api/universities", () => ({
  fetchChatSessions: vi.fn().mockResolvedValue([]),
  fetchMessages: vi.fn().mockResolvedValue([]),
  createChatSession: vi.fn().mockResolvedValue({
    id: "s-cv-new",
    title: "CV assistant",
    context: { surface: "cv_builder", cv_id: "cv-9" },
    created_at: "2026-09-11T10:00:00Z",
  }),
  fetchUniversities: vi.fn(),
  fetchUniversity: vi.fn(),
  fetchUniversityPathways: vi.fn(),
  fetchChatContext: vi.fn(),
}));

const sources = {
  sources: [
    {
      key: "basics",
      label: "Contact header",
      description: "",
      items: [{ item_id: "basics", label: "Alex Sample", detail: "" }],
    },
    {
      key: "summary",
      label: "Objective",
      description: "",
      items: [{ item_id: "summary", label: "Career objective", detail: "" }],
    },
    {
      key: "experience",
      label: "Experience",
      description: "",
      items: [{ item_id: "exp-1", label: "DevOps intern", detail: "Acme" }],
    },
    {
      key: "skills",
      label: "Skills",
      description: "",
      items: [],
    },
  ],
};

const generatedCv = {
  id: "cv-9",
  title: "CV — QA Engineer",
  kind: "resume",
  target_posting_id: null,
  language: "en",
  page_size: "a4",
  max_pages: 1,
  status: "draft",
  working_content: { generated_by: "cv_draft" },
  context: { mode: "all", include: [], exclude: [] },
  source_document_id: null,
  created_at: "2026-09-09T10:00:00Z",
  updated_at: "2026-09-09T10:00:00Z",
  latest_version: 1,
};

const runningJob = {
  id: "job-1",
  job_type: "cv_generate",
  status: "running",
  progress: 30,
  stage: "planned sections",
  error: null,
  result: null,
  payload: null,
  attempts: 1,
  max_attempts: 2,
  created_at: "2026-09-09T10:00:00Z",
  updated_at: "2026-09-09T10:00:00Z",
  finished_at: null,
};

const succeededJob = {
  ...runningJob,
  status: "succeeded",
  progress: 100,
  stage: "done",
  result: {
    cv_id: "cv-9",
    title: "CV — QA Engineer",
    version: 1,
    lint: { score: 100, passed: true, checks: [] },
    warnings: [],
    fallback_sections: [],
    plan_fallback: false,
  },
  finished_at: "2026-09-09T10:00:05Z",
};

function renderStudio(entry = "/cv") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/cv" element={<CvStudio />} />
        <Route path="/cv/:id" element={<div data-testid="builder-probe" />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  fetchCvs.mockResolvedValue([generatedCv]);
  fetchContextSources.mockResolvedValue(sources);
  fetchPostings.mockResolvedValue({ items: [] });
  fetchTemplates.mockResolvedValue([]);
  suggestTemplates.mockResolvedValue({ picks: [], candidates_considered: 0 });
  generateCv.mockResolvedValue({ job_id: "job-1", status: "queued" });
  fetchBackgroundJob.mockResolvedValue(succeededJob);
  fetchGeneratePreview.mockResolvedValue({
    stage: "",
    pct: 0,
    iteration: 0,
    html: "",
  });
  polishCv.mockResolvedValue({ job_id: "job-2", status: "queued" });
  cancelBackgroundJob.mockResolvedValue({ ...runningJob, status: "cancelled" });
  previewSynthMatches.mockResolvedValue({
    items: [],
    total: 0,
  });
});

describe("GenerateCvFlow", () => {
  it("deep link opens the modal and submits smart defaults", async () => {
    renderStudio("/cv?generate=1");
    fireEvent.click(await screen.findByTestId("cv-generate-submit"));
    await waitFor(() => expect(generateCv).toHaveBeenCalledTimes(1));
    expect(generateCv.mock.calls[0][0]).toMatchObject({
      language: "en",
      length: "standard",
      max_pages: 1,
      include_photo: false,
      sections: ["summary", "experience"],
      context: { mode: "all", include: [], exclude: [] },
    });
    expect(await screen.findByTestId("builder-probe")).toBeInTheDocument();
    await waitFor(() => expect(useChatStore.getState().chatMode).toBe("docked"));
  });

  it("sends a pasted job posting as posting_text", async () => {
    renderStudio("/cv?generate=1");
    fireEvent.change(await screen.findByTestId("cv-generate-posting-text"), {
      target: {
        value:
          "Geriatric Nurse — Daily nurse job\nNight shift, ventilator experience, 2 years acute.",
      },
    });
    fireEvent.click(await screen.findByTestId("cv-generate-submit"));
    await waitFor(() => expect(generateCv).toHaveBeenCalledTimes(1));
    expect(generateCv.mock.calls[0][0]).toMatchObject({
      posting_text:
        "Geriatric Nurse — Daily nurse job\nNight shift, ventilator experience, 2 years acute.",
      target_posting_id: undefined,
    });
    expect(await screen.findByTestId("builder-probe")).toBeInTheDocument();
  });

  it("offers section chips only where context data exists", async () => {
    renderStudio("/cv?generate=1");
    await screen.findByTestId("cv-generate-submit");
    fireEvent.click(screen.getByTestId("cv-generate-advanced"));
    expect(
      screen.getByRole("button", { name: "Experience", pressed: true })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Objective", pressed: true })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Skills" })
    ).not.toBeInTheDocument();
  });

  it("prefer-synth toggle sends synth_mode and shows the match hint", async () => {
    previewSynthMatches.mockResolvedValue({
      items: [],
      total: 2,
    });
    renderStudio("/cv?generate=1");
    await screen.findByTestId("cv-generate-submit");
    fireEvent.click(screen.getByTestId("cv-generate-advanced"));
    fireEvent.click(
      screen.getByRole("switch", { name: "Prefer synthesized items" })
    );
    expect(
      await screen.findByTestId("cv-generate-synth-hint")
    ).toHaveTextContent("2 of your synthesized variants");
    fireEvent.click(screen.getByTestId("cv-generate-submit"));
    await waitFor(() => expect(generateCv).toHaveBeenCalledTimes(1));
    expect(generateCv.mock.calls[0][0].context.synth_mode).toBe("prefer");
  });

  it("shows the variant review banner before opening the builder", async () => {
    fetchBackgroundJob.mockResolvedValue({
      ...succeededJob,
      result: {
        ...succeededJob.result,
        synth_applied: { "experience:exp-1": "synth-1" },
        synth_proposed: [
          {
            source_key: "experience",
            item_id: "exp-1",
            action: "restyle",
            synth_item_id: "synth-2",
          },
        ],
      },
    });
    renderStudio("/cv?generate=1");
    fireEvent.click(await screen.findByTestId("cv-generate-submit"));
    expect(
      await screen.findByTestId("cv-generate-finished")
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("builder-probe")
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("cv-generate-open-finished"));
    expect(await screen.findByTestId("builder-probe")).toBeInTheDocument();
    await waitFor(() => expect(useChatStore.getState().chatMode).toBe("docked"));
  });

  it("disables generate with a hint on a sparse profile", async () => {
    fetchContextSources.mockResolvedValue({
      sources: [{ key: "skills", label: "Skills", description: "", items: [] }],
    });
    renderStudio("/cv?generate=1");
    const submit = await screen.findByTestId("cv-generate-submit");
    expect(submit).toBeDisabled();
    expect(await screen.findByText(/nothing to generate from yet/i)).toBeInTheDocument();
    expect(generateCv).not.toHaveBeenCalled();
  });

  it("honours context toggles: a disabled source leaves sections + context", async () => {
    renderStudio("/cv?generate=1");
    await screen.findByTestId("cv-generate-submit");
    fireEvent.click(screen.getByTestId("cv-generate-advanced"));
    fireEvent.click(screen.getByRole("switch", { name: "Experience (1)" }));
    fireEvent.click(screen.getByTestId("cv-generate-submit"));
    await waitFor(() => expect(generateCv).toHaveBeenCalledTimes(1));
    const body = generateCv.mock.calls[0][0];
    expect(body.sections).toEqual(["summary"]);
    expect(body.context.mode).toBe("none");
    expect(body.context.include).toEqual([
      { source_key: "summary", item_id: "summary" },
    ]);
  });

  it("submits template_pick 'ai' instantly — no template call in the UI", async () => {
    suggestTemplates.mockResolvedValue({
      picks: [
        { template_id: "tpl-1", title: "Sidebar Pro", reason: "ATS-safe" },
      ],
      candidates_considered: 6,
    });
    renderStudio("/cv?generate=1");
    fireEvent.click(await screen.findByTestId("cv-generate-submit"));
    await waitFor(() => expect(generateCv).toHaveBeenCalledTimes(1));
    expect(generateCv.mock.calls[0][0]).toMatchObject({
      template_pick: "ai",
      template_id: undefined,
    });
    expect(suggestTemplates).not.toHaveBeenCalled();
    expect(await screen.findByTestId("builder-probe")).toBeInTheDocument();
  });

  it("explicit studio default skips the AI pick", async () => {
    renderStudio("/cv?generate=1");
    fireEvent.change(await screen.findByTestId("cv-generate-template"), {
      target: { value: "none" },
    });
    fireEvent.click(await screen.findByTestId("cv-generate-submit"));
    await waitFor(() => expect(generateCv).toHaveBeenCalledTimes(1));
    expect(generateCv.mock.calls[0][0]).toMatchObject({
      template_pick: "none",
      template_id: undefined,
    });
  });

  it("sends the hand-picked template verbatim", async () => {
    fetchTemplates.mockResolvedValue([
      {
        id: "tpl-x",
        key: "chosen",
        version: 1,
        title: "Chosen Style",
        description: "",
        author_key: "bank",
        source: "bank",
        visibility: "private",
        language: "en",
        page_size: "a4",
        ats_safe: true,
        status: "published",
        content: {},
      },
    ]);
    renderStudio("/cv?generate=1");
    fireEvent.change(await screen.findByTestId("cv-generate-template"), {
      target: { value: "tpl-x" },
    });
    fireEvent.click(await screen.findByTestId("cv-generate-submit"));
    await waitFor(() => expect(generateCv).toHaveBeenCalledTimes(1));
    expect(generateCv.mock.calls[0][0].template_id).toBe("tpl-x");
    expect(suggestTemplates).not.toHaveBeenCalled();
  });

  it("cancels a running generation", async () => {
    fetchBackgroundJob.mockResolvedValue(runningJob);
    renderStudio("/cv?generate=1");
    fireEvent.click(await screen.findByTestId("cv-generate-submit"));
    await screen.findByTestId("cv-generate-progress");
    fireEvent.click(screen.getByTestId("cv-generate-cancel"));
    await waitFor(() =>
      expect(cancelBackgroundJob).toHaveBeenCalledWith("job-1")
    );
    expect(await screen.findByTestId("cv-generate-cancelled")).toBeInTheDocument();
    expect(screen.queryByTestId("builder-probe")).not.toBeInTheDocument();
  });

  it("returns to the form with the error when the job fails", async () => {
    fetchBackgroundJob.mockResolvedValue({
      ...runningJob,
      status: "failed",
      error: "AI exploded",
    });
    renderStudio("/cv?generate=1");
    fireEvent.click(await screen.findByTestId("cv-generate-submit"));
    expect(await screen.findByRole("alert")).toHaveTextContent("AI exploded");
    expect(screen.getByTestId("cv-generate-submit")).toBeInTheDocument();
  });

  it("previews the committed draft while the job runs", async () => {
    fetchBackgroundJob.mockResolvedValue(runningJob);
    fetchGeneratePreview.mockResolvedValue({
      stage: "reviewing the draft (1/3)",
      pct: 96,
      iteration: 1,
      html: "<!DOCTYPE html><html><body>draft preview</body></html>",
      trace: {
        iterations: [
          {
            n: 0,
            summary: "Shifted a section",
            issues: [{ level: "warn", area: "density", message: "tight spacing" }],
            ops: [{ op: "move_block", ok: true, detail: "Languages moved up" }],
          },
        ],
        llm_calls: [
          {
            id: "a1",
            task: "cv_build_review",
            stage: "cv_draft.review",
            status: "ok",
            provider: "mock",
            model: "mock-vision",
            tokens_in: 1200,
            tokens_out: 300,
            latency_ms: 850,
          },
        ],
      },
    });
    renderStudio("/cv?generate=1");
    fireEvent.click(await screen.findByTestId("cv-generate-submit"));
    const iframe = await screen.findByTestId("cv-generate-preview");
    expect(iframe.getAttribute("srcdoc")).toContain("draft preview");
    expect(await screen.findByTestId("cv-generate-polish-step")).toHaveTextContent(
      "1"
    );
    expect(screen.getAllByText("Languages moved up").length).toBeGreaterThan(0);
    const strip = await screen.findByTestId("cv-generate-telemetry");
    expect(strip).toHaveTextContent("1 call(s)");
    expect(strip).toHaveTextContent("1200 tokens in");
    expect(strip).toHaveTextContent("300 tokens out");
    expect(strip).toHaveTextContent("1 edits");
    expect(strip).toHaveTextContent("Simulated");
  });

  it("renders no preview column before the first pages commit", async () => {
    fetchBackgroundJob.mockResolvedValue(runningJob);
    fetchGeneratePreview.mockResolvedValue({
      stage: "planned sections",
      pct: 20,
      iteration: 0,
      html: "",
    });
    renderStudio("/cv?generate=1");
    fireEvent.click(await screen.findByTestId("cv-generate-submit"));
    await screen.findByTestId("cv-generate-progress");
    expect(
      screen.queryByTestId("cv-generate-preview")
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("cv-generate-preview-placeholder")
    ).not.toBeInTheDocument();
  });

  it("widens the modal only when the first preview HTML renders", async () => {
    fetchBackgroundJob.mockResolvedValue(runningJob);
    fetchGeneratePreview
      .mockResolvedValueOnce({ stage: "planned sections", pct: 20, iteration: 0, html: "" })
      .mockResolvedValue({
        stage: "reviewing the draft (1/3)",
        pct: 96,
        iteration: 1,
        html: "<!DOCTYPE html><html><body>draft preview</body></html>",
      });
    renderStudio("/cv?generate=1");
    fireEvent.click(await screen.findByTestId("cv-generate-submit"));
    await screen.findByTestId("cv-generate-progress");
    const compact = screen.getByRole("dialog").className;
    expect(compact).toContain("w-[min(680px,96vw)]");
    expect(compact).not.toContain("w-[min(1500px,96vw)]");
    expect(screen.queryByTestId("cv-generate-preview")).not.toBeInTheDocument();

    await screen.findByTestId(
      "cv-generate-preview",
      {},
      { timeout: 4000 }
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog.className).toContain("w-[min(1500px,96vw)]");
    expect(dialog.className).not.toContain("w-[min(680px,96vw)]");
    expect(dialog.className).toContain("max-sm:w-screen");
    expect(dialog.className).toContain("max-sm:h-[100dvh]");
    expect(dialog.className).toContain("max-sm:max-h-none");
    expect(dialog.className).toContain("max-sm:rounded-none");
  });

  it("resumes polish after a failed run and reports the outcome", async () => {
    polishCv.mockResolvedValue({ job_id: "job-2", status: "queued" });
    fetchBackgroundJob.mockResolvedValue({
      ...runningJob,
      status: "failed",
      error: "the polish loop crashed",
      result: {
        cv_id: "cv-9",
        title: "CV — QA Engineer",
        version: 2,
        lint: { score: 100, passed: true, checks: [] },
        warnings: [],
        fallback_sections: [],
        plan_fallback: false,
      },
    });
    renderStudio("/cv?generate=1");
    fireEvent.click(await screen.findByTestId("cv-generate-submit"));
    fireEvent.click(await screen.findByTestId("cv-generate-resume-polish"));
    expect(polishCv).toHaveBeenCalledWith("cv-9", "job-1");
    expect(await screen.findByTestId("cv-generate-progress")).toBeInTheDocument();
  });
});

describe("CvStudio generate entries", () => {
  it("defaults the new-CV modal to generate mode when the profile has content", async () => {
    renderStudio();
    fireEvent.click(await screen.findByTestId("new-cv"));
    expect(await screen.findByTestId("cv-generate-form")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start from scratch" }));
    expect(screen.getByTestId("new-cv-title")).toBeInTheDocument();
    expect(screen.queryByTestId("cv-generate-form")).not.toBeInTheDocument();
  });

  it("badges AI-generated CVs in the studio list", async () => {
    renderStudio();
    expect(await screen.findByTestId("cv-generated")).toHaveTextContent(
      "AI draft"
    );
  });

  it("keeps the studio quiet at /cv without the query param", async () => {
    renderStudio();
    expect(await screen.findByTestId("cv-generated")).toBeInTheDocument();
    expect(screen.queryByTestId("cv-generate-form")).not.toBeInTheDocument();
    expect(screen.queryByTestId("cv-generate-progress")).not.toBeInTheDocument();
  });
});

describe("GenerateCvFlow — plan 70 experience split", () => {
  it("offers Work Experience / Projects / Volunteering as separate toggles", async () => {
    fetchContextSources.mockResolvedValue({
      sources: [
        {
          key: "experience",
          label: "Work Experience",
          description: "Paid work",
          items: [{ item_id: "exp-1", label: "DevOps intern", detail: "Acme" }],
        },
        {
          key: "projects",
          label: "Projects",
          description: "Projects",
          items: [{ item_id: "prj-1", label: "Campus app", detail: "" }],
        },
        {
          key: "volunteer",
          label: "Volunteering",
          description: "Volunteer roles",
          items: [{ item_id: "vol-1", label: "Food bank", detail: "" }],
        },
      ],
    });
    renderStudio("/cv?generate=1");
    await screen.findByTestId("cv-generate-submit");
    fireEvent.click(screen.getByTestId("cv-generate-advanced"));
    expect(
      screen.getByRole("button", { name: "Work Experience", pressed: true })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Projects", pressed: true })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Volunteering", pressed: true })
    ).toBeInTheDocument();
  });

  it("carries the split kinds in the request body", async () => {
    fetchContextSources.mockResolvedValue({
      sources: [
        {
          key: "experience",
          label: "Work Experience",
          description: "",
          items: [{ item_id: "exp-1", label: "DevOps intern", detail: "Acme" }],
        },
        {
          key: "volunteer",
          label: "Volunteering",
          description: "",
          items: [{ item_id: "vol-1", label: "Food bank", detail: "" }],
        },
      ],
    });
    renderStudio("/cv?generate=1");
    fireEvent.click(await screen.findByTestId("cv-generate-submit"));
    await waitFor(() => expect(generateCv).toHaveBeenCalledTimes(1));
    expect(generateCv.mock.calls[0][0].sections).toEqual(
      expect.arrayContaining(["experience", "volunteer"])
    );
    expect(generateCv.mock.calls[0][0].sections).not.toContain("projects");
  });
});
