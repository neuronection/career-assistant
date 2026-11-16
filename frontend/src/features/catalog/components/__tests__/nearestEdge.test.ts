import { describe, expect, it } from "vitest";

import { chooseNearestSides, handleId, nearestSide, type Rect } from "../nearestEdge";

const box = (x: number, y: number, width = 150, height = 44): Rect => ({ x, y, width, height });

describe("nearestSide", () => {
  it("leaves to the right of a horizontally aligned target", () => {
    const source = box(0, 0);
    const target = box(300, 0);
    expect(nearestSide(source, target)).toBe("right");
    expect(nearestSide(target, source)).toBe("left");
  });

  it("drops below a vertically aligned target", () => {
    const source = box(0, 0);
    const target = box(0, 200);
    expect(nearestSide(source, target)).toBe("bottom");
    expect(nearestSide(target, source)).toBe("top");
  });

  it("resolves a 45-degree diagonal deterministically", () => {
    const source = box(0, 0, 100, 100);
    const target = box(200, 200, 100, 100);
    const sides = chooseNearestSides(source, target);
    expect(sides).toEqual({ source: "right", target: "left" });
    expect(chooseNearestSides(source, target)).toEqual(sides);
  });

  it("resolves a near tie inside the tolerance towards the closer side", () => {
    const source = box(0, 0);
    const target = box(162, 47.52);
    expect(nearestSide(source, target)).toBe("right");
    expect(nearestSide(target, source)).toBe("left");
  });

  it("resolves the same pair without a tolerance by border distance", () => {
    const source = box(0, 0);
    const target = box(162, 47.52);
    expect(nearestSide(source, target, 0)).toBe("bottom");
    expect(nearestSide(target, source, 0)).toBe("top");
  });

  it("uses the dominant axis for a truly symmetric tie", () => {
    const source = box(0, 0, 100, 100);
    const target = box(200, 200, 100, 100);
    expect(nearestSide(source, target, 0)).toBe("right");
    expect(nearestSide(source, box(-200, 200, 100, 100), 0)).toBe("left");
    expect(nearestSide(source, box(0, 300, 100, 100), 0)).toBe("bottom");
    expect(nearestSide(source, box(0, -300, 100, 100), 0)).toBe("top");
  });

  it("never produces NaN for overlapping or identical boxes", () => {
    const source = box(0, 0);
    expect(nearestSide(source, source)).toBe("right");
    expect(nearestSide(source, box(75, 0))).toBe("right");
    expect(nearestSide(source, box(-75, 0))).toBe("left");
    expect(nearestSide(source, box(0, 100))).toBe("bottom");
    expect(nearestSide(source, box(0, -100))).toBe("top");
  });

  it("pairs the source and target sides on the same axis", () => {
    const pairs: Array<[Rect, Rect]> = [
      [box(0, 0), box(400, 12)],
      [box(0, 0), box(12, 400)],
      [box(120, 80), box(340, 240)],
      [box(340, 240), box(120, 80)],
    ];
    for (const [source, target] of pairs) {
      const sides = chooseNearestSides(source, target);
      const horizontal = sides.source === "left" || sides.source === "right";
      expect(horizontal ? sides.target === "left" || sides.target === "right" : sides.target === "top" || sides.target === "bottom").toBe(
        true,
      );
    }
  });
});

describe("handleId", () => {
  it("names the eight measured handles", () => {
    expect(handleId("source", "left")).toBe("s-left");
    expect(handleId("source", "right")).toBe("s-right");
    expect(handleId("source", "top")).toBe("s-top");
    expect(handleId("source", "bottom")).toBe("s-bottom");
    expect(handleId("target", "left")).toBe("t-left");
    expect(handleId("target", "right")).toBe("t-right");
    expect(handleId("target", "top")).toBe("t-top");
    expect(handleId("target", "bottom")).toBe("t-bottom");
  });
});
