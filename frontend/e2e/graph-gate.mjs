#!/usr/bin/env node
/**
 * Catalog graph browser gate.
 *
 * The pure tests own geometry and determinism; this gate owns what only a real
 * browser can prove: no two rendered boxes overlap, the label is actually
 * readable at the recorded viewport, dimmed nodes are really dimmed, a
 * neighbour ring is visible, connected jobs have a real edge (not a hairline),
 * the focused job's edges are highlighted, and the `Open job` action never
 * covers a node.
 *
 * Usage:
 *   npm run gate:graph                       # expects the dev stack on :3100
 *   GRAPH_URL=http://127.0.0.1:3101/catalog/graph npm run gate:graph
 *
 * Desktop-shell-less dev authenticates with the loopback owner exchange; a
 * web-mode stack needs an existing session cookie instead.
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { chromium } from "playwright";

const url = process.env.GRAPH_URL ?? "http://127.0.0.1:3100/catalog/graph";
const outDir = process.env.GRAPH_OUT ?? new URL("../.tmp/graph-gate", import.meta.url).pathname;
const viewport = { width: 1440, height: 1080 };
const failures = [];

function check(label, condition, detail) {
  if (condition) {
    console.log(`  ok   ${label}${detail === undefined ? "" : ` — ${detail}`}`);
    return;
  }
  failures.push(`${label}${detail === undefined ? "" : ` — ${detail}`}`);
  console.log(`  FAIL ${label}${detail === undefined ? "" : ` — ${detail}`}`);
}

const round = (value) => Math.round(value * 100) / 100;

const metrics = () =>
  page.evaluate(() => {
    const nodes = [...document.querySelectorAll(".react-flow__node")].map((wrapper) => {
      const rect = wrapper.getBoundingClientRect();
      const node = wrapper.querySelector("[data-dimmed]") ?? wrapper;
      return {
        id: wrapper.getAttribute("data-id"),
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
        dimmed: node.getAttribute("data-dimmed") === "true",
        neighbour: node.getAttribute("data-neighbour") === "true",
        focused: node.getAttribute("data-focused") === "true",
        opacity: Number.parseFloat(getComputedStyle(node).opacity),
        boxShadow: getComputedStyle(node).boxShadow,
      };
    });

    let overlaps = 0;
    for (let first = 0; first < nodes.length; first += 1) {
      for (let second = first + 1; second < nodes.length; second += 1) {
        const a = nodes[first];
        const b = nodes[second];
        const overlapX = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
        const overlapY = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
        if (overlapX > 0.5 && overlapY > 0.5) {
          overlaps += 1;
        }
      }
    }

    const edges = [...document.querySelectorAll(".react-flow__edge")].map((edge) => {
      const path = edge.querySelector(".react-flow__edge-path");
      return {
        id: edge.getAttribute("data-testid") ?? "",
        length: path ? path.getTotalLength() : 0,
        opacity: path ? Number.parseFloat(getComputedStyle(path).opacity) : 1,
        stroke: path ? getComputedStyle(path).stroke : "",
      };
    });
    const lengths = edges.map((edge) => edge.length).sort((a, b) => a - b);

    const label = document.querySelector(".ca-graph-node-label");
    const fontSize = label ? Number.parseFloat(getComputedStyle(label).fontSize) : 0;
    const zoom = nodes[0] !== undefined && nodes[0].width > 0 ? nodes[0].width / 150 : 1;

    return {
      nodes: nodes.length,
      overlaps,
      zoom,
      fontSize,
      effectiveLabel: fontSize * zoom,
      edges: edges.length,
      minEdge: lengths[0] ?? 0,
      medianEdge: lengths[Math.floor(lengths.length / 2)] ?? 0,
      shortest: edges
        .slice()
        .sort((a, b) => a.length - b.length)
        .slice(0, 3)
        .map((edge) => `${edge.id}:${Math.round(edge.length * 100) / 100}`),
      dimmed: nodes.filter((node) => node.dimmed).length,
      dimOpacity: nodes.filter((node) => node.dimmed).map((node) => node.opacity),
      neighbours: nodes.filter((node) => node.neighbour).map((node) => node.boxShadow),
      focused: nodes.filter((node) => node.focused).map((node) => ({ id: node.id, boxShadow: node.boxShadow })),
      edgeList: edges,
      nodeRects: nodes.map((node) => ({ id: node.id, x: node.x, y: node.y, width: node.width, height: node.height })),
      card: (() => {
        const card = document.querySelector('[data-testid="relation-graph"]');
        const rect = card?.getBoundingClientRect();
        return rect === undefined ? null : { width: rect.width, height: rect.height };
      })(),
      canvasBackground: (() => {
        const canvas = document.querySelector(".react-flow");
        return canvas === null ? "rgb(248, 250, 252)" : getComputedStyle(canvas).backgroundColor;
      })(),
    };
  });

const relativeLuminance = (rgb) => {
  const [red, green, blue] = rgb.map((channel) => {
    const value = channel / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
};

const parseRgb = (value) => {
  const match = value.match(/rgba?\(([^)]+)\)/);
  if (match === null) {
    return null;
  }
  return match[1].split(",").slice(0, 3).map((part) => Number.parseFloat(part));
};

const contrast = (rgb, background) => {
  const first = relativeLuminance(rgb);
  const second = relativeLuminance(background);
  const lighter = Math.max(first, second);
  const darker = Math.min(first, second);
  return (lighter + 0.05) / (darker + 0.05);
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport });
mkdirSync(outDir, { recursive: true });

await page
  .request.post(url.replace("/catalog/graph", "/api/v1/auth/desktop/exchange"))
  .catch(() => undefined);
await page.goto(url, { waitUntil: "domcontentloaded" });
await page.waitForSelector('[data-testid^="graph-focus-"]', { timeout: 30000 });
for (const label of ["Continue", "Dismiss"]) {
  const button = page.getByRole("button", { name: label });
  if (await button.count()) {
    await button.first().click().catch(() => undefined);
    break;
  }
}
await page.waitForTimeout(900);

const card = await page.locator('[data-testid="relation-graph"]').boundingBox();
const shot = async (name) => {
  await page.screenshot({ path: join(outDir, `${name}-1440x1080.png`) });
  if (card !== null) {
    await page.screenshot({ path: join(outDir, `${name}-card.png`), clip: card });
  }
};

console.log(`Graph gate: ${url}`);
console.log("default view");
const initial = await metrics();
await shot("default");
check("renders the default budget", initial.nodes === 30, `${initial.nodes} nodes`);
check("no node overlaps", initial.overlaps === 0, `${initial.overlaps} pairs`);
check("effective label >= 10px", initial.effectiveLabel >= 10, `${round(initial.effectiveLabel)}px at zoom ${round(initial.zoom)}`);
check("min rendered edge >= 40px", initial.minEdge >= 40, `${round(initial.minEdge)}px`);
check("median rendered edge >= 80px", initial.medianEdge >= 80, `${round(initial.medianEdge)}px`);

await page.getByTestId("graph-filter-similar_to").click();
await page.waitForTimeout(400);
console.log("similar filter");
const similar = await metrics();
await shot("similar");
check("dims non-matching jobs", similar.dimmed > 0, `${similar.dimmed} nodes`);
check(
  "dimmed nodes are actually dimmed",
  similar.dimOpacity.every((opacity) => opacity <= 0.5),
  `opacity ${round(Math.max(...similar.dimOpacity))}`,
);

await page.getByTestId("graph-filter-all").click();
await page.waitForTimeout(250);
const dataScientist = page.getByTestId("graph-focus-data-scientist");
check("data-scientist is in the default view", (await dataScientist.count()) === 1);
if ((await dataScientist.count()) === 1) {
  await dataScientist.click();
  await page.waitForTimeout(400);
  console.log("focus data-scientist");
  const focused = await metrics();
  await shot("focus");
  check("focus ring is visible", focused.focused.length === 1, focused.focused[0]?.boxShadow);
  check("neighbours get a ring", focused.neighbours.length > 0, `${focused.neighbours.length} neighbours`);

  const ring = parseRgb(focused.neighbours[0] ?? "");
  const canvas = parseRgb(focused.canvasBackground);
  check(
    "neighbour ring contrasts with the canvas",
    ring !== null && canvas !== null && contrast(ring, canvas) >= 3,
    ring === null ? "no ring" : `${round(contrast(ring, canvas))}:1`,
  );

  const incident = focused.edgeList.filter((edge) => edge.id.includes("data-scientist"));
  const visible = incident.filter((edge) => edge.opacity >= 0.5);
  check(
    "focused job shows its incident edges",
    visible.length >= 2,
    `${visible.length} of ${incident.length} at opacity >= 0.5`,
  );

  const openJob = await page.getByTestId("graph-open-job").boundingBox();
  check("open job action exists", openJob !== null);
  if (openJob !== null) {
    const covered = focused.nodeRects.filter(
      (node) =>
        Math.min(openJob.x + openJob.width, node.x + node.width) - Math.max(openJob.x, node.x) > 0.5 &&
        Math.min(openJob.y + openJob.height, node.y + node.height) - Math.max(openJob.y, node.y) > 0.5,
    );
    check("open job action covers no job node", covered.length === 0, `${covered.length} covered`);
  }
}

await page.getByTestId("graph-show-all").click();
await page.waitForTimeout(700);
console.log("show all");
const all = await metrics();
await shot("all");
check("show all renders every job", all.nodes === 45, `${all.nodes} nodes`);
check("show all has no node overlaps", all.overlaps === 0, `${all.overlaps} pairs`);

await page.emulateMedia({ reducedMotion: "reduce" });
await page.reload({ waitUntil: "domcontentloaded" });
await page.waitForSelector('[data-testid^="graph-focus-"]', { timeout: 30000 });
await page.waitForTimeout(400);
console.log("reduced motion");
const reduced = await page.evaluate(() => {
  const surface = document.querySelector(".ca-graph-node-surface");
  const node = document.querySelector('.ca-graph-node-enter');
  return {
    enterClass: node !== null,
    animationName: surface === null ? "none" : getComputedStyle(surface).animationName,
    animationDuration: surface === null ? "0s" : getComputedStyle(surface).animationDuration,
  };
});
check("reduced motion drops the entry animation", reduced.animationName === "none" || reduced.animationDuration === "0.01ms", reduced.animationName);

const summary = {
  url,
  viewport,
  default: {
    nodes: initial.nodes,
    overlaps: initial.overlaps,
    zoom: round(initial.zoom),
    fontSize: initial.fontSize,
    effectiveLabel: round(initial.effectiveLabel),
    edges: initial.edges,
    minEdge: round(initial.minEdge),
    medianEdge: round(initial.medianEdge),
    shortest: initial.shortest,
  },
  similar: {
    nodes: similar.nodes,
    edges: similar.edges,
    dimmed: similar.dimmed,
    maxDimOpacity: similar.dimOpacity.length === 0 ? null : round(Math.max(...similar.dimOpacity)),
    minEdge: round(similar.minEdge),
  },
  showAll: { nodes: all.nodes, overlaps: all.overlaps, zoom: round(all.zoom), effectiveLabel: round(all.effectiveLabel) },
  artifacts: outDir,
};

console.log(`\n${JSON.stringify(summary, null, 2)}`);
await browser.close();

if (failures.length > 0) {
  console.error(`\n${failures.length} gate check(s) failed:`);
  for (const failure of failures) {
    console.error(`  - ${failure}`);
  }
  process.exit(1);
}
console.log("\ngraph gate passed");
