import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";

import * as relationsApi from "@/api/skillRelations";
import type { SkillRelationRow, SkillRelationRun } from "@/api/skillRelations";
import * as taxonomyApi from "@/api/taxonomy";
import {
  SkillRelationsPanel,
  type RelationSection,
} from "@/components/settings/SkillRelationsPanel";

vi.mock("@/api/skillRelations", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/skillRelations")>();
  return {
    ...actual,
    fetchSkillRelations: vi.fn(),
    createSkillRelation: vi.fn(),
    acceptSkillRelation: vi.fn(),
    dismissSkillRelation: vi.fn(),
    bulkSkillRelationAction: vi.fn(),
    saveSkillRelationAlias: vi.fn(),
    removeSkillRelation: vi.fn(),
    fetchSkillRelationThresholds: vi.fn(),
    saveSkillRelationThresholds: vi.fn(),
    fetchSkillRelationRuns: vi.fn(),
  };
});

vi.mock("@/api/taxonomy", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/taxonomy")>();
  return { ...actual, fetchSkillRows: vi.fn(), fetchTaxonomyStats: vi.fn().mockResolvedValue(null) };
});

vi.mock("@/components/ui", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/ui")>();
  let picks = 0;
  return {
    ...actual,
    MultiSelectPicker: ({
      value,
      onChange,
    }: {
      value: { value: string; label: string }[];
      onChange: (next: { value: string; label: string }[]) => void;
    }) => (
      <button
        data-testid="fake-picker"
        onClick={() => {
          picks += 1;
          const entry =
            picks % 2 === 1 ? { value: "java", label: "Java" } : { value: "javascript", label: "JavaScript" };
          onChange([entry]);
        }}
      >
        {value.map((entry) => entry.label).join(", ") || "pick"}
      </button>
    ),
  };
});

const mocked = vi.mocked(relationsApi);
const mockedTaxonomy = vi.mocked(taxonomyApi);

const BASE_ROW = {
  source: "llm" as const,
  confidence: 0.9,
  evidence: { rationale: "Java is a programming language." },
  decided_by: null,
  decided_at: null,
  created_at: "2026-10-28T00:00:00Z",
  updated_at: "2026-10-28T00:00:00Z",
};

const PROPOSED: SkillRelationRow = {
  ...BASE_ROW,
  id: "r-proposed",
  relation: "is_a",
  status: "proposed",
  from_skill: {
    id: "s-java",
    key: "java",
    label: "Java",
    status: "active",
    evidence_quote: "Java required",
  },
  to_skill: {
    id: "s-prog",
    key: "programming",
    label: "Programming",
    status: "active",
    evidence_quote: null,
  },
  alias_candidate: false,
};

const ALIASABLE: SkillRelationRow = {
  ...BASE_ROW,
  id: "r-alias",
  relation: "synonym",
  status: "proposed",
  confidence: 0.7,
  from_skill: { id: "s-js", key: "js", label: "Js", status: "proposed", evidence_quote: "JS required" },
  to_skill: {
    id: "s-javascript",
    key: "javascript",
    label: "JavaScript",
    status: "active",
    evidence_quote: null,
  },
  alias_candidate: true,
};

const DISTINCT_CONCEPT: SkillRelationRow = {
  ...BASE_ROW,
  id: "r-distinct",
  relation: "related_to",
  status: "proposed",
  confidence: 0.93,
  from_skill: {
    id: "s-frontier",
    key: "frontier-models",
    label: "Frontier Models",
    status: "proposed",
    evidence_quote: "Frontier models commonly power AI agents.",
  },
  to_skill: {
    id: "s-agents",
    key: "ai-agents",
    label: "AI Agents",
    status: "active",
    evidence_quote: null,
  },
  alias_candidate: true,
};

