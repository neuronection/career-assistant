import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { MessageProposals, ProposalCards } from "@/components/chat/MessageProposals";
import type { ChatMessage, ProfileProposalCardData } from "@/types";

const approveApi = vi.hoisted(() => vi.fn());
const rejectApi = vi.hoisted(() => vi.fn());
const listApi = vi.hoisted(() => vi.fn());
const previewApi = vi.hoisted(() => vi.fn());
const revertApi = vi.hoisted(() => vi.fn());

vi.mock("@/api/profileProposals", () => ({
  approveProfileProposal: (id: string) => approveApi(id),
  rejectProfileProposal: (id: string) => rejectApi(id),
  fetchProfileProposals: () => listApi(),
  dismissProfileProposal: vi.fn(),
  getProposalPreview: (id: string) => previewApi(id),
  revertProfileProposal: (id: string) => revertApi(id),
}));

import { useProfileProposalsStore } from "@/stores/profileProposalsStore";

const CARD: ProfileProposalCardData = {
  id: "prop-1",
  kind: "experience_item",
  action: "update",
  status: "pending",
  title: "Update experience · Siemens internship",
  entity_id: "item-1",
  entity_label: "Siemens internship",
  diff: [
    { field: "end", label: "End date", before: null, after: "2026-06-30" },
    { field: "hours_per_week", label: "Hours per week", before: 35, after: 20 },
  ],
  destructive: false,
  source: "chat",
  created_at: "2026-09-14T12:00:00Z",
};

function messageWith(cards: ProfileProposalCardData[], dropped = 0): ChatMessage {
  return {
    id: "m1",
    role: "assistant",
    content: "I've prepared the changes",
    parent_id: "u1",
    metadata_json: {
      proposals: cards,
      proposals_dropped: dropped,
    },
    created_at: "2026-09-14T12:00:00Z",
  };
}

function resetStore() {
  useProfileProposalsStore.setState({
    live: [],
    overrides: {},
    pendingCount: 0,
    pendingBySession: {},
    lastResolved: null,
    lastFollowupKey: null,
    previews: {},
  });
}

const LIVE_CARD: ProfileProposalCardData = {
  ...CARD,
  chat_session_id: "s1",
};

