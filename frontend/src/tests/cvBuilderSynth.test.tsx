import { beforeEach, describe, expect, it } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { TooltipProvider } from "@neuronection/assistant-ui";
import { bulletsVariantRow, cv, deleteSynthItem, fetchCv, fetchSynthItems, generateSynthItems, openInspectorTab, patchCv, patchSynthItem, preview, previewCv, refreshSynthSourceState, resetCvStudioMocks, setContext, setSynthPin, typeIntoRichText } from "@/tests/cvStudioHarness";
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

describe("CvBuilder — plan 72 synth highlights + item ordering", () => {
  it("adds the Custom highlights section from the add-section card", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    fireEvent.click(screen.getByTestId("add-section-button"));
    fireEvent.click(await screen.findByTestId("add-block-synth_items"));
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(1));
    const [, body] = patchCv.mock.calls[0];
    const added = body.working_content.blocks[body.working_content.blocks.length - 1];
    expect(added.kind).toBe("synth_items");
    expect(added.props.title).toBe("Highlights");
    expect(added.props.show_source_chips).toBe(true);
  });

  it("configs a synth_items block and round-trips its props", async () => {
    fetchSynthItems.mockResolvedValue([
      {
        id: "syn-1",
        scope: "item",
        variant_key: "default",
        target_posting_id: null,
        source_refs: [{ source_key: "experience", item_id: "exp-1" }],
        source_state: [],
        payload: { description: "Tailored text" },
        voice: { language: "en" },
        status: "active",
        source: "manual",
        verified: true,
        stale: true,
        orphaned: false,
        last_used_at: null,
        created_at: "",
      },
    ]);
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    fireEvent.click(screen.getByTestId("add-section-button"));
    fireEvent.click(await screen.findByTestId("add-block-synth_items"));
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId("configure-section-2"));
    const chips = await screen.findByRole("button", {
      name: /Tailored text \(changed\)/,
    });
    fireEvent.click(chips);
    await waitFor(() => {
      const blocks =
        patchCv.mock.calls[patchCv.mock.calls.length - 1][1].working_content
          .blocks;
      expect(blocks[blocks.length - 1].props.selected).toEqual(["syn-1"]);
    });
    fireEvent.click(screen.getByTestId("stepper-max-items").children[2]);
    await waitFor(() => {
      const blocks =
        patchCv.mock.calls[patchCv.mock.calls.length - 1][1].working_content
          .blocks;
      expect(blocks[blocks.length - 1].props.max_items).toBe(7);
    });
    const chipsToggle = screen.getByTestId("toggle-show-source-chips") as HTMLInputElement;
    expect(chipsToggle.checked).toBe(true);
    fireEvent.click(chipsToggle);
    await waitFor(() => {
      const blocks =
        patchCv.mock.calls[patchCv.mock.calls.length - 1][1].working_content
          .blocks;
      expect(blocks[blocks.length - 1].props.show_source_chips).toBe(false);
    });
  });

  it("reorders items in an items block and persists the full order array", async () => {
    const richPreview = {
      ...preview,
      resolution: {
        ...preview.resolution,
        snapshot: {
          experience: [
            { id: "exp-1", title: "Older Role" },
            { id: "exp-2", title: "Newer Role" },
          ],
        },
        snapshot_index: { ...preview.resolution.snapshot_index, experience: ["exp-1", "exp-2"] },
      },
    };
    previewCv.mockImplementation(async () => {
      const lastPatch = patchCv.mock.calls[patchCv.mock.calls.length - 1]?.[1] as
        | { working_content?: { blocks?: typeof richPreview.blocks } }
        | undefined;
      return {
        ...richPreview,
        blocks: lastPatch?.working_content?.blocks ?? richPreview.blocks,
      };
    });
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("sections");
    fireEvent.click(screen.getByTestId("add-section-button"));
    fireEvent.click(await screen.findByTestId("add-block-items"));
    await waitFor(() => expect(patchCv).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId("configure-section-2"));
    fireEvent.click(await screen.findByTestId("items-order-toggle"));
    await screen.findByTestId("items-order-list");
    fireEvent.click(screen.getByTestId("items-order-up-exp-2"));
    await waitFor(() => {
      const blocks =
        patchCv.mock.calls[patchCv.mock.calls.length - 1][1].working_content
          .blocks;
      const itemsBlock = blocks.find(
        (block: { kind: string }) => block.kind === "items"
      );
      expect(itemsBlock.props.order).toEqual(["exp-2", "exp-1"]);
    });
  });

  it("renders active variants nested under their items, cross-listed per ref", async () => {
    fetchSynthItems.mockResolvedValue([
      {
        id: "syn-1",
        scope: "item",
        variant_key: "tailored",
        target_posting_id: null,
        source_refs: [
          { source_key: "experience", item_id: "exp-1" },
          { source_key: "skills", item_id: "sk-1" },
        ],
        source_state: [],
        payload: { description: "Cross-listed text" },
        voice: { language: "en" },
        status: "active",
        source: "ai",
        verified: true,
        stale: false,
        orphaned: false,
        last_used_at: null,
        created_at: "",
      },
    ]);
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    fireEvent.click(screen.getByTestId("context-group-header-skills"));
    expect(
      await screen.findAllByTestId("context-variant-syn-1"),
    ).toHaveLength(2);
    expect(screen.queryByTestId("context-variant-toggle-syn-1")).toBeNull(),
      void screen.queryByTestId("context-variant-toggle-syn-1");
  });

  it("stars a draft variant through the surgical pin endpoint (plan 102)", async () => {
    cv.context = {
      mode: "all",
      include: [],
      exclude: [],
      synth_pins: {},
    };
    fetchSynthItems.mockResolvedValue([
      {
        id: "syn-1",
        scope: "item",
        variant_key: "tailored",
        target_posting_id: null,
        source_refs: [{ source_key: "experience", item_id: "exp-1" }],
        source_state: [],
        payload: { description: "Draft text" },
        voice: { language: "en" },
        status: "draft",
        source: "ai",
        verified: true,
        stale: false,
        orphaned: false,
        last_used_at: null,
        created_at: "",
      },
    ]);
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    await screen.findByTestId("context-variant-syn-1");
    fireEvent.click(await screen.findByTestId("context-pin-star-syn-1"));
    await waitFor(() =>
      expect(setSynthPin).toHaveBeenCalledWith(
        "cv-1",
        "experience",
        "exp-1",
        "syn-1",
      ),
    );
    cv.context = { mode: "all", include: [], exclude: [] };
  });

  it("pins a variant per item with the star and persists synth_pins", async () => {
    fetchSynthItems.mockResolvedValue([
      {
        id: "syn-1",
        scope: "item",
        variant_key: "tailored",
        target_posting_id: null,
        source_refs: [{ source_key: "experience", item_id: "exp-1" }],
        source_state: [],
        payload: { description: "Pinned text" },
        voice: { language: "en" },
        status: "active",
        source: "manual",
        verified: true,
        stale: false,
        orphaned: false,
        last_used_at: null,
        created_at: "",
      },
    ]);
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    const star = await screen.findByTestId("context-pin-star-syn-1");
    expect(star.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(star);
    await waitFor(() =>
      expect(setSynthPin).toHaveBeenCalledWith(
        "cv-1",
        "experience",
        "exp-1",
        "syn-1",
      ),
    );
    const starred = await screen.findByTestId("context-pin-star-syn-1");
    expect(starred.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(starred);
    await waitFor(() => expect(setSynthPin).toHaveBeenCalledTimes(2));
    expect(setSynthPin.mock.calls[1]).toEqual([
      "cv-1",
      "experience",
      "exp-1",
      null,
    ]);
  });

  it("marks a pinned variant not-rendering when the preview omits it from synth_applied", async () => {
    cv.context = {
      mode: "all",
      include: [],
      exclude: [],
      synth_pins: { "experience:exp-1": "syn-1" },
    };
    fetchSynthItems.mockResolvedValue([
      {
        id: "syn-1",
        scope: "item",
        variant_key: "de-variant",
        target_posting_id: null,
        source_refs: [{ source_key: "experience", item_id: "exp-1" }],
        source_state: [],
        payload: { description: "German text" },
        voice: { language: "de" },
        status: "active",
        source: "manual",
        verified: true,
        stale: false,
        orphaned: false,
        last_used_at: null,
        created_at: "",
      },
    ]);
    previewCv.mockImplementation(async () => ({
      ...preview,
      resolution: { ...preview.resolution, synth_applied: {} },
    }));
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    expect(
      await screen.findByTestId("context-variant-inactive-syn-1"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("context-pin-star-syn-1").getAttribute("data-inactive"),
    ).toBe("true");
    cv.context = { mode: "all", include: [], exclude: [] };
  });

  it("pins a bullets variant on the single slot (plan 110)", async () => {
    fetchSynthItems.mockResolvedValue([
      bulletsVariantRow("syn-b1", ["Cut latency 40%"]),
    ]);
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    expect(
      await screen.findByTestId("context-variant-bullets-syn-b1"),
    ).toBeInTheDocument();
    const star = await screen.findByTestId("context-pin-star-syn-b1");
    expect(star.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(star);
    await waitFor(() =>
      expect(setSynthPin).toHaveBeenCalledWith(
        "cv-1",
        "experience",
        "exp-1",
        "syn-b1",
      ),
    );
  });

  it("offers Reset on a stale variant and re-snapshots via the API (plan 102)", async () => {
    fetchSynthItems.mockResolvedValue([
      {
        id: "syn-1",
        scope: "item",
        variant_key: "tailored",
        target_posting_id: null,
        source_refs: [{ source_key: "experience", item_id: "exp-1" }],
        source_state: [],
        payload: { description: "Stale text" },
        voice: { language: "en" },
        status: "active",
        source: "ai",
        verified: true,
        stale: true,
        orphaned: false,
        last_used_at: null,
        created_at: "",
      },
    ]);
    refreshSynthSourceState.mockImplementation(async () => ({}));
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    expect(await screen.findByTestId("context-variant-stale")).toBeInTheDocument();
    fireEvent.click(await screen.findByTestId("context-variant-reset-syn-1"));
    await waitFor(() =>
      expect(refreshSynthSourceState).toHaveBeenCalledWith("syn-1"),
    );
  });

  it("shows an edit button on variant rows that opens the editor", async () => {
    fetchSynthItems.mockResolvedValue([
      {
        id: "syn-1",
        scope: "item",
        variant_key: "tailored",
        target_posting_id: null,
        source_refs: [{ source_key: "experience", item_id: "exp-1" }],
        source_state: [],
        payload: { description: "Nested under its item" },
        voice: { language: "en" },
        status: "active",
        source: "manual",
        verified: true,
        stale: false,
        orphaned: false,
        last_used_at: null,
        created_at: "",
      },
    ]);
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    fireEvent.click(await screen.findByTestId("context-variant-edit-syn-1"));
    const text = await screen.findByTestId("synth-editor-description-input");
    await typeIntoRichText(text, "Nested under its item");
    await waitFor(() =>
      expect(
        (text.querySelector(".ProseMirror") as HTMLElement | null)?.textContent,
      ).toContain("Nested under its item"),
    );
  });

  it("deletes the variant from the edit form and unpins it from any slot", async () => {
    const user = userEvent.setup();
    fetchSynthItems.mockResolvedValue([
      {
        id: "syn-1",
        scope: "item",
        variant_key: "tailored",
        target_posting_id: null,
        source_refs: [{ source_key: "experience", item_id: "exp-1" }],
        source_state: [],
        payload: { description: "Pinned text" },
        voice: { language: "en" },
        status: "active",
        source: "manual",
        verified: true,
        stale: false,
        orphaned: false,
        last_used_at: null,
        created_at: "",
      },
    ]);
    fetchCv.mockResolvedValue({
      ...cv,
      context: { ...cv.context, synth_pins: { "experience:exp-1": "syn-1" } },
    });
    deleteSynthItem.mockResolvedValue(undefined);
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    fireEvent.click(await screen.findByTestId("context-variant-edit-syn-1"));
    await screen.findByTestId("synth-editor-description-input");
    expect(screen.getByTestId("synth-editor-delete")).toBeInTheDocument();
    const fetchCvCalls = fetchCv.mock.calls.length;
    await user.click(screen.getByTestId("synth-editor-delete"));
    await user.click(
      await screen.findByRole("button", { name: "Delete" }),
    );
    await waitFor(() => expect(deleteSynthItem).toHaveBeenCalledWith("syn-1"));
    await waitFor(() =>
      expect(fetchCv.mock.calls.length).toBeGreaterThan(fetchCvCalls),
    );
    expect(screen.queryByTestId("synth-editor-delete")).not.toBeInTheDocument();
  });

  it("finds variants nested under their own item row, not the group bottom", async () => {
    fetchSynthItems.mockResolvedValue([
      {
        id: "syn-1",
        scope: "item",
        variant_key: "tailored",
        target_posting_id: null,
        source_refs: [{ source_key: "experience", item_id: "exp-1" }],
        source_state: [],
        payload: { description: "Cross-listed text" },
        voice: { language: "en" },
        status: "draft",
        source: "ai",
        verified: true,
        stale: false,
        orphaned: false,
        last_used_at: null,
        created_at: "",
      },
    ]);
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    expect(await screen.findByTestId("context-variant-syn-1")).toBeTruthy();
  });

  it("opens the variant editor from the context panel add-variant button", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    fireEvent.click(await screen.findByTestId("ai-add-variant-exp-1"));
    expect(
      await screen.findByTestId("synth-editor-description-input"),
    ).toBeInTheDocument();
  });

  it("AI-generates into the form and Save & use promotes it (plan 103)", async () => {
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    fireEvent.click(await screen.findByTestId("ai-add-variant-exp-1"));
    generateSynthItems.mockImplementation(async () => ({
      items: [
        {
          id: "syn-gen",
          scope: "item",
          variant_key: "default",
          target_posting_id: null,
          source_refs: [{ source_key: "experience", item_id: "exp-1" }],
          source_state: [],
          payload: { description: "Generated text" },
          voice: { language: "en" },
          status: "draft",
          source: "ai",
          verified: true,
          stale: false,
          orphaned: false,
          last_used_at: null,
          created_at: "",
        },
      ],
    }));
    patchSynthItem.mockImplementation(async () => ({ id: "syn-gen" }));
    setContext.mockImplementation(async () => ({ ...cv }));
    fireEvent.click(await screen.findByTestId("synth-editor-gen-action-detail"));
    fireEvent.click(await screen.findByTestId("synth-editor-gen-run"));
    const text = await screen.findByTestId("synth-editor-description-input");
    await waitFor(() => expect(text.textContent).toContain("Generated text"));
    await waitFor(() =>
      expect(generateSynthItems).toHaveBeenCalledWith(
        expect.objectContaining({
          action: "detail",
          refs: [{ source_key: "experience", item_id: "exp-1" }],
        }),
      ),
    );
    fireEvent.click(await screen.findByTestId("synth-editor-save-use"));
    await waitFor(() =>
      expect(patchSynthItem).toHaveBeenCalledWith("syn-gen", {
        status: "active",
      }),
    );
  });

  it("the editor's On-the-CV-now row follows the star, not the newest active row", async () => {
    const row = (id: string, text: string, created: string) => ({
      id,
      scope: "item",
      variant_key: "tailored",
      target_posting_id: null,
      source_refs: [{ source_key: "experience", item_id: "exp-1" }],
      source_state: [],
      payload: { description: text },
      voice: { language: "en" },
      status: "active",
      source: "manual",
      verified: true,
      stale: false,
      orphaned: false,
      last_used_at: null,
      created_at: created,
    });
    cv.context = {
      mode: "all",
      include: [],
      exclude: [],
      synth_pins: { "experience:exp-1": "syn-pinned" },
    };
    fetchSynthItems.mockResolvedValue([
      row("syn-newer", "Newest active text", "2026-09-20T00:00:00Z"),
      row("syn-pinned", "Pinned text", "2026-09-10T00:00:00Z"),
    ]);
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    fireEvent.click(await screen.findByTestId("context-variant-edit-syn-newer"));
    const previewRow = await screen.findByTestId("synth-editor-preview");
    expect(previewRow).toHaveTextContent("Pinned text");
    cv.context = { mode: "all", include: [], exclude: [] };
  });

  it("steps through the slot's rows with the chevrons (plan 103)", async () => {
    const row = (id: string, text: string, created: string) => ({
      id,
      scope: "item",
      variant_key: "tailored",
      target_posting_id: null,
      source_refs: [{ source_key: "experience", item_id: "exp-1" }],
      source_state: [],
      payload: { description: text },
      voice: { language: "en" },
      status: "active",
      source: "manual",
      verified: true,
      stale: false,
      orphaned: false,
      last_used_at: null,
      created_at: created,
    });
    fetchSynthItems.mockResolvedValue([
      row("syn-old", "Older text", "2026-09-01T00:00:00Z"),
      row("syn-new", "Newer text", "2026-09-02T00:00:00Z"),
      {
        ...row("syn-other", "Other slot text", "2026-09-03T00:00:00Z"),
        variant_key: "concise",
      },
    ]);
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    fireEvent.click(await screen.findByTestId("context-variant-edit-syn-new"));
    await waitFor(() => screen.getByTestId("synth-editor-slot-prev"));
    await waitFor(() => expect(screen.getByTestId("synth-editor-slot-pos").textContent).toBe("1/2"));
    fireEvent.click(screen.getByTestId("synth-editor-slot-next"));
    await waitFor(() =>
      expect(screen.getByTestId("synth-editor-slot-pos").textContent).toBe("2/2"),
    );
    fireEvent.click(screen.getByTestId("synth-editor-slot-prev"));
    await waitFor(() =>
      expect(screen.getByTestId("synth-editor-slot-pos").textContent).toBe("1/2"),
    );
  });

  it("marks draft variants in the tree; the star activates them (plan 102)", async () => {
    const draft = {
      id: "syn-1",
      scope: "item",
      variant_key: "tailored",
      target_posting_id: null,
      source_refs: [{ source_key: "experience", item_id: "exp-1" }],
      source_state: [],
      payload: { description: "Drafted by the polish run" },
      voice: { language: "en" },
      status: "draft",
      source: "ai",
      verified: true,
      stale: false,
      orphaned: false,
      last_used_at: null,
      created_at: "",
    };
    fetchSynthItems.mockResolvedValue([draft]);
    renderBuilder();
    await screen.findByTestId("preview-frame");
    await openInspectorTab("context");
    fireEvent.click(screen.getByTestId("context-group-header-experience"));
    await screen.findByTestId("context-variant-syn-1");
    expect(screen.queryByTestId("context-variant-draft")).toBeNull();
    expect(screen.queryByTestId("context-variant-activate-syn-1")).toBeNull();
    fireEvent.click(await screen.findByTestId("context-pin-star-syn-1"));
    await waitFor(() =>
      expect(setSynthPin).toHaveBeenCalledWith(
        "cv-1",
        "experience",
        "exp-1",
        "syn-1",
      ),
    );
  });
});

describe("CvBuilder — plan 104 chat live sync", () => {
  it("refetches the document + preview + meta + synth rows when a chat mutation bumps the data revision", async () => {
    const { useCvBuilderLink } = await import("@/stores/cvBuilderLinkStore");
    useCvBuilderLink.setState({ dataRevision: 0 });
    renderBuilder();
    await screen.findByTestId("preview-frame");
    const initialCalls = previewCv.mock.calls.length;
    expect(initialCalls).toBeGreaterThan(0);
    const initialSynth = fetchSynthItems.mock.calls.length;
    const initialCv = fetchCv.mock.calls.length;

    act(() => {
      useCvBuilderLink.getState().notifyDataChanged();
    });
    await waitFor(
      () => expect(previewCv.mock.calls.length).toBeGreaterThan(initialCalls),
      { timeout: 3000 },
    );
    expect(fetchSynthItems.mock.calls.length).toBeGreaterThan(initialSynth);
    expect(fetchCv.mock.calls.length).toBeGreaterThan(initialCv);
  });

  it("ignores revision 0 (no chat mutation yet) and stays quiet otherwise", async () => {
    const { useCvBuilderLink } = await import("@/stores/cvBuilderLinkStore");
    useCvBuilderLink.setState({ dataRevision: 0 });
    renderBuilder();
    await screen.findByTestId("preview-frame");
    const calls = previewCv.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 450));
    expect(previewCv.mock.calls.length).toBe(calls);
  });
});

