import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { TooltipProvider } from "@neuronection/assistant-ui";
import { createCv, cv, deleteCv, draftTemplateAi, fetchCvs, fetchTemplatePreview, fetchTemplates, resetCvStudioMocks, template } from "./cvStudioHarness";
import { CvStudio } from "@/pages/CvStudio";
import { CvBuilder } from "@/pages/CvBuilder";
import { CvTemplateEditor } from "@/pages/CvTemplateEditor";

function renderStudio() {
  return render(
    <TooltipProvider>
      <MemoryRouter initialEntries={["/cv"]}>
        <Routes>
          <Route path="/cv" element={<CvStudio />} />
          <Route path="/cv/:id" element={<CvBuilder />} />
          <Route path="/cv/templates/:id" element={<CvTemplateEditor />} />
          <Route path="/profile/import" element={<div data-testid="import-dest" />} />
        </Routes>
      </MemoryRouter>
    </TooltipProvider>
  );
}

beforeEach(resetCvStudioMocks);

describe("CvStudio", () => {
  it("lists CVs and opens the create modal", async () => {
    renderStudio();
    expect(await screen.findByText("Backend Intern CV")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("new-cv"));
    await screen.findByTestId("cv-generate-form");
    fireEvent.click(screen.getByRole("button", { name: "Start from scratch" }));
    fireEvent.change(screen.getByTestId("new-cv-title"), { target: { value: "Design CV" } });
    fireEvent.click(screen.getByTestId("create-cv"));
    await waitFor(() => expect(createCv).toHaveBeenCalled());
    expect(createCv.mock.calls[0][0].title).toBe("Design CV");
  });

  it("shows an error state when loading fails", async () => {
    fetchCvs.mockRejectedValue(new Error("boom"));
    renderStudio();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("asks for confirmation before deleting a CV", async () => {
    renderStudio();
    fireEvent.click(await screen.findByTestId(`delete-cv-${cv.id}`));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/Delete “Backend Intern CV”/);
    expect(deleteCv).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete CV" }));
    await waitFor(() => expect(deleteCv).toHaveBeenCalledWith("cv-1"));
  });

  it("shows a first-page thumbnail on the card and degrades without the engine", async () => {
    renderStudio();
    expect(
      await screen.findByRole("heading", { name: "Your CVs" })
    ).toBeInTheDocument();
    const thumb = await screen.findByTestId("cv-card-thumbnail");
    expect(thumb).toHaveAttribute("data-thumbnail-state", "loading");
    const image = within(thumb).getByRole("img");
    expect(image).toHaveAttribute(
      "src",
      `/api/v1/cv/cv-1/preview.png?v=${Date.parse(cv.updated_at)}`
    );
    fireEvent.error(image);
    expect(thumb).toHaveAttribute("data-thumbnail-state", "error");

    const dates = await screen.findByTestId("cv-card-dates-cv-1");
    expect(dates).toHaveTextContent("Created");
    expect(dates).toHaveTextContent("Updated");
  });

  it("opens the CV when the card (thumbnail) is clicked", async () => {
    renderStudio();
    fireEvent.click(await screen.findByTestId("cv-card-thumbnail"));
    expect(await screen.findByTestId("preview-frame")).toBeInTheDocument();
  });

  it("gallery shows a grid-only picker with previews and per-card customize", async () => {
    fetchTemplates.mockResolvedValue([
      template,
      { ...template, id: "tpl-2", title: "Second Style" },
    ]);
    renderStudio();
    fireEvent.click(screen.getByTestId("new-cv"));
    await screen.findByTestId("cv-generate-form");
    fireEvent.click(screen.getByRole("button", { name: "Start from scratch" }));
    fireEvent.click(await screen.findByTestId("choose-template"));
    expect(await screen.findByTestId("gallery-grid")).toBeInTheDocument();
    expect(screen.queryByTestId("gallery-featured")).not.toBeInTheDocument();
    const cards = screen.getAllByTestId("template-card");
    expect(cards).toHaveLength(2);
    expect(screen.getByTestId("preview-template-tpl-2")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("edit-template-tpl-2"));
    expect(await screen.findByTestId("template-title")).toHaveValue(
      "Second Style"
    );
  });

  it("picks a template with AI inside the new-CV form", async () => {
    renderStudio();
    fireEvent.click(screen.getByTestId("new-cv"));
    await screen.findByTestId("cv-generate-form");
    fireEvent.click(screen.getByRole("button", { name: "Start from scratch" }));
    fireEvent.click(await screen.findByTestId("ask-ai-choose"));
    const tile = await screen.findByTestId("use-suggestion-tpl-1");
    expect(tile).toHaveTextContent("Classic Serif");
    expect(tile.parentElement).toHaveTextContent("ATS-safe serif");
    fireEvent.click(tile);
    await waitFor(() =>
      expect(screen.getByTestId("new-cv-template-section")).toHaveTextContent(
        "Classic Serif"
      )
    );
    fireEvent.change(screen.getByTestId("new-cv-title"), { target: { value: "AI CV" } });
    fireEvent.click(screen.getByTestId("create-cv"));
    await waitFor(() => expect(createCv).toHaveBeenCalled());
    expect(createCv.mock.calls[0][0]).toEqual({
      title: "AI CV",
      template_id: "tpl-1",
    });
  });

  it("creates a CV with no template chosen (studio default)", async () => {
    renderStudio();
    fireEvent.click(screen.getByTestId("new-cv"));
    await screen.findByTestId("cv-generate-form");
    fireEvent.click(screen.getByRole("button", { name: "Start from scratch" }));
    fireEvent.click(await screen.findByTestId("new-cv-template-section"));
    expect(screen.getByTestId("no-template-note")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("new-cv-title"), { target: { value: "Plain CV" } });
    fireEvent.click(screen.getByTestId("create-cv"));
    await waitFor(() => expect(createCv).toHaveBeenCalled());
    expect(createCv.mock.calls[0][0]).toEqual({ title: "Plain CV" });
  });

  it("opens the gallery and creates a CV from a chosen template", async () => {
    renderStudio();
    fireEvent.click(screen.getByTestId("new-cv"));
    await screen.findByTestId("cv-generate-form");
    fireEvent.click(screen.getByRole("button", { name: "Start from scratch" }));
    fireEvent.click(await screen.findByTestId("choose-template"));
    const card = await screen.findByTestId("template-card");
    expect(card).toHaveTextContent("Classic Serif");
    await waitFor(() =>
      expect(fetchTemplatePreview).toHaveBeenCalledWith("tpl-1")
    );
    fireEvent.click(screen.getByTestId(`use-template-${template.id}`));
    expect(await screen.findByText(/New CV from “Classic Serif”/)).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("new-cv-title"), { target: { value: "Serif CV" } });
    fireEvent.click(screen.getByTestId("create-cv"));
    await waitFor(() => expect(createCv).toHaveBeenCalled());
    expect(createCv.mock.calls[0][0]).toEqual({
      title: "Serif CV",
      template_id: "tpl-1",
    });
  });

  it("drafts a template with AI from the gallery", async () => {
    renderStudio();
    fireEvent.click(screen.getByTestId("new-cv"));
    await screen.findByTestId("cv-generate-form");
    fireEvent.click(screen.getByRole("button", { name: "Start from scratch" }));
    fireEvent.click(await screen.findByTestId("choose-template"));
    fireEvent.change(await screen.findByTestId("template-brief"), {
      target: { value: "serif, teal accent" },
    });
    fireEvent.click(screen.getByText("Draft with AI"));
    await waitFor(() => expect(draftTemplateAi).toHaveBeenCalledWith("serif, teal accent"));
    expect(await screen.findByText("AI draft")).toBeInTheDocument();
  });
});

describe("CvStudio — import routing", () => {
  it("the New CV modal offers an Import-from-CV mode that routes to the workspace", async () => {
    renderStudio();
    fireEvent.click(await screen.findByTestId("new-cv"));
    fireEvent.click(await screen.findByRole("button", { name: "Import from CV" }));
    fireEvent.click(await screen.findByTestId("import-cv-go"));
    expect(await screen.findByTestId("import-dest")).toBeInTheDocument();
  });
});

