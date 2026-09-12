import { useTranslation } from "react-i18next";
import type { CvDesignTokens } from "@/types/cvTemplate";
import {
  ColorField,
  GapsField,
  RangeField,
  SelectField,
  ToggleRow,
} from "@/components/cv/formPrimitives";

const FONTS = [
  { value: "sans", label: "Sans" },
  { value: "serif", label: "Serif" },
  { value: "mixed", label: "Mixed" },
  { value: "geometric", label: "Geometric" },
];
const HEADER_STYLES = [
  { value: "left", label: "Left" },
  { value: "centered", label: "Centered" },
  { value: "banner", label: "Banner" },
];
const DENSITIES = [
  { value: "compact", label: "Compact" },
  { value: "normal", label: "Normal" },
  { value: "roomy", label: "Roomy" },
];
const SECTION_STYLES = [
  { value: "flat", label: "Flat" },
  { value: "card", label: "Card" },
];
const HEADING_CASES = [
  { value: "uppercase", label: "UPPERCASE" },
  { value: "title", label: "Title" },
  { value: "none", label: "Normal" },
];
const HEADING_RULES = [
  { value: "line", label: "Line" },
  { value: "accent", label: "Accent line" },
  { value: "none", label: "None" },
];
const LAYOUTS = [
  { value: "single", label: "Single column" },
  { value: "sidebar", label: "Two-column sidebar" },
];
const SIDEBAR_SIDES = [
  { value: "left", label: "Left" },
  { value: "right", label: "Right" },
];

function Group({
  title,
  children,
  testId,
}: {
  title: string;
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <div className="space-y-2 rounded-lg border border-[var(--as-border)] p-2.5" data-testid={testId}>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">{title}</p>
      {children}
    </div>
  );
}

