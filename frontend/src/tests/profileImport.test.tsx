import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AxiosError } from "axios";
import { ProfileImport } from "@/pages/ProfileImport";
import {
  deleteCvDocument,
  fetchCvFileUrl,
  getCvDrafts,
  listCvDocuments,
  listCvDraftHistory,
  reparseCv,
} from "@/api/cvIntake";
import type { CvDraft, DraftHistoryRow } from "@/types/cvIntake";
import type { DocumentRecord } from "@/types";

vi.mock("@/api/cvIntake", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/cvIntake")>();
  return {
    ...mod,
    listCvDocuments: vi.fn<typeof mod.listCvDocuments>(),
    listCvDraftHistory: vi.fn<typeof mod.listCvDraftHistory>(),
    getCvDrafts: vi.fn<typeof mod.getCvDrafts>(),
    reparseCv: vi.fn<typeof mod.reparseCv>(),
    deleteCvDocument: vi.fn<typeof mod.deleteCvDocument>(),
    fetchCvFileUrl: vi.fn<typeof mod.fetchCvFileUrl>(),
    fetchCvPageImageUrl: vi.fn<typeof mod.fetchCvPageImageUrl>(),
  };
});

function documentRecord(overrides: Partial<DocumentRecord> = {}): DocumentRecord {
  return {
    id: "doc-1",
    kind: "cv",
    filename: "cv-2026.pdf",
    mime: "application/pdf",
    size_bytes: 2048,
    page_count: 2,
    status: "ready",
    error: "",
    extraction: { universities: [] },
    created_at: "2026-09-08T10:00:00Z",
    ...overrides,
  };
}

function historyRow(overrides: Partial<DraftHistoryRow> = {}): DraftHistoryRow {
  return {
    document_id: "doc-1",
    status: "pending",
    updated_at: "2026-09-08T10:05:00Z",
    report: {},
    document: {
      id: "doc-1",
      filename: "cv-2026.pdf",
      mime: "application/pdf",
      size_bytes: 2048,
      page_count: 2,
      status: "ready",
      error: "",
      created_at: "2026-09-08T10:00:00Z",
    },
    ...overrides,
  };
}

