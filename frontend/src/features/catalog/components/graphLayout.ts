/**
 * Deterministic family constellation for the catalog graph.
 *
 * The layout is pure: the same jobs and relations always produce the same
 * positions — there is no random source, no force library and no clock. Each
 * root family gets an anchor on a fixed ellipse; its members start as a
 * sunflower spiral around that anchor and are then relaxed by a fixed number
 * of deterministic separation passes.
 *
 * Two spacing rules are enforced every pass:
 *
 * - any two jobs keep `MIN_DX` x `MIN_DY` of centre distance on at least one
 *   axis, so their boxes can never overlap at any zoom;
 * - two *connected* jobs keep `EDGE_MIN_DX` x `EDGE_MIN_DY`, so a rendered
 *   edge is a visible line (>= ~50px at the fitted zoom) instead of the 3px
 *   hairline that adjacent lattice neighbours produce.
 */

import { chooseNearestSides, type EdgeSide } from "./nearestEdge";

export const ROOT_FAMILIES = [
  "technology",
  "healthcare",
  "education",
  "engineering",
  "business",
  "creative",
  "public-safety",
  "science",
  "agriculture",
  "hospitality",
] as const;

export type RootFamily = (typeof ROOT_FAMILIES)[number];

/**
 * One distinct, AA-contrast fill per root family (white labels stay readable
 * on every value). Unknown families fall back to `FALLBACK_FAMILY_COLOR`.
 */
export const FAMILY_COLORS: Record<RootFamily, string> = {
  technology: "#1d4ed8",
  healthcare: "#b91c1c",
  education: "#a16207",
  engineering: "#6d28d9",
  business: "#047857",
  creative: "#be185d",
  "public-safety": "#0c4a6e",
  science: "#0f766e",
  agriculture: "#4d7c0f",
  hospitality: "#c2410c",
};

export const FALLBACK_FAMILY_COLOR = "#475569";

/** Node box in layout units; a two-line title grows to `NODE_HEIGHT`. */
export const NODE_WIDTH = 150;
export const NODE_HEIGHT = 44;

/** Hard no-overlap rule: two boxes never share a pixel (2px of air). */
export const MIN_DX = NODE_WIDTH + 2;
export const MIN_DY = NODE_HEIGHT + 2;

/** Comfort spacing the forces aim for inside a family cluster. */
export const COMFORT_DX = NODE_WIDTH + 16;
export const COMFORT_DY = NODE_HEIGHT + 16;

/**
 * Minimum rendered edge: the distance between the two handle points of a
 * connected pair, in layout units. At the fitted zoom this is >= 45px, so a
 * relation reads as a line instead of a hairline.
 */
export const EDGE_CHORD_MIN = 58;

/** Dense "show all" overviews trade edge length for a legible zoom. */
export const EDGE_CHORD_MIN_DENSE = 44;
export const DENSE_NODE_COUNT = 32;

/** The edge-length floor for a set of this size. */
export function edgeChordFloor(count: number): number {
  return count > DENSE_NODE_COUNT ? EDGE_CHORD_MIN_DENSE : EDGE_CHORD_MIN;
}

/** The graph card the layout is fitted into. */
export const GRAPH_CARD_WIDTH = 752;
export const GRAPH_CARD_HEIGHT = 480;
export const GRAPH_PADDING = 12;

/**
 * Jobs shown before "Show all". 24 keeps every family present and still leaves
 * roughly a quarter of the spacing grid empty, which is what buys the negative
 * space and the >=50px edges; at 30+ the card can only hold a packed lattice.
 */
export const DEFAULT_VISIBLE_JOBS = 30;

/** Base node type size in layout units. */
export const NODE_FONT_SIZE = 15;

/** Zoom bounds for the one uniform scale/translate into the card. */
export const MIN_ZOOM = 0.4;
export const MAX_ZOOM = 1.15;

const SUNFLOWER_ANGLE = 2.399963229728653;
const SUNFLOWER_STEP = 46;
const ELLIPSE_SHRINK = 0.98;

/** Forces: repulsion keeps jobs apart, springs give connected jobs a long edge. */
const REPULSION = 9000;
/** Same-family members attract into a blob; other clusters push them away. */
const FAMILY_REPULSION = 0.15;
const CLUSTER_REPULSION = 2.2;
const EDGE_REST_LENGTH = 250;
const EDGE_SPRING = 0.008;
const FAMILY_COHESION = 0.34;
const CENTER_PULL = 0.002;
const FORCE_STEP = 0.35;
const FORCE_DAMPING = 0.86;
const FORCE_ITERATIONS = 600;
const REPAIR_ROUNDS = 60;