export function DesignTokenEditor({
  design,
  onChange,
  showPhotoControls = true,
  showLayout = true,
}: {
  design: CvDesignTokens;
  onChange: (patch: Partial<CvDesignTokens>) => void;
  showPhotoControls?: boolean;
  showLayout?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-3" data-testid="design-token-editor">
      <Group title={t("templateEditor.color.group", { defaultValue: "Colors" })} testId="token-colors">
        <ColorField label={t("templateEditor.color.accent")} value={design.accent_color} onChange={(accent_color) => onChange({ accent_color })} />
        <ColorField label={t("templateEditor.color.headings")} value={design.heading_color} onChange={(heading_color) => onChange({ heading_color })} />
        <ColorField label={t("templateEditor.color.body")} value={design.text_color} onChange={(text_color) => onChange({ text_color })} />
        <ColorField label={t("templateEditor.color.muted")} value={design.muted_color} onChange={(muted_color) => onChange({ muted_color })} />
        <ColorField label={t("templateEditor.color.background")} value={design.background_color} onChange={(background_color) => onChange({ background_color })} />
      </Group>

      <Group title={t("templateEditor.typography", { defaultValue: "Typography" })} testId="token-typography">
        <SelectField label={t("templateEditor.fontLabel")} value={design.font_stack} onChange={(font_stack) => onChange({ font_stack: font_stack as CvDesignTokens["font_stack"] })} options={FONTS} />
        <RangeField label={t("templateEditor.baseSize")} value={design.base_size_pt} min={7} max={14} onChange={(base_size_pt) => onChange({ base_size_pt })} suffix="pt" />
        <RangeField
          label={t("templateEditor.lineHeight", { defaultValue: "Line height" })}
          value={design.line_height}
          min={1}
          max={2}
          step={0.05}
          onChange={(line_height) => onChange({ line_height })}
        />
        <RangeField
          label={t("templateEditor.spacingScale", { defaultValue: "Spacing scale" })}
          value={design.spacing_scale}
          min={0.6}
          max={1.8}
          step={0.05}
          onChange={(spacing_scale) => onChange({ spacing_scale })}
        />
      </Group>

      <Group title={t("templateEditor.headings", { defaultValue: "Headings" })} testId="token-headings">
        <SelectField label={t("templateEditor.headerStyleLabel")} value={design.header_style} onChange={(header_style) => onChange({ header_style: header_style as CvDesignTokens["header_style"] })} options={HEADER_STYLES} />
        <SelectField label={t("templateEditor.headingCaseLabel")} value={design.heading_case} onChange={(heading_case) => onChange({ heading_case: heading_case as CvDesignTokens["heading_case"] })} options={HEADING_CASES} />
        <RangeField label={t("templateEditor.headingWeight")} value={design.heading_weight} min={400} max={800} step={100} onChange={(heading_weight) => onChange({ heading_weight })} />
        <SelectField label={t("templateEditor.headingRuleLabel")} value={design.heading_rule} onChange={(heading_rule) => onChange({ heading_rule: heading_rule as CvDesignTokens["heading_rule"] })} options={HEADING_RULES} />
      </Group>

      <Group title={t("templateEditor.sections", { defaultValue: "Sections" })} testId="token-sections">
        <SelectField label={t("templateEditor.sectionStyleLabel")} value={design.section_style} onChange={(section_style) => onChange({ section_style: section_style as CvDesignTokens["section_style"] })} options={SECTION_STYLES} />
        <RangeField label={t("templateEditor.cornerRadius")} value={design.corner_radius} min={0} max={6} onChange={(corner_radius) => onChange({ corner_radius })} suffix="mm" />
        <GapsField label={t("templateEditor.sectionGap")} value={design.section_gap_mm} options={[2, 4, 6, 8, 10, 12]} onChange={(section_gap_mm) => onChange({ section_gap_mm })} />
        <GapsField label={t("templateEditor.itemGap")} value={design.item_gap_mm} options={[1, 2, 3, 4, 5, 6]} onChange={(item_gap_mm) => onChange({ item_gap_mm })} />
      </Group>

      <Group title={t("templateEditor.page", { defaultValue: "Page" })} testId="token-page">
        <SelectField label={t("templateEditor.densityLabel")} value={design.density} onChange={(density) => onChange({ density: density as CvDesignTokens["density"] })} options={DENSITIES} />
        <GapsField label={t("templateEditor.pageMargin")} value={design.margin_mm} options={[0, 5, 8, 12, 16, 20, 25]} onChange={(margin_mm) => onChange({ margin_mm })} />
      </Group>

      {showLayout && (
        <Group title={t("templateEditor.layoutLabel", { defaultValue: "Layout" })} testId="token-layout">
          <SelectField label={t("templateEditor.layoutLabel")} value={design.layout} onChange={(layout) => onChange({ layout: layout as CvDesignTokens["layout"] })} options={LAYOUTS} testId="layout-select" />
          {design.layout === "sidebar" && (
            <div className="space-y-2" data-testid="sidebar-controls">
              <SelectField label={t("templateEditor.sidebarSide")} value={design.sidebar_side} onChange={(sidebar_side) => onChange({ sidebar_side: sidebar_side as CvDesignTokens["sidebar_side"] })} options={SIDEBAR_SIDES} />
              <ColorField label={t("templateEditor.color.sidebar")} value={design.sidebar_color} onChange={(sidebar_color) => onChange({ sidebar_color })} />
              <ColorField label={t("templateEditor.color.sidebarText")} value={design.sidebar_text_color} onChange={(sidebar_text_color) => onChange({ sidebar_text_color })} />
              <RangeField label={t("templateEditor.sidebarWidth")} value={design.sidebar_width_pct} min={25} max={45} onChange={(sidebar_width_pct) => onChange({ sidebar_width_pct })} suffix="%" />
              <GapsField label={t("templateEditor.mainPadding")} value={design.main_padding_mm} options={[0, 4, 6, 8, 10, 12]} onChange={(main_padding_mm) => onChange({ main_padding_mm })} />
              <GapsField label={t("templateEditor.sidebarPadding")} value={design.sidebar_padding_mm} options={[0, 2, 4, 6, 8, 10]} onChange={(sidebar_padding_mm) => onChange({ sidebar_padding_mm })} />
            </div>
          )}
        </Group>
      )}

      {showPhotoControls && (
        <Group title={t("templateEditor.profilePhoto", { defaultValue: "Profile photo" })} testId="photo-controls">
          <ToggleRow
            label={t("templateEditor.profilePhoto")}
            checked={design.show_photo}
            onChange={(show_photo) => onChange({ show_photo })}
          />
          {design.show_photo && (
            <>
              <SelectField
                label={t("templateEditor.shape")}
                value={design.photo_shape}
                onChange={(photo_shape) => onChange({ photo_shape: photo_shape as CvDesignTokens["photo_shape"] })}
                options={[
                  { value: "circle", label: "Circle" },
                  { value: "rounded", label: "Rounded" },
                  { value: "square", label: "Square" },
                ]}
              />
              <RangeField label={t("templateEditor.size")} value={design.photo_size_mm} min={10} max={40} onChange={(photo_size_mm) => onChange({ photo_size_mm })} suffix="mm" />
            </>
          )}
          <ToggleRow label={t("templateEditor.contactIcons")} checked={design.show_icons} onChange={(show_icons) => onChange({ show_icons })} />
          {design.show_icons && (
            <RangeField label={t("templateEditor.iconSize")} value={design.icon_size_mm} min={2} max={6} step={0.2} onChange={(icon_size_mm) => onChange({ icon_size_mm })} suffix="mm" />
          )}
        </Group>
      )}
    </div>
  );
}
