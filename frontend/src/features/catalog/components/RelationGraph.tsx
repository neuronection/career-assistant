import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
} from "react";
import ReactFlow, { Background, type Edge, type Node, type ReactFlowInstance } from "reactflow";
import "reactflow/dist/style.css";
import { useTranslation } from "react-i18next";

import { Input } from "@neuronection/assistant-ui";

import { Button } from "@/components/ui/Button";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import type { JobGraph } from "@/types/wire";

import { JobNode, type JobNodeData } from "./JobNode";
import {
  DEFAULT_VISIBLE_JOBS,
  GRAPH_CARD_HEIGHT,
  GRAPH_CARD_WIDTH,
  NODE_HEIGHT,
  NODE_WIDTH,
  familyColor,
  fitViewport,
  layoutGraph,
  selectDefaultJobCodes,
} from "./graphLayout";
import { chooseNearestSides, handleId } from "./nearestEdge";

const nodeTypes = { job: JobNode };

const ENTRY_DURATION_MS = 180;
const ENTRY_TOTAL_MS = 500;

const RELATION_FILTERS = [
  "all",
  "similar_to",
  "leads_to",
  "alternative_to",
  "prerequisite_of",
  "specialises_into",
] as const;

type RelationFilter = (typeof RELATION_FILTERS)[number];

const RELATION_COLORS: Record<string, string> = {
  similar_to: "#64748b",
  leads_to: "#2563eb",
  alternative_to: "#d97706",
  prerequisite_of: "#db2777",
  specialises_into: "#7c3aed",
};

export interface RelationGraphProps {
  graph: JobGraph;
  onOpenJob?: (code: string) => void;
}

/**
 * The catalog constellation: a deterministic family-packed layout, single-select
 * relation filters, title search, node focus and one explicit navigation action.
 *
 * Navigation deliberately lives in the `Open job` panel — clicking a node only
 * focuses it, so a stray click never leaves the graph.
 */
