/**
 * Pure rectangle-border geometry that picks the side of each node an edge
 * should leave from and enter, so a family constellation never routes an edge
 * across its own node box.
 *
 * The candidate side is the one the centre-to-centre segment crosses first.
 * When that segment hits a corner (both borders within `NEAR_TIE_TOLERANCE`
 * pixels) the side whose midpoint sits closer to the other rectangle wins, and
 * a true draw falls back to the dominant axis, so the result never depends on
 * iteration order.
 */

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export type EdgeSide = "left" | "right" | "top" | "bottom";

export const NEAR_TIE_TOLERANCE = 0.5;

export interface EdgeSides {
  source: EdgeSide;
  target: EdgeSide;
}

function center(rect: Rect): { x: number; y: number } {
  return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
}

function sideMidpoint(rect: Rect, side: EdgeSide): { x: number; y: number } {
  switch (side) {
    case "left":
      return { x: rect.x, y: rect.y + rect.height / 2 };
    case "right":
      return { x: rect.x + rect.width, y: rect.y + rect.height / 2 };
    case "top":
      return { x: rect.x + rect.width / 2, y: rect.y };
    case "bottom":
      return { x: rect.x + rect.width / 2, y: rect.y + rect.height };
  }
}

function distanceToRect(point: { x: number; y: number }, rect: Rect): number {
  const dx = Math.max(0, rect.x - point.x, point.x - (rect.x + rect.width));
  const dy = Math.max(0, rect.y - point.y, point.y - (rect.y + rect.height));
  return Math.hypot(dx, dy);
}

function horizontalSide(dx: number): EdgeSide {
  return dx >= 0 ? "right" : "left";
}

function verticalSide(dy: number): EdgeSide {
  return dy >= 0 ? "bottom" : "top";
}

/** Side of `from` that faces `to`, resolved by rectangle border intersection. */
export function nearestSide(from: Rect, to: Rect, tolerance: number = NEAR_TIE_TOLERANCE): EdgeSide {
  const origin = center(from);
  const target = center(to);
  const dx = target.x - origin.x;
  const dy = target.y - origin.y;
  if (dx === 0 && dy === 0) {
    return "right";
  }

  const length = Math.hypot(dx, dy);
  const horizontal = horizontalSide(dx);
  const vertical = verticalSide(dy);
  const distanceToVerticalBorder = dx === 0 ? Number.POSITIVE_INFINITY : (from.width / 2) * (length / Math.abs(dx));
  const distanceToHorizontalBorder =
    dy === 0 ? Number.POSITIVE_INFINITY : (from.height / 2) * (length / Math.abs(dy));

  if (Math.abs(distanceToVerticalBorder - distanceToHorizontalBorder) <= tolerance) {
    const horizontalDistance = distanceToRect(sideMidpoint(from, horizontal), to);
    const verticalDistance = distanceToRect(sideMidpoint(from, vertical), to);
    if (Math.abs(horizontalDistance - verticalDistance) > tolerance) {
      return horizontalDistance < verticalDistance ? horizontal : vertical;
    }
    return Math.abs(dx) >= Math.abs(dy) ? horizontal : vertical;
  }

  return distanceToVerticalBorder < distanceToHorizontalBorder ? horizontal : vertical;
}

/** The source and target sides for one edge between two node boxes. */
export function chooseNearestSides(
  source: Rect,
  target: Rect,
  tolerance: number = NEAR_TIE_TOLERANCE,
): EdgeSides {
  return {
    source: nearestSide(source, target, tolerance),
    target: nearestSide(target, source, tolerance),
  };
}

/** React Flow handle id for a side, e.g. `s-right` / `t-top`. */
export function handleId(kind: "source" | "target", side: EdgeSide): string {
  return `${kind === "source" ? "s" : "t"}-${side}`;
}
