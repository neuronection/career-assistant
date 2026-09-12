export interface CvDesignTokens {
  accent_color: string;
  text_color: string;
  muted_color: string;
  heading_color: string;
  background_color: string;
  font_stack: "sans" | "serif" | "mixed" | "geometric";
  base_size_pt: number;
  line_height: number;
  spacing_scale: number;
  header_style: "left" | "centered" | "banner";
  show_photo: boolean;
  density: "compact" | "normal" | "roomy";
  margin_mm: number | null;
  section_style: "flat" | "card";
  corner_radius: number;
  heading_case: "uppercase" | "title" | "none";
  heading_weight: number;
  heading_rule: "line" | "none" | "accent";
  show_icons: boolean;
  icon_size_mm: number;
  photo_shape: "circle" | "rounded" | "square";
  photo_size_mm: number;
  section_gap_mm: number | null;
  item_gap_mm: number | null;
  border_color: string;
  layout: "single" | "sidebar";
  sidebar_side: "left" | "right";
  sidebar_color: string;
  sidebar_text_color: string;
  sidebar_width_pct: number;
  main_padding_mm: number | null;
  sidebar_padding_mm: number | null;
}

export interface TemplateContent {
  blocks: CvTemplateBlock[];
  design: CvDesignTokens;
  pages: { default_max_pages: number; overflow_policy: string };
  prompts: { field_prompts: Record<string, string>; field_handling: string };
}

export interface CvTemplateBlock {
  kind: string;
  area?: "main" | "sidebar";
  column?: "main" | "sidebar";
  props?: Record<string, unknown>;
}

export interface BlockContainer {
  container?:
    | "inherit"
    | "flat"
    | "tinted"
    | "card"
    | "outline"
    | "accent-bar";
  background?: string | null;
  border_color?: string | null;
  radius?: number | null;
  padding_mm?: number | null;
}

export interface CvTemplateSummary {
  id: string;
  key: string;
  version: number;
  title: string;
  description: string;
  author_key: string;
  source: string;
  visibility: string;
  language: string;
  page_size: string;
  ats_safe: boolean;
  status: string;
  content: {
    blocks?: { kind: string; props?: Record<string, unknown> }[];
    design?: {
      accent_color?: string;
      font_stack?: string;
      density?: string;
      header_style?: string;
      [key: string]: unknown;
    };
    pages?: { default_max_pages?: number; overflow_policy?: string };
    prompts?: Record<string, unknown>;
  };
  content_hash: string;
}
