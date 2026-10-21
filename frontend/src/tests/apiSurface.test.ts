/**
 * API-client surface wall (plan 114.3).
 *
 * An API client function ships with its first consumer: every exported
 * function in `src/api/` must be referenced outside its own module,
 * otherwise it is dead surface — plan 114 deleted nineteen of them
 * (`api/growth.ts`'s planner, the background-jobs list, the orphaned
 * chat-stream request, `duplicateTemplate`, …). Code a client shares
 * between its own calls stays module-private (`function`, no `export`) —
 * `streamChatRequest` and `scoreJobs` are the reference cases.
 *
 * Consumers count anywhere under `src/` (pages, components, stores,
 * hooks, tests): a function nobody imports and nobody calls is not
 * surface, it is inventory.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..");
const API_DIR = join(SRC, "api");

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      out.push(...sourceFiles(path));
    } else if (path.endsWith(".ts") || path.endsWith(".tsx")) {
      out.push(path);
    }
  }
  return out;
}

function apiExports(): { file: string; name: string }[] {
  const exports: { file: string; name: string }[] = [];
  for (const file of sourceFiles(API_DIR)) {
    const source = readFileSync(file, "utf8");
    for (const match of source.matchAll(/^export\s+(?:async\s+)?function\s+(\w+)/gm)) {
      exports.push({ file, name: match[1] });
    }
  }
  return exports;
}

let source_cache: { file: string; text: string }[] | null = null;

function sources(): { file: string; text: string }[] {
  source_cache ??= sourceFiles(SRC).map((file) => ({
    file,
    text: readFileSync(file, "utf8"),
  }));
  return source_cache;
}

function consumers(name: string, ownFile: string): string[] {
  const pattern = new RegExp(`\\b${name}\\b`);
  return sources()
    .filter(({ file }) => file !== ownFile)
    .filter(({ text }) => pattern.test(text))
    .map(({ file }) => relative(SRC, file).split(sep).join("/"));
}

describe("api client surface", () => {
  it("ships every exported client function with a consumer", () => {
    const orphans = apiExports()
      .filter(({ file, name }) => consumers(name, file).length === 0)
      .map(({ file, name }) => `${relative(SRC, file).split(sep).join("/")} → ${name}`);
    expect(orphans).toEqual([]);
  });
});
