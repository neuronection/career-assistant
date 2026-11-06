import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import ts from "typescript";
import { describe, expect, test } from "vitest";

const SRC = __dirname;
const SCANNED_ROOTS = ["pages", "components", "features"];

const USER_FACING_ATTRIBUTES = new Set([
  "alt",
  "aria-label",
  "cancelLabel",
  "confirmLabel",
  "cta",
  "description",
  "emptyDescription",
  "emptyTitle",
  "heading",
  "hint",
  "label",
  "message",
  "note",
  "placeholder",
  "subtitle",
  "title",
  "tooltip",
]);

const TRANSLATION_CALLEES = new Set(["t", "translate", "i18n.t", "i18next.t"]);

const ALLOWED_LITERALS = new Set([
  "AI",
  "ATS",
  "CV",
  "Career",
  "Career Assistant",
  "Assistant",
  "Ctrl",
  "GitHub",
  "Google Gemini",
  "Ilias Chatzopoulos",
  "Career Assistant logo",
  "Microsoft Teams",
  "OpenAI",
  "OpenAI-compatible",
  "OpenRouter / Ollama / LM Studio",
  "Part of Neuronection",
  "Slack",
  "Telegram",
  "api.openai.com",
  "generativelanguage.googleapis.com",
  "neuronection/career-assistant",
  "ntfy",
  "LinkedIn",
  "Google",
  "JSON",
  "JPEG",
  "MCP",
  "Neuronection",
  "ORCID",
  "PDF",
  "PNG",
  "RSS",
  "SMTP",
  "URL",
  "WebP",
]);

const ALLOWED_ATTRIBUTE_LITERALS = new Set([
  "you@example.com",
  "Firstname Lastname",
]);

const URL_LIKE = /^(?:https?:\/\/|mailto:)[\w./:@?=&%#+~-]*$/;
const EMAIL_LIKE = /^[\w.+-]+@[\w-]+\.[\w.-]+$/;
const LOOKS_LIKE_KEY = /^[a-z][a-zA-Z0-9_]*(\.[a-zA-Z0-9_-]+)+$/;
const UNIT_ONLY = /^(ms|s|mm|cm|pt|px|kb|mb|gb|%|€|\$|£|#|·|\+|—|-)+$/i;
const HAS_WORDS = /[A-Za-z]{2,}/;

interface Finding {
  file: string;
  line: number;
  text: string;
}

function collectSourceFiles(dir: string): string[] {
  const files: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      files.push(...collectSourceFiles(full));
    } else if (/\.tsx?$/.test(name) && !name.endsWith(".d.ts")) {
      files.push(full);
    }
  }
  return files;
}

function lineOf(source: ts.SourceFile, position: number): number {
  return source.getLineAndCharacterOfPosition(position).line + 1;
}

function isIgnoredText(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed || !HAS_WORDS.test(trimmed)) {
    return true;
  }
  if (ALLOWED_LITERALS.has(trimmed)) {
    return true;
  }
  if (
    URL_LIKE.test(trimmed) ||
    EMAIL_LIKE.test(trimmed) ||
    UNIT_ONLY.test(trimmed) ||
    LOOKS_LIKE_KEY.test(trimmed)
  ) {
    return true;
  }
  return false;
}

function calleeText(node: ts.CallExpression, source: ts.SourceFile): string {
  return node.expression.getText(source);
}

function isTranslationCall(node: ts.Node, source: ts.SourceFile): boolean {
  const parent = node.parent;
  return (
    ts.isCallExpression(parent) && TRANSLATION_CALLEES.has(calleeText(parent, source))
  );
}

function attributeOf(node: ts.Node): ts.JsxAttribute | null {
  let current: ts.Node | undefined = node;
  while (current) {
    if (ts.isJsxAttribute(current)) {
      return current;
    }
    current = current.parent;
  }
  return null;
}

