import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TaxonomyJobProposalCards } from "@/components/settings/TaxonomyJobProposalCards";
import type { JobProposalRow } from "@/api/taxonomy";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      let out = key;
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
  };
});

const { applyJobProposal, dismissJobProposal } = await import("@/api/taxonomy");
const applyMock = vi.mocked(applyJobProposal);
const dismissMock = vi.mocked(dismissJobProposal);

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
  suggested_family_key: "tech",
  mapping_signals: {
    overlap: { score: 0.05, runner_up: null },
    semantic: { top: null, threshold: 0.6, candidates: [] },
  },
  extract_version: 4,
};

const families = [{ key: "tech", label: "Technology" }];

afterEach(() => {
  applyMock.mockReset();
  dismissMock.mockReset();
});

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
    // the skill-affinity suggestion preselects the family
    expect(picker.value).toBe("tech");
    const titleInput = screen.getByTestId("proposal-title-input") as HTMLInputElement;
    expect(titleInput.value).toBe("Observability Engineer");
    // jsdom keeps the library dialog's overlay inert; drive the confirm
    // through the event (the handler contract is what this test pins).
    fireEvent.click(screen.getByTestId("proposal-apply-confirm"));
    await waitFor(() => expect(applyMock).toHaveBeenCalledTimes(1));
    expect(applyMock.mock.calls[0]).toEqual([
      "p-1",
      { family_key: "tech", title: "Observability Engineer", code: undefined },
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
});
