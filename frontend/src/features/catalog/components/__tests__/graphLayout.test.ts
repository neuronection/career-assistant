import { describe, expect, it } from "vitest";

import {
  COMFORT_DX,
  DEFAULT_VISIBLE_JOBS,
  EDGE_CHORD_MIN,
  FALLBACK_FAMILY_COLOR,
  FAMILY_COLORS,
  MIN_DX,
  MIN_DY,
  NODE_FONT_SIZE,
  NODE_HEIGHT,
  NODE_WIDTH,
  ROOT_FAMILIES,
  edgeChord,
  familyAnchor,
  familyColor,
  fitViewport,
  layoutGraph,
  relationDegrees,
  resolveRootFamily,
  selectDefaultJobCodes,
  type LayoutJob,
  type LayoutRelation,
  type RootFamily,
} from "../graphLayout";

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

const LEAF_SUFFIX: Record<RootFamily, string> = {
  technology: "software",
  healthcare: "clinical",
  education: "schools",
  engineering: "mechanical",
  business: "operations",
  creative: "design",
  "public-safety": "fire",
  science: "research",
  agriculture: "agronomy",
  hospitality: "hotels",
};

function buildJobs(): LayoutJob[] {
  const jobs: LayoutJob[] = [];
  for (const root of ROOT_FAMILIES) {
    for (let index = 0; index < FAMILY_SIZES[root]; index += 1) {
      jobs.push({
        code: `${root}-job-${index}`,
        title: `${root} ${index}`,
        family_key: `${root}-${LEAF_SUFFIX[root]}`,
      });
    }
  }
  return jobs;
}

/** A chain per family plus cross-family bridges, like the shipped catalog. */
function buildEdges(jobs: LayoutJob[]): LayoutRelation[] {
  const byRoot = new Map<string, LayoutJob[]>();
  for (const job of jobs) {
    const root = resolveRootFamily(job.family_key) ?? "unknown";
    const members = byRoot.get(root) ?? [];
    members.push(job);
    byRoot.set(root, members);
  }
  const edges: LayoutRelation[] = [];
  for (const members of byRoot.values()) {
    members.slice(0, -1).forEach((member, index) => {
      const next = members[index + 1];
      if (next !== undefined) {
        edges.push({ from_code: member.code, to_code: next.code, relation_type: "leads_to", weight: 0.5 });
      }
    });
  }
  edges.push(
    { from_code: "technology-job-0", to_code: "healthcare-job-0", relation_type: "similar_to", weight: 0.5 },
    { from_code: "engineering-job-0", to_code: "business-job-0", relation_type: "similar_to", weight: 0.5 },
  );
  return edges;
}

function expectNoOverlap(positions: Record<string, { x: number; y: number }>): void {
  const points = Object.entries(positions);
  for (let first = 0; first < points.length; first += 1) {
    for (let second = first + 1; second < points.length; second += 1) {
      const a = points[first];
      const b = points[second];
      if (a === undefined || b === undefined) {
        continue;
      }
      const dx = Math.abs(a[1].x - b[1].x);
      const dy = Math.abs(a[1].y - b[1].y);
      expect(dx >= MIN_DX || dy >= MIN_DY).toBe(true);
    }
  }
}

describe("resolveRootFamily", () => {
  it("resolves every root key to itself", () => {
    for (const root of ROOT_FAMILIES) {
      expect(resolveRootFamily(root)).toBe(root);
    }
  });

  it("resolves a leaf key to its root", () => {
    for (const root of ROOT_FAMILIES) {
      expect(resolveRootFamily(`${root}-${LEAF_SUFFIX[root]}`)).toBe(root);
      expect(resolveRootFamily(`${root}-${LEAF_SUFFIX[root]}-senior`)).toBe(root);
    }
  });

  it("keeps the hyphenated public-safety root whole", () => {
    expect(resolveRootFamily("public-safety")).toBe("public-safety");
    expect(resolveRootFamily("public-safety-fire")).toBe("public-safety");
  });

  it("resolves business-creative to business, not creative", () => {
    expect(resolveRootFamily("business-creative")).toBe("business");
  });

  it("never resolves an unknown key", () => {
    expect(resolveRootFamily("space-mining")).toBeNull();
    expect(resolveRootFamily("technologist")).toBeNull();
    expect(resolveRootFamily(null)).toBeNull();
    expect(resolveRootFamily("")).toBeNull();
  });
});

