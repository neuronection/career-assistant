import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { CvSynthLibrary } from "@/pages/CvSynthLibrary";

const fetchSynthItems = vi.fn();
const generateSynthItems = vi.fn();
const patchSynthItem = vi.fn();
const regenerateSynthItem = vi.fn();
const deleteSynthItem = vi.fn();
const createSynthItem = vi.fn();
const fetchContextSources = vi.fn();

vi.mock("@/api/cv", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/cv")>();
  return {
    ...mod,
    fetchSynthItems: (...args: unknown[]) => fetchSynthItems(...args),
    generateSynthItems: (...args: unknown[]) => generateSynthItems(...args),
    patchSynthItem: (...args: unknown[]) => patchSynthItem(...args),
    regenerateSynthItem: (...args: unknown[]) => regenerateSynthItem(...args),
    deleteSynthItem: (...args: unknown[]) => deleteSynthItem(...args),
    createSynthItem: (...args: unknown[]) => createSynthItem(...args),
    fetchContextSources: (...args: unknown[]) => fetchContextSources(...args),
  };
});

const ITEM_ID = "exp-item-1-ref";
const VARIANT_A = "55440001-0000-0000-0000-000000000001";
const VARIANT_B = "55440002-0000-0000-0000-000000000002";

async function renderLibrary() {
  const view = render(
    <MemoryRouter initialEntries={["/cv/synth"]}>
      <Routes>
        <Route path="/cv/synth" element={<CvSynthLibrary />} />
        <Route path="/cv" element={<div data-testid="studio-dest" />} />
      </Routes>
    </MemoryRouter>,
  );
  await waitFor(() =>
    expect(
      screen.queryByTestId("synth-library")?.textContent ?? "",
    ).not.toContain("Loading"),
  );
  return view;
}

// Stateful mock: every fixture list below is built from a mutable base;
// tests mutate before waiting on fetchSynthItems re-reads.
let items: unknown[] = [];

beforeEach(() => {
  items = [];
  fetchSynthItems.mockImplementation(async () => items);
  fetchContextSources.mockResolvedValue({
    sources: [
      {
        key: "experience",
        label: "Experience",
        description: "",
        items: [
          { item_id: ITEM_ID, label: "Backend Intern", detail: "Sample Corp" },
        ],
      },
    ],
  });
  generateSynthItems.mockImplementation(
    async (body: { refs: unknown[]; action: string }) => {
      items = [
        ...items,
        {
          id: VARIANT_B,
          scope: "item",
          variant_key: "default",
          target_posting_id: null,
          source_refs: body.refs,
          source_state: [{ source_key: "experience", item_id: ITEM_ID, content_hash: "h1" }],
          payload: { description: `Generated ${body.action} variant` },
          voice: { language: "en", action: body.action },
          status: "draft",
          source: "ai",
          verified: true,
          stale: false,
          orphaned: false,
          last_used_at: null,
          created_at: VARIANT_B,
        },
      ];
      return { job_id: null, items: [items[items.length - 1]] };
    },
  );
});

