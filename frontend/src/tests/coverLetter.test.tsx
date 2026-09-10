import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { TooltipProvider } from "@neuronection/assistant-ui";
import { CvStudio } from "@/pages/CvStudio";
import { CvBuilder } from "@/pages/CvBuilder";
import { PostingDetail } from "@/components/PostingDetail";
import type { CvDocumentOut } from "@/types/cv";

const fetchCvs = vi.fn();
const createCv = vi.fn();
const createCoverLetter = vi.fn();
const fetchCv = vi.fn();
const fetchContextSources = vi.fn();
const previewCv = vi.fn();
const fetchVersions = vi.fn();
const fetchLint = vi.fn();
const fetchContextStatus = vi.fn();
const patchCv = vi.fn();
const fetchCoverLetterBrief = vi.fn();
const draftCoverLetter = vi.fn();
const fetchTemplates = vi.fn();
const fetchPhotoGallery = vi.fn();
const fetchPostings = vi.fn();
const fetchPostingDetail = vi.fn();

vi.mock("@/api/mePhoto", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/mePhoto")>();
  return { ...mod, fetchPhotoGallery: (...args: unknown[]) => fetchPhotoGallery(...args) };
});

vi.mock("@/api/postings", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/postings")>();
  return {
    ...mod,
    fetchPostings: (...args: unknown[]) => fetchPostings(...args),
    fetchPostingDetail: (...args: unknown[]) => fetchPostingDetail(...args),
  };
});

vi.mock("@/api/cvTemplates", () => ({
  fetchTemplates: (...args: unknown[]) => fetchTemplates(...args),
}));

vi.mock("@/api/cv", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/cv")>();
  return {
    ...mod,
    fetchCvs: (...args: unknown[]) => fetchCvs(...args),
    createCv: (...args: unknown[]) => createCv(...args),
    createCoverLetter: (...args: unknown[]) => createCoverLetter(...args),
    fetchCv: (...args: unknown[]) => fetchCv(...args),
    fetchContextSources: (...args: unknown[]) => fetchContextSources(...args),
    previewCv: (...args: unknown[]) => previewCv(...args),
    fetchVersions: (...args: unknown[]) => fetchVersions(...args),
    fetchLint: (...args: unknown[]) => fetchLint(...args),
    fetchContextStatus: (...args: unknown[]) => fetchContextStatus(...args),
    patchCv: (...args: unknown[]) => patchCv(...args),
    fetchCoverLetterBrief: (...args: unknown[]) => fetchCoverLetterBrief(...args),
    draftCoverLetter: (...args: unknown[]) => draftCoverLetter(...args),
  };
});

const resumeCv: CvDocumentOut = {
  id: "cv-1",
  title: "Backend Intern CV",
  kind: "resume",
  target_posting_id: null,
  template_id: null,
  photo_document_id: null,
  language: "en",
  page_size: "a4",
  max_pages: 1,
  status: "draft",
  working_content: {},
  context: { mode: "all", include: [], exclude: [] },
  source_document_id: null,
  created_at: "2026-09-04T10:00:00Z",
  updated_at: "2026-09-04T10:00:00Z",
  latest_version: null,
};

const letterCv: CvDocumentOut = {
  id: "letter-1",
  title: "Cover letter — Junior DevOps",
  kind: "cover_letter",
  target_posting_id: "post-1",
  template_id: null,
  photo_document_id: null,
  language: "en",
  page_size: "a4",
  max_pages: 1,
  status: "draft",
  working_content: {
    blocks: [
      { kind: "header" },
      { kind: "letter", props: { recipient_org: "Acme" } },
    ],
  },
  context: { mode: "all", include: [], exclude: [] },
  source_document_id: null,
  created_at: "2026-09-05T10:00:00Z",
  updated_at: "2026-09-05T10:00:00Z",
  latest_version: null,
};

const brief = {
  posting_id: "post-1",
  posting_title: "Junior DevOps",
  org: "Acme",
  location: "Athens, GR",
  extract_ready: true,
  must_have: [
    {
      skill_key: "docker",
      label: "docker",
      required_level: 4,
      priority: "must_have",
      evidence_quote: "ships containers daily",
      user_level: 6,
    },
    {
      skill_key: "kubernetes",
      label: "kubernetes",
      required_level: 3,
      priority: "must_have",
      evidence_quote: "kubernetes required",
      user_level: null,
    },
  ],
  nice_to_have: [],
  responsibilities: [],
  fit: { score: 7.2, estimate: false, dimensions: [] },
  coverage: {
    covered: [{ skill_key: "docker", label: "docker", priority: "must_have", user_level: 6 }],
    missing: [{ skill_key: "kubernetes", label: "kubernetes", priority: "must_have", user_level: null }],
  },
  goal: "Build and ship my own apps",
  evidence_items: 5,
};

