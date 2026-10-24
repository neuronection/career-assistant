import {
  AlignLeft,
  Briefcase,
  Heart,
  IdCard,
  Languages,
  MoveVertical,
  PenLine,
  QrCode,
  Sparkles,
  Trophy,
  Wrench,
  type LucideIcon,
} from "lucide-react";

export interface BlockTypeSpec {
  value: string;
  labelKey: string;
  descriptionKey: string;
  icon: LucideIcon;
  props: Record<string, unknown>;
}

export const BLOCK_TYPES: BlockTypeSpec[] = [
  {
    value: "items",
    labelKey: "templateEditor.block.items",
    descriptionKey: "templateEditor.block.items_desc",
    icon: Briefcase,
    props: {
      title: "Work Experience",
      source_key: "experience",
      max_items: 10,
      show_skills: true,
      show_achievements: true,
      show_links: false,
      show_org: true,
      show_description: true,
      date_format: "mon_yyyy",
      style: "list",
    },
  },
  {
    value: "summary",
    labelKey: "templateEditor.block.summary",
    descriptionKey: "templateEditor.block.summary_desc",
    icon: AlignLeft,
    props: { title: "Summary", max_chars: 600 },
  },
  {
    value: "custom_text",
    labelKey: "templateEditor.block.custom_text",
    descriptionKey: "templateEditor.block.custom_text_desc",
    icon: PenLine,
    props: { title: "About me", text: "" },
  },
  {
    value: "skills",
    labelKey: "templateEditor.block.skills",
    descriptionKey: "templateEditor.block.skills_desc",
    icon: Wrench,
    props: { title: "Skills", display: "chips", max_items: 18, show_levels: false },
  },
  {
    value: "languages",
    labelKey: "templateEditor.block.languages",
    descriptionKey: "templateEditor.block.languages_desc",
    icon: Languages,
    props: { title: "Languages", display: "chips", show_cefr: false, show_proficiency: false },
  },
  {
    value: "achievements",
    labelKey: "templateEditor.block.achievements",
    descriptionKey: "templateEditor.block.achievements_desc",
    icon: Trophy,
    props: { title: "Achievements" },
  },
  {
    value: "interests",
    labelKey: "templateEditor.block.interests",
    descriptionKey: "templateEditor.block.interests_desc",
    icon: Heart,
    props: { title: "Interests", max_items: 6 },
  },
  {
    value: "synth_items",
    labelKey: "cvSynth.block.label",
    descriptionKey: "cvSynth.block.description",
    icon: Sparkles,
    props: {
      title: "Highlights",
      selected: [],
      show_source_chips: true,
      max_items: 6,
    },
  },
  {
    value: "spacer",
    labelKey: "templateEditor.block.spacer",
    descriptionKey: "templateEditor.block.spacer_desc",
    icon: MoveVertical,
    props: { height_mm: 4 },
  },
  {
    value: "qr",
    labelKey: "templateEditor.block.qr",
    descriptionKey: "templateEditor.block.qr_desc",
    icon: QrCode,
    props: { link_kind: "web", size_mm: 24 },
  },
];

export function blockTypeOf(kind: string): BlockTypeSpec | undefined {
  return BLOCK_TYPES.find((type) => type.value === kind);
}

const KIND_FALLBACK_ICONS: Record<string, LucideIcon> = {
  header: IdCard,
  qr: QrCode,
};

const KIND_FALLBACK_LABELS: Record<string, string> = {
  header: "templateEditor.block.header",
  qr: "templateEditor.block.qr",
};

export function blockIconOf(kind: string): LucideIcon {
  return blockTypeOf(kind)?.icon ?? KIND_FALLBACK_ICONS[kind] ?? Sparkles;
}

export function blockLabelOf(kind: string): string {
  const spec = blockTypeOf(kind);
  return spec ? spec.labelKey : KIND_FALLBACK_LABELS[kind] ?? kind;
}

export function blockHasTitle(kind: string): boolean {
  const spec = blockTypeOf(kind);
  return Boolean(spec && "title" in spec.props);
}

export const ITEM_SOURCE_OPTIONS = [
  { value: "experience", labelKey: "templateEditor.item_sources.experience" },
  { value: "education", labelKey: "templateEditor.item_sources.education" },
  { value: "certifications", labelKey: "templateEditor.item_sources.certifications" },
  { value: "projects", labelKey: "templateEditor.item_sources.projects" },
  { value: "volunteer", labelKey: "templateEditor.item_sources.volunteer" },
];

export const EXPERIENCE_KIND_OPTIONS = [
  { value: "job", labelKey: "templateEditor.experience_kinds.job" },
  { value: "internship", labelKey: "templateEditor.experience_kinds.internship" },
  { value: "freelance", labelKey: "templateEditor.experience_kinds.freelance" },
];

export const SKILLS_DISPLAY_OPTIONS = [
  { value: "chips", labelKey: "templateEditor.skills_display.chips" },
  { value: "list", labelKey: "templateEditor.skills_display.list" },
  { value: "grouped", labelKey: "templateEditor.skills_display.grouped" },
  { value: "bars", labelKey: "templateEditor.skills_display.bars" },
];

export const DATE_FORMAT_OPTIONS = [
  { value: "mon_yyyy", labelKey: "templateEditor.date_formats.mon_yyyy" },
  { value: "eu", labelKey: "templateEditor.date_formats.eu" },
  { value: "year", labelKey: "templateEditor.date_formats.year" },
  { value: "iso", labelKey: "templateEditor.date_formats.iso" },
];

export const ACHIEVEMENT_KIND_OPTIONS = [
  { value: "award", labelKey: "templateEditor.achievement_kinds.award" },
  { value: "honor", labelKey: "templateEditor.achievement_kinds.honor" },
  { value: "publication", labelKey: "templateEditor.achievement_kinds.publication" },
  { value: "extracurricular", labelKey: "templateEditor.achievement_kinds.extracurricular" },
];
