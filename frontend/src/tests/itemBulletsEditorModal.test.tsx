import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { ItemBulletsEditorModal } from "@/components/cv/ItemBulletsEditorModal";

const BASE = [{ text: "Shipped the QA harness" }];
const OVERRIDE = [{ text: "Cut the deploy pipeline to minutes" }];

function mount(
  props: Partial<Parameters<typeof ItemBulletsEditorModal>[0]> = {}
) {
  const onSave = vi.fn();
  const onReset = vi.fn();
  const onClose = vi.fn();
  const onProposalConsumed = vi.fn();
  render(
    <MemoryRouter>
      <ItemBulletsEditorModal
        sourceKey="experience"
        itemId="exp-1"
        head={{ title: "DevOps intern", org: "Acme" }}
        base={BASE}
        override={null}
        proposal={null}
        onProposalConsumed={onProposalConsumed}
        onSave={onSave}
        onReset={onReset}
        onClose={onClose}
        {...props}
      />
    </MemoryRouter>
  );
  return { onSave, onReset, onClose, onProposalConsumed };
}

describe("ItemBulletsEditorModal", () => {
  it("renders the rendered head, the resolved list and no edited chip", () => {
    mount();
    expect(screen.getByTestId("bullets-editor-head")).toHaveTextContent(
      "DevOps intern · Acme"
    );
    expect(screen.getByTestId("bullets-row-0")).toHaveValue(
      "Shipped the QA harness"
    );
    expect(screen.queryByTestId("bullets-edited-chip")).toBeNull();
    expect(screen.queryByTestId("bullets-editor-reset")).toBeNull();
  });

  it("prefers the override over the base and marks the item edited", () => {
    mount({ override: OVERRIDE });
    expect(screen.getByTestId("bullets-row-0")).toHaveValue(
      "Cut the deploy pipeline to minutes"
    );
    expect(screen.getByTestId("bullets-edited-chip")).toBeInTheDocument();
    expect(screen.getByTestId("bullets-editor-reset")).toBeInTheDocument();
  });

  it("saves trimmed entries and reorder works", async () => {
    const user = userEvent.setup();
    const { onSave } = mount({ base: [] });
    await user.type(screen.getByTestId("bullets-row-0"), "  First bullet  ");
    await user.click(screen.getByTestId("bullets-add"));
    await user.type(screen.getByTestId("bullets-row-1"), "Second bullet");
    await user.click(screen.getByTestId("bullets-up-1"));
    await user.click(screen.getByTestId("bullets-editor-save"));
    expect(onSave).toHaveBeenCalledWith([
      { text: "Second bullet" },
      { text: "First bullet" },
    ]);
  });

  it("reset restores the base and removes the override", async () => {
    const user = userEvent.setup();
    const { onReset } = mount({ override: OVERRIDE });
    await user.click(screen.getByTestId("bullets-editor-reset"));
    const confirms = screen.getAllByRole("button", {
      name: "Reset to profile",
    });
    await user.click(confirms[confirms.length - 1]);
    expect(onReset).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("bullets-row-0")).toHaveValue(
      "Shipped the QA harness"
    );
  });

  it("confirms proposals into the list and consumes them", async () => {
    const user = userEvent.setup();
    const { onProposalConsumed } = mount({
      proposal: { bullets: ["Proposed bullet"] },
    });
    expect(screen.getByTestId("bullet-chip-0")).toHaveTextContent(
      "Proposed bullet"
    );
    await user.click(screen.getByTestId("bullet-chips-confirm"));
    expect(onProposalConsumed).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("bullets-row-1")).toHaveValue("Proposed bullet");
  });

  it("discarding proposals consumes them without writing", async () => {
    const user = userEvent.setup();
    const { onProposalConsumed, onSave } = mount({
      override: OVERRIDE,
      proposal: { bullets: ["Proposed bullet"] },
    });
    await user.click(screen.getByTestId("bullet-chips-discard"));
    expect(onProposalConsumed).toHaveBeenCalledTimes(1);
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByTestId("bullets-row-0")).toHaveValue(
      "Cut the deploy pipeline to minutes"
    );
  });

  it("guards closing with unsaved edits behind a discard confirm", async () => {
    const user = userEvent.setup();
    const { onClose } = mount();
    await user.type(screen.getByTestId("bullets-row-0"), "!");
    await user.click(screen.getByTestId("bullets-editor-cancel"));
    expect(onClose).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Discard" }));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("generate-fill loads the AI draft as chips (plan 106 slice 5)", async () => {
    const user = userEvent.setup();
    const onGenerate = vi.fn().mockResolvedValue(["Drafted bullet A"]);
    mount({ base: [], onGenerate });
    await user.click(screen.getByTestId("bullets-editor-generate"));
    await waitFor(() =>
      expect(screen.getByTestId("bullet-chip-0")).toHaveTextContent(
        "Drafted bullet A"
      )
    );
    expect(onGenerate).toHaveBeenCalledTimes(1);
    await user.click(screen.getByTestId("bullet-chips-confirm"));
    expect(screen.getByTestId("bullets-row-0")).toHaveValue("Drafted bullet A");
    expect(screen.queryByTestId("bullet-chip-0")).toBeNull();
  });

  it("generate is dirty-guarded when the editor has unsaved edits", async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    const onGenerate = vi.fn().mockResolvedValue(["Drafted bullet A"]);
    mount({ base: BASE, onGenerate });
    await user.type(screen.getByTestId("bullets-row-0"), "!");
    await user.click(screen.getByTestId("bullets-editor-generate"));
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(onGenerate).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });
});
