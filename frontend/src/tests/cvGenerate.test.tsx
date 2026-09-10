import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CvStudio } from "@/pages/CvStudio";

const fetchCvs = vi.fn();
const fetchContextSources = vi.fn();
const generateCv = vi.fn();
const fetchBackgroundJob = vi.fn();
const cancelBackgroundJob = vi.fn();
const fetchPostings = vi.fn();
const fetchTemplates = vi.fn();

vi.mock("@/api/cv", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/cv")>();
  return {
    ...mod,
    fetchCvs: (...args: unknown[]) => fetchCvs(...args),
    fetchContextSources: (...args: unknown[]) => fetchContextSources(...args),
    generateCv: (...args: unknown[]) => generateCv(...args),
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
  generateCv.mockResolvedValue({ job_id: "job-1", status: "queued" });
  fetchBackgroundJob.mockResolvedValue(succeededJob);
  cancelBackgroundJob.mockResolvedValue({ ...runningJob, status: "cancelled" });
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
