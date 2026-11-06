import { describe, expect, it, vi, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import axe from "axe-core";

import { PathRenderer } from "@/features/paths/PathRenderer";
import {
  buildPathView,
  buildTreeLayout,
  defaultViewMode,
  PATH_TARGET,
  prefersReducedMotion,
} from "@/features/paths/viewModel";
import type { PathStepInput } from "@/types";

const STEPS: PathStepInput[] = [
  {
    id: "s1",
    position: 0,
    kind: "education",
    label: "Finish secondary school",
    education_level: "bachelor",
  },
  {
    id: "s2",
    position: 1,
    kind: "skill",
    label: "Learn the core toolset",
    skill_key: "python",
    skill_label: "Python",
  },
  {
    id: "s3",
    position: 2,
    kind: "certification",
    label: "Entry certificate",
    optional: true,
  },
  {
    id: "b1",
    position: 3,
    kind: "experience",
    label: "Research assistant semester",
    parent_step_id: "s2",
    edge_label: "or: research track",
  },
  {
    id: "b2",
    position: 4,
    kind: "experience",
    label: "Publish a small study",
    parent_step_id: "b1",
  },
  {
    id: "s4",
    position: 5,
    kind: "job",
    label: "Junior role",
  },
];

const SOURCE = {
  id: "path-1",
  title: "Route to Data Scientist",
  description: "Study, practice, enter.",
  source: "seed",
  status: "published",
  job_code: "data-scientist",
  job_title: "Data Scientist",
  steps: STEPS,
};

function fixture() {
  return buildPathView(SOURCE);
}

function matchMedia(matches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockReturnValue({ matches, addEventListener: () => {}, removeEventListener: () => {} }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("buildPathView", () => {
  it("chains main steps in position order into the target", () => {
    const view = fixture();
    expect(view.nodes.map((node) => node.stepId)).toEqual(["s1", "s2", "s3", "b1", "b2", "s4"]);
    const plain = view.edges
      .filter((edge) => !edge.branch)
      .map((edge) => `${edge.from}->${edge.to}`);
    expect(plain).toEqual([
      "__start__->s1",
      "s1->s2",
      "s2->s3",
      "s3->s4",
      `s4->${PATH_TARGET}`,
    ]);
  });

  it("hangs branches off their parent with the edge label and rejoins", () => {
    const view = fixture();
    const branchEdges = view.edges.filter((edge) => edge.branch);
    expect(branchEdges).toContainEqual({
      from: "s2",
      to: "b1",
      label: "or: research track",
      branch: true,
    });
    expect(branchEdges).toContainEqual({ from: "b1", to: "b2", label: "", branch: true });
    expect(branchEdges).toContainEqual({ from: "b2", to: "s4", label: "", branch: true });
  });

  it("flags branch nodes and keeps entity refs", () => {
    const view = fixture();
    const b1 = view.nodes.find((node) => node.stepId === "b1");
    expect(b1?.branch).toBe(true);
    expect(b1?.edgeLabel).toBe("or: research track");
    const s2 = view.nodes.find((node) => node.stepId === "s2");
    expect(s2?.skillKey).toBe("python");
  });

  it("rejoins a branch tip at the target when no later main step exists", () => {
    const view = buildPathView({ ...SOURCE, steps: STEPS.slice(0, 5) });
    const tip = view.edges.find((edge) => edge.from === "b2");
    expect(tip?.to).toBe(PATH_TARGET);
  });

  it("builds a tree layout with branches nested under their split step", () => {
    const layout = buildTreeLayout(fixture());
    expect(layout.chain.map((entry) => entry.node.stepId)).toEqual(["s1", "s2", "s3", "s4"]);
    const s2 = layout.chain.find((entry) => entry.node.stepId === "s2");
    expect(s2?.branches.map((branch) => branch.node.stepId)).toEqual(["b1"]);
    expect(s2?.branches[0]?.children.map((child) => child.node.stepId)).toEqual(["b2"]);
  });

  it("falls back to label-less kinds and empty steps", () => {
    const view = buildPathView({ id: "p", title: "Empty", steps: [] });
    expect(view.nodes).toEqual([]);
    expect(view.edges).toEqual([{ from: "__start__", to: PATH_TARGET, label: "", branch: false }]);
  });
});

describe("defaultViewMode", () => {
  it("is graph by default and tree under reduced motion", () => {
    matchMedia(false);
    expect(prefersReducedMotion()).toBe(false);
    expect(defaultViewMode()).toBe("graph");
    matchMedia(true);
    expect(defaultViewMode()).toBe("tree");
  });
});

describe("PathRenderer projections", () => {
  it("renders the graph view by default with every step and the target", () => {
    render(<PathRenderer view={fixture()} />);
    expect(screen.getByTestId("path-renderer-graph")).toBeInTheDocument();
    expect(screen.getByTestId("path-step-graph-s1")).toHaveTextContent("Finish secondary school");
    expect(screen.getByTestId("path-renderer-target")).toHaveTextContent("Data Scientist");
    expect(screen.getByTestId("path-view-graph")).toHaveAttribute("aria-pressed", "true");
  });

  it("renders the same fixture as a tree with the branch label", () => {
    render(<PathRenderer view={fixture()} viewMode="tree" />);
    expect(screen.getByTestId("path-renderer-tree")).toBeInTheDocument();
    expect(screen.getByTestId("path-step-tree-b1")).toHaveTextContent("or: research track");
    expect(screen.getByTestId("path-renderer-tree-target")).toHaveTextContent("Data Scientist");
  });

  it("renders the same fixture as a list with branch footnotes", () => {
    render(<PathRenderer view={fixture()} viewMode="list" />);
    expect(screen.getByTestId("path-renderer-list")).toBeInTheDocument();
    expect(screen.getByTestId("path-renderer-list-branches")).toHaveTextContent(
      "Branch: or: research track"
    );
    expect(screen.getByTestId("path-step-list-b2")).toBeInTheDocument();
    expect(screen.getByTestId("path-renderer-list-target")).toHaveTextContent("Data Scientist");
  });

  it("marks optional steps", () => {
    render(<PathRenderer view={fixture()} viewMode="list" />);
    expect(screen.getByTestId("path-step-list-s3")).toHaveTextContent("optional");
  });

  it("switches views through the built-in switcher", async () => {
    const user = (await import("@testing-library/user-event")).default;
    render(<PathRenderer view={fixture()} />);
    await user.setup().click(screen.getByTestId("path-view-list"));
    expect(screen.getByTestId("path-renderer-list")).toBeInTheDocument();
  });

  it("moves focus between steps with the arrow keys", () => {
    render(<PathRenderer view={fixture()} viewMode="tree" />);
    const first = screen.getByTestId("path-step-tree-s1");
    first.focus();
    fireEvent.keyDown(screen.getByTestId("path-renderer-tree").parentElement!, {
      key: "ArrowDown",
    });
    expect(document.activeElement).toBe(screen.getByTestId("path-step-tree-s2"));
  });

  it("selects a step on click", async () => {
    const onStepClick = vi.fn();
    const user = (await import("@testing-library/user-event")).default;
    render(<PathRenderer view={fixture()} viewMode="tree" onStepClick={onStepClick} />);
    await user.setup().click(screen.getByTestId("path-step-tree-b1"));
    expect(onStepClick).toHaveBeenCalledWith("b1");
  });

  it("shows an honest empty state", () => {
    render(
      <PathRenderer view={buildPathView({ id: "p", title: "Empty", steps: [] })} viewMode="list" />
    );
    expect(screen.getByTestId("path-renderer-empty")).toBeInTheDocument();
  });
});

describe("PathRenderer a11y", () => {
  async function expectClean(mode: "graph" | "tree" | "list") {
    const { container } = render(<PathRenderer view={fixture()} viewMode={mode} />);
    const results = await axe.run(container, {
      rules: {
        "color-contrast": { enabled: false },
        region: { enabled: false },
        "landmark-one-main": { enabled: false },
      },
    });
    const violations = results.violations.map(
      (violation) => `${violation.id}: ${violation.help}`
    );
    expect(violations).toEqual([]);
  }

  it("graph view has no axe violations", async () => {
    await expectClean("graph");
  });

  it("tree view has no axe violations", async () => {
    await expectClean("tree");
  });

  it("list view has no axe violations", async () => {
    await expectClean("list");
  });
});
