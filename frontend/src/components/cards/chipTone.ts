import type { LucideIcon } from "lucide-react";
import type { BadgeProps } from "@/components/ui/Badge";

export type ChipTone =
  | "neutral"
  | "outline"
  | "primary"
  | "success"
  | "warning"
  | "danger"
  | "ai";

export type ChipVariant = NonNullable<BadgeProps["variant"]>;

export const CHIP_VARIANT: Record<ChipTone, ChipVariant> = {
  neutral: "secondary",
  outline: "outline",
  primary: "default",
  success: "success",
  warning: "warning",
  danger: "danger",
  ai: "ai",
};

export interface ChipItem {
  key: string;
  label: string;
  tone?: ChipTone;
  title?: string;
  icon?: LucideIcon;
  /** Skill variant only: 1–10 requirement score (heat bullet + number). */
  score?: number | null;
  /** Skill variant only: the skill is not resolved in the taxonomy. */
  unmapped?: boolean;
  /** Skill variant only: opt-in skill-peek affordance (plan 149). */
  onOpen?: (trigger: HTMLElement | null) => void;
}
