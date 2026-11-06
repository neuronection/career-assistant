import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { Taxonomy } from "@/pages/settings/Taxonomy";

vi.mock("@/api/taxonomy", () => ({
  fetchInterests: vi.fn().mockResolvedValue([]),
  fetchSkillRows: vi.fn().mockResolvedValue([]),
  fetchTaxonomyStats: vi.fn().mockResolvedValue({
    skills: { total: 0, active: 0, proposed: 0, deprecated: 0, auto_promoted: 0, promoted_7d: 0 },
    queue: { relations: 0, enrichment: 0, paths: 0, translations: 0, total: 0 },
  }),
  fetchJobProposals: vi.fn(),
  regenerateJobProposals: vi.fn(),
  createTag: vi.fn(),
  deleteTag: vi.fn(),
  updateTag: vi.fn(),
  promoteSkill: vi.fn(),
  mergeSkill: vi.fn(),
  bulkSkillAction: vi.fn(),
  bulkJobProposalDismiss: vi.fn(),
}));

vi.mock("@/api/jobs", () => ({ fetchFamilyTree: vi.fn().mockResolvedValue([]) }));

vi.mock("@/api/skillRelations", () => ({
  fetchSkillRelations: vi.fn().mockResolvedValue([]),
  fetchSkillRelationThresholds: vi.fn().mockResolvedValue(null),
  fetchSkillRelationRuns: vi.fn().mockResolvedValue([]),
  saveSkillRelationThresholds: vi.fn(),
  acceptSkillRelation: vi.fn(),
  dismissSkillRelation: vi.fn(),
  removeSkillRelation: vi.fn(),
  saveSkillRelationAlias: vi.fn(),
  createSkillRelation: vi.fn(),
  bulkSkillRelationAction: vi.fn(),
}));

vi.mock("@/api/postingResolution", () => ({
  fetchResolutionThresholds: vi.fn().mockResolvedValue(null),
  saveResolutionThresholds: vi.fn(),
  fetchResolutionStats: vi.fn().mockResolvedValue(null),
  replayPostingResolution: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  api: { get: vi.fn().mockResolvedValue({ data: [] }), post: vi.fn() },
  apiDetail: (err: unknown) => (err instanceof Error ? err.message : ""),
}));

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

const { fetchJobProposals, regenerateJobProposals } = await import("@/api/taxonomy");
const fetchProposalsMock = vi.mocked(fetchJobProposals);
const regenerateMock = vi.mocked(regenerateJobProposals);

describe("job proposal legacy banner (plan 202 S6)", () => {
  beforeEach(() => {
    fetchProposalsMock.mockReset();
    regenerateMock.mockReset();
    fetchProposalsMock.mockResolvedValue({ items: [], legacy_count: 3, next_cursor: null, total: 0 });
  });

  it("shows the all-v1/empty-v2 envelope and queues the backfill", async () => {
    const user = userEvent.setup();
    regenerateMock.mockResolvedValue({ queued: true, job_id: "job-9", created: true });
    render(
      <MemoryRouter initialEntries={["/settings/taxonomy?tab=enrichment"]}>
        <Taxonomy />
      </MemoryRouter>,
    );
    const banner = await screen.findByTestId("job-proposals-legacy-banner");
    expect(banner).toBeTruthy();
    await user.click(screen.getByTestId("job-proposals-regenerate"));
    await waitFor(() => expect(regenerateMock).toHaveBeenCalledWith({}));
  });

  it("hides the banner once no legacy rows remain", async () => {
    fetchProposalsMock.mockResolvedValue({ items: [], legacy_count: 0, next_cursor: null, total: 0 });
    render(
      <MemoryRouter initialEntries={["/settings/taxonomy?tab=enrichment"]}>
        <Taxonomy />
      </MemoryRouter>,
    );
    await waitFor(() => expect(fetchProposalsMock).toHaveBeenCalled());
    expect(screen.queryByTestId("job-proposals-legacy-banner")).toBeNull();
  });
});
