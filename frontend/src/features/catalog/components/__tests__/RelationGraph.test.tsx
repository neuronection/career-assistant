import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { JobGraph } from "@/types/wire";

import { RelationGraph } from "../RelationGraph";
import { ROOT_FAMILIES, selectDefaultJobCodes, type RootFamily } from "../graphLayout";

const FAMILY_SIZES: Record<RootFamily, number> = {
  technology: 6,
  healthcare: 7,
  education: 2,
  engineering: 7,
  business: 6,
  creative: 2,
  "public-safety": 4,
  science: 4,
  agriculture: 4,
  hospitality: 3,
};

const FAMILY_LABELS: Record<RootFamily, string> = {
  technology: "Technology",
  healthcare: "Healthcare",
  education: "Education",
  engineering: "Engineering",
  business: "Business",
  creative: "Creative",
  "public-safety": "Public Safety",
  science: "Science",
  agriculture: "Agriculture",
  hospitality: "Hospitality",
};

function buildGraph(): JobGraph {
  const nodes: JobGraph["nodes"] = [];
  const edges: JobGraph["edges"] = [];
  const members = new Map<RootFamily, string[]>();

  for (const root of ROOT_FAMILIES) {
    const codes: string[] = [];
    for (let index = 0; index < FAMILY_SIZES[root]; index += 1) {
      const code = `${root}-job-${index}`;
      codes.push(code);
      nodes.push({
        id: code,
        code,
        title: `${FAMILY_LABELS[root]} Job ${index}`,
        family_key: `${root}-leaf`,
        demand: "steady",
      });
    }
    members.set(root, codes);
  }

  for (const codes of members.values()) {
    codes.forEach((code, index) => {
      const next = codes[(index + 1) % codes.length];
      if (next !== undefined && next !== code) {
        edges.push({ from_code: code, to_code: next, relation_type: "leads_to", weight: 0.5 });
      }
    });
  }

  edges.push(
    { from_code: "technology-job-0", to_code: "technology-job-3", relation_type: "similar_to", weight: 0.5 },
    { from_code: "technology-job-1", to_code: "technology-job-4", relation_type: "similar_to", weight: 0.5 },
    { from_code: "healthcare-job-0", to_code: "healthcare-job-1", relation_type: "similar_to", weight: 0.5 },
  );

  return { nodes, edges };
}

function renderGraph(graph: JobGraph = buildGraph(), onOpenJob = vi.fn()) {
  const view = render(<RelationGraph graph={graph} onOpenJob={onOpenJob} />);
  return { ...view, onOpenJob };
}

const pressedFilters = () =>
  ["all", "similar_to", "leads_to", "alternative_to", "prerequisite_of", "specialises_into"].filter(
    (key) => screen.getByTestId(`graph-filter-${key}`).getAttribute("aria-pressed") === "true",
  );

afterEach(() => {
  cleanup();
});

describe("RelationGraph — summary and filters", () => {
  it("shows 30 of 45 jobs with the default filter active", () => {
    const graph = buildGraph();
    renderGraph(graph);

    const summary = screen.getByTestId("graph-summary");
    expect(summary).toHaveTextContent("30 of 45 jobs");
    expect(summary.getAttribute("data-node-count")).toBe("30");
    expect(summary.getAttribute("data-edge-count")).toBe("27");
    expect(pressedFilters()).toEqual(["all"]);
  });

  it("renders every job node it counts, with a focus testid per code", () => {
    renderGraph();

    expect(screen.getAllByTestId(/^graph-focus-/)).toHaveLength(30);
    expect(screen.getByTestId("graph-focus-technology-job-0")).toBeInTheDocument();
    expect(screen.queryByTestId("graph-focus-hospitality-job-1")).toBeNull();
  });

  it("single-selects a relation filter and keeps non-matching nodes", async () => {
    const user = userEvent.setup();
    renderGraph();

    await user.click(screen.getByTestId("graph-filter-similar_to"));

    expect(pressedFilters()).toEqual(["similar_to"]);
    const summary = screen.getByTestId("graph-summary");
    expect(summary.getAttribute("data-node-count")).toBe("30");
    expect(summary.getAttribute("data-edge-count")).toBe("3");
    expect(screen.getAllByTestId(/^graph-focus-/)).toHaveLength(30);

    await user.click(screen.getByTestId("graph-filter-leads_to"));

    expect(pressedFilters()).toEqual(["leads_to"]);
    expect(screen.getByTestId("graph-summary").getAttribute("data-edge-count")).toBe("24");
  });

  it("expands to all 45 jobs and back", async () => {
    const user = userEvent.setup();
    renderGraph();

    const showAll = screen.getByTestId("graph-show-all");
    await user.click(showAll);

    expect(showAll).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("graph-summary").getAttribute("data-node-count")).toBe("45");
    expect(screen.getByTestId("graph-summary").getAttribute("data-edge-count")).toBe("48");
    expect(screen.getByTestId("graph-summary")).toHaveTextContent("45 of 45 jobs");

    await user.click(showAll);

    expect(showAll).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("graph-summary").getAttribute("data-node-count")).toBe("30");
  });
});