describe("MessageProposals / ProposalCards", () => {
  beforeEach(() => {
    resetStore();
    approveApi.mockReset();
    rejectApi.mockReset();
    revertApi.mockReset();
    previewApi.mockReset();
    listApi.mockReset().mockResolvedValue({ proposals: [], pending_count: 0 });
  });

  it("renders persisted cards with their diff rows", () => {
    render(<MessageProposals message={messageWith([CARD])} />);
    expect(screen.getByTestId("hitl-cards")).toBeInTheDocument();
    expect(
      screen.getByText("Update experience · Siemens internship"),
    ).toBeInTheDocument();
    expect(screen.getByText("End date")).toBeInTheDocument();
    expect(screen.getByText("2026-06-30")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
  });

  it("renders nothing without proposals", () => {
    const { container } = render(
      <MessageProposals message={messageWith([])} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("approve resolves through the store and flips the card", async () => {
    const user = userEvent.setup();
    approveApi.mockResolvedValue({
      proposal: { ...CARD, status: "approved" },
      applied: { id: "item-1", kind: "experience_item", label: "Siemens" },
      already: false,
    });
    render(<MessageProposals message={messageWith([CARD])} />);
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(approveApi).toHaveBeenCalledWith("prop-1");
    await waitFor(() => {
      expect(screen.getByText("Approved")).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("a 409 conflict flips the card to the conflict state with the detail", async () => {
    const user = userEvent.setup();
    approveApi.mockRejectedValue({
      response: { data: { detail: "Changed since it was proposed — review the updated diff" } },
    });
    render(<MessageProposals message={messageWith([CARD])} />);
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => {
      expect(screen.getByText("Changed since proposed")).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("destructive cards arm a confirm before approving", async () => {
    const user = userEvent.setup();
    const destructive: ProfileProposalCardData = { ...CARD, action: "delete", destructive: true };
    render(<MessageProposals message={messageWith([destructive])} />);
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(approveApi).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Confirm delete" })).toBeInTheDocument();
    approveApi.mockResolvedValue({
      proposal: { ...destructive, status: "approved" },
      applied: null,
      already: false,
    });
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));
    expect(approveApi).toHaveBeenCalledWith("prop-1");
  });

  it("reject keeps the card visible in the rejected state", async () => {
    const user = userEvent.setup();
    rejectApi.mockResolvedValue({
      proposal: { ...CARD, status: "rejected" },
      applied: null,
    });
    render(<MessageProposals message={messageWith([CARD])} />);
    await user.click(screen.getByRole("button", { name: "Reject" }));
    expect(rejectApi).toHaveBeenCalledWith("prop-1");
    await waitFor(() => {
      expect(screen.getByText("Rejected")).toBeInTheDocument();
    });
  });

  it("create cards render a field summary instead of a before/after diff", () => {
    const created: ProfileProposalCardData = {
      ...CARD,
      action: "create",
      title: "Add experience · Desktop Assistant",
      diff: [
        { field: "title", label: "Title", before: null, after: "Desktop Assistant" },
        { field: "kind", label: "Type", before: null, after: "project" },
        { field: "org_name", label: "Organization", before: null, after: "" },
        { field: "end", label: "End date", before: null, after: null },
      ],
    };
    const { container } = render(<MessageProposals message={messageWith([created])} />);
    expect(container.querySelector('[data-as="hitl-field-summary"]')).not.toBeNull();
    expect(screen.getByText("Desktop Assistant")).toBeInTheDocument();
    expect(screen.getByText("project")).toBeInTheDocument();
    expect(screen.queryByText("Organization")).not.toBeInTheDocument();
    expect(screen.queryByText("End date")).not.toBeInTheDocument();
    expect(container.querySelector('[data-as="text-diff-view"]')).toBeNull();
  });

  it("variant cards use the draft-variants labels (plan 82A)", async () => {
    const user = userEvent.setup();
    const card: ProfileProposalCardData = {
      ...CARD,
      kind: "cv_synth",
      action: "create",
      title: "Add CV variants · 2 item(s) · summarize",
      diff: [
        {
          field: "refs",
          label: "Items",
          before: null,
          after: ["projects:p-1", "experience:p-2"],
        },
        { field: "action", label: "Action", before: null, after: "summarize" },
      ],
    };
    approveApi.mockResolvedValue({
      proposal: { ...card, status: "approved" },
      applied: { queued: false, kind: "cv_synth", items: [{ id: "v1" }] },
      already: false,
    });
    render(<MessageProposals message={messageWith([card])} />);
    expect(screen.getByText("projects:p-1")).toBeInTheDocument();
    expect(screen.getByText("experience:p-2")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Draft variants" }));
    expect(approveApi).toHaveBeenCalledWith("prop-1");
    await waitFor(() => {
      expect(
        screen.getByText("Activated — see the Synth Library"),
      ).toBeInTheDocument();
    });
  });

  it("live cards render through the same stack", async () => {
    useProfileProposalsStore.setState({ live: [CARD] });
    render(<ProposalCards cards={useProfileProposalsStore.getState().live} />);
    expect(
      screen.getByText("Update experience · Siemens internship"),
    ).toBeInTheDocument();
  });

  it("shows the dropped-ops note", () => {
    render(<MessageProposals message={messageWith([CARD], 2)} />);
    expect(screen.getByTestId("hitl-dropped-note")).toHaveTextContent(
      /2 suggestion/,
    );
  });

  it("shows the drop reasons under the note", () => {
    const msg = messageWith([], 1);
    msg.metadata_json!.proposals_dropped_reasons = [
      {
        kind: "experience_item",
        reason: "end is required unless open_ended",
      },
    ];
    render(<MessageProposals message={msg} />);
    expect(screen.getByTestId("hitl-dropped-reasons")).toHaveTextContent(
      "experience_item: end is required unless open_ended",
    );
  });

  it("the plan-99 reason codes get friendly copy", () => {
    const msg = messageWith([], 1);
    msg.metadata_json!.proposals_dropped_reasons = [
      {
        kind: "experience_item",
        reason:
          "unread_target: the full content of experience_item was not read this turn",
      },
    ];
    render(<MessageProposals message={msg} />);
    expect(screen.getByTestId("hitl-dropped-reasons")).toHaveTextContent(
      "read-before-edit guard",
    );
  });

  it("pipeline profile_op_errors render as the same note family (99.3)", () => {
    const msg = messageWith([], 1);
    msg.metadata_json!.profile_op_errors = [
      { kind: "experience_item", code: "anchor_mismatch" },
    ];
    render(<MessageProposals message={msg} />);
    expect(screen.getByTestId("hitl-dropped-reasons")).toHaveTextContent(
      "the quoted text no longer matches the current content",
    );
  });
});

describe("proposal preview + revert (plan 99.6)", () => {
  beforeEach(() => {
    resetStore();
    approveApi.mockReset();
    rejectApi.mockReset();
    revertApi.mockReset();
    previewApi.mockReset();
    listApi.mockReset().mockResolvedValue({ proposals: [], pending_count: 0 });
  });

  const SNAPSHOT = {
    title: "Support Engineer",
    kind: "job",
    org_name: "Sample Logistics GmbH",
    start: "2024-01-01",
    end: "2024-12-31",
    open_ended: false,
    status: "active",
    description: "Kept the warehouse systems online.",
    skills: [{ id: "s1", skill_key: "python", skill_label: "Python" }],
    achievements: [{ id: "a1", text: "Owned monitoring" }],
  } as const;

  function previewPayload() {
    return {
      before: { ...SNAPSHOT, description: "Kept the warehouse systems online." },
      after: {
        ...SNAPSHOT,
        description: "Kept the warehouse systems online.\nOptimized the nightly queries.",
      },
      edits: {
        text_edits: [
          {
            field: "description",
            op: "append",
            text: "Optimized the nightly queries.",
          },
        ],
      },
    };
  }

  it("shows the preview button for entity kinds and opens the modal lazily", async () => {
    previewApi.mockResolvedValue(previewPayload());
    const user = userEvent.setup();
    render(
      <MessageProposals message={messageWith([{ ...CARD, id: "p-x" }])} />,
    );
    await user.click(await screen.findByTestId("hitl-preview-p-x"));
    expect(previewApi).toHaveBeenCalledWith("p-x");
    expect(await screen.findByTestId("hitl-preview-modal")).toBeInTheDocument();
    expect(screen.getByTestId("hitl-preview-after")).toBeInTheDocument();
    await waitFor(() => {
      expect(
        screen.getByTestId("hitl-preview-after").textContent,
      ).toContain("Kept the warehouse systems online.");
    });
    // The appended sentence highlights in the after card.
    expect(screen.getAllByTestId("hitl-highlight")[0]).toHaveTextContent(
      "Optimized the nightly queries.",
    );
  });

  it("hides the preview button for kinds without snapshots and after a 404", async () => {
    previewApi.mockRejectedValue({
      response: { data: { detail: "No preview for this proposal" } },
    });
    const cvCard: ProfileProposalCardData = {
      ...CARD,
      id: "p-cv",
      kind: "cv_synth",
      action: "create",
    };
    const user = userEvent.setup();
    render(
      <MessageProposals message={messageWith([{ ...CARD, id: "p-y" }, cvCard])} />,
    );
    expect(screen.queryByTestId("hitl-preview-p-cv")).not.toBeInTheDocument();
    await user.click(await screen.findByTestId("hitl-preview-p-y"));
    expect(await screen.findByTestId("hitl-preview-missing")).toBeInTheDocument();
    await waitFor(() => {
      expect(
        screen.queryByTestId("hitl-preview-p-y"),
      ).not.toBeInTheDocument();
    });
  });

  it("reverts an approved card through an armed confirm", async () => {
    const user = userEvent.setup();
    approveApi.mockResolvedValue({
      proposal: { ...CARD, status: "approved" },
      applied: { id: "item-1", kind: "experience_item", label: "x" },
      already: false,
    });
    render(<MessageProposals message={messageWith([CARD])} />);
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await screen.findByTestId("hitl-revert-prop-1");
    expect(screen.getByTestId("hitl-revert-prop-1").textContent).toContain(
      "Revert",
    );
    await user.click(screen.getByTestId("hitl-revert-prop-1"));
    expect(revertApi).not.toHaveBeenCalled();
    revertApi.mockResolvedValue({ ...CARD, status: "reverted" });
    await user.click(screen.getByTestId("hitl-revert-prop-1"));
    expect(revertApi).toHaveBeenCalledWith("prop-1");
    await waitFor(() => {
      expect(screen.getByText("Reverted")).toBeInTheDocument();
    });
  });

  it("a moved-target 409 shows the changed-since-applied copy", async () => {
    const user = userEvent.setup();
    approveApi.mockResolvedValue({
      proposal: { ...CARD, status: "approved" },
      applied: { id: "item-1", kind: "experience_item", label: "x" },
      already: false,
    });
    render(<MessageProposals message={messageWith([CARD])} />);
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await screen.findByTestId("hitl-revert-prop-1");
    revertApi.mockRejectedValue({
      response: {
        data: { detail: "Changed since it was applied — edit state moved" },
      },
    });
    await user.click(screen.getByTestId("hitl-revert-prop-1"));
    await user.click(screen.getByTestId("hitl-revert-prop-1"));
    await waitFor(() => {
      expect(
        screen.getByText(/Changed since applied — the target was edited/),
      ).toBeInTheDocument();
    });
  });
});

async function resolveOf(id: string) {
  await useProfileProposalsStore.getState().resolve(id, "approve");
}

describe("profileProposalsStore", () => {
  beforeEach(() => {
    resetStore();
  });

  it("tracks pending cards per session and the last resolve burst signal", async () => {
    useProfileProposalsStore.getState().receiveLive(LIVE_CARD);
    expect(useProfileProposalsStore.getState().pendingBySession).toEqual({
      s1: 1,
    });

    approveApi.mockResolvedValue({
      proposal: { ...LIVE_CARD, status: "approved" },
      applied: { id: "item-1", kind: "experience_item", label: "AI Launcher" },
      already: false,
    });
    await resolveOf(LIVE_CARD.id);
    const state = useProfileProposalsStore.getState();
    // The post-resolve hydrate rebase takes the server truth: no pending
    // s1 cards left (absent key reads as 0 for burst detection).
    expect(state.pendingBySession["s1"] ?? 0).toBe(0);
    expect(state.lastResolved).toMatchObject({
      id: LIVE_CARD.id,
      sessionId: "s1",
      title: "Update experience · Siemens internship",
      status: "approved",
    });
  });

  it("rebuilds pendingBySession from the hydrate snapshot", async () => {
    listApi.mockResolvedValue({
      proposals: [
        { ...CARD, id: "p-1", status: "pending", chat_session_id: "s1" },
        { ...CARD, id: "p-2", status: "pending", chat_session_id: "s2" },
        { ...CARD, id: "p-3", status: "approved", chat_session_id: "s2" },
      ],
      pending_count: 2,
    });
    await useProfileProposalsStore.getState().hydrate();
    expect(
      useProfileProposalsStore.getState().pendingBySession,
    ).toEqual({ s1: 1, s2: 1 });
  });

  it("claimFollowup consumes a burst key exactly once", () => {
    const store = useProfileProposalsStore.getState();
    expect(store.claimFollowup("k1")).toBe(true);
    expect(store.claimFollowup("k1")).toBe(false);
    expect(store.claimFollowup("k2")).toBe(true);
  });

  it("resolve maps a generic failure to pending with the error", async () => {
    approveApi.mockRejectedValue({
      response: { data: { detail: "Apply failed: validation" } },
    });
    const { resolve } = useProfileProposalsStore.getState();
    await resolve("prop-9", "approve");
    expect(useProfileProposalsStore.getState().overrides["prop-9"]).toMatchObject({
      status: "pending",
      error: "Apply failed: validation",
      busy: false,
    });
  });

  it("hydrate merges non-pending statuses without clobbering local overrides", async () => {
    listApi.mockResolvedValue({
      proposals: [
        { ...CARD, id: "a", status: "approved" },
        { ...CARD, id: "b", status: "pending" },
      ],
      pending_count: 1,
    });
    useProfileProposalsStore.setState({
      overrides: { b: { status: "rejected" } },
    });
    const { hydrate } = useProfileProposalsStore.getState();
    await hydrate();
    const overrides = useProfileProposalsStore.getState().overrides;
    expect(overrides.a).toMatchObject({ status: "approved" });
    expect(overrides.b).toMatchObject({ status: "rejected" });
    expect(useProfileProposalsStore.getState().pendingCount).toBe(1);
  });
});