/**
 * Longest root prefix at a `-` boundary.
 *
 * `public-safety` is itself a root, so splitting on `-` is unsafe: the key is
 * matched as a whole before any prefix is considered.
 */
export function resolveRootFamily(familyKey: string | null | undefined): RootFamily | null {
  if (!familyKey) {
    return null;
  }
  const key = familyKey.trim();
  let best: RootFamily | null = null;
  for (const root of ROOT_FAMILIES) {
    if (key === root || key.startsWith(`${root}-`)) {
      if (best === null || root.length > best.length) {
        best = root;
      }
    }
  }
  return best;
}

/** Fill for a job family; known roots never fall back to slate. */
export function familyColor(familyKey: string | null | undefined): string {
  const root = resolveRootFamily(familyKey);
  return root === null ? FALLBACK_FAMILY_COLOR : FAMILY_COLORS[root];
}

export interface LayoutJob {
  code: string;
  title: string;
  family_key: string;
}

export interface LayoutRelation {
  from_code: string;
  to_code: string;
  relation_type: string;
  weight?: number;
}

export interface LayoutPoint {
  x: number;
  y: number;
}

export interface Viewport {
  x: number;
  y: number;
  zoom: number;
}

export interface LayoutOptions {
  width?: number;
  height?: number;
  padding?: number;
}

export interface GraphLayout {
  positions: Record<string, LayoutPoint>;
  /** Root family per job code; `null` when the family is not a known root. */
  families: Record<string, RootFamily | null>;
  worldWidth: number;
  worldHeight: number;
  /** Uniform scale/translate that fits every laid-out node into the card. */
  viewport: Viewport;
}

export function relationDegrees(edges: LayoutRelation[]): Record<string, number> {
  const degrees: Record<string, number> = {};
  for (const edge of edges) {
    degrees[edge.from_code] = (degrees[edge.from_code] ?? 0) + 1;
    degrees[edge.to_code] = (degrees[edge.to_code] ?? 0) + 1;
  }
  return degrees;
}

function rootRank(familyKey: string): number {
  const root = resolveRootFamily(familyKey);
  return root === null ? ROOT_FAMILIES.length : ROOT_FAMILIES.indexOf(root);
}

/**
 * The default constellation set: rank by relation degree, then family/title for
 * determinism, with a floor of one job per represented root family.
 */
export function selectDefaultJobCodes(
  jobs: LayoutJob[],
  edges: LayoutRelation[],
  limit: number = DEFAULT_VISIBLE_JOBS,
): string[] {
  const degrees = relationDegrees(edges);
  const ranked = [...jobs].sort((a, b) => {
    const byDegree = (degrees[b.code] ?? 0) - (degrees[a.code] ?? 0);
    if (byDegree !== 0) {
      return byDegree;
    }
    const byFamily = rootRank(a.family_key) - rootRank(b.family_key);
    if (byFamily !== 0) {
      return byFamily;
    }
    const byTitle = a.title.localeCompare(b.title);
    return byTitle !== 0 ? byTitle : a.code.localeCompare(b.code);
  });

  const chosen: string[] = [];
  const used = new Set<string>();
  for (const root of ROOT_FAMILIES) {
    const member = ranked.find((job) => resolveRootFamily(job.family_key) === root);
    if (member !== undefined && !used.has(member.code)) {
      chosen.push(member.code);
      used.add(member.code);
    }
  }
  for (const job of ranked) {
    if (chosen.length >= limit) {
      break;
    }
    if (!used.has(job.code)) {
      chosen.push(job.code);
      used.add(job.code);
    }
  }
  return chosen.slice(0, limit);
}

/**
 * Deterministic family anchor: a sunflower over the card, biggest family at the
 * centre. Even spacing, no random source — the clusters land where they land
 * for every render of the same catalog.
 */
export function familyAnchor(index: number, total: number, width: number, height: number): LayoutPoint {
  const centerX = width / 2;
  const centerY = height / 2;
  const radiusX = Math.max(0, width / 2 - NODE_WIDTH / 2 - GRAPH_PADDING) * ELLIPSE_SHRINK;
  const radiusY = Math.max(0, height / 2 - NODE_HEIGHT / 2 - GRAPH_PADDING) * ELLIPSE_SHRINK;
  const radius = Math.sqrt((index + 0.5) / Math.max(1, total));
  const angle = index * SUNFLOWER_ANGLE - Math.PI / 2;
  return {
    x: centerX + Math.cos(angle) * radiusX * radius,
    y: centerY + Math.sin(angle) * radiusY * radius,
  };
}

