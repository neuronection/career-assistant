import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { TemplateGallery, galleryFilter } from "@/components/cv/TemplateGallery";
import type { CvTemplateSummary } from "@/types/cvTemplate";

vi.mock("@/api/cvTemplates", () => ({
  fetchTemplates: vi.fn(() => Promise.resolve([
    baseTemplate,
    sidebarTemplate,
  ])),
  fetchTemplatePreview: vi.fn(() => Promise.resolve("<h1>Sample</h1>")),
  fetchTemplatePreviewWith: vi.fn(() =>
    Promise.resolve({ html: "<h1>Sample</h1>", metrics: { estimated_pages: 1 } })
  ),
}));

const onUse = vi.fn();
const onClose = vi.fn();

const baseTemplate = {
  id: "tpl-1",
  key: "ats-classic",
  version: 3,
  title: "Classic Serif",
  description: "Serif stack",
  author_key: "bank",
  source: "bank",
  visibility: "private",
  language: "en",
  page_size: "a4",
  ats_safe: true,
  status: "published",
  content_hash: "h1",
  content: {
    blocks: [{ kind: "header" }],
    design: { accent_color: "#1d4ed8", font_stack: "sans" },
    pages: { default_max_pages: 1, overflow_policy: "warn" },
    prompts: {},
  },
} as unknown as CvTemplateSummary;

const sidebarTemplate = {
  ...baseTemplate,
  id: "tpl-2",
  title: "Dark Sidebar",
  ats_safe: false,
  content: {
    ...baseTemplate.content,
    design: { ...baseTemplate.content.design, layout: "sidebar", sidebar_color: "#16324f" },
    pages: { default_max_pages: 2, overflow_policy: "warn" },
  },
} as unknown as CvTemplateSummary;

describe("gallery filter predicates", () => {
  it("derives layout / page-count / ATS filters from the template content", () => {
    expect(galleryFilter(baseTemplate, "all")).toBe(true);
    expect(galleryFilter(baseTemplate, "single")).toBe(true);
    expect(galleryFilter(baseTemplate, "sidebar")).toBe(false);
    expect(galleryFilter(baseTemplate, "one-page")).toBe(true);
    expect(galleryFilter(baseTemplate, "ats-safe")).toBe(true);
    expect(galleryFilter(sidebarTemplate, "sidebar")).toBe(true);
    expect(galleryFilter(sidebarTemplate, "single")).toBe(false);
    expect(galleryFilter(sidebarTemplate, "one-page")).toBe(false);
    expect(galleryFilter(sidebarTemplate, "ats-safe")).toBe(false);
  });
});

describe("TemplateGallery filters + compare", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("filters the grid by chip and shows the empty filter state", async () => {
    render(
      <MemoryRouter>
        <TemplateGallery
          open
          onClose={onClose}
          actionLabel="Use for new CV"
          onUse={onUse}
        />
      </MemoryRouter>
    );
    const sidebarChip = await screen.findByTestId("gallery-filter-sidebar");
    fireEvent.click(sidebarChip);
    expect(await screen.getAllByTestId("template-card")).toHaveLength(1);
    fireEvent.click(screen.getByTestId("gallery-filter-all"));
    expect(await screen.findByTestId("gallery-grid")).toBeInTheDocument();
  });

  it("selects two templates and opens the compare preview", async () => {
    render(
      <MemoryRouter>
        <TemplateGallery
          open
          onClose={onClose}
          actionLabel="Use for new CV"
          onUse={onUse}
        />
      </MemoryRouter>
    );
    await screen.findByTestId("gallery-grid");
    fireEvent.click(screen.getByTestId("compare-template-tpl-1"));
    fireEvent.click(screen.getByTestId("compare-template-tpl-2"));
    expect(screen.getByTestId("compare-tray")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("compare-open"));
    const grid = await screen.findByTestId("compare-grid");
    expect(grid).toHaveTextContent("Classic Serif");
    expect(grid).toHaveTextContent("Dark Sidebar");
    fireEvent.click(screen.getByTestId("compare-use-tpl-2"));
    await waitFor(() => expect(onUse).toHaveBeenCalled());
    expect(onClose).toHaveBeenCalled();
  });
});
