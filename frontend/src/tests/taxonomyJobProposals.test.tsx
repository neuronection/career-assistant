import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TaxonomyJobProposalCards } from "@/components/settings/TaxonomyJobProposalCards";
import type { JobProposalRow } from "@/api/taxonomy";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      const templates: Record<string, string> = {
        "taxonomy.jobProposals.pendingNotice": "Semantic pass queued — {{reason}}",
        "taxonomy.jobProposals.pendingReasons.ambiguous":
          "ambiguous deterministic outcome",
        "taxonomy.jobProposals.remapNote":
          "Deterministic decision recorded — no semantic pass was queued.",
        "taxonomy.jobProposals.remapPendingNote":
          "Deterministic decision recorded — semantic pass queued ({{reason}}).",
        "taxonomy.jobProposals.remapQueued": "Queued",
        "taxonomy.jobProposals.rerankTrace":
          "Semantic rerank: {{code}} {{score}} — {{outcome}}",
        "taxonomy.jobProposals.rerankAccepted": "accepted",
      };
      let out = templates[key] ?? key;
      for (const [name, value] of Object.entries(params ?? {})) {
        out = out.split(`{{${name}}}`).join(String(value));
      }
      return out;
    },
    i18n: { language: "en" },
  }),
}));

vi.mock("@/api/taxonomy", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/taxonomy")>();
  return {
    ...actual,
    applyJobProposal: vi.fn(),
    dismissJobProposal: vi.fn(),
    remapPosting: vi.fn(),
  };
});

const { applyJobProposal, dismissJobProposal, remapPosting } = await import("@/api/taxonomy");
const applyMock = vi.mocked(applyJobProposal);
const dismissMock = vi.mocked(dismissJobProposal);
const remapMock = vi.mocked(remapPosting);

const row: JobProposalRow = {
  id: "p-1",
  ref: "REF01",
  title: "Observability Engineer",
  org: "Acme",
  proposal: {
    title_norm: "Observability Engineer",
    short_description: "Watches the watches.",
    skills: [
      { skill_key: "sql", required_level: 4, priority: "must_have" },
      { skill_key: "programming", required_level: 4, priority: "must_have" },
    ],
    seniority: "mid",
    proposed_at: "2026-11-02T10:00:00Z",
  },
  proposed_at: "2026-11-02T10:00:00Z",
  suggested_family_key: "tech-ops",
  mapping_signals: {
    overlap: { score: 0.05, runner_up: null },
    semantic: { top: null, threshold: 0.6, candidates: [] },
  },
  extract_version: 4,
};

const families = [
  { key: "tech", label: "Technology & IT", depth: 0 },
  { key: "tech-ops", label: "Technology & IT › IT Operations & Security", depth: 1 },
];

afterEach(() => {
  applyMock.mockReset();
  dismissMock.mockReset();
  remapMock.mockReset();
});

const pendingRow: JobProposalRow = {
  ...row,
  mapping_signals: {
    ...row.mapping_signals,
    semantic_pending: true,
    semantic_pending_reason: "ambiguous deterministic outcome",
  },
};