interface World {
  width: number;
  height: number;
  columns: number;
  rows: number;
  zoom: number;
}

/**
 * Pick the world a set of jobs needs: the smallest grid that holds them at the
 * separation pitch while keeping the best uniform fit in the card. Small sets
 * buy a little slack so the constellation keeps negative space.
 */
function chooseWorld(count: number, cardWidth: number, cardHeight: number, padding: number): World {
  const slack = count <= 30 ? 4 : 0;
  let best: World | null = null;
  for (let columns = 1; columns <= count; columns += 1) {
    const rows = Math.ceil((count + slack) / columns);
    const width = (columns - 1) * COMFORT_DX + NODE_WIDTH + padding * 2;
    const height = (rows - 1) * COMFORT_DY + NODE_HEIGHT + padding * 2;
    const zoom = Math.min(cardWidth / width, cardHeight / height);
    const candidate: World = { width, height, columns, rows, zoom };
    const better =
      best === null ||
      zoom > best.zoom + 1e-9 ||
      (Math.abs(zoom - best.zoom) <= 1e-9 &&
        Math.abs(width / height - cardWidth / cardHeight) <
          Math.abs(best.width / best.height - cardWidth / cardHeight));
    if (better) {
      best = candidate;
    }
  }
  return best ?? { width: cardWidth, height: cardHeight, columns: 1, rows: 1, zoom: 1 };
}

function pushApart(
  positions: LayoutPoint[],
  first: number,
  second: number,
  minDx: number,
  minDy: number,
): boolean {
  const a = positions[first];
  const b = positions[second];
  if (a === undefined || b === undefined) {
    return false;
  }
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const needX = minDx - Math.abs(dx);
  const needY = minDy - Math.abs(dy);
  if (needX <= 0 || needY <= 0) {
    return false;
  }
  if (needX <= needY) {
    const push = (needX / 2) * (dx < 0 ? -1 : 1);
    a.x -= push;
    b.x += push;
  } else {
    const push = (needY / 2) * (dy < 0 ? -1 : 1);
    a.y -= push;
    b.y += push;
  }
  return true;
}

function clampToWorld(positions: LayoutPoint[], world: World, padding: number): void {
  const minX = padding + NODE_WIDTH / 2;
  const maxX = world.width - padding - NODE_WIDTH / 2;
  const minY = padding + NODE_HEIGHT / 2;
  const maxY = world.height - padding - NODE_HEIGHT / 2;
  for (const position of positions) {
    position.x = Math.min(maxX, Math.max(minX, position.x));
    position.y = Math.min(maxY, Math.max(minY, position.y));
  }
}

/**
 * Deterministic constellation relaxation.
 *
 * A force pass (repulsion, edge springs at a long rest length, family
 * cohesion, centring) finds an organic arrangement; alternating hard rounds
 * then guarantee the two spacing rules: the overlap rule always holds, and the
 * long-edge rule is repaired until no connected pair sits too close. No random
 * source, no clock — the same input always settles on the same positions.
 */
