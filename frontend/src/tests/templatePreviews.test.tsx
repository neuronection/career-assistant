import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  LiveTemplatePreviews,
  MessageTemplatePreviews,
} from "@/components/chat/TemplatePreviews";
import { useTemplatePreviewsStore } from "@/stores/templatePreviewsStore";
import type { ChatMessage, ChatTemplatePreview } from "@/types";

const PREVIEW: ChatTemplatePreview = {
  template_id: "t-1",
  title: "ATS Classic",
  url: "/api/v1/cv/templates/t-1/preview.png",
};

const PREVIEW_2: ChatTemplatePreview = {
  template_id: "t-2",
  title: "Modern Two-Column",
  url: "/api/v1/cv/templates/t-2/preview.png",
};

function messageWith(previews: ChatTemplatePreview[]): ChatMessage {
  return {
    id: "m1",
    role: "assistant",
    content: "Here is what they look like.",
    parent_id: "u1",
    metadata_json: { template_previews: previews },
    created_at: "2026-09-15T12:00:00Z",
  };
}

describe("template previews (plan 83)", () => {
  beforeEach(() => {
    useTemplatePreviewsStore.setState({ live: [] });
  });

  it("renders persisted metadata as a thumbnail strip", () => {
    render(<MessageTemplatePreviews message={messageWith([PREVIEW, PREVIEW_2])} />);
    const strip = screen.getByTestId("template-previews");
    expect(strip).toBeInTheDocument();
    const images = strip.querySelectorAll("img");
    expect(images).toHaveLength(2);
    expect(images[0].getAttribute("src")).toBe(PREVIEW.url);
    expect(images[1].getAttribute("src")).toBe(PREVIEW_2.url);
  });

  it("renders nothing without previews", () => {
    const { container } = render(<MessageTemplatePreviews message={messageWith([])} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the live strip from the store, deduped by template", () => {
    const store = useTemplatePreviewsStore.getState();
    store.receiveLive(PREVIEW);
    store.receiveLive(PREVIEW);
    store.receiveLive(PREVIEW_2);
    render(<LiveTemplatePreviews />);
    expect(screen.getAllByRole("img")).toHaveLength(2);
    store.reset();
    useTemplatePreviewsStore.setState({ live: [] });
    expect(screen.getByTestId("template-previews").querySelectorAll("img")).toHaveLength(
      2,
    );
  });
});
