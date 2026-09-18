import { describe, expect, it } from "vitest";

import { normalizeProse } from "./prose";

describe("normalizeProse", () => {
  it("honors single hard breaks", () => {
    expect(normalizeProse("line one\nline two")).toBe("line one\nline two");
  });

  it("collapses blank runs to one break", () => {
    expect(normalizeProse("a\n\n\nb")).toBe("a\nb");
    expect(normalizeProse("a\n \n \nb")).toBe("a\nb");
  });

  it("trims outer whitespace", () => {
    expect(normalizeProse("  hello\n\n")).toBe("hello");
  });
});
