import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import ts from "typescript";
import { describe, expect, test } from "vitest";

import catalog from "./locales/en.json";

const literals: Record<string, unknown> = catalog;

function resolveKey(path: string): boolean {
  let current: unknown = literals;
  for (const segment of path.split(".")) {
    if (typeof current !== "object" || current === null) {
      return false;
    }
    current = (current as Record<string, unknown>)[segment];
  }
  return current !== undefined;
}

function keyExists(key: string): boolean {
  if (resolveKey(key)) {
    return true;
  }
  return resolveKey(`${key}_one`) && resolveKey(`${key}_other`);
}

function collectFiles(dir: string): string[] {
  const entries: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      entries.push(...collectFiles(full));
    } else if (/\.(tsx?)$/.test(name)) {
      entries.push(full);
    }
  }
  return entries;
}

const tCallPattern = /\bt\(\s*['"]([a-zA-Z0-9_.]+)['"]/g;
const srcRoot = join(__dirname);

function catalogKeys(): string[] {
  const keys: string[] = [];
  const walk = (node: unknown, prefix: string) => {
    if (typeof node !== "object" || node === null) {
      keys.push(prefix);
      return;
    }
    for (const [key, value] of Object.entries(node)) {
      walk(value, prefix ? `${prefix}.${key}` : key);
    }
  };
  walk(literals, "");
  return keys;
}

function collectSourceLiterals(dir: string, into: Set<string>): void {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      if (name === "tests" || name === "locales") {
        continue;
      }
      collectSourceLiterals(full, into);
      continue;
    }
    if (!/\.(tsx?)$/.test(name) || /\.test\.tsx?$/.test(name)) {
      continue;
    }
    const source = ts.createSourceFile(
      full,
      readFileSync(full, "utf8"),
      ts.ScriptTarget.Latest,
      true,
      name.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
    );
    const visit = (node: ts.Node) => {
      if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
        into.add(node.text);
      } else if (ts.isTemplateExpression(node)) {
        into.add(node.head.text);
        for (const span of node.templateSpans) {
          into.add(span.literal.text);
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
  }
}

function keyIsUsed(key: string, literalsFound: Set<string>): boolean {
  const base = key.replace(/_(zero|one|two|few|many|other)$/, "");
  if (literalsFound.has(base) || literalsFound.has(key)) {
    return true;
  }
  const segments = base.split(".");
  for (let index = 1; index < segments.length; index += 1) {
    const prefix = segments.slice(0, index).join(".");
    if (literalsFound.has(prefix) || literalsFound.has(`${prefix}.`)) {
      return true;
    }
  }
  for (const literal of literalsFound) {
    if (
      literal.length > 1 &&
      literal.endsWith(".") &&
      base.startsWith(literal)
    ) {
      return true;
    }
  }
  return false;
}

describe("translation catalog completeness", () => {
  test("every static t() key exists in en.json", () => {
    const missing: string[] = [];
    for (const file of collectFiles(srcRoot)) {
      const source = readFileSync(file, "utf8");
      for (const match of source.matchAll(tCallPattern)) {
        const key = match[1];
        if (!keyExists(key)) {
          missing.push(`${file.replace(srcRoot, "")}: ${key}`);
        }
      }
    }
    expect(missing.sort()).toEqual([]);
  });

  test("every catalog key is referenced from app source", () => {
    const literalsFound = new Set<string>();
    collectSourceLiterals(srcRoot, literalsFound);
    const unused = catalogKeys().filter(
      (key) => !keyIsUsed(key, literalsFound),
    );
    expect(unused.sort()).toEqual([]);
  });
});
