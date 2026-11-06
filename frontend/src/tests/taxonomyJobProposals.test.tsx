import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TaxonomyJobProposalCards } from "@/components/settings/TaxonomyJobProposalCards";
import type { JobProposalRow } from "@/api/taxonomy";

const onBulkDismiss = vi.fn(async () => true);

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      const templates: Record<string, string> = {
        "taxonomy.jobProposals.pendingNotice": "Semantic pass queued — {{reason}}",
        "taxonomy.jobProposals.remapQueuedNote":
          "Re-decision queued — the proposal refreshes in the background.",
        "taxonomy.jobProposals.remapQueued": "Queued",
        "taxonomy.jobProposals.mapTo": "Map to {{title}}",
        "taxonomy.jobProposals.appliedNote": "Created {{code}}",
        "taxonomy.jobProposals.mappedNote": "Mapped to {{title}}",
        "taxonomy.jobProposals.duplicateWarning":
          "“{{title}}” is an exact or near duplicate. Map to it, or create anyway.",
        "taxonomy.jobProposals.bulkDismissTitle": "Dismiss {{count}} proposals?",
        "taxonomy.jobProposals.bulkDismissBody": "Bulk dismiss body",
        "taxonomy.jobProposals.skillsMust": "Must-have",
        "taxonomy.jobProposals.skillsNice": "Nice-to-have",
        "taxonomy.jobProposals.skillsBonus": "Bonus",
        "taxonomy.jobProposals.createType": "Create job type",
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
    mapJobProposal: vi.fn(),
    remapPosting: vi.fn(),
  };
});

vi.mock("@/api/jobs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/jobs")>();
  return { ...actual, fetchJobs: vi.fn(async () => ({ items: [] })) };
});

const { applyJobProposal, dismissJobProposal, mapJobProposal, remapPosting } = await import(
  "@/api/taxonomy"
);
const applyMock = vi.mocked(applyJobProposal);
const dismissMock = vi.mocked(dismissJobProposal);
const mapMock = vi.mocked(mapJobProposal);
const remapMock = vi.mocked(remapPosting);

const row: JobProposalRow = {
  id: "p-1",
  ref: "REF01",
  title: "Principal Software Engineer, Product Engineering",
  org: "Dropbox",
  url: "https://example.com/job",
  proposal: {
    proposal_version: 2,
    action: "create",
    job_type: "Software Engineer",
    title_norm: "Software Engineer, Product Engineering",
    posting_title: "Principal Software Engineer, Product Engineering",
    short_description: "Builds and operates software systems across employers.",
    skills: [
      { skill_key: "sql", required_level: 4, priority: "must_have" },
      { skill_key: "python", required_level: 4, priority: "nice_to_have" },
      { skill_key: "docker", required_level: 3, priority: "bonus" },
    ],
    seniority: "principal",
    confidence: 0.9,
    rationale: "The catalog already covers this occupation.",
    needs_edit: false,
    proposed_at: "2026-11-02T10:00:00Z",
  },
  proposed_at: "2026-11-02T10:00:00Z",
  suggested_family_key: "tech-ops",
  mapping_signals: null,
  extract_version: 5,
  existing_job: null,
  catalog_candidates: [
    {
      code: "software-engineer",
      title: "Software Engineer",
      family_key: "tech",
      family_label: "Technology",
      short_description: "Builds software.",
      score: 0.82,
      source: "containment",
    },
  ],
  duplicate_candidates: [],
};

const mapRow: JobProposalRow = {
  ...row,
  id: "p-map",
  proposal: { ...row.proposal, action: "map_existing", existing_job_code: "software-engineer" },
  existing_job: {
    code: "software-engineer",
    title: "Software Engineer",
    status: "published",
    family_key: "tech",
    short_description: "Builds software.",
  },
};

const families = [
  { key: "tech", label: "Technology & IT", depth: 0 },
  { key: "tech-ops", label: "Technology & IT › IT Operations & Security", depth: 1 },
];

afterEach(() => {
  applyMock.mockReset();
  dismissMock.mockReset();
  mapMock.mockReset();
  remapMock.mockReset();
});