function literalIsRendered(node: ts.Node): boolean {
  let current: ts.Node | undefined = node;
  while (current) {
    if (ts.isJsxExpression(current)) {
      return true;
    }
    if (ts.isBinaryExpression(current)) {
      const operator = current.operatorToken.kind;
      if (
        operator === ts.SyntaxKind.EqualsEqualsEqualsToken ||
        operator === ts.SyntaxKind.ExclamationEqualsEqualsToken ||
        operator === ts.SyntaxKind.EqualsEqualsToken ||
        operator === ts.SyntaxKind.ExclamationEqualsToken
      ) {
        return false;
      }
    }
    if (
      ts.isCallExpression(current) ||
      ts.isPropertyAssignment(current) ||
      ts.isImportDeclaration(current)
    ) {
      return false;
    }
    current = current.parent;
  }
  return false;
}

function insideBlockDefaults(node: ts.Node): boolean {
  let current: ts.Node | undefined = node.parent;
  while (current) {
    if (
      ts.isPropertyAssignment(current) &&
      ts.isIdentifier(current.name) &&
      current.name.text === "props"
    ) {
      return true;
    }
    if (ts.isVariableDeclaration(current) || ts.isSourceFile(current)) {
      return false;
    }
    current = current.parent;
  }
  return false;
}

function inspect(file: string): Finding[] {
  const source = ts.createSourceFile(
    file,
    readFileSync(file, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const findings: Finding[] = [];
  const report = (node: ts.Node, text: string) => {
    findings.push({
      file: relative(SRC, file),
      line: lineOf(source, node.getStart(source)),
      text: text.trim(),
    });
  };

  const visit = (node: ts.Node) => {
    if (ts.isJsxText(node)) {
      if (!isIgnoredText(node.text)) {
        report(node, node.text);
      }
    } else if (ts.isJsxAttribute(node)) {
      const name = node.name.getText(source);
      if (USER_FACING_ATTRIBUTES.has(name) && node.initializer) {
        const init = node.initializer;
        if (ts.isStringLiteral(init)) {
          const value = init.text;
          if (!isIgnoredText(value) && !ALLOWED_ATTRIBUTE_LITERALS.has(value)) {
            report(init, `${name}="${value}"`);
          }
        }
        if (ts.isJsxExpression(init) && init.expression) {
          const expression = init.expression;
          if (ts.isTemplateExpression(expression)) {
            if (!isIgnoredText(expression.head.text)) {
              report(expression, `${name}=${expression.head.text}`);
            }
          }
          const reportBranches = (branch: ts.Node) => {
            if (ts.isConditionalExpression(branch)) {
              reportBranches(branch.whenTrue);
              reportBranches(branch.whenFalse);
            } else if (ts.isStringLiteral(branch) && !isIgnoredText(branch.text)) {
              report(branch, `${name}=${branch.text}`);
            } else if (ts.isParenthesizedExpression(branch)) {
              reportBranches(branch.expression);
            }
          };
          reportBranches(expression);
        }
      }
    } else if (
      ts.isPropertyAssignment(node) &&
      (ts.isIdentifier(node.name) || ts.isStringLiteral(node.name)) &&
      USER_FACING_ATTRIBUTES.has(node.name.text) &&
      !insideBlockDefaults(node)
    ) {
      const init = node.initializer;
      if (ts.isStringLiteral(init) && !isIgnoredText(init.text)) {
        report(init, `${node.name.text}: ${init.text}`);
      }
    } else if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
      if (
        !isIgnoredText(node.text) &&
        !isTranslationCall(node, source) &&
        !attributeOf(node)
      ) {
        if (literalIsRendered(node)) {
          report(node, node.text);
        }
      }
    } else if (ts.isTemplateExpression(node)) {
      if (
        !isTranslationCall(node, source) &&
        !isIgnoredText(node.head.text) &&
        !attributeOf(node) &&
        literalIsRendered(node)
      ) {
        report(node, node.head.text);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return findings;
}

describe("reverse i18n lint", () => {
  test(
    "no raw user-facing English in pages or components",
    () => {
      const findings = SCANNED_ROOTS.flatMap((root) =>
        collectSourceFiles(join(SRC, root)).flatMap(inspect),
      );
      const rendered = findings.map((f) => `${f.file}:${f.line}  ${f.text}`);
      expect(rendered.sort()).toEqual([]);
    },
    // A whole-tree TypeScript parse; the 5 s default trips when the
    // coverage run has every worker busy (plan 195 F6).
    20_000,
  );
});
