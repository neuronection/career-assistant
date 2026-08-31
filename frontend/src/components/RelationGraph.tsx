import ReactFlow, { Background, type Edge, type Node } from "reactflow";
import "reactflow/dist/style.css";
import type { JobGraph } from "@/types";

const FAMILY_COLORS: Record<string, string> = {
  technology: "#2563eb",
  healthcare: "#dc2626",
  education: "#d97706",
  engineering: "#7c3aed",
  business: "#059669",
  creative: "#db2777",
  "public-safety": "#475569",
  science: "#0891b2",
  agriculture: "#65a30d",
  hospitality: "#ea580c",
};

export function RelationGraph({ graph, onNodeClick }: { graph: JobGraph; onNodeClick?: (code: string) => void }) {
  const nodes: Node[] = graph.nodes.map((n, i) => {
    const root = n.code === graph.nodes[0]?.id;
    const angle = (2 * Math.PI * i) / Math.max(1, graph.nodes.length);
    return {
      id: n.id,
      position: {
        x: Math.cos(angle) * (root ? 0 : 220) + (root ? 0 : Math.sin(i * 7) * 40),
        y: Math.sin(angle) * (root ? 0 : 160) + (root ? 0 : Math.cos(i * 5) * 30),
      },
      data: { label: n.title },
      style: {
        background: FAMILY_COLORS[n.family_key.split("/")[0]] ?? "#64748b",
        color: "#fff",
        border: "none",
        borderRadius: 10,
        padding: 8,
        fontSize: 12,
        width: 150,
      },
    };
  });
  const edges: Edge[] = graph.edges.map((e, i) => ({
    id: `e${i}`,
    source: e.from_code,
    target: e.to_code,
    label: e.relation_type.replace(/_/g, " "),
    animated: e.relation_type === "leads_to",
    style: { stroke: "#94a3b8", width: 1 + e.weight * 2 },
    labelStyle: { fontSize: 10, fill: "#475569" },
  }));
  return (
    <div className="h-[480px] bg-slate-50 rounded-xl border border-slate-200" data-testid="relation-graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        minZoom={0.2}
        onNodeClick={(_, node) => onNodeClick?.(node.id)}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={24} />
      </ReactFlow>
    </div>
  );
}
