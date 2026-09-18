import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

import { MessageProposals } from "@/components/chat/MessageProposals";
import { ProposalPreviewModal } from "@/components/chat/ProposalPreviewModal";
import type {
  ChatMessage,
  ProfileProposalCardData,
} from "@/types";
import type { ProfileProposalPreviewData } from "@/api/profileProposals";
import { useProfileProposalsStore } from "@/stores/profileProposalsStore";

const listApi = vi.hoisted(() => vi.fn());
vi.mock("@/api/profileProposals", () => ({
  approveProfileProposal: vi.fn(),
  rejectProfileProposal: vi.fn(),
  fetchProfileProposals: () => listApi(),
  dismissProfileProposal: vi.fn(),
  getProposalPreview: vi.fn(),
  revertProfileProposal: vi.fn(),
}));

function messageWith(cards: ProfileProposalCardData[]): ChatMessage {
  return {
    id: "m1",
    role: "assistant",
    content: "",
    parent_id: "u1",
    metadata_json: { proposals: cards },
    created_at: "2026-09-18T09:00:00Z",
  };
}

function seedPreview(id: string, data: ProfileProposalPreviewData) {
  useProfileProposalsStore.setState({
    previews: { [id]: { state: "ready", data } },
  });
}

const VARIANT_CARD: ProfileProposalCardData = {
  id: "prop-v",
  kind: "cv_synth",
  action: "create",
  status: "approved",
  title: "Add CV variants · Siemens internship (+2) · restyle",
  entity_id: null,
  entity_label: "Siemens internship (+2) · restyle",
  diff: [
    {
      field: "refs",
      label: "Items",
      before: null,
      after: [
        {
          label: "Siemens internship",
          source_key: "experience",
          item_id: "i1",
        },
      ],
    },
    { field: "action", label: "Action", before: null, after: "restyle" },
  ],
  destructive: false,
  source: "chat",
  created_at: "2026-09-18T09:00:00Z",
};

const SYNTH_PREVIEW: ProfileProposalPreviewData = {
  before: [
    {
      source_key: "experience",
      item_id: "i1",
      label: "Siemens internship",
      snapshot: {
        title: "Siemens internship",
        kind: "internship",
        org_name: "Siemens",
        start: "2025-09-01",
        open_ended: true,
        status: "active",
        description: "Kept the systems online.",
      },
    },
    {
      source_key: "education",
      item_id: "e1",
      label: "BSc Informatics",
      snapshot: {
        institution: "TU Munich",
        program: "BSc Informatics",
        level: "bachelor",
        in_progress: true,
        focus_subjects: ["machine learning", "databases"],
        description: "Studied distributed systems and Algo Labs.",
      },
    },
  ],
  after: null,
  edits: {
    kind: "cv_synth",
    action: "restyle",
    language: "en",
    resolved_refs: [
      { label: "Siemens internship", source_key: "experience", item_id: "i1" },
    ],
  },
};

const DELETE_PREVIEW: ProfileProposalPreviewData = {
  before: {
    name: "AWS Practitioner",
    issuer: "Amazon",
    issued: "2024-03-15",
    expires: "2027-03-15",
    description: "Renewed twice.",
  },
  after: null,
  edits: {},
};

function snapshotProposal(
  kind: string,
  action = "delete",
): ProfileProposalCardData {
  return {
    ...VARIANT_CARD,
    id: `prop-${kind}`,
    kind,
    action,
    title: `Delete ${kind}`,
  };
}

