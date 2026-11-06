import type { CvAreaId, CvBlock } from "@/types/cv";
import type { CvDesignTokens } from "@/types/cvTemplate";

export type { CvAreaId };

export interface CvArea {
  id: CvAreaId;
  labelKey: string;
}

export function areasForDesign(design: Partial<CvDesignTokens> | null | undefined): CvArea[] {
  if (!design || design.layout !== "sidebar") return [{ id: "main", labelKey: "templateEditor.area.main" }];
  const sidebarLabelKey =
    design.sidebar_side === "right"
      ? "templateEditor.area.rightPanel"
      : "templateEditor.area.leftPanel";
  return design.sidebar_side === "right"
    ? [
        { id: "main", labelKey: "templateEditor.area.main" },
        { id: "sidebar", labelKey: sidebarLabelKey },
      ]
    : [
        { id: "sidebar", labelKey: sidebarLabelKey },
        { id: "main", labelKey: "templateEditor.area.main" },
      ];
}

export function areaOf(block: CvBlock | undefined | null): CvAreaId {
  const area = block?.area ?? (block as { column?: unknown } | undefined)?.column;
  return area === "sidebar" ? "sidebar" : "main";
}