describe("familyColor", () => {
  it("gives every root a distinct, non-fallback fill", () => {
    const colors = ROOT_FAMILIES.map((root) => familyColor(root));
    expect(new Set(colors).size).toBe(ROOT_FAMILIES.length);
    for (const color of colors) {
      expect(color).not.toBe(FALLBACK_FAMILY_COLOR);
    }
  });

  it("keeps public-safety distinct from the unknown-family fallback", () => {
    expect(FAMILY_COLORS["public-safety"]).not.toBe(FALLBACK_FAMILY_COLOR);
    expect(familyColor("public-safety-fire")).not.toBe(familyColor("space-mining"));
  });

  it("is stable for leaf keys and never slate for a known root", () => {
    for (const root of ROOT_FAMILIES) {
      expect(familyColor(`${root}-${LEAF_SUFFIX[root]}`)).toBe(FAMILY_COLORS[root]);
    }
  });

  it("uses the fallback only for unknown families", () => {
    expect(familyColor("space-mining")).toBe(FALLBACK_FAMILY_COLOR);
    expect(familyColor(null)).toBe(FALLBACK_FAMILY_COLOR);
  });

  it("keeps white labels at AA contrast on every family fill", () => {
    const luminance = (hex: string) => {
      const value = hex.replace("#", "");
      const channels = [0, 2, 4].map((offset) => Number.parseInt(value.slice(offset, offset + 2), 16) / 255);
      const [red, green, blue] = channels.map((channel) =>
        channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
      ) as [number, number, number];
      return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
    };
    for (const color of [...ROOT_FAMILIES.map((root) => FAMILY_COLORS[root]), FALLBACK_FAMILY_COLOR]) {
      expect(1.05 / (luminance(color) + 0.05)).toBeGreaterThanOrEqual(4.5);
    }
  });
});

describe("layoutGraph", () => {
  const jobs = buildJobs();
  const edges = buildEdges(jobs);

  it("lays out every job exactly once", () => {
    const layout = layoutGraph(jobs, edges);
    expect(Object.keys(layout.positions)).toHaveLength(jobs.length);
    for (const job of jobs) {
      expect(layout.positions[job.code]).toBeDefined();
      expect(layout.families[job.code]).not.toBeNull();
    }
  });

  it("is deterministic", () => {
    expect(layoutGraph(jobs, edges)).toEqual(layoutGraph(jobs, edges));
  });

  it("never overlaps two boxes at the default set", () => {
    const codes = new Set(selectDefaultJobCodes(jobs, edges));
    const visible = jobs.filter((job) => codes.has(job.code));
    const layout = layoutGraph(
      visible,
      edges.filter((edge) => codes.has(edge.from_code) && codes.has(edge.to_code)),
    );
    expectNoOverlap(layout.positions);
  });

  it("never overlaps two boxes at the full 45-job set", () => {
    expectNoOverlap(layoutGraph(jobs, edges).positions);
  });

  it("keeps every connected pair's edge long enough to read", () => {
    const codes = new Set(selectDefaultJobCodes(jobs, edges));
    const visible = jobs.filter((job) => codes.has(job.code));
    const visibleEdges = edges.filter(
      (edge) => codes.has(edge.from_code) && codes.has(edge.to_code),
    );
    const layout = layoutGraph(visible, visibleEdges);
    for (const edge of visibleEdges) {
      const source = layout.positions[edge.from_code];
      const target = layout.positions[edge.to_code];
      expect(source).toBeDefined();
      expect(target).toBeDefined();
      if (source !== undefined && target !== undefined) {
        expect(edgeChord(source, target)).toBeGreaterThanOrEqual(EDGE_CHORD_MIN);
      }
    }
  });

  it("keeps a readable rendered label at the fitted zoom", () => {
    const codes = new Set(selectDefaultJobCodes(jobs, edges));
    const visible = jobs.filter((job) => codes.has(job.code));
    const layout = layoutGraph(
      visible,
      edges.filter((edge) => codes.has(edge.from_code) && codes.has(edge.to_code)),
    );
    expect(layout.viewport.zoom).toBeGreaterThanOrEqual(0.55);
    expect(NODE_FONT_SIZE * layout.viewport.zoom).toBeGreaterThanOrEqual(9.5);
    expect(layout.viewport.zoom).toBeLessThanOrEqual(1.15);
  });

  it("keeps families closer to themselves than to other families", () => {
    const layout = layoutGraph(jobs, edges);
    const byRoot = new Map<string, Array<{ x: number; y: number }>>();
    for (const job of jobs) {
      const root = resolveRootFamily(job.family_key) ?? "unknown";
      const position = layout.positions[job.code];
      if (position !== undefined) {
        const members = byRoot.get(root) ?? [];
        members.push(position);
        byRoot.set(root, members);
      }
    }
    const meanDistance = (points: Array<{ x: number; y: number }>) => {
      let total = 0;
      let pairs = 0;
      for (let first = 0; first < points.length; first += 1) {
        for (let second = first + 1; second < points.length; second += 1) {
          const a = points[first];
          const b = points[second];
          if (a !== undefined && b !== undefined) {
            total += Math.hypot(a.x - b.x, a.y - b.y);
            pairs += 1;
          }
        }
      }
      return pairs === 0 ? 0 : total / pairs;
    };
    const intra = meanDistance([...byRoot.values()].flat());
    let interTotal = 0;
    let interPairs = 0;
    for (const [root, positions] of byRoot) {
      for (const [otherRoot, otherPositions] of byRoot) {
        if (root === otherRoot) {
          continue;
        }
        for (const a of positions) {
          for (const b of otherPositions) {
            interTotal += Math.hypot(a.x - b.x, a.y - b.y);
            interPairs += 1;
          }
        }
      }
    }
    const inter = interPairs === 0 ? 0 : interTotal / interPairs;
    expect(intra).toBeLessThan(inter);
  });

  it("returns an empty layout for an empty catalog", () => {
    expect(layoutGraph([], [])).toMatchObject({ positions: {} });
  });
});