describe("RelationGraph — search, focus and open job", () => {
  it("searches hidden jobs, focuses the first match on Enter and clears on Escape", async () => {
    const user = userEvent.setup();
    renderGraph();

    const search = screen.getByTestId("graph-search");
    await user.type(search, "Hospitality");

    expect(screen.getByTestId("graph-summary").getAttribute("data-node-count")).toBe("3");
    expect(screen.getByTestId("graph-focus-hospitality-job-1")).toBeInTheDocument();

    await user.keyboard("{Enter}");

    expect(screen.getByTestId("graph-focus-hospitality-job-0")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("graph-open-job")).toBeInTheDocument();

    fireEvent.keyDown(search, { key: "Escape" });

    expect(search).toHaveValue("");
    expect(screen.getByTestId("graph-summary").getAttribute("data-node-count")).toBe("30");
    expect(screen.queryByTestId("graph-open-job")).toBeNull();
  });

  it("focuses a node on click and opens it from the graph panel", async () => {
    const user = userEvent.setup();
    const { onOpenJob } = renderGraph();

    expect(screen.queryByTestId("graph-open-job")).toBeNull();

    fireEvent.click(screen.getByTestId("graph-focus-technology-job-0"));

    expect(screen.getByTestId("graph-focus-technology-job-0")).toHaveAttribute("aria-pressed", "true");
    const open = screen.getByTestId("graph-open-job");
    expect(open).toHaveTextContent("Open job");

    await user.click(open);

    expect(onOpenJob).toHaveBeenCalledWith("technology-job-0");
  });

  it("focuses a node with Enter and Space, and clears focus with Escape", () => {
    renderGraph();

    const node = screen.getByTestId("graph-focus-healthcare-job-0");
    fireEvent.keyDown(node, { key: "Enter" });

    expect(screen.getByTestId("graph-open-job")).toBeInTheDocument();

    fireEvent.keyDown(screen.getByTestId("relation-graph"), { key: "Escape" });
    expect(screen.queryByTestId("graph-open-job")).toBeNull();

    fireEvent.keyDown(screen.getByTestId("graph-focus-healthcare-job-0"), { key: " " });
    expect(screen.getByTestId("graph-open-job")).toBeInTheDocument();
  });

  it("marks neighbours of the focused job", () => {
    renderGraph();

    fireEvent.click(screen.getByTestId("graph-focus-technology-job-0"));

    expect(screen.getByTestId("graph-focus-technology-job-1")).toHaveAttribute("data-neighbour", "true");
    expect(screen.getByTestId("graph-focus-technology-job-2")).toHaveAttribute("data-dimmed", "true");
  });

  it("resets filter, search and focus back to the default 30", async () => {
    const user = userEvent.setup();
    renderGraph();

    await user.click(screen.getByTestId("graph-filter-similar_to"));
    await user.type(screen.getByTestId("graph-search"), "Technology");
    fireEvent.click(screen.getByTestId("graph-focus-technology-job-0"));
    await user.click(screen.getByTestId("graph-show-all"));

    await user.click(screen.getByTestId("graph-reset"));

    expect(pressedFilters()).toEqual(["all"]);
    expect(screen.getByTestId("graph-search")).toHaveValue("");
    expect(screen.getByTestId("graph-show-all")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("graph-summary").getAttribute("data-node-count")).toBe("30");
    expect(screen.queryByTestId("graph-open-job")).toBeNull();
  });
});

describe("RelationGraph — motion and structure", () => {
  it("stages the entry animation and keeps the total under 500ms", () => {
    renderGraph();

    const node = screen.getByTestId("graph-focus-technology-job-0");
    expect(node.className).toContain("ca-graph-node-enter");

    const delays = screen
      .getAllByTestId(/^graph-focus-/)
      .map((element) =>
        Number.parseFloat(
          element.querySelector<HTMLElement>(".ca-graph-node-surface")?.style.animationDelay ?? "",
        ),
      );
    expect(Math.max(...delays)).toBeLessThanOrEqual(320);
    expect(delays.every((delay) => Number.isFinite(delay))).toBe(true);
  });

  it("drops the entry animation when reduced motion is requested", () => {
    const original = window.matchMedia;
    window.matchMedia = ((query: string) => ({
      matches: query.includes("prefers-reduced-motion"),
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    })) as never;

    try {
      renderGraph();
      const node = screen.getByTestId("graph-focus-technology-job-0");
      expect(node.className).not.toContain("ca-graph-node-enter");
      expect(node.querySelector<HTMLElement>(".ca-graph-node-surface")?.style.animationDelay ?? "").toBe(
        "",
      );
    } finally {
      window.matchMedia = original;
    }
  });

  it("keeps the measured handle set on every node", () => {
    renderGraph();

    const node = screen.getByTestId("graph-focus-technology-job-0");
    const handles = node.querySelectorAll(".react-flow__handle");
    expect(handles).toHaveLength(8);
    const ids = Array.from(handles).map((handle) => handle.getAttribute("data-handleid"));
    expect(ids.sort()).toEqual(
      ["s-bottom", "s-left", "s-right", "s-top", "t-bottom", "t-left", "t-right", "t-top"].sort(),
    );
    for (const handle of Array.from(handles)) {
      expect((handle as HTMLElement).style.visibility).toBe("hidden");
    }
  });

  it("keeps the open-job action out of the canvas", () => {
    renderGraph();
    fireEvent.click(screen.getByTestId("graph-focus-technology-job-0"));

    const openJob = screen.getByTestId("graph-open-job");
    expect(openJob.closest(".react-flow")).toBeNull();
    expect(openJob.closest('[data-testid="relation-graph"]')).not.toBeNull();
  });

  it("does not navigate on node click", () => {
    const { onOpenJob } = renderGraph();

    fireEvent.click(screen.getByTestId("graph-focus-science-job-0"));

    expect(onOpenJob).not.toHaveBeenCalled();
  });
});

describe("RelationGraph — default selection", () => {
  it("renders exactly the degree-ranked default set", () => {
    const graph = buildGraph();
    renderGraph(graph);

    const expected = selectDefaultJobCodes(graph.nodes, graph.edges);
    const rendered = screen
      .getAllByTestId(/^graph-focus-/)
      .map((element) => element.getAttribute("data-testid")?.replace("graph-focus-", ""));

    expect([...(rendered ?? [])].sort()).toEqual([...expected].sort());
  });
});