function renderPage(initialPath = "/profile/import") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/profile/import" element={<ProfileImport />} />
        <Route path="/profile/import/:documentId" element={<ProfileImport />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("ProfileImport — CV import workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listCvDocuments).mockResolvedValue([documentRecord()]);
    vi.mocked(listCvDraftHistory).mockResolvedValue([historyRow()]);
    vi.mocked(fetchCvFileUrl).mockResolvedValue("blob:cv-file");
  });

  it("has an obvious back-to-profile button, not a tiny text link", async () => {
    renderPage();
    const back = await screen.findByTestId("import-back");
    expect(back).toHaveTextContent("Back to profile");
    expect(back).toHaveAttribute("href", "/profile");
  });

  it("lists the CV with its status and shows the applied report", async () => {
    vi.mocked(listCvDraftHistory).mockResolvedValue([
      historyRow({
        status: "applied",
        report: {
          created: { skills: 2, experience_items: 1 },
          proposed_skills: ["python"],
          skill_conflicts: [],
          unmapped_interests: [],
          duplicates: [],
        },
      }),
    ]);
    renderPage();
    const row = await screen.findByTestId("cv-history-row");
    expect(row).toHaveTextContent("cv-2026.pdf");
    expect(row).toHaveTextContent("Imported");
    expect(row).toHaveTextContent("Re-process");
    fireEvent.click(screen.getByTestId("cv-history-report-toggle"));
    expect(screen.getByTestId("cv-history-report")).toHaveTextContent(
      "Added 2 skills, 1 experience entries."
    );
    expect(screen.getByTestId("cv-history-report")).toHaveTextContent(
      "Skills suggested for review: python"
    );
  });

  it("pending drafts open the review flow for that document", async () => {
    vi.mocked(getCvDrafts).mockResolvedValue({
      id: "draft-1",
      status: "pending",
      payload: {
        basics: {
          full_name: "Jane",
          headline: "",
          email: "",
          phone: "",
          location: "",
          links: [],
          evidence: { quote: "Jane", page: null, confidence: 0.9 },
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
    });
    renderPage();
    fireEvent.click(await screen.findByTestId("cv-history-review"));
    expect(screen.getByTestId("import-back")).toHaveTextContent(
      "Back to your CVs"
    );
    await waitFor(() =>
      expect(getCvDrafts).toHaveBeenCalledWith("doc-1")
    );
    expect(await screen.findByTestId("cv-intake-review")).toBeInTheDocument();
  });

  it("re-process re-parses the stored document", async () => {
    vi.mocked(reparseCv).mockResolvedValue({ job_id: "job-1" });
    vi.mocked(getCvDrafts).mockRejectedValue(
      new AxiosError("nf", "404", undefined, undefined, {
        status: 404,
        statusText: "Not Found",
        headers: {},
        config: {} as never,
      } as never)
    );
    renderPage();
    fireEvent.click(await screen.findByTestId("cv-history-reprocess"));
    await waitFor(() => expect(reparseCv).toHaveBeenCalledWith("doc-1"));
  });

  it("downloads the original via a blob URL", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("cv-history-download"));
    await waitFor(() =>
      expect(fetchCvFileUrl).toHaveBeenCalledWith("doc-1")
    );
  });

  it("deletes a CV after confirmation and refreshes the list", async () => {
    vi.mocked(deleteCvDocument).mockResolvedValue(undefined);
    vi.mocked(listCvDraftHistory)
      .mockResolvedValueOnce([historyRow()])
      .mockResolvedValueOnce([]);
    vi.mocked(listCvDocuments)
      .mockResolvedValueOnce([documentRecord()])
      .mockResolvedValueOnce([]);
    renderPage();
    fireEvent.click(await screen.findByTestId("cv-history-delete"));
    fireEvent.click(await screen.findByRole("button", { name: "Delete CV" }));
    await waitFor(() =>
      expect(deleteCvDocument).toHaveBeenCalledWith("doc-1")
    );
    await waitFor(() =>
      expect(screen.getByText("No CVs yet")).toBeInTheDocument()
    );
  });

  describe("per-CV detail route", () => {
    const APPLIED_DRAFT: CvDraft = {
      id: "draft-1",
      status: "applied",
      payload: {
        basics: {
          full_name: "Jane",
          headline: "",
          email: "",
          phone: "",
          location: "",
          links: [],
          evidence: { quote: "Jane", page: null, confidence: 0.9 },
        },
        summary: "",
        education: [],
        experience: [],
        skills: [
          {
            name: "Python",
            level_claim: 8,
            evidence: { quote: "Python — 8", page: 0, confidence: 0.4 },
          },
        ],
        languages: [],
        certifications: [],
        awards: [],
        interests: [],
      },
      report: {
        created: { skills: 2 },
        proposed_skills: [],
        skill_conflicts: [],
        unmapped_interests: [],
        duplicates: [],
      },
      applied: [
        { entity_type: "basics", count: 1 },
        { entity_type: "skills", count: 2 },
        { entity_type: "experience_items", count: 1 },
      ],
    };

    function appliedRow(): DraftHistoryRow {
      return historyRow({
        status: "applied",
        report: { created: { skills: 2 } },
      });
    }

    it("the filename opens the read-only viewer for a processed CV", async () => {
      vi.mocked(listCvDraftHistory).mockResolvedValue([appliedRow()]);
      vi.mocked(getCvDrafts).mockResolvedValue(APPLIED_DRAFT);
      renderPage();
      fireEvent.click(await screen.findByTestId("cv-history-open"));
      const meta = await screen.findByTestId("cv-detail-meta");
      expect(meta).toHaveTextContent("cv-2026.pdf");
      expect(meta).toHaveTextContent("Imported");
      await waitFor(() =>
        expect(getCvDrafts).toHaveBeenCalledWith("doc-1")
      );
      expect(await screen.findByTestId("cv-draft-viewer")).toBeInTheDocument();
      expect(screen.getByText("Python")).toBeInTheDocument();
      expect(
        screen.queryByTestId("intake-section-toggle-skills")
      ).not.toBeInTheDocument();
      expect(screen.getByTestId("confidence-low")).toBeInTheDocument();
      const report = screen.getByTestId("cv-draft-report");
      expect(report).toHaveTextContent("Added 2 skills.");
      expect(report).toHaveTextContent("Imported");
      expect(screen.getByText("Landed in your profile")).toBeInTheDocument();
      const skillsLink = screen.getByTestId("cv-applied-link-skills");
      expect(skillsLink).toHaveAttribute("href", "/profile#skills");
      expect(skillsLink).toHaveTextContent("2 skills");
      expect(screen.getByTestId("cv-applied-link-experience_items")).toHaveAttribute(
        "href",
        "/profile/experience"
      );
    });

    it("a deep link opens the viewer directly", async () => {
      vi.mocked(listCvDraftHistory).mockResolvedValue([appliedRow()]);
      vi.mocked(getCvDrafts).mockResolvedValue(APPLIED_DRAFT);
      renderPage("/profile/import/doc-1");
      expect(await screen.findByTestId("cv-draft-viewer")).toBeInTheDocument();
    });

    it("the back button returns to the list", async () => {
      vi.mocked(listCvDraftHistory).mockResolvedValue([appliedRow()]);
      vi.mocked(getCvDrafts).mockResolvedValue(APPLIED_DRAFT);
      renderPage("/profile/import/doc-1");
      fireEvent.click(await screen.findByTestId("import-back"));
      expect(await screen.findByTestId("cv-history-row")).toBeInTheDocument();
    });

    it("an unknown document id shows not found", async () => {
      renderPage("/profile/import/nope");
      expect(await screen.findByText("CV not found")).toBeInTheDocument();
    });

    it("re-process from the detail re-parses the document", async () => {
      vi.mocked(reparseCv).mockResolvedValue({ job_id: "job-1" });
      vi.mocked(listCvDraftHistory).mockResolvedValue([appliedRow()]);
      vi.mocked(getCvDrafts).mockResolvedValue(APPLIED_DRAFT);
      renderPage("/profile/import/doc-1");
      fireEvent.click(await screen.findByTestId("cv-detail-reprocess"));
      await waitFor(() => expect(reparseCv).toHaveBeenCalledWith("doc-1"));
    });
  });
});
