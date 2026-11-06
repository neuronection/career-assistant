import axe from "axe-core";
import { expect } from "vitest";

type AxeOptions = Parameters<typeof axe.run>[1];

/**
 * Assert that a rendered surface has no axe violations.
 *
 * jsdom has no layout engine, so `color-contrast` is meaningless there and
 * the full-page `region`/`landmark-one-main` rules are excluded for
 * component fragments (a shell fragment is not a document). Everything
 * else — names, roles, label association, aria misuse — runs for real.
 */
export async function expectNoA11yViolations(
  container: HTMLElement,
  options: AxeOptions = {}
) {
  const results = await axe.run(container, {
    rules: {
      "color-contrast": { enabled: false },
      region: { enabled: false },
      "landmark-one-main": { enabled: false },
      ...(options.rules ?? {}),
    },
    ...options,
  });
  const violations = results.violations.map(
    (violation) =>
      `${violation.id}: ${violation.help} (${violation.nodes
        .map((node) => node.target.join(" "))
        .join(", ")})`
  );
  expect(violations).toEqual([]);
}