describe("CvSynthLibrary", () => {
  it("shows the empty state without variants", async () => {
    fetchSynthItems.mockResolvedValue([]);
    await renderLibrary();
    await waitFor(() =>
      expect(screen.getByText("No synthesized variants yet")).toBeTruthy(),
    );
  });

  it("groups variants by source item and shows badges", async () => {
    items = [
      {
        id: VARIANT_A,
        scope: "item",
        variant_key: "default",
        target_posting_id: null,
        source_refs: [{ source_key: "experience", item_id: ITEM_ID }],
        source_state: [{ source_key: "experience", item_id: ITEM_ID, content_hash: "h1" }],
        payload: { description: "Concise rewrite of the role" },
        voice: { language: "en", action: "summarize" },
        status: "active",
        source: "ai",
        verified: true,
        stale: true,
        orphaned: false,
        last_used_at: null,
        created_at: VARIANT_A,
      },
    ];
    fetchSynthItems.mockResolvedValue(items);
    await renderLibrary();
    await waitFor(() =>
      expect(screen.getByTestId(`synth-group-experience:${ITEM_ID}`)).toBeTruthy(),
    );
    expect(screen.getByTestId(`synth-variant-${VARIANT_A}`)).toBeTruthy();
    expect(screen.getByText("Source changed")).toBeTruthy();
    expect(screen.getByText("Active")).toBeTruthy();
    expect(screen.getByText("AI")).toBeTruthy();
  });

  it("generates a variant from a group with the selected action", async () => {
    items = [
      {
        id: VARIANT_A,
        scope: "item",
        variant_key: "default",
        target_posting_id: null,
        source_refs: [{ source_key: "experience", item_id: ITEM_ID }],
        source_state: [{ source_key: "experience", item_id: ITEM_ID, content_hash: "h1" }],
        payload: { description: "Original" },
        voice: { language: "en", action: "summarize" },
        status: "archived",
        source: "ai",
        verified: true,
        stale: false,
        orphaned: false,
        last_used_at: null,
        created_at: VARIANT_A,
      },
    ];
    fetchSynthItems.mockResolvedValue(items);
    await renderLibrary();
    const actionSelect = screen.getByTestId(
      "synth-action-experience:" + ITEM_ID,
    ) as HTMLSelectElement;
    await userEvent.setup().selectOptions(actionSelect, "detail");
    expect((actionSelect as HTMLSelectElement).value).toBe("detail");
    await userEvent.setup().click(
      screen.getByTestId(`synth-generate-experience:${ITEM_ID}`),
    );
    await waitFor(() => expect(generateSynthItems).toHaveBeenCalled());
    expect(generateSynthItems.mock.calls[0][0]).toMatchObject({
      action: "detail",
    });
    await waitFor(() =>
      expect(fetchSynthItems.mock.calls.length).toBeGreaterThan(1),
    );
    void within(document.body);
  });

  it("activates a draft (supersede flows through the API)", async () => {
    items = [
      {
        id: VARIANT_A,
        scope: "item",
        variant_key: "default",
        target_posting_id: null,
        source_refs: [{ source_key: "experience", item_id: ITEM_ID }],
        source_state: [{ source_key: "experience", item_id: ITEM_ID, content_hash: "h1" }],
        payload: { description: "Draft text" },
        voice: { language: "en", action: "summarize" },
        status: "draft",
        source: "ai",
        verified: true,
        stale: false,
        orphaned: false,
        last_used_at: null,
        created_at: VARIANT_A,
      },
    ];
    fetchSynthItems.mockResolvedValue(items);
    patchSynthItem.mockResolvedValue({
      ...JSON.parse(JSON.stringify(items[0])),
      status: "active",
    });
    await renderLibrary();
    await userEvent.setup().click(
      screen.getByTestId(`synth-activate-${VARIANT_A}`),
    );
    await waitFor(() => expect(patchSynthItem).toHaveBeenCalledWith(
      VARIANT_A,
      { status: "active" },
    ));
    expect(screen.getByTestId("synth-notice")).toBeTruthy();
  });

  it("archives an active variant", async () => {
    items = [
      {
        id: VARIANT_A,
        scope: "item",
        variant_key: "default",
        target_posting_id: null,
        source_refs: [{ source_key: "experience", item_id: ITEM_ID }],
        source_state: [],
        payload: { description: "Live text" },
        voice: { language: "en", action: "summarize" },
        status: "active",
        source: "ai",
        verified: true,
        stale: false,
        orphaned: false,
        last_used_at: null,
        created_at: VARIANT_A,
      },
    ];
    fetchSynthItems.mockResolvedValue(items);
    patchSynthItem.mockImplementation(async () => ({
      ...JSON.parse(JSON.stringify(items[0])),
      status: "archived",
    }));
    await renderLibrary();
    await userEvent
      .setup()
      .click(screen.getByTestId(`synth-archive-${VARIANT_A}`));
    await waitFor(() =>
      expect(patchSynthItem).toHaveBeenCalledWith(VARIANT_A, { status: "archived" }),
    );
  });

  it("regenerates only AI variants and deletes with confirmation", async () => {
    items = [
      {
        id: VARIANT_A,
        scope: "item",
        variant_key: "default",
        target_posting_id: null,
        source_refs: [{ source_key: "experience", item_id: ITEM_ID }],
        source_state: [],
        payload: { description: "AI text" },
        voice: { language: "en", action: "summarize" },
        status: "active",
        source: "ai",
        verified: true,
        stale: false,
        orphaned: false,
        last_used_at: null,
        created_at: VARIANT_A,
      },
      {
        id: VARIANT_B,
        scope: "item",
        variant_key: "default",
        target_posting_id: null,
        source_refs: [{ source_key: "experience", item_id: ITEM_ID }],
        source_state: [],
        payload: { description: "Manual text" },
        voice: { language: "en" },
        status: "archived",
        source: "manual",
        verified: true,
        stale: false,
        orphaned: false,
        last_used_at: null,
        created_at: VARIANT_B,
      },
    ];
    fetchSynthItems.mockResolvedValue(items);
    await renderLibrary();
    expect(
      screen.getByTestId(`synth-regenerate-${VARIANT_A}`),
    ).toBeTruthy();
    expect(
      screen.queryByTestId(`synth-regenerate-${VARIANT_B}`),
    ).toBeNull();

    await userEvent
      .setup()
      .click(screen.getByTestId(`synth-delete-${VARIANT_A}`));
    expect(
      within(document.body).getByText("Delete this variant?"),
    ).toBeTruthy();
    const confirmButtons = within(document.body).getAllByRole("button", {
      name: "Delete",
    });
    await userEvent.setup().click(confirmButtons[confirmButtons.length - 1]);
    await waitFor(() => expect(deleteSynthItem).toHaveBeenCalledWith(VARIANT_A));
  });

  it("edits variant text and key through the shared editor", async () => {
    items = [
      {
        id: VARIANT_A,
        scope: "item",
        variant_key: "default",
        target_posting_id: null,
        source_refs: [{ source_key: "experience", item_id: ITEM_ID }],
        source_state: [],
        payload: { description: "Old text" },
        voice: { language: "en" },
        status: "active",
        source: "manual",
        verified: true,
        stale: false,
        orphaned: false,
        last_used_at: null,
        created_at: VARIANT_A,
      },
    ];
    fetchSynthItems.mockResolvedValue(items);
    await renderLibrary();
    await userEvent.setup().click(screen.getByTestId(`synth-edit-${VARIANT_A}`));
    const text = within(document.body).getByTestId(
      "synth-editor-description-input",
    ) as HTMLTextAreaElement;
    expect(text.value).toContain("Old text");
    await userEvent.setup().type(text, " edited");
    await userEvent
      .setup()
      .click(within(document.body).getByTestId("synth-editor-save"));
    await waitFor(() =>
      expect(patchSynthItem).toHaveBeenCalledWith(
        VARIANT_A,
        expect.objectContaining({
          payload: expect.objectContaining({
            description: expect.stringContaining("edited"),
          }),
        }),
      ),
    );
  });

  it("creates a manual variant through the editor", async () => {
    fetchSynthItems.mockResolvedValue([]);
    await renderLibrary();
    await userEvent.setup().click(screen.getByTestId("synth-add-variant"));
    const text = within(document.body).getByTestId(
      "synth-editor-description-input",
    ) as HTMLTextAreaElement;
    const refCheckbox = within(document.body).getByTestId(
      `synth-editor-ref-experience:${ITEM_ID}`,
    ) as HTMLInputElement;
    await userEvent.setup().click(refCheckbox);
    await userEvent.setup().type(text, "My own tailored text");
    await userEvent
      .setup()
      .click(within(document.body).getByTestId("synth-editor-save"));
    await waitFor(() => expect(createSynthItem).toHaveBeenCalled());
    expect(createSynthItem.mock.calls[0][0]).toMatchObject({
      refs: [{ source_key: "experience", item_id: ITEM_ID }],
      payload: { description: "My own tailored text", bullets: [] },
      voice: { language: "en" },
    });
  });

  it("disables creation without any text", async () => {
    fetchSynthItems.mockResolvedValue([]);
    await renderLibrary();
    await userEvent.setup().click(screen.getByTestId("synth-add-variant"));
    const save = within(document.body).getByTestId(
      "synth-editor-save",
    ) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
  });
});
