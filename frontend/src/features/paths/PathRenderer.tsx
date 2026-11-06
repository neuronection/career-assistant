import { useMemo, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { Background, type Edge, type Node, NodeProps, Position, ReactFlow } from "reactflow";
import "reactflow/dist/style.css";
import {
  Award,
  Briefcase,
  Flag,
  GraduationCap,
  ListOrdered,
  Network,
  Target,
  TreePine,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import type { PathView, PathViewNode } from "@/types";
import {
  buildTreeLayout,
  defaultViewMode,
  PATH_TARGET,
  type PathBranchTree,
  type PathViewMode,
} from "@/features/paths/viewModel";

const KIND_ICONS: Record<string, LucideIcon> = {
  job: Briefcase,
  skill: Wrench,
  education: GraduationCap,
  certification: Award,
  experience: Briefcase,
  milestone: Flag,
};

const VIEW_ORDER: PathViewMode[] = ["graph", "tree", "list"];

function KindIcon({ kind }: { kind: string }) {
  const Icon = KIND_ICONS[kind] ?? Flag;
  return <Icon className="size-3.5 shrink-0" aria-hidden />;
}

function StepButton({
  node,
  selected,
  onSelect,
  testPrefix,
  compact,
}: {
  node: PathViewNode;
  selected: boolean;
  onSelect?: (stepId: string) => void;
  testPrefix: string;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      data-path-step
      data-testid={`${testPrefix}-${node.stepId}`}
      aria-pressed={selected}
      onClick={() => onSelect?.(node.stepId)}
      className={`flex w-full items-start gap-2 rounded-[var(--as-radius)] border text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)] ${
        selected
          ? "border-[var(--as-accent)] bg-[color-mix(in_srgb,var(--as-accent)_10%,transparent)]"
          : "border-[var(--as-border)] bg-[var(--as-surface)] hover:border-[var(--as-accent)]"
      } ${compact ? "px-2 py-1" : "px-2.5 py-1.5"}`}
    >
      <KindIcon kind={node.kind} />
      <span className="min-w-0">
        <span className={`block font-medium text-[var(--as-fg)] ${compact ? "text-xs" : "text-sm"}`}>
          {node.label}
          {node.optional ? (
            <span className="ml-1 text-[10px] uppercase tracking-wide text-[var(--as-muted-fg)]">
              {t("paths.renderer.optional")}
            </span>
          ) : null}
        </span>
        {node.edgeLabel ? (
          <span className={`block text-[var(--as-accent)] ${compact ? "text-[10px]" : "text-xs"}`}>
            {node.edgeLabel}
          </span>
        ) : null}
        {!compact && (node.skillLabel || node.familyLabel || node.educationLevel) ? (
          <span className="block text-xs text-[var(--as-muted-fg)]">
            {[node.skillLabel, node.familyLabel, node.educationLevel].filter(Boolean).join(" · ")}
          </span>
        ) : null}
      </span>
    </button>
  );
}

function nodeDepth(view: PathView): Map<string, number> {
  const depth = new Map<string, number>();
  const incoming = new Map<string, string[]>();
  for (const edge of view.edges) {
    incoming.set(edge.to, [...(incoming.get(edge.to) ?? []), edge.from]);
  }
  const resolve = (id: string, seen: Set<string>): number => {
    if (depth.has(id)) return depth.get(id)!;
    if (seen.has(id)) return 0;
    seen.add(id);
    const parents = incoming.get(id) ?? [];
    const value =
      parents.length === 0
        ? 0
        : 1 + Math.max(...parents.map((parent) => resolve(parent, seen)));
    depth.set(id, value);
    return value;
  };
  for (const node of view.nodes) resolve(node.stepId, new Set());
  resolve(PATH_TARGET, new Set());
  return depth;
}

function GraphView({
  view,
  selectedStepId,
  onStepClick,
  onTargetClick,
}: {
  view: PathView;
  selectedStepId?: string | null;
  onStepClick?: (stepId: string) => void;
  onTargetClick?: () => void;
}) {
  const { t } = useTranslation();
  const nodeTypes = useMemo(() => ({ step: StepNode, target: TargetNode }), []);
  const depth = useMemo(() => nodeDepth(view), [view]);
  const byLayer = new Map<number, PathViewNode[]>();
  for (const node of view.nodes) {
    const layer = depth.get(node.stepId) ?? 0;
    byLayer.set(layer, [...(byLayer.get(layer) ?? []), node]);
  }
  const nodes: Node[] = view.nodes.map((node) => ({
    id: node.stepId,
    type: "step",
    position: {
      x: (depth.get(node.stepId) ?? 0) * 230,
      y: ((byLayer.get(depth.get(node.stepId) ?? 0) ?? []).indexOf(node)) * 90,
    },
    data: {
      node,
      selected: selectedStepId === node.stepId,
      onSelect: onStepClick,
    },
  }));
  nodes.push({
    id: PATH_TARGET,
    type: "target",
    position: { x: (depth.get(PATH_TARGET) ?? 0) * 230, y: 0 },
    data: { label: view.target.title, onClick: onTargetClick },
  });
  const edges: Edge[] = view.edges.map((edge, index) => ({
    id: `edge-${index}`,
    source: edge.from,
    target: edge.to,
    label: edge.label || undefined,
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    style: edge.branch
      ? { stroke: "var(--as-accent)", strokeDasharray: "4 3", width: 1.5 }
      : { stroke: "var(--as-border)", width: 1.5 },
    labelStyle: { fontSize: 10, fill: "var(--as-muted-fg)" },
  }));
  return (
    <div
      className="h-[380px] rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-muted)]"
      data-testid="path-renderer-graph"
      role="group"
      aria-label={t("paths.renderer.graphAria", { title: view.title })}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        minZoom={0.2}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
      >
        <Background gap={24} />
      </ReactFlow>
    </div>
  );
}

function StepNode({ data }: NodeProps) {
  const { node, selected, onSelect } = data as {
    node: PathViewNode;
    selected: boolean;
    onSelect?: (stepId: string) => void;
  };
  return (
    <div className="w-[190px]">
      <StepButton
        node={node}
        selected={selected}
        onSelect={onSelect}
        testPrefix="path-step-graph"
        compact
      />
    </div>
  );
}

function TargetNode({ data }: NodeProps) {
  const { t } = useTranslation();
  const { label, onClick } = data as { label: string; onClick?: () => void };
  return (
    <button
      type="button"
      data-testid="path-renderer-target"
      onClick={onClick}
      aria-label={t("paths.renderer.targetAria", { job: label })}
      className="flex w-[190px] items-center gap-2 rounded-[var(--as-radius)] border-2 border-[var(--as-accent)] bg-[var(--as-surface-raised)] px-2.5 py-2 text-left text-sm font-semibold text-[var(--as-fg)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)]"
    >
      <Target className="size-4 shrink-0 text-[var(--as-accent)]" aria-hidden />
      <span className="min-w-0 truncate">{label}</span>
    </button>
  );
}

function BranchSubtree({
  tree,
  selectedStepId,
  onStepClick,
  testPrefix,
}: {
  tree: PathBranchTree;
  selectedStepId?: string | null;
  onStepClick?: (stepId: string) => void;
  testPrefix: string;
}) {
  return (
    <li className="ml-4 border-l border-[var(--as-border)] pl-3">
      <StepButton
        node={tree.node}
        selected={selectedStepId === tree.node.stepId}
        onSelect={onStepClick}
        testPrefix={testPrefix}
      />
      {tree.children.length > 0 ? (
        <ul className="mt-1 flex flex-col gap-1">
          {tree.children.map((child) => (
            <BranchSubtree
              key={child.node.stepId}
              tree={child}
              selectedStepId={selectedStepId}
              onStepClick={onStepClick}
              testPrefix={testPrefix}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function TreeView({
  view,
  selectedStepId,
  onStepClick,
}: {
  view: PathView;
  selectedStepId?: string | null;
  onStepClick?: (stepId: string) => void;
}) {
  const { t } = useTranslation();
  const layout = buildTreeLayout(view);
  return (
    <div
      data-testid="path-renderer-tree"
      role="group"
      aria-label={t("paths.renderer.treeAria", { title: view.title })}
    >
      <ul className="flex flex-col gap-1.5">
        {layout.chain.map(({ node, branches }) => (
          <li key={node.stepId} className="flex flex-col gap-1">
            <StepButton
              node={node}
              selected={selectedStepId === node.stepId}
              onSelect={onStepClick}
              testPrefix="path-step-tree"
            />
            {branches.length > 0 ? (
              <ul className="flex flex-col gap-1">
                {branches.map((branch) => (
                  <BranchSubtree
                    key={branch.node.stepId}
                    tree={branch}
                    selectedStepId={selectedStepId}
                    onStepClick={onStepClick}
                    testPrefix="path-step-tree"
                  />
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ul>
      {view.target.title ? (
        <p
          className="mt-2 flex items-center gap-2 border-t border-[var(--as-border)] pt-2 text-sm font-semibold text-[var(--as-fg)]"
          data-testid="path-renderer-tree-target"
        >
          <Target className="size-4 text-[var(--as-accent)]" aria-hidden />
          {t("paths.renderer.leadsTo", { job: view.target.title })}
        </p>
      ) : null}
    </div>
  );
}

function ListView({
  view,
  selectedStepId,
  onStepClick,
}: {
  view: PathView;
  selectedStepId?: string | null;
  onStepClick?: (stepId: string) => void;
}) {
  const { t } = useTranslation();
  const layout = buildTreeLayout(view);
  const branchRoots = layout.chain.flatMap((entry) => entry.branches);
  const hasBranches = branchRoots.length > 0;
  return (
    <div data-testid="path-renderer-list">
      <ol className="flex flex-col gap-1.5">
        {layout.chain.map(({ node }, index) => (
          <li key={node.stepId} className="flex items-start gap-2">
            <span
              className="mt-1 flex size-5 shrink-0 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--as-accent)_15%,transparent)] text-[11px] font-semibold text-[var(--as-accent)]"
              aria-hidden
            >
              {index + 1}
            </span>
            <div className="min-w-0 flex-1">
              <StepButton
                node={node}
                selected={selectedStepId === node.stepId}
                onSelect={onStepClick}
                testPrefix="path-step-list"
              />
              {node.edgeLabel ? (
                <span className="sr-only">{node.edgeLabel}</span>
              ) : null}
            </div>          </li>
        ))}
      </ol>
      {hasBranches ? (
        <div
          className="mt-3 border-t border-[var(--as-border)] pt-2"
          data-testid="path-renderer-list-branches"
        >
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
            {t("paths.renderer.branchesHeading")}
          </p>
          <ul className="flex flex-col gap-1.5">
            {branchRoots.map((branch) => (
              <li key={branch.node.stepId}>
                <p className="text-xs text-[var(--as-accent)]">
                  {t("paths.renderer.viaBranch", {
                    label: branch.node.edgeLabel || t("paths.renderer.branchFallback"),
                  })}
                </p>
                <ul className="mt-1 flex flex-col gap-1">
                  <BranchSubtree
                    tree={branch}
                    selectedStepId={selectedStepId}
                    onStepClick={onStepClick}
                    testPrefix="path-step-list"
                  />
                </ul>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {view.target.title ? (
        <p
          className="mt-2 flex items-center gap-2 border-t border-[var(--as-border)] pt-2 text-sm font-semibold text-[var(--as-fg)]"
          data-testid="path-renderer-list-target"
        >
          <Target className="size-4 text-[var(--as-accent)]" aria-hidden />
          {t("paths.renderer.leadsTo", { job: view.target.title })}
        </p>
      ) : null}
    </div>
  );
}

/** The modular career-path renderer: one typed `PathView`, three
projections. GRAPH is the default view, TREE the reduced-motion fallback,
LIST the flat alternative; steps are focusable and Enter/click selects. */
export function PathRenderer({
  view,
  viewMode,
  onViewModeChange,
  onStepClick,
  onTargetClick,
  selectedStepId,
  compact,
}: {
  view: PathView;
  viewMode?: PathViewMode;
  onViewModeChange?: (mode: PathViewMode) => void;
  onStepClick?: (stepId: string) => void;
  onTargetClick?: () => void;
  selectedStepId?: string | null;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  // Compact hosts (chat bubbles) start in the linear list; full hosts
  // follow the graph-default discipline (tree under reduced motion).
  const [internalMode, setInternalMode] = useState<PathViewMode>(() =>
    compact ? "list" : defaultViewMode(),
  );
  const mode = viewMode ?? internalMode;
  const setMode = (next: PathViewMode) => {
    setInternalMode(next);
    onViewModeChange?.(next);
  };
  const moveFocus = (event: KeyboardEvent<HTMLDivElement>, offset: number) => {
    const steps = Array.from(
      event.currentTarget.querySelectorAll<HTMLButtonElement>("[data-path-step]"),
    );
    const index = steps.indexOf(document.activeElement as HTMLButtonElement);
    const next = steps[index + offset];
    if (next) {
      event.preventDefault();
      next.focus();
    }
  };
  const viewLabels: Record<PathViewMode, { label: string; icon: LucideIcon }> = {
    graph: { label: t("paths.renderer.viewGraph"), icon: Network },
    tree: { label: t("paths.renderer.viewTree"), icon: TreePine },
    list: { label: t("paths.renderer.viewList"), icon: ListOrdered },
  };
  return (
    <div data-testid="path-renderer">
      {!compact ? (
        <div
          role="group"
          aria-label={t("paths.renderer.viewSwitcherAria")}
          className="mb-2 inline-flex rounded-[var(--as-radius)] border border-[var(--as-border)] p-0.5"
          data-testid="path-view-switcher"
        >
          {VIEW_ORDER.map((entry) => {
            const { label, icon: Icon } = viewLabels[entry];
            return (
              <button
                key={entry}
                type="button"
                aria-pressed={mode === entry}
                data-testid={`path-view-${entry}`}
                onClick={() => setMode(entry)}
                className={`inline-flex items-center gap-1 rounded-[calc(var(--as-radius)*0.6)] px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)] ${
                  mode === entry
                    ? "bg-[var(--as-accent)] text-[var(--as-accent-fg)]"
                    : "text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
                }`}
              >
                <Icon className="size-3.5" aria-hidden />
                {label}
              </button>
            );
          })}
        </div>
      ) : null}
      <div
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") moveFocus(event, 1);
          if (event.key === "ArrowUp") moveFocus(event, -1);
        }}
      >
        {view.nodes.length === 0 ? (
          <p className="text-sm text-[var(--as-muted-fg)]" data-testid="path-renderer-empty">
            {t("paths.renderer.empty")}
          </p>
        ) : mode === "graph" ? (
          <GraphView
            view={view}
            selectedStepId={selectedStepId}
            onStepClick={onStepClick}
            onTargetClick={onTargetClick}
          />
        ) : mode === "tree" ? (
          <TreeView
            view={view}
            selectedStepId={selectedStepId}
            onStepClick={onStepClick}
          />
        ) : (
          <ListView
            view={view}
            selectedStepId={selectedStepId}
            onStepClick={onStepClick}
          />
        )}
      </div>
    </div>
  );
}
