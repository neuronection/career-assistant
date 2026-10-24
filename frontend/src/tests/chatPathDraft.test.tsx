import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { MessagePathDraft } from "@/features/chat/components/chat/PathDraftCard";
import * as pathsApi from "@/api/paths";
import type { ChatMessage, ChatPathDraftMeta } from "@/types";

vi.mock("@/api/paths", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/api/paths")>();
  return { ...mod, createPath: vi.fn() };
});

function message(meta: ChatPathDraftMeta | null): ChatMessage {
  return {
    id: "m1",
    role: "assistant",
    content: "Here is a draft route.",
    metadata_json: meta ? { path_draft: meta } : null,
    created_at: "2026-10-24T00:00:00Z",
  };
}

const META: ChatPathDraftMeta = {
  draft: {
    title: "Route to Data Scientist",
    description: "Study then enter.",
    job_code: "data-scientist",
    job_title: "Data Scientist",
    steps: [
      { kind: "education", label: "Bachelor", education_level: "bachelor" },
      { kind: "experience", label: "Projects", skill_key: "python" },
      {
        kind: "certification",
        label: "Entry certificate",
        optional: true,
        parent: 1,
        edge_label: "or: certificate route",
      },
      { kind: "job", label: "Junior role" },
    ],
  },
  proposed_job: null,
  note: "Grounded against the published catalog.",
};

describe("MessagePathDraft", () => {
  beforeEach(() => {
    vi.mocked(pathsApi.createPath).mockClear();
  });

  it("renders nothing without a draft", () => {
    const { container } = render(<MessagePathDraft message={message(null)} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the embedded review preview with the branch", () => {
    render(
      <MemoryRouter>
        <MessagePathDraft message={message(META)} />
      </MemoryRouter>
    );
    expect(screen.getByTestId("path-draft-card")).toHaveTextContent("Route to Data Scientist");
    expect(screen.getByTestId("path-renderer")).toBeInTheDocument();
    expect(screen.getByTestId("path-step-list-d2")).toHaveTextContent("or: certificate route");
    expect(screen.getByTestId("path-draft-save")).toBeInTheDocument();
  });

  it("saves the draft as a review-first user path", async () => {
    vi.mocked(pathsApi.createPath).mockResolvedValue({} as never);
    render(
      <MemoryRouter>
        <MessagePathDraft message={message(META)} />
      </MemoryRouter>
    );
    const user = userEvent.setup();
    await user.click(screen.getByTestId("path-draft-save"));
    await waitFor(() =>
      expect(pathsApi.createPath).toHaveBeenCalledWith({
        job_ref: "data-scientist",
        title: "Route to Data Scientist",
        description: "Study then enter.",
        steps: [
          {
            kind: "education",
            label: "Bachelor",
            skill_key: undefined,
            family_key: undefined,
            education_level: "bachelor",
            optional: false,
            parent: undefined,
            edge_label: undefined,
          },
          {
            kind: "experience",
            label: "Projects",
            skill_key: "python",
            family_key: undefined,
            education_level: undefined,
            optional: false,
            parent: undefined,
            edge_label: undefined,
          },
          {
            kind: "certification",
            label: "Entry certificate",
            skill_key: undefined,
            family_key: undefined,
            education_level: undefined,
            optional: true,
            parent: 1,
            edge_label: "or: certificate route",
          },
          {
            kind: "job",
            label: "Junior role",
            skill_key: undefined,
            family_key: undefined,
            education_level: undefined,
            optional: false,
            parent: undefined,
            edge_label: undefined,
          },
        ],
      })
    );
    expect(await screen.findByTestId("path-draft-saved")).toBeInTheDocument();
    expect(screen.queryByTestId("path-draft-save")).not.toBeInTheDocument();
  });

  it("reports a failed save honestly", async () => {
    vi.mocked(pathsApi.createPath).mockRejectedValue(new Error("boom"));
    render(
      <MemoryRouter>
        <MessagePathDraft message={message(META)} />
      </MemoryRouter>
    );
    const user = userEvent.setup();
    await user.click(screen.getByTestId("path-draft-save"));
    expect(await screen.findByTestId("path-draft-error")).toBeInTheDocument();
    expect(screen.getByTestId("path-draft-save")).toBeInTheDocument();
  });
});
