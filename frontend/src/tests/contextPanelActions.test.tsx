import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { ContextPanel } from "@/components/cv/ContextPanel";
import type { CvContextSourceOut } from "@/types/cv";

const sources: CvContextSourceOut[] = [
  {
    key: "experience",
    label: "Experience",
    description: "",
    items: [{ item_id: "exp-1", label: "DevOps intern", detail: "Acme" }],
  },
  {
    key: "certifications",
    label: "Certifications",
    description: "",
    items: [{ item_id: "c1", label: "AWS SA", detail: "" }],
  },
  {
    key: "skills",
    label: "Skills",
    description: "",
    items: [{ item_id: "sk-1", label: "Python", detail: "programming" }],
  },
  {
    key: "languages",
    label: "Languages",
    description: "",
    items: [{ item_id: "lang-1", label: "English", detail: "" }],
  },
  { key: "volunteer", label: "Volunteering", description: "", items: [] },
];

function renderPanel(overrides: {
  onAddItem?: (sourceKey: string) => void;
  onEditItem?: (sourceKey: string, itemId: string) => void;
  onAddVariant?: (sourceKey: string) => void;
} = {}) {
  const onToggle = vi.fn();
  const onToggleGroup = vi.fn();
  render(
    <MemoryRouter>
      <ContextPanel
        sources={sources}
        selected={new Set(["experience:exp-1"])}
        onToggle={onToggle}
        onToggleGroup={onToggleGroup}
        onAddItem={overrides.onAddItem}
        onEditItem={overrides.onEditItem}
        onAddVariant={overrides.onAddVariant}
      />
    </MemoryRouter>
  );
  return { onToggle, onToggleGroup };
}

describe("ContextPanel — plan 105 entity affordances", () => {
  it("shows a create button only for sources with an editor", () => {
    renderPanel({ onAddItem: vi.fn() });
    expect(screen.getByTestId("context-add-experience")).toBeInTheDocument();
    expect(screen.getByTestId("context-add-certifications")).toBeInTheDocument();
    expect(screen.getByTestId("context-add-skills")).toBeInTheDocument();
    expect(screen.queryByTestId("context-add-languages")).toBeNull();
  });

  it("links card-backed groups to their profile section", () => {
    renderPanel();
    expect(
      screen
        .getByTestId("context-open-group-languages")
        .getAttribute("href")
    ).toBe("/profile#academics");
    expect(
      screen.getByTestId("context-open-group-skills").getAttribute("href")
    ).toBe("/profile#skills");
    expect(screen.queryByTestId("context-open-group-experience")).toBeNull();
  });

  it("edits and opens the profile entry behind focusable rows", () => {
    const onEditItem = vi.fn();
    renderPanel({ onEditItem });
    fireEvent.click(screen.getByTestId("context-edit-item-experience:exp-1"));
    expect(onEditItem).toHaveBeenCalledWith("experience", "exp-1");
    expect(
      screen
        .getByTestId("context-open-item-experience:exp-1")
        .getAttribute("href")
    ).toBe("/profile/experience?focus=exp-1");
    expect(
      screen
        .getByTestId("context-open-item-certifications:c1")
        .getAttribute("href")
    ).toBe("/profile/education?entity=certifications&focus=c1");
  });

  it("keeps card-backed rows action-free", () => {
    renderPanel();
    expect(screen.queryByTestId("context-edit-item-skills:sk-1")).toBeNull();
    expect(screen.queryByTestId("context-open-item-skills:sk-1")).toBeNull();
    expect(screen.queryByTestId("context-edit-item-languages:lang-1")).toBeNull();
  });

  it("offers create from an empty group body", () => {
    const onAddItem = vi.fn();
    renderPanel({ onAddItem });
    fireEvent.click(screen.getByTestId("context-add-empty-volunteer"));
    expect(onAddItem).toHaveBeenCalledWith("volunteer");
  });

  it("keeps the variant affordance and the switch intact", () => {
    const onAddVariant = vi.fn();
    const { onToggle } = renderPanel({ onAddVariant });
    expect(screen.getByTestId("ai-add-variant-exp-1")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("context-toggle-experience:exp-1"));
    expect(onToggle).toHaveBeenCalledWith("experience", "exp-1");
  });
});
