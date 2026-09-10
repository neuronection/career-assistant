import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchGraph } from "@/api/jobs";
import { RelationGraph } from "@/components/RelationGraph";
import type { JobGraph } from "@/types";

export function CatalogGraph() {
  const [graph, setGraph] = useState<JobGraph>({ nodes: [], edges: [] });
  const navigate = useNavigate();

  useEffect(() => {
    void fetchGraph({ depth: 2 }).then(setGraph);
  }, []);

  return <RelationGraph graph={graph} onNodeClick={(code) => navigate(`/jobs/${code}`)} />;
}