const RUN: SkillRelationRun = {
  id: "run-1",
  status: "succeeded",
  created_at: "2026-10-28T03:30:00Z",
  finished_at: "2026-10-28T03:31:00Z",
  error: null,
  ledger: {
    candidates: 3,
    batches: 1,
    judged_batches: 1,
    failed_batches: 0,
    uncovered: 0,
    derived: 0,
    edges_proposed: 2,
    negatives: 1,
    dropped: 0,
    below_bar: 0,
    materialized: 1,
    backfilled: 1,
    capped: true,
    watermark: null,
  },
};

const APPROVED_RELATED: SkillRelationRow = {
  ...BASE_ROW,
  id: "r-approved",
  relation: "related_to",
  status: "approved",
  decided_by: "u-admin",
  decided_at: "2026-10-28T02:00:00Z",
  from_skill: {
    id: "s-java",
    key: "java",
    label: "Java",
    status: "active",
    evidence_quote: null,
  },
  to_skill: {
    id: "s-javascript",
    key: "javascript",
    label: "JavaScript",
    status: "active",
    evidence_quote: null,
  },
  alias_candidate: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  mocked.fetchSkillRelations.mockResolvedValue([PROPOSED, ALIASABLE, DISTINCT_CONCEPT]);
  mockedTaxonomy.fetchSkillRows.mockResolvedValue([
    {
      id: "s-java",
      key: "java",
      label: "Java",
      category: "tech",
      description: "",
      parent_id: null,
      level_anchors: [],
      aliases: [],
      status: "active",
      origin: "import",
    },
    {
      id: "s-javascript",
      key: "javascript",
      label: "JavaScript",
      category: "tech",
      description: "",
      parent_id: null,
      level_anchors: [],
      aliases: [],
      status: "active",
      origin: "import",
    },
  ]);
  mocked.createSkillRelation.mockResolvedValue(PROPOSED);
  mocked.acceptSkillRelation.mockResolvedValue({ ...PROPOSED, status: "approved" });
  mocked.dismissSkillRelation.mockResolvedValue({ ...PROPOSED, status: "rejected" });
  mocked.saveSkillRelationAlias.mockResolvedValue({
    relation: { ...ALIASABLE, status: "rejected" },
    target: ALIASABLE.to_skill,
    aliases: ["js"],
  });
  mocked.removeSkillRelation.mockResolvedValue();
  mocked.fetchSkillRelationThresholds.mockResolvedValue({
    min_support: 2,
    batch_size: 40,
    max_pairs_per_run: 200,
    min_negative_confidence: 0.6,
  });
  mocked.saveSkillRelationThresholds.mockResolvedValue({
    min_support: 5,
    batch_size: 10,
    max_pairs_per_run: 50,
    min_negative_confidence: 0.8,
  });
  mocked.fetchSkillRelationRuns.mockResolvedValue([RUN]);
});

function PanelHarness({ initialSection }: { initialSection: RelationSection }) {
  const [section, setSection] = useState(initialSection);
  return <SkillRelationsPanel section={section} onSectionChange={setSection} />;
}

function renderPanel(section: RelationSection = "queue") {
  render(<PanelHarness initialSection={section} />);
}