function relax(
  positions: LayoutPoint[],
  anchors: LayoutPoint[],
  families: number[],
  edges: Array<[number, number]>,
  world: World,
  padding: number,
  chordFloor: number,
): void {
  const count = positions.length;
  const repulsion = (REPULSION * 30) / Math.max(1, count);
  const velocities: LayoutPoint[] = positions.map(() => ({ x: 0, y: 0 }));
  const centerX = world.width / 2;
  const centerY = world.height / 2;

  for (let iteration = 0; iteration < FORCE_ITERATIONS; iteration += 1) {
    const forces: LayoutPoint[] = positions.map(() => ({ x: 0, y: 0 }));

    for (let first = 0; first < count; first += 1) {
      for (let second = first + 1; second < count; second += 1) {
        const a = positions[first];
        const b = positions[second];
        const forceA = forces[first];
        const forceB = forces[second];
        if (a === undefined || b === undefined || forceA === undefined || forceB === undefined) {
          continue;
        }
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const distance = Math.max(1, Math.hypot(dx, dy));
        const sameFamily = families[first] === families[second];
        const strength =
          (repulsion * (sameFamily ? FAMILY_REPULSION : CLUSTER_REPULSION)) / (distance * distance);
        const nx = dx / distance;
        const ny = dy / distance;
        forceA.x -= nx * strength;
        forceA.y -= ny * strength;
        forceB.x += nx * strength;
        forceB.y += ny * strength;
      }
    }

    for (const [first, second] of edges) {
      const a = positions[first];
      const b = positions[second];
      const forceA = forces[first];
      const forceB = forces[second];
      if (a === undefined || b === undefined || forceA === undefined || forceB === undefined) {
        continue;
      }
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const distance = Math.max(1, Math.hypot(dx, dy));
      const strength = (distance - EDGE_REST_LENGTH) * EDGE_SPRING;
      const nx = dx / distance;
      const ny = dy / distance;
      forceA.x += nx * strength;
      forceA.y += ny * strength;
      forceB.x -= nx * strength;
      forceB.y -= ny * strength;
    }

    for (let index = 0; index < count; index += 1) {
      const position = positions[index];
      const anchor = anchors[index];
      const force = forces[index];
      if (position === undefined || anchor === undefined || force === undefined) {
        continue;
      }
      force.x += (anchor.x - position.x) * FAMILY_COHESION + (centerX - position.x) * CENTER_PULL;
      force.y += (anchor.y - position.y) * FAMILY_COHESION + (centerY - position.y) * CENTER_PULL;
    }

    for (let index = 0; index < count; index += 1) {
      const position = positions[index];
      const velocity = velocities[index];
      const force = forces[index];
      if (position === undefined || velocity === undefined || force === undefined) {
        continue;
      }
      velocity.x = (velocity.x + force.x * FORCE_STEP) * FORCE_DAMPING;
      velocity.y = (velocity.y + force.y * FORCE_STEP) * FORCE_DAMPING;
      position.x += velocity.x * FORCE_STEP;
      position.y += velocity.y * FORCE_STEP;
    }
    clampToWorld(positions, world, padding);
    if (iteration % 3 === 0) {
      repairEdgeChords(positions, edges, chordFloor);
      separateAll(positions);
    }
  }

  for (let round = 0; round < REPAIR_ROUNDS; round += 1) {
    const repairedEdges = repairEdgeChords(positions, edges, chordFloor);
    const repairedBoxes = separateAll(positions);
    if (!repairedEdges && !repairedBoxes) {
      break;
    }
  }
}

/**
 * Widen a tall constellation to the card's aspect: the fitted zoom is bound by
 * the shorter side, so a narrow cloud wastes the card and shrinks labels.
 * Stretching x can only increase distances, never create an overlap.
 */
function matchCardAspect(positions: LayoutPoint[], cardWidth: number, cardHeight: number): void {
  if (positions.length < 2) {
    return;
  }
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const position of positions) {
    minX = Math.min(minX, position.x);
    minY = Math.min(minY, position.y);
    maxX = Math.max(maxX, position.x);
    maxY = Math.max(maxY, position.y);
  }
  const contentAspect = (maxX - minX + NODE_WIDTH) / (maxY - minY + NODE_HEIGHT);
  const targetAspect = cardWidth / cardHeight;
  if (contentAspect >= targetAspect) {
    return;
  }
  const factor = targetAspect / contentAspect;
  const centerX = (minX + maxX) / 2;
  for (const position of positions) {
    position.x = centerX + (position.x - centerX) * factor;
  }
}

/**
 * Last-resort guarantee for pathological graphs: the separation sweep can stop
 * in a local pocket, and an overlap is never acceptable. Growing the cloud
 * about its centroid strictly increases every distance, so this terminates —
 * the uniform fit then gives back the pixels.
 */
function resolveRemainingOverlaps(positions: LayoutPoint[]): void {
  for (let attempt = 0; attempt < 12; attempt += 1) {
    let overlapping = false;
    for (let first = 0; first < positions.length && !overlapping; first += 1) {
      for (let second = first + 1; second < positions.length; second += 1) {
        const a = positions[first];
        const b = positions[second];
        if (a === undefined || b === undefined) {
          continue;
        }
        if (Math.abs(a.x - b.x) < MIN_DX && Math.abs(a.y - b.y) < MIN_DY) {
          overlapping = true;
          break;
        }
      }
    }
    if (!overlapping) {
      return;
    }
    const centerX = positions.reduce((sum, position) => sum + position.x, 0) / positions.length;
    const centerY = positions.reduce((sum, position) => sum + position.y, 0) / positions.length;
    for (const position of positions) {
      position.x = centerX + (position.x - centerX) * 1.08;
      position.y = centerY + (position.y - centerY) * 1.08;
    }
  }
}