export function RelationGraph({ graph, onOpenJob }: RelationGraphProps) {
  const { t } = useTranslation();
  const reducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const [filter, setFilter] = useState<RelationFilter>("all");
  const [search, setSearch] = useState("");
  const [focused, setFocused] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const [canvasSize, setCanvasSize] = useState({ width: GRAPH_CARD_WIDTH, height: GRAPH_CARD_HEIGHT });
  const [instance, setInstance] = useState<ReactFlowInstance | null>(null);

  useEffect(() => {
    const element = canvasRef.current;
    if (element === null || typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(() => {
      const rect = element.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        setCanvasSize({ width: rect.width, height: rect.height });
      }
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const defaultCodes = useMemo(
    () => selectDefaultJobCodes(graph.nodes, graph.edges, DEFAULT_VISIBLE_JOBS),
    [graph],
  );

  const searchResults = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (term === "") {
      return [] as JobGraph["nodes"];
    }
    return graph.nodes
      .filter((node) => node.title.toLowerCase().includes(term) || node.code.includes(term))
      .sort((a, b) => a.title.localeCompare(b.title) || a.code.localeCompare(b.code));
  }, [graph, search]);

  const visibleCodes = useMemo(() => {
    if (search.trim() !== "") {
      return new Set(searchResults.map((node) => node.code));
    }
    return new Set(showAll ? graph.nodes.map((node) => node.code) : defaultCodes);
  }, [graph, search, searchResults, showAll, defaultCodes]);

  const visibleEdges = useMemo(
    () =>
      graph.edges.filter(
        (edge) =>
          visibleCodes.has(edge.from_code) &&
          visibleCodes.has(edge.to_code) &&
          (filter === "all" || edge.relation_type === filter),
      ),
    [graph, visibleCodes, filter],
  );

  const neighbours = useMemo(() => {
    const codes = new Set<string>();
    if (focused === null) {
      return codes;
    }
    for (const edge of graph.edges) {
      if (edge.from_code === focused) {
        codes.add(edge.to_code);
      }
      if (edge.to_code === focused) {
        codes.add(edge.from_code);
      }
    }
    return codes;
  }, [graph, focused]);

  const connectedByFilter = useMemo(() => {
    const codes = new Set<string>();
    for (const edge of visibleEdges) {
      codes.add(edge.from_code);
      codes.add(edge.to_code);
    }
    return codes;
  }, [visibleEdges]);

  const visibleNodes = useMemo(
    () => graph.nodes.filter((node) => visibleCodes.has(node.code)),
    [graph, visibleCodes],
  );

  const layout = useMemo(
    () =>
      layoutGraph(
        visibleNodes,
        graph.edges.filter(
          (edge) => visibleCodes.has(edge.from_code) && visibleCodes.has(edge.to_code),
        ),
      ),
    [visibleNodes, graph, visibleCodes],
  );

  const viewport = useMemo(
    () =>
      fitViewport(layout.positions, {
        width: canvasSize.width,
        height: canvasSize.height,
      }),
    [layout, canvasSize],
  );

  useEffect(() => {
    if (instance !== null) {
      void instance.setViewport(viewport, { duration: 0 });
    }
  }, [instance, viewport]);

  const handleSelect = useCallback((code: string) => {
    setFocused((current) => (current === code ? null : code));
  }, []);

  const reset = useCallback(() => {
    setFilter("all");
    setSearch("");
    setFocused(null);
    setShowAll(false);
  }, []);

  const staggered = useMemo(
    () =>
      [...visibleNodes].sort((a, b) => {
        const positionA = layout.positions[a.code];
        const positionB = layout.positions[b.code];
        if (positionA === undefined || positionB === undefined) {
          return a.code.localeCompare(b.code);
        }
        return positionA.y - positionB.y || positionA.x - positionB.x;
      }),
    [visibleNodes, layout],
  );
  const staggerMs = Math.min(25, ENTRY_TOTAL_MS / Math.max(1, staggered.length));
  const maxDelayMs = ENTRY_TOTAL_MS - ENTRY_DURATION_MS;

  const flowNodes: Node<JobNodeData>[] = staggered.map((node, index) => {
    const position = layout.positions[node.code] ?? { x: 0, y: 0 };
    const isFocused = focused === node.code;
    const isNeighbour = neighbours.has(node.code);
    const mutedByFilter = filter !== "all" && !connectedByFilter.has(node.code);
    const mutedByFocus = focused !== null && !isFocused && !isNeighbour;
    return {
      id: node.code,
      type: "job",
      position,
      draggable: false,
      connectable: false,
      selectable: false,
      data: {
        code: node.code,
        title: node.title,
        familyRoot: layout.families[node.code] ?? null,
        color: familyColor(node.family_key),
        focused: isFocused,
        neighbour: isNeighbour,
        dimmed: mutedByFilter || mutedByFocus,
        animate: !reducedMotion,
        delayMs: Math.min(index * staggerMs, maxDelayMs),
        onSelect: handleSelect,
      },
    };
  });

  const flowEdges: Edge[] = visibleEdges.map((edge) => {
    const sourcePosition = layout.positions[edge.from_code] ?? { x: 0, y: 0 };
    const targetPosition = layout.positions[edge.to_code] ?? { x: 0, y: 0 };
    const sides = chooseNearestSides(
      { ...sourcePosition, width: NODE_WIDTH, height: NODE_HEIGHT },
      { ...targetPosition, width: NODE_WIDTH, height: NODE_HEIGHT },
    );
    const incident = focused === null || edge.from_code === focused || edge.to_code === focused;
    return {
      id: `${edge.from_code}->${edge.to_code}:${edge.relation_type}`,
      source: edge.from_code,
      target: edge.to_code,
      sourceHandle: handleId("source", sides.source),
      targetHandle: handleId("target", sides.target),
      animated: false,
      selectable: false,
      className: "ca-graph-edge",
      style: {
        stroke: RELATION_COLORS[edge.relation_type] ?? "#94a3b8",
        strokeWidth: 0.8 + edge.weight * 1.2,
        opacity: focused === null ? 0.35 : incident ? 0.7 : 0.08,
      },
    };
  });

  const focusedNode = focused === null ? undefined : graph.nodes.find((node) => node.code === focused);
  const legendTypes = useMemo(() => {
    const types = new Set(graph.edges.map((edge) => edge.relation_type));
    return RELATION_FILTERS.filter((key) => key !== "all" && types.has(key));
  }, [graph]);

  const handleSearchKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      const first = searchResults[0];
      if (first !== undefined) {
        event.preventDefault();
        setFocused(first.code);
      }
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setSearch("");
      setFocused(null);
    }
  };

  const filterLabel = (key: RelationFilter) => {
    switch (key) {
      case "all":
        return t("catalog.graphViewer.filterAll");
      case "similar_to":
        return t("catalog.graphViewer.filterSimilar");
      case "leads_to":
        return t("catalog.graphViewer.filterLeads");
      case "alternative_to":
        return t("catalog.graphViewer.filterAlternative");
      case "prerequisite_of":
        return t("catalog.graphViewer.filterPrerequisite");
      case "specialises_into":
        return t("catalog.graphViewer.filterSpecialises");
    }
  };

  return (
    <div
      role="region"
      aria-label={t("catalog.graphViewer.title")}
      className="rounded-xl border border-slate-200 bg-white"
      data-testid="relation-graph"
      onKeyDown={(event) => {
        if (event.key === "Escape" && (focused !== null || search !== "")) {
          setFocused(null);
          setSearch("");
        }
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-3 py-2">
        <span
          className="text-xs font-medium tabular-nums text-slate-600"
          data-testid="graph-summary"
          data-node-count={visibleCodes.size}
          data-edge-count={visibleEdges.length}
        >
          {t("catalog.graphViewer.summary", { visible: visibleCodes.size, total: graph.nodes.length })}
          {" · "}
          {t("catalog.graphViewer.relations", { count: visibleEdges.length })}
        </span>
        <div className="flex flex-wrap items-center gap-2">
          {focusedNode !== undefined && onOpenJob !== undefined && (
            <Button
              type="button"
              size="sm"
              className="min-h-11"
              onClick={() => onOpenJob(focusedNode.code)}
              data-testid="graph-open-job"
            >
              {t("catalog.graphViewer.openJob")}
            </Button>
          )}
          <Input
            type="search"
            value={search}
            onChange={(event: ChangeEvent<HTMLInputElement>) => setSearch(event.target.value)}
            onKeyDown={handleSearchKeyDown}
            placeholder={t("catalog.graphViewer.search")}
            aria-label={t("catalog.graphViewer.search")}
            className="h-11 w-44"
            data-testid="graph-search"
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-pressed={showAll}
            onClick={() => setShowAll((current) => !current)}
            className={`min-h-11 ${showAll ? "border-primary-600 bg-primary-50 text-primary-700" : ""}`}
            data-testid="graph-show-all"
          >
            {showAll
              ? t("catalog.graphViewer.showDefault", { count: DEFAULT_VISIBLE_JOBS })
              : t("catalog.graphViewer.showAll", { count: graph.nodes.length })}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={reset}
            className="min-h-11"
            data-testid="graph-reset"
          >
            {t("catalog.graphViewer.reset")}
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-3 py-2">
        <div
          role="group"
          aria-label={t("catalog.graphViewer.filterLabel")}
          className="flex flex-wrap items-center gap-1"
        >
          {RELATION_FILTERS.map((key) => {
            const active = filter === key;
            return (
              <Button
                key={key}
                type="button"
                size="sm"
                variant={active ? "default" : "outline"}
                aria-pressed={active}
                onClick={() => setFilter(key)}
                className="min-h-11 rounded-full text-xs"
                data-testid={`graph-filter-${key}`}
              >
                {filterLabel(key)}
              </Button>
            );
          })}
        </div>
        {legendTypes.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 pl-1" aria-hidden="true">
            {legendTypes.map((type) => (
              <span key={type} className="flex items-center gap-1 text-[10px] text-slate-500">
                <span
                  className="inline-block size-1.5 rounded-full"
                  style={{ background: RELATION_COLORS[type] }}
                />
                {t(`shared.relation.${type}`)}
              </span>
            ))}
          </div>
        )}
      </div>

      <div ref={canvasRef} className="h-[480px] bg-slate-50">
        <ReactFlow
          nodes={flowNodes}
          edges={flowEdges}
          nodeTypes={nodeTypes}
          defaultViewport={viewport}
          onInit={setInstance}
          minZoom={0.5}
          maxZoom={1.6}
          nodesDraggable={false}
          nodesConnectable={false}
          nodesFocusable={false}
          elementsSelectable={false}
          zoomOnDoubleClick={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={24} />
        </ReactFlow>
      </div>
    </div>
  );
}
