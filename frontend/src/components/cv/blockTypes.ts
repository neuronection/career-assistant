import {
  AlignLeft,
  Briefcase,
  Heart,
  Languages,
  MoveVertical,
  PenLine,
  Trophy,
  Wrench,
  type LucideIcon,
} from "lucide-react";

export interface BlockTypeSpec {
  value: string;
  label: string;
  description: string;
  icon: LucideIcon;
  props: Record<string, unknown>;
}

export const BLOCK_TYPES: BlockTypeSpec[] = [
  {
    value: "items",
    label: "templateEditor.block.items",
    description: "templateEditor.block.items_desc",
    icon: Briefcase,
    props: {
      title: "Experience",
      source_key: "experience",
      max_items: 10,
      show_skills: true,
      show_achievements: true,
      show_org: true,
      show_description: true,
      date_format: "mon_yyyy",
      style: "list",
    },
  },
  {
    value: "summary",
    label: "templateEditor.block.summary",
    description: "templateEditor.block.summary_desc",
    icon: AlignLeft,
    props: { title: "Summary", max_chars: 600 },
  },
  {
    value: "custom_text",
    label: "templateEditor.block.custom_text",
    description: "templateEditor.block.custom_text_desc",
    icon: PenLine,
    props: { title: "About me", text: "" },
  },
  {
    value: "skills",
    label: "templateEditor.block.skills",
    description: "templateEditor.block.skills_desc",
    icon: Wrench,
    props: { title: "Skills", display: "chips", max_items: 18, show_levels: false },
  },
  {
    value: "languages",
    label: "templateEditor.block.languages",
    description: "templateEditor.block.languages_desc",
    icon: Languages,
    props: { title: "Languages" },
  },
  {
    value: "achievements",
    label: "templateEditor.block.achievements",
    description: "templateEditor.block.achievements_desc",
    icon: Trophy,
    props: { title: "Achievements" },
  },
  {
    value: "interests",
    label: "templateEditor.block.interests",
    description: "templateEditor.block.interests_desc",
    icon: Heart,
    props: { title: "Interests", max_items: 6 },
  },
  {
    value: "spacer",
    label: "templateEditor.block.spacer",
    description: "templateEditor.block.spacer_desc",
    icon: MoveVertical,
    props: { height_mm: 4 },
  },
];

export function blockTypeOf(kind: string): BlockTypeSpec | undefined {
  return BLOCK_TYPES.find((type) => type.value === kind);
}

export const ITEM_SOURCE_OPTIONS = [
  { value: "experience", label: "Experience" },
  { value: "education", label: "Education" },
  { value: "certifications", label: "Certifications" },
  { value: "projects", label: "Projects" },
];

export const SKILLS_DISPLAY_OPTIONS = [
  { value: "chips", label: "Chips" },
  { value: "list", label: "List" },
  { value: "grouped", label: "Grouped" },
  { value: "bars", label: "Bars" },
];

export const DATE_FORMAT_OPTIONS = [
  { value: "mon_yyyy", label: "Jan 2025" },
  { value: "eu", label: "01/2025" },
  { value: "year", label: "2025" },
  { value: "iso", label: "2025-01" },
];

export const ACHIEVEMENT_KIND_OPTIONS = [
  { value: "award", label: "Awards" },
  { value: "honor", label: "Honors" },
  { value: "publication", label: "Publications" },
  { value: "extracurricular", label: "Extracurricular" },
];
