import type { LucideIcon } from "lucide-react";
import {
  Archive,
  Brain,
  Briefcase,
  Building2,
  CircleCheck,
  ClipboardCheck,
  Cpu,
  FileText,
  FlaskConical,
  Gauge,
  Globe,
  GraduationCap,
  Hammer,
  Languages,
  Layers,
  MessagesSquare,
  Palette,
  Sparkles,
  Tag,
  Trophy,
  Users,
  Wrench,
} from "lucide-react";

/** Category → icon registry for the taxonomy listing (plan 150): rows and
 * category groups key off the row's own category; unknown categories fall
 * back to the generic tag icon. */
export const CATEGORY_ICONS: Record<string, LucideIcon> = {
  // interest categories (seed: taxonomy.json INTEREST_TAGS)
  arts: Palette,
  business: Briefcase,
  "hands-on": Hammer,
  people: Users,
  science: FlaskConical,
  society: Globe,
  sports: Trophy,
  technology: Cpu,
  // skill categories (seed + runtime extraction)
  technical: Cpu,
  communication: MessagesSquare,
  interpersonal: Users,
  creative: Palette,
  cognitive: Brain,
  physical: Hammer,
};

export function categoryIcon(category: string): LucideIcon {
  return CATEGORY_ICONS[category] ?? Tag;
}

/** Skill status groups (triage order: proposed first) + their icons. */
export const STATUS_GROUP_ICONS: Record<string, LucideIcon> = {
  proposed: Sparkles,
  active: CircleCheck,
  deprecated: Archive,
};

/** Label-overlay entity kinds in review-board group order (plan 150
 * phase 4: the translation queue reads as job/skill/family work first,
 * then the institution/template kinds); unknown kinds fall back to the
 * generic languages icon. */
export const OVERLAY_KIND_ICONS: Record<string, LucideIcon> = {
  job: Briefcase,
  skill: Wrench,
  family: Layers,
  university: GraduationCap,
  department: Building2,
  metric_dimension: Gauge,
  assessment_template: ClipboardCheck,
  cv_template: FileText,
};

export function overlayKindIcon(kind: string): LucideIcon {
  return OVERLAY_KIND_ICONS[kind] ?? Languages;
}
