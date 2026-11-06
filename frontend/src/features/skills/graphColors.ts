/** The skill graph's color vocabulary (shared by the taxonomy panel and
 * the skill page's subgraph — plan 148 extraction from SkillRelationsPanel). */

export type RelationKind = "is_a" | "synonym" | "part_of" | "related_to";

export const NODE_COLORS: Record<string, string> = {
  active: "#059669",
  deprecated: "#d97706",
};

export const EDGE_COLORS: Record<string, string> = {
  is_a: "#2563eb",
  synonym: "#059669",
  part_of: "#7c3aed",
  related_to: "#64748b",
};

/** Container-style relations: the parent/container ranks above in the
 * hierarchy layout (an is_a child sits under its parent). */
export const REVERSED_RELATIONS = ["is_a", "part_of"];
