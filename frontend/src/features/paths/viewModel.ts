import type {
  PathStepInput,
  PathView,
  PathViewEdge,
  PathViewNode,
} from "@/types";

export const PATH_START = "__start__";
export const PATH_TARGET = "__target__";

export type PathViewMode = "graph" | "tree" | "list";

export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true
  );
}

/** GRAPH is the default view; TREE is the reduced-motion fallback. */
export function defaultViewMode(): PathViewMode {
  return prefersReducedMotion() ? "tree" : "graph";
}

export interface PathViewSource {
  id: string;
  title: string;
  description?: string;
  source?: string;
  status?: string;
  job_code?: string | null;
  job_title?: string | null;
  steps?: PathStepInput[] | null;
}

/** Projects one path (wire shape) into the typed view model.

Main-chain steps (no `parent_step_id`) chain in position order and flow
into the target job. A step with `parent_step_id` is a branch subpath:
it hangs off its parent with `edge_label` as the reason, chains through
its own children, and its deepest tip rejoins the first main-chain step
positioned after it (or the target). */
export function buildPathView(path: PathViewSource): PathView {
  const steps = [...(path.steps ?? [])].sort((a, b) => a.position - b.position);
  const nodes: PathViewNode[] = steps.map((step, index) => ({
    stepId: step.id ?? `pos-${step.position}-${index}`,
    position: step.position,
    kind: step.kind,
    label: step.label || step.kind,
    optional: step.optional === true,
    familyKey: step.family_key ?? null,
    familyLabel: step.family_label ?? null,
    skillKey: step.skill_key ?? null,
    skillLabel: step.skill_label ?? null,
    educationLevel: step.education_level ?? null,
    edgeLabel: step.edge_label || null,
    branch: step.parent_step_id != null,
  }));
  const knownIds = new Set(nodes.map((node) => node.stepId));
  const childEdges = new Map<string, string[]>();
  steps.forEach((step, index) => {
    if (step.parent_step_id == null || !knownIds.has(step.parent_step_id)) return;
    childEdges.set(step.parent_step_id, [
      ...(childEdges.get(step.parent_step_id) ?? []),
      nodes[index].stepId,
    ]);
  });
  const parentOf = new Map<string, string>();
  for (const [parent, children] of childEdges) {
    for (const child of children) parentOf.set(child, parent);
  }

  const mainChain = nodes.filter((node) => !node.branch);
  const edges: PathViewEdge[] = [];
  if (mainChain.length === 0) {
    edges.push({ from: PATH_START, to: PATH_TARGET, label: "", branch: false });
  } else {
    edges.push({ from: PATH_START, to: mainChain[0].stepId, label: "", branch: false });
    mainChain.slice(0, -1).forEach((node, index) => {
      edges.push({ from: node.stepId, to: mainChain[index + 1].stepId, label: "", branch: false });
    });
    edges.push({
      from: mainChain[mainChain.length - 1].stepId,
      to: PATH_TARGET,
      label: "",
      branch: false,
    });
  }
  for (const node of nodes) {
    const parentStepId = parentOf.get(node.stepId);
    if (parentStepId == null) continue;
    edges.push({
      from: parentStepId,
      to: node.stepId,
      label: node.edgeLabel ?? "",
      branch: true,
    });
  }
  for (const node of nodes) {
    if (!node.branch || (childEdges.get(node.stepId) ?? []).length > 0) continue;
    const rejoin = mainChain.find((main) => main.position > node.position);
    edges.push({
      from: node.stepId,
      to: rejoin ? rejoin.stepId : PATH_TARGET,
      label: "",
      branch: true,
    });
  }

  return {
    id: path.id,
    title: path.title,
    description: path.description ?? "",
    status: path.status ?? "draft",
    source: path.source ?? "",
    target: { code: path.job_code ?? null, title: path.job_title ?? path.title },
    nodes,
    edges,
  };
}

export interface PathBranchTree {
  node: PathViewNode;
  children: PathBranchTree[];
}

export interface PathTreeLayout {
  /** Main-chain steps in order; each carries its branch subtrees. */
  chain: Array<{ node: PathViewNode; branches: PathBranchTree[] }>;
}

/** Tree/list projection: the linear chain with branch subpaths nested
under the step they split from. */
export function buildTreeLayout(view: PathView): PathTreeLayout {
  const parentOf = new Map<string, string>();
  for (const edge of view.edges) {
    if (edge.branch && !edge.from.startsWith("__")) parentOf.set(edge.to, edge.from);
  }
  const branchChildren = (stepId: string): PathBranchTree[] =>
    view.nodes
      .filter((node) => parentOf.get(node.stepId) === stepId)
      .sort((a, b) => a.position - b.position)
      .map((node) => ({ node, children: branchChildren(node.stepId) }));
  const chain = view.nodes
    .filter((node) => !node.branch)
    .sort((a, b) => a.position - b.position)
    .map((node) => ({ node, branches: branchChildren(node.stepId) }));
  return { chain };
}