/** One hard no-overlap sweep over every pair. */
function separateAll(positions: LayoutPoint[]): boolean {
  let moved = false;
  for (let first = 0; first < positions.length; first += 1) {
    for (let second = first + 1; second < positions.length; second += 1) {
      moved = pushApart(positions, first, second, MIN_DX, MIN_DY) || moved;
    }
  }
  return moved;
}

function handlePoint(position: LayoutPoint, side: EdgeSide): LayoutPoint {
  switch (side) {
    case "left":
      return { x: position.x, y: position.y + NODE_HEIGHT / 2 };
    case "right":
      return { x: position.x + NODE_WIDTH, y: position.y + NODE_HEIGHT / 2 };
    case "top":
      return { x: position.x + NODE_WIDTH / 2, y: position.y };
    case "bottom":
      return { x: position.x + NODE_WIDTH / 2, y: position.y + NODE_HEIGHT };
  }
}

/** Rendered length of the edge between two boxes, in layout units. */
export function edgeChord(source: LayoutPoint, target: LayoutPoint): number {
  const sides = chooseNearestSides(
    { ...source, width: NODE_WIDTH, height: NODE_HEIGHT },
    { ...target, width: NODE_WIDTH, height: NODE_HEIGHT },
  );
  const from = handlePoint(source, sides.source);
  const to = handlePoint(target, sides.target);
  return Math.hypot(to.x - from.x, to.y - from.y);
}

/** Push connected pairs apart until their edge is at least `EDGE_CHORD_MIN`. */
function repairEdgeChords(
  positions: LayoutPoint[],
  edges: Array<[number, number]>,
  floor: number = EDGE_CHORD_MIN,
): boolean {
  let moved = false;
  for (const [first, second] of edges) {
    const a = positions[first];
    const b = positions[second];
    if (a === undefined || b === undefined) {
      continue;
    }
    const chord = edgeChord(a, b);
    if (chord >= floor) {
      continue;
    }
    const sides = chooseNearestSides(
      { ...a, width: NODE_WIDTH, height: NODE_HEIGHT },
      { ...b, width: NODE_WIDTH, height: NODE_HEIGHT },
    );
    const horizontal = sides.source === "left" || sides.source === "right";
    const need = (floor - chord) / 2 + 0.5;
    const direction = horizontal
      ? b.x >= a.x
        ? 1
        : -1
      : b.y >= a.y
        ? 1
        : -1;
    if (horizontal) {
      a.x -= need * direction;
      b.x += need * direction;
    } else {
      a.y -= need * direction;
      b.y += need * direction;
    }
    moved = true;
  }
  return moved;
}

/**
 * Lay out a set of jobs as a family constellation in the card's coordinate
 * space at a uniform fit.
 */