describe("TaxonomyJobProposalCards", () => {
  it("renders the proposal with its skills, signals and moderation actions", () => {
    render(
      <TaxonomyJobProposalCards rows={[row]} families={families} onDone={() => {}} />,
    );
    expect(screen.getByTestId("job-proposal-row-p-1")).toBeTruthy();
    expect(screen.getByText("Observability Engineer")).toBeTruthy();
    expect(screen.getByText(/sql/)).toBeTruthy();
    expect(screen.getByTestId(`proposal-apply-p-1`)).toBeTruthy();
    expect(screen.getByTestId(`proposal-dismiss-p-1`)).toBeTruthy();
  });

  it("apply opens the dialog and submits family + editable title", async () => {
    const user = userEvent.setup();
    applyMock.mockResolvedValueOnce({ job_code: "observability-engineer" });
    const onDone = vi.fn();
    render(
      <TaxonomyJobProposalCards rows={[row]} families={families} onDone={onDone} />,
    );
    await user.click(screen.getByTestId("proposal-apply-p-1"));
    const picker = screen.getByTestId("proposal-family-picker") as HTMLSelectElement;
    expect(picker).toBeTruthy();
    // the skill-affinity suggestion preselects the exact (child) family
    expect(picker.value).toBe("tech-ops");
    const titleInput = screen.getByTestId("proposal-title-input") as HTMLInputElement;
    expect(titleInput.value).toBe("Observability Engineer");
    // jsdom keeps the library dialog's overlay inert; drive the confirm
    // through the event (the handler contract is what this test pins).
    fireEvent.click(screen.getByTestId("proposal-apply-confirm"));
    await waitFor(() => expect(applyMock).toHaveBeenCalledTimes(1));
    expect(applyMock.mock.calls[0]).toEqual([
      "p-1",
      { family_key: "tech-ops", title: "Observability Engineer", code: undefined },
    ]);
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  it("no suggestion means the picker starts empty until a family is chosen", async () => {
    const user = userEvent.setup();
    render(
      <TaxonomyJobProposalCards
        rows={[{ ...row, suggested_family_key: null }]}
        families={families}
        onDone={() => {}}
      />,
    );
    await user.click(screen.getByTestId("proposal-apply-p-1"));
    const picker = screen.getByTestId("proposal-family-picker") as HTMLSelectElement;
    expect(picker.value).toBe("");
    expect(
      (screen.getByTestId("proposal-apply-confirm") as HTMLButtonElement).disabled,
    ).toBe(true), "apply stays disabled until a family is picked";
  });

  it("dismiss requires the confirm step and calls through", async () => {
    const user = userEvent.setup();
    dismissMock.mockResolvedValueOnce(undefined);
    render(
      <TaxonomyJobProposalCards rows={[row]} families={families} onDone={() => {}} />,
    );
    await user.click(screen.getByTestId("proposal-dismiss-p-1"));
    const confirms = await screen.findAllByText(
      (content, element) =>
        element?.tagName === "BUTTON" && content.trim() === "taxonomy.jobProposals.dismiss",
    );
    // the modal's confirm renders after the row's own dismiss trigger
    fireEvent.click(confirms[confirms.length - 1]);
    await waitFor(() => expect(dismissMock).toHaveBeenCalledWith("p-1"));
  });

  it("marks a deferred semantic pass with its reason, not a completion", () => {
    render(
      <TaxonomyJobProposalCards rows={[pendingRow]} families={families} onDone={() => {}} />,
    );
    expect(screen.getByTestId("proposal-pending-p-1")).toBeTruthy();
    expect(screen.getByTestId("proposal-pending-p-1").textContent).toContain(
      "Semantic pass queued",
    );
    expect(screen.getByTestId("proposal-pending-p-1").textContent).toContain(
      "ambiguous deterministic outcome",
    );
    expect(screen.queryByTestId("proposal-refresh-p-1")).toBeNull();
  });

  it("shows the final rerank trace once the worker settles, with no pending chip", () => {
    const settled: JobProposalRow = {
      ...row,
      mapping_signals: {
        ...row.mapping_signals,
        rerank: {
          ran: true,
          accepted: true,
          top: 0.72,
          top_code: "observability-engineer",
        },
      },
    };
    render(
      <TaxonomyJobProposalCards rows={[settled]} families={families} onDone={() => {}} />,
    );
    expect(screen.queryByTestId("proposal-pending-p-1")).toBeNull();
    expect(screen.getByTestId("proposal-rerank-p-1").textContent).toContain(
      "observability-engineer",
    );
    expect(screen.getByTestId("proposal-rerank-p-1").textContent).toContain("0.72");
    expect(screen.getByTestId("proposal-rerank-p-1").textContent).toContain("accepted");
  });

  it("offers Check again for a pending row and reloads through the parent", async () => {
    const user = userEvent.setup();
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    render(
      <TaxonomyJobProposalCards
        rows={[pendingRow]}
        families={families}
        onDone={() => {}}
        onRefresh={onRefresh}
      />,
    );
    await user.click(screen.getByTestId("proposal-refresh-p-1"));
    await waitFor(() => expect(onRefresh).toHaveBeenCalledTimes(1));
  });

  it("reports a deterministic decision when no semantic pass was queued", async () => {
    const user = userEvent.setup();
    const onDone = vi.fn();
    remapMock.mockResolvedValueOnce({
      mapping_method: "skill_overlap",
      semantic_pending: false,
      semantic_pending_reason: null,
    });
    render(
      <TaxonomyJobProposalCards rows={[row]} families={families} onDone={onDone} />,
    );
    await user.click(screen.getByTestId("proposal-remap-p-1"));
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(onDone.mock.calls[0][0]).toBe(
      "Deterministic decision recorded — no semantic pass was queued.",
    );
    expect(
      (screen.getByTestId("proposal-remap-p-1") as HTMLButtonElement).disabled,
    ).toBe(false);
  });

  it("queues the semantic pass and does not imply it finished synchronously", async () => {
    const user = userEvent.setup();
    const onDone = vi.fn();
    remapMock.mockResolvedValueOnce({
      mapping_method: null,
      semantic_pending: true,
      semantic_pending_reason: "ambiguous deterministic outcome",
    });
    render(
      <TaxonomyJobProposalCards rows={[row]} families={families} onDone={onDone} />,
    );
    await user.click(screen.getByTestId("proposal-remap-p-1"));
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(onDone.mock.calls[0][0]).toContain("semantic pass queued");
    expect(onDone.mock.calls[0][0]).toContain("ambiguous deterministic outcome");
    const button = screen.getByTestId("proposal-remap-p-1") as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(true));
    expect(button.textContent).toContain("Queued");
  });

  it("surfaces the server's 409 message instead of swallowing it", async () => {
    const user = userEvent.setup();
    const rejection = Object.assign(new Error("Request failed with status code 409"), {
      isAxiosError: true,
      response: {
        data: {
          detail:
            "This posting was mapped manually — use the manual map endpoint to override",
        },
      },
    });
    remapMock.mockRejectedValueOnce(rejection);
    render(
      <TaxonomyJobProposalCards rows={[row]} families={families} onDone={() => {}} />,
    );
    await user.click(screen.getByTestId("proposal-remap-p-1"));
    await waitFor(() =>
      expect(
        screen.getByText(
          "This posting was mapped manually — use the manual map endpoint to override",
        ),
      ).toBeTruthy(),
    );
  });
});