const suggestion = {
  action: "cover_letter",
  notes: "",
  draft: {
    subject: "Application — Junior DevOps",
    salutation: "Dear Hiring Team,",
    closing: "Sincerely,",
    paragraphs: [],
  },
  paragraphs: [
    {
      text: "I am applying for the Junior DevOps role.",
      evidence_refs: [{ source_key: "experience", item_id: "exp-1" }],
      verified: true,
    },
    {
      text: "My docker work maps directly to your stack.",
      evidence_refs: [{ source_key: "skills", item_id: "sk-1" }],
      verified: true,
    },
    {
      text: "I have ten years of kubernetes production experience.",
      evidence_refs: [],
      verified: false,
    },
  ],
};

const preview = {
  html: "<html><body><h1>Test Student</h1><p class='letter-p'>x</p></body></html>",
  metrics: { estimated_pages: 1, lines_per_page: 40, overflow: false, empty_blocks: [] },
  blocks: [{ kind: "header" }, { kind: "letter", props: { recipient_org: "Acme" } }],
  resolution: {
    snapshot: {},
    snapshot_index: { experience: ["exp-1"], skills: ["sk-1"] },
    items: [],
    resolved_at: "2026-09-05T10:00:00Z",
  },
};

const lint = {
  score: 96,
  passed: true,
  checks: [
    { id: "section_order", level: "pass", message: "Section order matches reading order." },
    { id: "letter_length", level: "pass", message: "Cover letter length is in the sweet spot." },
  ],
  metrics: {},
  resolved_items: 3,
};

const contextStatus = {
  has_baseline: false,
  stale: false,
  changed: [],
  added: [],
  removed: [],
};

function mockBuilderLoad(kind: string) {
  const document: CvDocumentOut = kind === "cover_letter" ? letterCv : resumeCv;
  fetchCv.mockResolvedValue(document);
  fetchContextSources.mockResolvedValue({
    sources: [
      { key: "experience", label: "Experience", description: "Roles", items: [{ item_id: "exp-1", label: "DevOps intern", detail: "Acme" }] },
    ],
  });
  fetchTemplates.mockResolvedValue([]);
  fetchPostings.mockResolvedValue({
    items: [{ id: "post-1", ref: "abc", source_id: "s1", external_id: "e1", title: "Junior DevOps", org: "Acme", location: {}, url: "" }],
    total: 1,
    unseen: 0,
  });
  fetchPhotoGallery.mockResolvedValue([]);
  fetchVersions.mockResolvedValue([]);
  fetchLint.mockResolvedValue(lint);
  fetchContextStatus.mockResolvedValue(contextStatus);
  patchCv.mockImplementation(async (_id: string, body: { working_content?: { blocks?: unknown[] } }) => ({
    ...document,
    working_content: { ...document.working_content, ...body.working_content },
  }));
  previewCv.mockImplementation(async () => {
    const lastPatch = patchCv.mock.calls[patchCv.mock.calls.length - 1];
    const blocks =
      lastPatch?.[1]?.working_content?.blocks ?? document.working_content.blocks ?? [];
    return { ...preview, blocks };
  });
}

