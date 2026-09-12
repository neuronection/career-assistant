import type { CvAreaId, CvBlock } from "@/types/cv";
import type { CvDesignTokens } from "@/types/cvTemplate";

export type { CvAreaId };

export interface CvArea {
  id: CvAreaId;
  label: string;
}

export function areasForDesign(design: Partial<CvDesignTokens> | null | undefined): CvArea[] {
  if (!design || design.layout !== "sidebar") return [{ id: "main", label: "Main" }];
  const sidebarLabel = design.sidebar_side === "right" ? "Right panel" : "Left panel";
  return design.sidebar_side === "right"
    ? [
        { id: "main", label: "Main" },
        { id: "sidebar", label: sidebarLabel },
      ]
    : [
        { id: "sidebar", label: sidebarLabel },
        { id: "main", label: "Main" },
      ];
}

export function areaOf(block: CvBlock | undefined | null): CvAreaId {
  const area = block?.area ?? (block as { column?: unknown } | undefined)?.column;
  return area === "sidebar" ? "sidebar" : "main";
}
