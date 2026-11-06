import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { TooltipProvider } from "@neuronection/assistant-ui";
import { createTemplate, fetchTemplateDiff, fetchTemplateVersions, fetchTemplates, previewTemplateDraft, publishTemplateVersion, resetCvStudioMocks, sidebarTemplate, template } from "@/tests/cvStudioHarness";
import { CvTemplateEditor } from "@/features/cv/pages/CvTemplateEditor";

function renderEditor() {
  return render(
    <TooltipProvider>
      <MemoryRouter initialEntries={["/cv/templates/tpl-1"]}>
        <Routes>
          <Route path="/cv/templates/:id" element={<CvTemplateEditor />} />
        </Routes>
      </MemoryRouter>
    </TooltipProvider>
  );
}

beforeEach(resetCvStudioMocks);

describe("CvTemplateEditor", () => {
  it("loads a bank template, applies a theme and saves as a copy", async () => {
    renderEditor();
    expect(await screen.findByTestId("template-title")).toHaveValue(
      "Classic Serif"
    );
    await waitFor(() => expect(previewTemplateDraft).toHaveBeenCalled());
    fireEvent.click(await screen.findByTestId("theme-teal_modern"));
    fireEvent.click(screen.getByTestId("save-template"));
    await waitFor(() => expect(createTemplate).toHaveBeenCalled());
    const body = createTemplate.mock.calls[0][0];
    expect(body.title).toContain("Classic Serif");
    expect(body.content.design.accent_color).toBe("#0f766e");
  });

  it("publishes a new version for an owned template", async () => {
    fetchTemplates.mockResolvedValue([
      { ...template, author_key: "user-1", source: "custom" },
    ]);
    renderEditor();
    expect(await screen.findByTestId("template-title")).toHaveValue(
      "Classic Serif"
    );
    fireEvent.click(await screen.findByTestId("save-template"));
    await waitFor(() =>
      expect(publishTemplateVersion).toHaveBeenCalledWith(
        "tpl-1",
        expect.objectContaining({ title: "Classic Serif" })
      )
    );
  });
});

describe("CvTemplateEditor — plan 70 area paddings", () => {
  it("exposes main/sidebar padding controls for sidebar layouts and round-trips them", async () => {
    fetchTemplates.mockResolvedValue([sidebarTemplate]);
    renderEditor();
    expect(await screen.findByTestId("template-title")).toHaveValue(
      "Navy Sidebar"
    );
    const controls = await screen.findByTestId("sidebar-controls");
    expect(within(controls).getByText("Main column padding")).toBeInTheDocument();
    expect(within(controls).getByText("Sidebar padding")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("save-template"));
    await waitFor(() => expect(createTemplate).toHaveBeenCalled());
    const body = createTemplate.mock.calls[0][0];
    expect(body.content.design).toHaveProperty("main_padding_mm");
    expect(body.content.design).toHaveProperty("sidebar_padding_mm");
  });
});

describe("template editor: version history + diff", () => {
  it("lists versions and renders the deterministic token/block diff", async () => {
    fetchTemplateVersions.mockResolvedValue([
      { id: "tpl-2", version: 2, title: "Classic Serif", created_at: "2026-09-15T10:00:00Z", content_hash: "h2" },
      { id: "tpl-1", version: 1, title: "Classic Serif", created_at: "2026-09-14T10:00:00Z", content_hash: "h1" },
    ]);
    fetchTemplateDiff.mockResolvedValue({
      from_version: 1,
      to_version: 2,
      token_changes: [
        { path: "design.accent_color", from: "#1d4ed8", to: "#0f766e" },
      ],
      block_changes: {
        added: ["interests:"],
        removed: [],
        props_changed: [],
      },
    });
    renderEditor();
    expect(await screen.findByTestId("template-title")).toHaveValue("Classic Serif");
    fireEvent.click(screen.getByTestId("template-history-toggle"));
    expect(await screen.findByTestId("template-history-v2")).toBeInTheDocument();
    const diff = await screen.findByTestId("template-history-diff");
    expect(diff).toHaveTextContent("Changes v1 → v2");
    expect(diff).toHaveTextContent("design.accent_color");
    expect(diff).toHaveTextContent("#1d4ed8 → #0f766e");
    expect(diff).toHaveTextContent("+ interests:");
  });
});