function renderApp(initial = "/cv") {
  return render(
    <TooltipProvider>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/cv" element={<CvStudio />} />
          <Route path="/cv/:id" element={<CvBuilder />} />
          <Route path="/postings" element={<div />} />
        </Routes>
      </MemoryRouter>
    </TooltipProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("CvStudio cover letters", () => {
  it("badges cover letters in the list and opens the letter builder", async () => {
    fetchCvs.mockResolvedValue([resumeCv, letterCv]);
    createCoverLetter.mockResolvedValue(letterCv);
    mockBuilderLoad("cover_letter");
    fetchCoverLetterBrief.mockResolvedValue(brief);
    draftCoverLetter.mockResolvedValue(suggestion);
    const user = userEvent.setup();
    renderApp();
    expect(await screen.findByTestId("cv-studio")).toBeInTheDocument();
    expect(screen.getByTestId("cv-kind")).toHaveTextContent("Cover letter");

    await user.click(screen.getByTestId("new-letter"));
    const select = await screen.findByTestId("letter-posting-select");
    await user.selectOptions(select, "post-1");
    await user.click(screen.getByTestId("create-letter"));

    await waitFor(() => expect(createCoverLetter).toHaveBeenCalledWith({ posting_id: "post-1" }));
    expect(await screen.findByTestId("letter-brief")).toBeInTheDocument();
  });
});

describe("CvBuilder cover-letter mode", () => {
  it("shows the brief pane, letter editor and no photo picker", async () => {
    fetchCvs.mockResolvedValue([letterCv]);
    mockBuilderLoad("cover_letter");
    fetchCoverLetterBrief.mockResolvedValue(brief);
    const user = userEvent.setup();
    renderApp("/cv/letter-1");

    const panel = await screen.findByTestId("letter-brief");
    expect(panel).toHaveTextContent("Junior DevOps");
    expect(screen.getByTestId("brief-fit")).toHaveTextContent("7.2");
    expect(screen.getByTestId("brief-skill-docker")).toHaveTextContent("docker");
    const missing = screen.getByTestId("brief-skill-kubernetes");
    expect(missing).toHaveTextContent("kubernetes");
    await user.click(screen.getByTestId("brief-skill-docker-quote-toggle"));
    expect(screen.getByTestId("brief-skill-docker-quote")).toHaveTextContent("ships containers daily");

    await user.click(screen.getByTestId("inspector-tab-sections"));
    expect(await screen.findByTestId("letter-editor")).toBeInTheDocument();
    expect(screen.getByTestId("letter-recipient-org")).toHaveValue("Acme");

    await user.click(screen.getByTestId("inspector-tab-design"));
    expect(screen.queryByText("Profile photo")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("inspector-tab-ai"));
    expect(await screen.findByTestId("draft-letter")).toBeInTheDocument();
  });

  it("reviews the AI draft and applies only the chosen paragraphs", async () => {
    fetchCvs.mockResolvedValue([letterCv]);
    mockBuilderLoad("cover_letter");
    fetchCoverLetterBrief.mockResolvedValue(brief);
    draftCoverLetter.mockResolvedValue(suggestion);
    const user = userEvent.setup();
    renderApp("/cv/letter-1");

    await screen.findByTestId("letter-brief");
    await user.click(screen.getByTestId("inspector-tab-ai"));
    await user.click(await screen.findByTestId("draft-letter"));

    const slideover = await screen.findByTestId("letter-slideover");
    expect(within(slideover).getByTestId("letter-paragraph-0")).toHaveTextContent(
      "I am applying for the Junior DevOps role."
    );
    const flagged = within(slideover).getByTestId("include-paragraph-2");
    expect(flagged).toBeDisabled();
    expect(within(slideover).getByTestId("letter-flag-2")).toHaveTextContent(
      "Flagged: no evidence behind this paragraph."
    );

    await user.click(within(slideover).getByTestId("include-paragraph-1"));
    await user.click(within(slideover).getByTestId("apply-letter-draft"));

    await waitFor(() => expect(patchCv).toHaveBeenCalled());
    const body = patchCv.mock.calls[0][1];
    const letterBlock = body.working_content.blocks.find(
      (block: { kind: string }) => block.kind === "letter"
    );
    expect(letterBlock.props.paragraphs).toEqual([
      "I am applying for the Junior DevOps role.",
    ]);
    expect(letterBlock.props.salutation).toBe("Dear Hiring Team,");
    await waitFor(() =>
      expect(
        previewCv.mock.calls.length
      ).toBeGreaterThan(0)
    );
  });
});

describe("PostingDetail cover-letter entry point", () => {
  it("creates a cover letter for the posting and opens the builder", async () => {
    fetchPostingDetail.mockResolvedValue({
      id: "post-1",
      ref: "abc",
      title: "Junior DevOps",
      org: "Acme",
      location: {},
      url: "",
    });
    createCoverLetter.mockResolvedValue(letterCv);
    mockBuilderLoad("cover_letter");
    fetchCoverLetterBrief.mockResolvedValue(brief);
    const user = userEvent.setup();
    render(
      <TooltipProvider>
        <MemoryRouter initialEntries={["/postings"]}>
          <Routes>
            <Route
              path="/postings"
              element={<PostingDetail postingId="post-1" onClose={() => undefined} />}
            />
            <Route path="/cv/:id" element={<CvBuilder />} />
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    );
    await user.click(await screen.findByTestId("draft-cover-letter"));
    await waitFor(() =>
      expect(createCoverLetter).toHaveBeenCalledWith({ posting_id: "post-1" })
    );
    expect(await screen.findByTestId("letter-brief")).toBeInTheDocument();
  });
});
