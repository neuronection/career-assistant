import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { fetchGraph } from "@/api/jobs";
import { RelationGraph } from "@/features/catalog/components/RelationGraph";
import type { JobGraph } from "@/types/wire";

export function CatalogGraph() {
  const [graph, setGraph] = useState<JobGraph>({ nodes: [], edges: [] });
  const navigate = useNavigate();

  useEffect(() => {
    void fetchGraph().then(setGraph);
  }, []);

  return <RelationGraph graph={graph} onOpenJob={(code) => navigate(`/jobs/${code}`)} />;
}