describe("TaxonomyJobProposalCards", () => {
  it("shows provenance separately from the proposed job type", () => {
    render(
      <TaxonomyJobProposalCards
        onBulkDismiss={onBulkDismiss}
        rows={[row]}
        families={families}
        onDone={() => {}}
      />,
    );
    const source = screen.getByTestId("proposal-source-p-1");
    expect(source.textContent).toContain("Principal Software Engineer, Product Engineering");
    expect(source.textContent).toContain("Dropbox");
    expect(source.textContent).toContain("principal");
    expect(screen.getByTestId("proposal-type-p-1").textContent).toBe("Software Engineer");
    expect(screen.getByTestId("proposal-apply-p-1").textContent).toContain(
      "Create job type",
    );
  });

  it("groups skills must-have, nice-to-have and bonus", () => {
    render(
      <TaxonomyJobProposalCards
        onBulkDismiss={onBulkDismiss}
        rows={[row]}
        families={families}
        onDone={() => {}}
      />,
    );
    const skills = screen.getByTestId("proposal-skills-p-1");
    expect(skills.textContent).toContain("Must-have");
    expect(skills.textContent).toContain("Nice-to-have");
    expect(skills.textContent).toContain("Bonus");
  });

  it("creates a type and sends the edited description", async () => {
    const user = userEvent.setup();
    applyMock.mockResolvedValueOnce({ job_code: "software-engineer" });
    const onDone = vi.fn();
    render(
      <TaxonomyJobProposalCards
        onBulkDismiss={onBulkDismiss}
        rows={[row]}
        families={families}
        onDone={onDone}
      />,
    );
    await user.click(screen.getByTestId("proposal-apply-p-1"));
    expect((screen.getByTestId("proposal-family-picker") as HTMLSelectElement).value).toBe(
      "tech-ops",
    );
    expect((screen.getByTestId("proposal-title-input") as HTMLInputElement).value).toBe(
      "Software Engineer",
    );
    await user.clear(screen.getByTestId("proposal-description-input"));
    await user.type(screen.getByTestId("proposal-description-input"), "An archetype.");
    fireEvent.click(screen.getByTestId("proposal-apply-confirm"));
    await waitFor(() => expect(applyMock).toHaveBeenCalledTimes(1));
    expect(applyMock.mock.calls[0][1]).toMatchObject({
      family_key: "tech-ops",
      title: "Software Engineer",
      short_description: "An archetype.",
    });
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  it("maps to an existing type in one action (no create dialog)", async () => {
    const user = userEvent.setup();
    mapMock.mockResolvedValueOnce({ job_code: "software-engineer", job_id: "j-1" });
    const onDone = vi.fn();
    render(
      <TaxonomyJobProposalCards
        onBulkDismiss={onBulkDismiss}
        rows={[mapRow]}
        families={families}
        onDone={onDone}
      />,
    );
    expect(screen.getByTestId("proposal-apply-p-map").textContent).toContain(
      "Map to Software Engineer",
    );
    await user.click(screen.getByTestId("proposal-apply-p-map"));
    const confirm = await screen.findByRole("button", {
      name: "taxonomy.jobProposals.mapConfirm",
    });
    fireEvent.click(confirm);
    await waitFor(() => expect(mapMock).toHaveBeenCalledWith("p-map", "software-engineer"));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  it("offers candidate buttons that map without opening the create dialog", async () => {
    const user = userEvent.setup();
    mapMock.mockResolvedValueOnce({ job_code: "software-engineer", job_id: "j-1" });
    render(
      <TaxonomyJobProposalCards
        onBulkDismiss={onBulkDismiss}
        rows={[row]}
        families={families}
        onDone={() => {}}
      />,
    );
    await user.click(screen.getByTestId("proposal-candidate-p-1-software-engineer"));
    const confirm = await screen.findByRole("button", {
      name: "taxonomy.jobProposals.mapConfirm",
    });
    fireEvent.click(confirm);
    await waitFor(() => expect(mapMock).toHaveBeenCalledWith("p-1", "software-engineer"));
  });

  it("surfaces the duplicate warning and can create anyway", async () => {
    const user = userEvent.setup();
    applyMock.mockRejectedValueOnce(
      Object.assign(new Error("conflict"), {
        isAxiosError: true,
        response: {
          data: {
            code: "duplicate_job_type",
            existing: [{ code: "software-engineer", title: "Software Engineer" }],
          },
        },
      }),
    );
    applyMock.mockResolvedValueOnce({ job_code: "software-engineer-2" });
    render(
      <TaxonomyJobProposalCards
        onBulkDismiss={onBulkDismiss}
        rows={[row]}
        families={families}
        onDone={() => {}}
      />,
    );
    await user.click(screen.getByTestId("proposal-apply-p-1"));
    fireEvent.click(screen.getByTestId("proposal-apply-confirm"));
    const warning = await screen.findByTestId("proposal-duplicate-warning");
    expect(warning.textContent).toContain("Software Engineer");
    fireEvent.click(screen.getByTestId("proposal-duplicate-create"));
    fireEvent.click(screen.getByTestId("proposal-apply-confirm"));
    await waitFor(() =>
      expect(applyMock.mock.calls[applyMock.mock.calls.length - 1][1]).toMatchObject({
        allow_duplicate: true,
      }),
    );
  });

  it("re-decides in the background and shows the queued state", async () => {
    remapMock.mockResolvedValueOnce({ queued: true, job_id: "job-1" });
    render(
      <TaxonomyJobProposalCards
        onBulkDismiss={onBulkDismiss}
        rows={[row]}
        families={families}
        onDone={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("proposal-remap-p-1"));
    const button = screen.getByTestId("proposal-remap-p-1") as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(true));
    expect(button.textContent).toContain("Queued");
  });

  it("dismiss requires the confirm step and calls through", async () => {
    const user = userEvent.setup();
    dismissMock.mockResolvedValueOnce(undefined);
    render(
      <TaxonomyJobProposalCards
        onBulkDismiss={onBulkDismiss}
        rows={[row]}
        families={families}
        onDone={() => {}}
      />,
    );
    await user.click(screen.getByTestId("proposal-dismiss-p-1"));
    const confirms = await screen.findAllByText(
      (content, element) =>
        element?.tagName === "BUTTON" && content.trim() === "taxonomy.jobProposals.dismiss",
    );
    fireEvent.click(confirms[confirms.length - 1]);
    await waitFor(() => expect(dismissMock).toHaveBeenCalledWith("p-1"));
  });

  it("keeps apply disabled until a family is chosen", async () => {
    const user = userEvent.setup();
    render(
      <TaxonomyJobProposalCards
        onBulkDismiss={onBulkDismiss}
        rows={[{ ...row, suggested_family_key: null }]}
        families={families}
        onDone={() => {}}
      />,
    );
    await user.click(screen.getByTestId("proposal-apply-p-1"));
    expect((screen.getByTestId("proposal-apply-confirm") as HTMLButtonElement).disabled).toBe(
      true,
    );
  });
});

describe("TaxonomyJobProposalCards bulk dismissal", () => {
  it("dismisses the whole selection behind one confirmation", async () => {
    const user = userEvent.setup();
    onBulkDismiss.mockClear();
    const second: JobProposalRow = {
      ...row,
      id: "p-2",
      ref: "REF02",
      title: "Platform Engineer",
      proposal: { ...row.proposal, job_type: "Platform Engineer" },
    };
    render(
      <TaxonomyJobProposalCards
        onBulkDismiss={onBulkDismiss}
        rows={[row, second]}
        families={families}
        onDone={() => {}}
      />,
    );

    await user.click(screen.getByTestId("proposals-select"));
    await user.click(
      within(screen.getByTestId("proposals-bulk-bar-select-all")).getByRole("checkbox"),
    );
    await user.click(screen.getByTestId("proposals-bulk-dismiss"));
    const confirms = await screen.findAllByRole("button", {
      name: "taxonomy.jobProposals.dismiss",
    });
    fireEvent.click(confirms[confirms.length - 1]);
    await waitFor(() => expect(onBulkDismiss).toHaveBeenCalledWith(["p-1", "p-2"]));
  });
});