describe("familyAnchor", () => {
  it("anchors families inside the card and spreads them apart", () => {
    const anchors = ROOT_FAMILIES.map((_, index) => familyAnchor(index, ROOT_FAMILIES.length, 752, 480));
    for (const anchor of anchors) {
      expect(anchor.x).toBeGreaterThan(NODE_WIDTH / 2);
      expect(anchor.x).toBeLessThan(752 - NODE_WIDTH / 2);
      expect(anchor.y).toBeGreaterThan(NODE_HEIGHT / 2);
      expect(anchor.y).toBeLessThan(480 - NODE_HEIGHT / 2);
    }
    const spread = Math.max(...anchors.map((a) => a.x)) - Math.min(...anchors.map((a) => a.x));
    expect(spread).toBeGreaterThan(COMFORT_DX);
  });
});

describe("selectDefaultJobCodes", () => {
  const jobs = buildJobs();
  const edges = buildEdges(jobs);

  it("keeps 30 jobs with one per represented family", () => {
    const codes = selectDefaultJobCodes(jobs, edges);
    expect(codes).toHaveLength(DEFAULT_VISIBLE_JOBS);
    expect(new Set(codes).size).toBe(DEFAULT_VISIBLE_JOBS);
    const roots = new Set(
      jobs.filter((job) => codes.includes(job.code)).map((job) => resolveRootFamily(job.family_key)),
    );
    expect(roots.size).toBe(ROOT_FAMILIES.length);
  });

  it("is deterministic and degree-led", () => {
    const extra: LayoutRelation = {
      from_code: "hospitality-job-0",
      to_code: "agriculture-job-0",
      relation_type: "similar_to",
      weight: 0.5,
    };
    const codes = selectDefaultJobCodes(jobs, [...edges, extra]);
    expect(codes).toEqual(selectDefaultJobCodes(jobs, [...edges, extra]));
    expect(codes).toContain("hospitality-job-0");
    expect(codes).toContain("agriculture-job-0");
  });

  it("honours a smaller limit", () => {
    const codes = selectDefaultJobCodes(jobs, edges, 12);
    expect(codes).toHaveLength(12);
    expect(new Set(codes).size).toBe(12);
  });
});

describe("relationDegrees", () => {
  it("counts both endpoints", () => {
    expect(
      relationDegrees([
        { from_code: "a", to_code: "b", relation_type: "leads_to" },
        { from_code: "a", to_code: "c", relation_type: "similar_to" },
      ]),
    ).toEqual({ a: 2, b: 1, c: 1 });
  });
});

describe("fitViewport", () => {
  it("centres a single node and never exceeds the zoom ceiling", () => {
    const viewport = fitViewport({ a: { x: 0, y: 0 } });
    expect(viewport.zoom).toBeLessThanOrEqual(1.15);
    expect(viewport.zoom).toBeGreaterThan(0);
  });

  it("returns the identity viewport when there is nothing to fit", () => {
    expect(fitViewport({})).toEqual({ x: 0, y: 0, zoom: 1 });
  });
});
