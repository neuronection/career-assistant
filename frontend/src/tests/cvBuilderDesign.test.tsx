import { beforeEach, describe, expect, it } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { TooltipProvider } from "@neuronection/assistant-ui";
import { applyCvOps, openInspectorTab, patchCv, preview, resetCvStudioMocks } from "@/tests/cvStudioHarness";
import { CvBuilder } from "@/features/cv/pages/CvBuilder";
import { CvStudio } from "@/features/cv/pages/CvStudio";
import { CvTemplateEditor } from "@/features/cv/pages/CvTemplateEditor";

function renderBuilder() {
  return render(
    <TooltipProvider>
      <MemoryRouter initialEntries={["/cv/cv-1"]}>
        <Routes>
          <Route path="/cv" element={<CvStudio />} />
          <Route path="/cv/:id" element={<CvBuilder />} />
          <Route path="/cv/templates/:id" element={<CvTemplateEditor />} />
        </Routes>
      </MemoryRouter>
    </TooltipProvider>
  );
}

beforeEach(resetCvStudioMocks);

describe("CvBuilder — plan 70 items kinds filter", () => {
  it("toggles experience kinds on an items section and saves the filter", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    fireEvent.click(screen.getByTestId("add-section-button"));
    fireEvent.click(await screen.findByTestId("add-block-items"));
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId("configure-section-2"));
    const group = await screen.findByRole("group", { name: "Include kinds" });
    fireEvent.click(within(group).getByRole("button", { name: "Jobs" }));
    await waitFor(
      () => {
        const blocks =
          patchCv.mock.calls[patchCv.mock.calls.length - 1][1].working_content
            .blocks;
        expect(blocks[blocks.length - 1].props.kinds).toEqual(["job"]);
      },
      { timeout: 3000 }
    );
  });
});

describe("CvBuilder — plan 85 consolidated Design tab", () => {
  it("renders the merged Design tab with template card, tokens and photo", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("design");
    const body = await screen.findByTestId("inspector-body-design");
    expect(within(body).getByTestId("design-token-editor")).toBeInTheDocument();
    expect(within(body).getByTestId("template-meta")).toHaveTextContent(
      "Classic Serif"
    );
    expect(within(body).getByTestId("template-picker")).toBeInTheDocument();
    expect(within(body).getByTestId("browse-templates")).toBeInTheDocument();
    expect(within(body).getByTestId("photo-picker-card")).toBeInTheDocument();
    expect(within(body).getByTestId("apply-design")).toBeDisabled();
    // The action footer is pinned outside the scrollable body.
    const scroll = within(body).getByTestId("design-scroll");
    expect(scroll).not.toContainElement(within(body).getByTestId("design-footer"));
    expect(within(body).getByTestId("design-footer")).toContainElement(
      within(body).getByTestId("apply-design")
    );
    // The inspector is a segmented tablist — no "Template" entry exists.
    const tablist = screen.getByRole("tablist", { name: "Inspector panels" });
    expect(within(tablist).queryByRole("tab", { name: "Template" })).not.toBeInTheDocument();
    expect(within(tablist).getByRole("tab", { name: "Design" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });

  it("applies a design change through the ops endpoint and re-syncs", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("design");
    const body = await screen.findByTestId("inspector-body-design");
    fireEvent.change(within(body).getByLabelText("Accent"), {
      target: { value: "#b91c1c" },
    });
    expect(within(body).getByTestId("apply-design")).toBeEnabled();
    fireEvent.click(within(body).getByTestId("apply-design"));
    await waitFor(() => expect(applyCvOps).toHaveBeenCalledTimes(1));
    const [cvId, ops] = applyCvOps.mock.calls[0];
    expect(cvId).toBe("cv-1");
    expect(ops[0].op).toBe("update_design");
    expect(ops[0].design.accent_color).toBe("#b91c1c");
    expect(await screen.findByTestId("preview-frame")).toBeInTheDocument();
  });
});

describe("CvBuilder — plan 71 container styling", () => {
  it("configures a block container in the builder sections panel", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    fireEvent.click(screen.getByTestId("add-section-button"));
    fireEvent.click(await screen.findByTestId("add-block-skills"));
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId("configure-section-2"));
    const container = await screen.findByTestId("container-2");
    fireEvent.change(within(container).getByLabelText("Container"), {
      target: { value: "card" },
    });
    await waitFor(
      () => {
        const blocks =
          patchCv.mock.calls[patchCv.mock.calls.length - 1][1].working_content
            .blocks;
        expect(blocks[blocks.length - 1].props.container.container).toBe("card");
      },
      { timeout: 3000 }
    );
  });
});

describe("CvBuilder — plan 71 critique card", () => {
  it("renders the copilot critique with one-click fixes", async () => {
    const { useCvBuilderLink } = await import("@/stores/cvBuilderLinkStore");
    act(() => {
      useCvBuilderLink.setState({
        lastBuilderState: {
          document: { id: "cv-1", title: "T", kind: "resume", language: "en", page_size: "a4", max_pages: 1, status: "draft", template_id: null, photo_document_id: null },
          blocks: preview.blocks,
          overrides: {},
          html: preview.html,
          metrics: preview.metrics,
          resolution: { snapshot_index: {} },
          operations: [],
          critique: {
            summary: "Layout is close to budget",
            issues: [{ severity: "major", area: "page_budget", message: "Content renders on 2 pages but the budget is 1." }],
            safe_token_fixes: { base_size_pt: "9.5" },
          },
          version: 1,
        },
      });
    });
    renderBuilder();
    await screen.findByTestId("preview-frame");
    const canvas = screen.getByTestId("builder-canvas");
    const card = await within(canvas).findByTestId("critique-card");
    expect(within(card).getByTestId("critique-issue-0")).toHaveTextContent("page_budget");
    applyCvOps.mockResolvedValueOnce({
      results: [{ op: "update_design", ok: true, detail: "ok" }],
      state: {
        document: { id: "cv-1" },
        blocks: preview.blocks,
        overrides: {},
        html: "<html>fixed</html>",
        metrics: preview.metrics,
        resolution: { snapshot_index: {} },
        operations: [],
        critique: null,
        version: 2,
      },
    });
    fireEvent.click(within(card).getByTestId("apply-critique-fixes"));
    await waitFor(() => expect(applyCvOps).toHaveBeenCalledTimes(1));
    expect(applyCvOps.mock.calls[0][1][0].design).toEqual({ base_size_pt: "9.5" });
  });
});