describe("SkillRelationsPanel", () => {
  it("lists the queue with pair context and per-row actions", async () => {
    renderPanel();
    expect(await screen.findByTestId("relation-row-r-proposed")).toBeTruthy();
    expect(screen.getByTestId("relation-row-r-alias")).toBeTruthy();
    expect(screen.getByTestId("relation-accept-r-proposed")).toBeTruthy();
    expect(screen.queryByTestId("relation-alias-r-proposed")).toBeNull();
    expect(screen.getByTestId("relation-alias-r-alias")).toBeTruthy();
    expect(screen.getByText(/raw label/i)).toBeTruthy();
  });

  it("shows the alias hint only for alias-shaped labels and the promotion hint for distinct concepts", async () => {
    renderPanel();
    const aliasRow = await screen.findByTestId("relation-row-r-alias");
    expect(within(aliasRow).getByText(/raw label/i)).toBeTruthy();

    const distinctRow = await screen.findByTestId("relation-row-r-distinct");
    expect(
      within(distinctRow).queryByText(/raw label/i),
    ).toBeNull();
    expect(
      within(distinctRow).getByText(/awaiting promotion/i),
    ).toBeTruthy();

    const proposedRow = await screen.findByTestId("relation-row-r-proposed");
    expect(within(proposedRow).queryByText(/awaiting promotion/i)).toBeNull();
  });

  it("accept calls the API and reloads the queue", async () => {
    renderPanel();
    fireEvent.click(await screen.findByTestId("relation-accept-r-proposed"));
    await waitFor(() =>
      expect(mocked.acceptSkillRelation).toHaveBeenCalledWith("r-proposed"),
    );
    await waitFor(() => expect(mocked.fetchSkillRelations).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/sub-skill tree is caught up/i)).toBeTruthy();
  });

  it("surfaces a refused accept and keeps the row in the queue", async () => {
    mocked.acceptSkillRelation.mockRejectedValue(
      Object.assign(new Error("fail"), {
        isAxiosError: true,
        response: { data: { detail: "is_a edge would create a cycle" } },
      }),
    );
    renderPanel();
    fireEvent.click(await screen.findByTestId("relation-accept-r-proposed"));
    expect(await screen.findByText(/would create a cycle/i)).toBeTruthy();
    expect(screen.getByTestId("relation-row-r-proposed")).toBeTruthy();
  });

  it("save as alias merges the label row and reports the target", async () => {
    renderPanel();
    fireEvent.click(await screen.findByTestId("relation-alias-r-alias"));
    await waitFor(() => expect(mocked.saveSkillRelationAlias).toHaveBeenCalledWith("r-alias"));
    expect(await screen.findByText(/alias of JavaScript/i)).toBeTruthy();
  });

  it("the editor adds a manual relation from the pickers", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("tab", { name: /all relations/i }));
    const pickers = await screen.findAllByTestId("fake-picker");
    fireEvent.click(pickers[0]);
    fireEvent.click(pickers[1]);
    fireEvent.change(screen.getByTestId("relation-kind-select"), {
      target: { value: "synonym" },
    });
    fireEvent.change(screen.getByTestId("relation-confidence-input"), {
      target: { value: "0.8" },
    });
    fireEvent.click(screen.getByTestId("relation-add-submit"));
    await waitFor(() =>
      expect(mocked.createSkillRelation).toHaveBeenCalledWith({
        from_skill: "java",
        to_skill: "javascript",
        relation: "synonym",
        confidence: 0.8,
      }),
    );
  });

  it("thresholds save the edited knobs", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("tab", { name: /thresholds/i }));
    fireEvent.change(await screen.findByTestId("threshold-min_support"), {
      target: { value: "5" },
    });
    fireEvent.click(screen.getByTestId("thresholds-save"));
    await waitFor(() =>
      expect(mocked.saveSkillRelationThresholds).toHaveBeenCalledWith({
        min_support: 5,
        batch_size: 40,
        max_pairs_per_run: 200,
        min_negative_confidence: 0.6,
      }),
    );
    expect(await screen.findByText("Saved.")).toBeTruthy();
  });

  it("runs render the ledger and a held watermark", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("tab", { name: /runs/i }));
    expect(await screen.findByTestId("run-row-run-1")).toBeTruthy();
    expect(screen.getByTestId("run-watermark-run-1").textContent).toMatch(/held/i);
    expect(screen.getByTestId("run-ledger-backfilled").textContent).toMatch(/1/);
    expect(mocked.fetchSkillRelationRuns).toHaveBeenCalled();
  });

  it("bulk accept applies one decision to the selected queue rows", async () => {
    mocked.bulkSkillRelationAction.mockResolvedValue({
      affected: ["r-proposed", "r-alias"],
      failed: [],
    });
    renderPanel();
    fireEvent.click(await screen.findByTestId("relation-select"));
    fireEvent.click(screen.getByRole("checkbox", { name: /select java/i }));
    fireEvent.click(screen.getByRole("checkbox", { name: /select js/i }));
    expect(screen.getByTestId("relation-bulk-bar")).toHaveTextContent("2 selected");

    fireEvent.click(screen.getByTestId("relation-bulk-accept"));

    await waitFor(() =>
      expect(mocked.bulkSkillRelationAction).toHaveBeenCalledWith(
        ["r-proposed", "r-alias"],
        "accept",
      ),
    );
    expect(await screen.findByText("2 edges updated.")).toBeTruthy();
    await waitFor(() => expect(mocked.fetchSkillRelations).toHaveBeenCalledTimes(2));
  });

  it("bulk dismiss reports per-row failures", async () => {
    mocked.bulkSkillRelationAction.mockResolvedValue({
      affected: ["r-proposed"],
      failed: [{ id: "r-alias", key: "Js → JavaScript", reason: "is_a edge would create a cycle" }],
    });
    renderPanel();
    fireEvent.click(await screen.findByTestId("relation-select"));
    fireEvent.click(screen.getByRole("checkbox", { name: /select java/i }));
    fireEvent.click(screen.getByRole("checkbox", { name: /select js/i }));

    fireEvent.click(screen.getByTestId("relation-bulk-dismiss"));

    await waitFor(() =>
      expect(mocked.bulkSkillRelationAction).toHaveBeenCalledWith(
        ["r-proposed", "r-alias"],
        "dismiss",
      ),
    );
    const failures = await screen.findByTestId("relation-bulk-failures");
    expect(failures.textContent).toMatch(/Js → JavaScript/);
    expect(failures.textContent).toMatch(/cycle/);
  });

  it("exiting select mode clears the selection", async () => {
    renderPanel();
    fireEvent.click(await screen.findByTestId("relation-select"));
    fireEvent.click(screen.getByRole("checkbox", { name: /select java/i }));
    expect(screen.getByTestId("relation-bulk-bar")).toHaveTextContent("1 selected");

    fireEvent.click(screen.getByTestId("relation-select"));

    expect(screen.queryByTestId("relation-bulk-bar")).toBeNull();
    expect(screen.queryByRole("checkbox", { name: /select java/i })).toBeNull();
  });

  it("the graph tab renders nodes and the relation palette", async () => {
    mocked.fetchSkillRelations.mockResolvedValue([APPROVED_RELATED]);
    mockedTaxonomy.fetchSkillRows.mockResolvedValue([
      {
        id: "s-java",
        key: "java",
        label: "Java",
        category: "tech",
        description: "",
        parent_id: "s-javascript",
        level_anchors: [],
        aliases: [],
        status: "active",
        origin: "import",
      },
      {
        id: "s-javascript",
        key: "javascript",
        label: "JavaScript",
        category: "tech",
        description: "",
        parent_id: null,
        level_anchors: [],
        aliases: [],
        status: "active",
        origin: "import",
      },
    ]);
    renderPanel();

    fireEvent.click(await screen.findByRole("tab", { name: "Graph" }));

    expect(await screen.findByTestId("skill-relations-graph")).toBeTruthy();
    expect(await screen.findByText("Java")).toBeTruthy();
    expect(screen.getByText("JavaScript")).toBeTruthy();
    // ReactFlow keeps edges hidden until nodes measure (ResizeObserver is a
    // no-op stub in jsdom), so the edge palette is asserted through the
    // legend rather than edge DOM.
    fireEvent.click(screen.getByRole("button", { name: "Legend" }));
    expect(await screen.findByText("is a")).toBeTruthy();
    expect(screen.getByText("related to")).toBeTruthy();
  });

  it("the graph tab shows the empty state before anything exists", async () => {
    mocked.fetchSkillRelations.mockResolvedValue([]);
    mockedTaxonomy.fetchSkillRows.mockResolvedValue([]);
    renderPanel();

    fireEvent.click(await screen.findByRole("tab", { name: "Graph" }));

    expect(await screen.findByTestId("skill-relations-graph")).toBeTruthy();
    expect(
      await screen.findByText(/Nothing to visualize yet — approve relations/),
    ).toBeTruthy();
  });
});