describe("plan-101 cv_synth card + preview", () => {
  beforeEach(() => {
    listApi.mockReset().mockResolvedValue({ proposals: [], pending_count: 0 });
    useProfileProposalsStore.setState({ previews: {} });
  });

  it("renders structured ref chips, not raw uuid strings", () => {
    render(<MessageProposals message={messageWith([VARIANT_CARD])} />);
    expect(screen.getByText("Siemens internship")).toBeInTheDocument();
    expect(screen.queryByText(/experience:/)).not.toBeInTheDocument();
    expect(
      screen.getByText("Add CV variants · Siemens internship (+2) · restyle"),
    ).toBeInTheDocument();
  });

  it("variant cards get no revert row even when approved", () => {
    useProfileProposalsStore.setState({
      overrides: {
        "prop-v": { status: "approved" },
      },
    });
    render(<MessageProposals message={messageWith([{ ...VARIANT_CARD }])} />);
    expect(screen.queryByTestId("hitl-revert-prop-v")).not.toBeInTheDocument();
  });

  it("the modal branches on KIND: stacked sources, note, no tabs", () => {
    seedPreview("prop-v", SYNTH_PREVIEW);
    render(
      <ProposalPreviewModal
        proposal={{ ...VARIANT_CARD, status: "pending" }}
        onClose={() => {}}
      />,
    );
    expect(
      screen.getByTestId("hitl-preview-sources-heading"),
    ).toHaveTextContent("What the variant drafts from");
    expect(screen.getByTestId("hitl-preview-source-experience")).toBeInTheDocument();
    expect(screen.getByTestId("hitl-preview-source-education")).toBeInTheDocument();
    expect(
      screen.getByTestId("hitl-preview-source-education"),
    ).toHaveTextContent("BSc Informatics");
    expect(screen.getByTestId("hitl-preview-variant-note")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });

  it("education snapshot rows use field labels and focus-subject chips", () => {
    seedPreview("prop-v", SYNTH_PREVIEW);
    render(
      <ProposalPreviewModal
        proposal={{ ...VARIANT_CARD, status: "pending" }}
        onClose={() => {}}
      />,
    );
    expect(screen.getByTestId("hitl-preview-field-institution")).toHaveTextContent(
      "Institution",
    );
    expect(screen.getByTestId("hitl-preview-value-in_progress")).toHaveTextContent(
      "Yes",
    );
    expect(screen.getByTestId("hitl-preview-value-focus_subjects")).toHaveTextContent(
      /machine learning\s*databases/,
    );
  });

  it("label-only rows (deleted source) degrade without crashing", () => {
    seedPreview("prop-v", {
      ...SYNTH_PREVIEW,
      before: [
        {
          source_key: "education",
          item_id: "e2",
          label: "Unknown item (education)",
          snapshot: null,
        },
      ],
    });
    render(
      <ProposalPreviewModal
        proposal={{ ...VARIANT_CARD, status: "pending" }}
        onClose={() => {}}
      />,
    );
    expect(
      screen.getByTestId("hitl-preview-source-education"),
    ).toHaveTextContent("Unknown item (education)");
    expect(
      screen.getByText(
        "Source was deleted since this card was made — shown by label only.",
      ),
    ).toBeInTheDocument();
  });

  it("delete previews render the certification snapshot card", () => {
    seedPreview("prop-certification", DELETE_PREVIEW);
    render(
      <ProposalPreviewModal
        proposal={snapshotProposal("certification", "delete")}
        onClose={() => {}}
      />,
    );
    expect(
      screen.getByTestId("hitl-preview-value-name"),
    ).toHaveTextContent("AWS Practitioner");
  });

  it("month-year formatting and highlight marks ride the snapshot card", () => {
    seedPreview("prop-certification", DELETE_PREVIEW);
    render(
      <ProposalPreviewModal
        proposal={snapshotProposal("certification", "delete")}
        onClose={() => {}}
      />,
    );
    expect(screen.getByTestId("hitl-preview-value-issued")).toHaveTextContent(
      "March 2024",
    );
  });
});

describe("plan-101 education preview highlight", () => {
  beforeEach(() => {
    listApi.mockReset().mockResolvedValue({ proposals: [], pending_count: 0 });
    useProfileProposalsStore.setState({ previews: {} });
  });

  it("marks the appended sentence in the after-side education card", () => {
    const editPreview: ProfileProposalPreviewData = {
      before: {
        institution: "TU Munich",
        program: "BSc Informatics",
        description: "Studied distributed systems.",
      },
      after: {
        institution: "TU Munich",
        program: "BSc Informatics",
        description: "Studied distributed systems.\nAlgo Labs focus.",
      },
      edits: {
        text_edits: [
          { field: "description", op: "append", text: "Algo Labs focus." },
        ],
      },
    };
    seedPreview("prop-education_item", editPreview);
    render(
      <ProposalPreviewModal
        proposal={snapshotProposal("education_item", "update")}
        onClose={() => {}}
      />,
    );
    const marks = screen.getAllByTestId("hitl-highlight");
    expect(marks.map((m) => m.textContent)).toContain("Algo Labs focus.");
  });
});