export function layoutGraph(
  jobs: LayoutJob[],
  edges: LayoutRelation[],
  options: LayoutOptions = {},
): GraphLayout {
  const cardWidth = options.width ?? GRAPH_CARD_WIDTH;
  const cardHeight = options.height ?? GRAPH_CARD_HEIGHT;
  const padding = options.padding ?? GRAPH_PADDING;

  if (jobs.length === 0) {
    return {
      positions: {},
      families: {},
      worldWidth: cardWidth,
      worldHeight: cardHeight,
      viewport: { x: 0, y: 0, zoom: 1 },
    };
  }

  const world = chooseWorld(jobs.length, cardWidth, cardHeight, padding);
  const degrees = relationDegrees(edges);
  const families: Record<string, RootFamily | null> = {};
  const indexOf = new Map<string, number>();
  const codeAtIndex: string[] = [];
  const anchors: LayoutPoint[] = [];
  const positions: LayoutPoint[] = [];

  const groups = new Map<string, LayoutJob[]>();
  for (const job of jobs) {
    const root = resolveRootFamily(job.family_key);
    families[job.code] = root;
    const key = root ?? `\uffff${job.family_key}`;
    const members = groups.get(key);
    if (members === undefined) {
      groups.set(key, [job]);
    } else {
      members.push(job);
    }
  }

  const orderedGroups = [...groups.entries()]
    .map(([key, members]) => ({
      key,
      members: [...members].sort((a, b) => {
        const byDegree = (degrees[b.code] ?? 0) - (degrees[a.code] ?? 0);
        if (byDegree !== 0) {
          return byDegree;
        }
        const byTitle = a.title.localeCompare(b.title);
        return byTitle !== 0 ? byTitle : a.code.localeCompare(b.code);
      }),
    }))
    .sort((a, b) => {
      const rankA = resolveRootFamily(a.members[0]?.family_key ?? "");
      const rankB = resolveRootFamily(b.members[0]?.family_key ?? "");
      const byRank = (rankA === null ? 99 : ROOT_FAMILIES.indexOf(rankA)) - (rankB === null ? 99 : ROOT_FAMILIES.indexOf(rankB));
      return byRank !== 0 ? byRank : a.key.localeCompare(b.key);
    });

  const bySize = [...orderedGroups].sort((a, b) => {
    const byMembers = b.members.length - a.members.length;
    return byMembers !== 0 ? byMembers : a.key.localeCompare(b.key);
  });

  bySize.forEach((group, groupIndex) => {
    const anchor = familyAnchor(groupIndex, bySize.length, world.width, world.height);
    group.members.forEach((member, index) => {
      const radius = SUNFLOWER_STEP * Math.sqrt(index + 0.5);
      const angle = index * SUNFLOWER_ANGLE;
      indexOf.set(member.code, positions.length);
      codeAtIndex.push(member.code);
      anchors.push(anchor);
      positions.push({
        x: anchor.x + Math.cos(angle) * radius,
        y: anchor.y + Math.sin(angle) * radius,
      });
    });
  });

  const edgePairs: Array<[number, number]> = [];
  const seen = new Set<string>();
  for (const edge of [...edges].sort((a, b) => `${a.from_code}${a.to_code}${a.relation_type}`.localeCompare(`${b.from_code}${b.to_code}${b.relation_type}`))) {
    const from = indexOf.get(edge.from_code);
    const to = indexOf.get(edge.to_code);
    if (from === undefined || to === undefined) {
      continue;
    }
    const key = from < to ? `${from}:${to}` : `${to}:${from}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    edgePairs.push([from, to]);
  }

  const familyIds: number[] = [];
  bySize.forEach((_group, groupIndex) => {
    _group.members.forEach(() => {
      familyIds.push(groupIndex);
    });
  });
  const chordFloor = edgeChordFloor(jobs.length);
  relax(positions, anchors, familyIds, edgePairs, world, padding, chordFloor);
  matchCardAspect(positions, cardWidth, cardHeight);
  for (let round = 0; round < REPAIR_ROUNDS; round += 1) {
    const repairedEdges = repairEdgeChords(positions, edgePairs, chordFloor);
    const repairedBoxes = separateAll(positions);
    if (!repairedEdges && !repairedBoxes) {
      break;
    }
  }
  resolveRemainingOverlaps(positions);

  const byCode: Record<string, LayoutPoint> = {};
  codeAtIndex.forEach((code, index) => {
    const position = positions[index];
    if (position !== undefined) {
      byCode[code] = { x: position.x, y: position.y };
    }
  });

  return {
    positions: byCode,
    families,
    worldWidth: world.width,
    worldHeight: world.height,
    viewport: fitViewport(byCode, { width: cardWidth, height: cardHeight, padding }),
  };
}

/** One uniform scale/translate that centres the given positions in the card. */
export function fitViewport(
  positions: Record<string, LayoutPoint> | LayoutPoint[],
  options: LayoutOptions = {},
): Viewport {
  const width = options.width ?? GRAPH_CARD_WIDTH;
  const height = options.height ?? GRAPH_CARD_HEIGHT;
  const padding = options.padding ?? GRAPH_PADDING;
  const points = Array.isArray(positions) ? positions : Object.values(positions);
  if (points.length === 0) {
    return { x: 0, y: 0, zoom: 1 };
  }
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const point of points) {
    minX = Math.min(minX, point.x);
    minY = Math.min(minY, point.y);
    maxX = Math.max(maxX, point.x);
    maxY = Math.max(maxY, point.y);
  }
  const contentWidth = maxX - minX + NODE_WIDTH;
  const contentHeight = maxY - minY + NODE_HEIGHT;
  const zoom = Math.min(
    MAX_ZOOM,
    Math.max(MIN_ZOOM, Math.min((width - padding * 2) / contentWidth, (height - padding * 2) / contentHeight)),
  );
  return {
    x: (width - contentWidth * zoom) / 2 - minX * zoom,
    y: (height - contentHeight * zoom) / 2 - minY * zoom,
    zoom,
  };
}
