import { useTranslation } from "react-i18next";
import type { CvDesignTokens } from "@/types/cvTemplate";
import {
  ColorField,
  GapsField,
  RangeField,
  SelectField,
  ToggleRow,
} from "@/components/cv/formPrimitives";

type TokenOption = { value: string; labelKey: string };

const FONTS: TokenOption[] = [
  { value: "sans", labelKey: "templateEditor.fonts.sans" },
  { value: "serif", labelKey: "templateEditor.fonts.serif" },
  { value: "mixed", labelKey: "templateEditor.fonts.mixed" },
  { value: "geometric", labelKey: "templateEditor.fonts.geometric" },
  { value: "embedded-sans", labelKey: "templateEditor.fonts.embedded-sans" },
  { value: "embedded-serif", labelKey: "templateEditor.fonts.embedded-serif" },
];
const HEADER_STYLES: TokenOption[] = [
  { value: "left", labelKey: "templateEditor.header_styles.left" },
  { value: "centered", labelKey: "templateEditor.header_styles.centered" },
  { value: "banner", labelKey: "templateEditor.header_styles.banner" },
  { value: "band", labelKey: "templateEditor.header_styles.band" },
];
const DENSITIES: TokenOption[] = [
  { value: "compact", labelKey: "templateEditor.densities.compact" },
  { value: "normal", labelKey: "templateEditor.densities.normal" },
  { value: "roomy", labelKey: "templateEditor.densities.roomy" },
];
const SECTION_STYLES: TokenOption[] = [
  { value: "flat", labelKey: "templateEditor.section_styles.flat" },
  { value: "card", labelKey: "templateEditor.section_styles.card" },
];
const ELEVATIONS: TokenOption[] = [
  { value: "none", labelKey: "templateEditor.elevations.none" },
  { value: "soft", labelKey: "templateEditor.elevations.soft" },
  { value: "raised", labelKey: "templateEditor.elevations.raised" },
];
const HEADING_CASES: TokenOption[] = [
  { value: "uppercase", labelKey: "templateEditor.heading_cases.uppercase" },
  { value: "title", labelKey: "templateEditor.heading_cases.title" },
  { value: "none", labelKey: "templateEditor.heading_cases.none" },
];
const HEADING_RULES: TokenOption[] = [
  { value: "line", labelKey: "templateEditor.heading_rules.line" },
  { value: "accent", labelKey: "templateEditor.heading_rules.accent" },
  { value: "none", labelKey: "templateEditor.heading_rules.none" },
];
const LAYOUTS: TokenOption[] = [
  { value: "single", labelKey: "templateEditor.layouts.single" },
  { value: "sidebar", labelKey: "templateEditor.layouts.sidebar" },
];
const SIDEBAR_SIDES: TokenOption[] = [
  { value: "left", labelKey: "templateEditor.sidebar_sides.left" },
  { value: "right", labelKey: "templateEditor.sidebar_sides.right" },
];

const RUNNING_FOOTERS: TokenOption[] = [
  { value: "none", labelKey: "templateEditor.running_footers.none" },
  { value: "name", labelKey: "templateEditor.running_footers.name" },
  { value: "numbers", labelKey: "templateEditor.running_footers.numbers" },
];

const CHIP_STYLES: TokenOption[] = [
  { value: "tint", labelKey: "templateEditor.chip_styles.tint" },
  { value: "outline", labelKey: "templateEditor.chip_styles.outline" },
  { value: "solid", labelKey: "templateEditor.chip_styles.solid" },
  { value: "plain", labelKey: "templateEditor.chip_styles.plain" },
];

const NAME_STYLES: TokenOption[] = [
  { value: "plain", labelKey: "templateEditor.name_styles.plain" },
  { value: "accent_surname", labelKey: "templateEditor.name_styles.accent_surname" },
];

const PHOTO_SHAPES: TokenOption[] = [
  { value: "circle", labelKey: "templateEditor.photo_shapes.circle" },
  { value: "rounded", labelKey: "templateEditor.photo_shapes.rounded" },
  { value: "square", labelKey: "templateEditor.photo_shapes.square" },
  { value: "arch", labelKey: "templateEditor.photo_shapes.arch" },
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
  const localize = (options: TokenOption[]) =>
    options.map((option) => ({ value: option.value, label: t(option.labelKey) }));
  return (
    <div className="space-y-3" data-testid="design-token-editor">
      <Group title={t("templateEditor.color.group", { defaultValue: "Colors" })} testId="token-colors">
        <ColorField label={t("templateEditor.color.accent")} value={design.accent_color} onChange={(accent_color) => onChange({ accent_color })} />
        <ColorField label={t("templateEditor.color.headings")} value={design.heading_color} onChange={(heading_color) => onChange({ heading_color })} />
        <ColorField label={t("templateEditor.color.body")} value={design.text_color} onChange={(text_color) => onChange({ text_color })} />
        <ColorField label={t("templateEditor.color.muted")} value={design.muted_color} onChange={(muted_color) => onChange({ muted_color })} />
        <ColorField label={t("templateEditor.color.background")} value={design.background_color} onChange={(background_color) => onChange({ background_color })} />
        <ColorField label={t("templateEditor.color.border")} value={design.border_color} onChange={(border_color) => onChange({ border_color })} />
      </Group>

      <Group title={t("templateEditor.typography", { defaultValue: "Typography" })} testId="token-typography">
        <SelectField label={t("templateEditor.fontLabel")} value={design.font_stack} onChange={(font_stack) => onChange({ font_stack: font_stack as CvDesignTokens["font_stack"] })} options={localize(FONTS)} />
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
        <SelectField label={t("templateEditor.headerStyleLabel")} value={design.header_style} onChange={(header_style) => onChange({ header_style: header_style as CvDesignTokens["header_style"] })} options={localize(HEADER_STYLES)} />
        <SelectField label={t("templateEditor.nameStyle")} value={design.name_style} onChange={(name_style) => onChange({ name_style: name_style as CvDesignTokens["name_style"] })} options={localize(NAME_STYLES)} testId="name-style-select" />
        <ToggleRow
          label={t("templateEditor.headingIcons", { defaultValue: "Heading icons" })}
          checked={design.show_heading_icons}
          onChange={(show_heading_icons) => onChange({ show_heading_icons })}
        />
        <SelectField label={t("templateEditor.headingCaseLabel")} value={design.heading_case} onChange={(heading_case) => onChange({ heading_case: heading_case as CvDesignTokens["heading_case"] })} options={localize(HEADING_CASES)} />
        <RangeField label={t("templateEditor.headingWeight")} value={design.heading_weight} min={400} max={800} step={100} onChange={(heading_weight) => onChange({ heading_weight })} />
        <SelectField label={t("templateEditor.headingRuleLabel")} value={design.heading_rule} onChange={(heading_rule) => onChange({ heading_rule: heading_rule as CvDesignTokens["heading_rule"] })} options={localize(HEADING_RULES)} />
      </Group>

      <Group title={t("templateEditor.sections", { defaultValue: "Sections" })} testId="token-sections">
        <SelectField label={t("templateEditor.sectionStyleLabel")} value={design.section_style} onChange={(section_style) => onChange({ section_style: section_style as CvDesignTokens["section_style"] })} options={localize(SECTION_STYLES)} />
        {design.section_style === "card" && (
          <SelectField label={t("templateEditor.elevationLabel", { defaultValue: "Elevation" })} value={design.elevation ?? "none"} onChange={(elevation) => onChange({ elevation: elevation as CvDesignTokens["elevation"] })} options={localize(ELEVATIONS)} testId="elevation-select" />
        )}
        <RangeField label={t("templateEditor.cornerRadius")} value={design.corner_radius} min={0} max={6} onChange={(corner_radius) => onChange({ corner_radius })} suffix="mm" />
        <GapsField label={t("templateEditor.sectionGap")} value={design.section_gap_mm} options={[2, 4, 6, 8, 10, 12]} onChange={(section_gap_mm) => onChange({ section_gap_mm })} />
        <GapsField label={t("templateEditor.itemGap")} value={design.item_gap_mm} options={[1, 2, 3, 4, 5, 6]} onChange={(item_gap_mm) => onChange({ item_gap_mm })} />
        <SelectField
          label={t("templateEditor.chipStyle", { defaultValue: "Chip style" })}
          value={design.chip_style ?? "tint"}
          onChange={(chip_style) => onChange({ chip_style: chip_style as CvDesignTokens["chip_style"] })}
          options={localize(CHIP_STYLES)}
          testId="chip-style-select"
        />
        {(!design.chip_style || design.chip_style === "tint") && (
          <RangeField
            label={t("templateEditor.chipTint", { defaultValue: "Chip tint" })}
            value={design.chip_tint_pct ?? 12}
            min={0}
            max={40}
            onChange={(chip_tint_pct) => onChange({ chip_tint_pct })}
            suffix="%"
          />
        )}
        <SelectField
          label={t("templateEditor.color.chipText")}
          value={design.chip_text_color ? "custom" : "auto"}
          onChange={(next) =>
            next === "custom"
              ? onChange({ chip_text_color: design.heading_color })
              : onChange({ chip_text_color: null })
          }
          options={[
            { value: "auto", label: t("templateEditor.auto") },
            { value: "custom", label: t("templateEditor.custom") },
          ]}
          testId="chip-text-select"
        />
        {design.chip_text_color && (
          <ColorField
            label={t("templateEditor.color.chipText")}
            value={design.chip_text_color}
            onChange={(chip_text_color) => onChange({ chip_text_color })}
          />
        )}
      </Group>

      <Group title={t("templateEditor.page", { defaultValue: "Page" })} testId="token-page">
        <SelectField label={t("templateEditor.densityLabel")} value={design.density} onChange={(density) => onChange({ density: density as CvDesignTokens["density"] })} options={localize(DENSITIES)} />
        <GapsField label={t("templateEditor.pageMargin")} value={design.margin_mm} options={[0, 5, 8, 12, 16, 20, 25]} onChange={(margin_mm) => onChange({ margin_mm })} />
        <SelectField
          label={t("templateEditor.runningFooter", { defaultValue: "Running footer" })}
          value={design.running_footer ?? "none"}
          onChange={(running_footer) => onChange({ running_footer: running_footer as CvDesignTokens["running_footer"] })}
          options={localize(RUNNING_FOOTERS)}
          testId="running-footer-select"
        />
      </Group>

      {showLayout && (
        <Group title={t("templateEditor.layoutLabel", { defaultValue: "Layout" })} testId="token-layout">
          <SelectField label={t("templateEditor.layoutLabel")} value={design.layout} onChange={(layout) => onChange({ layout: layout as CvDesignTokens["layout"] })} options={localize(LAYOUTS)} testId="layout-select" />
          {design.layout === "sidebar" && (
            <div className="space-y-2" data-testid="sidebar-controls">
              <SelectField label={t("templateEditor.sidebarSide")} value={design.sidebar_side} onChange={(sidebar_side) => onChange({ sidebar_side: sidebar_side as CvDesignTokens["sidebar_side"] })} options={localize(SIDEBAR_SIDES)} />
              <ColorField label={t("templateEditor.color.sidebar")} value={design.sidebar_color} onChange={(sidebar_color) => onChange({ sidebar_color })} />
              <ColorField label={t("templateEditor.color.sidebarText")} value={design.sidebar_text_color} onChange={(sidebar_text_color) => onChange({ sidebar_text_color })} />
              <RangeField label={t("templateEditor.sidebarWidth")} value={design.sidebar_width_pct} min={25} max={45} onChange={(sidebar_width_pct) => onChange({ sidebar_width_pct })} suffix="%" />
              <GapsField label={t("templateEditor.mainPadding")} value={design.main_padding_mm} options={[0, 4, 6, 8, 10, 12]} onChange={(main_padding_mm) => onChange({ main_padding_mm })} />
              <GapsField label={t("templateEditor.sidebarPadding")} value={design.sidebar_padding_mm} options={[0, 2, 4, 6, 8, 10]} onChange={(sidebar_padding_mm) => onChange({ sidebar_padding_mm })} />
              <SelectField label={t("templateEditor.mainColumns", { defaultValue: "Main columns" })} value={String(design.main_columns)} onChange={(raw) => onChange({ main_columns: Number(raw) as CvDesignTokens["main_columns"] })} options={[{ value: "1", label: "1" }, { value: "2", label: "2" }]} testId="main-columns-select" />
              <SelectField label={t("templateEditor.sidebarColumns", { defaultValue: "Sidebar columns" })} value={String(design.sidebar_columns)} onChange={(raw) => onChange({ sidebar_columns: Number(raw) as CvDesignTokens["sidebar_columns"] })} options={[{ value: "1", label: "1" }, { value: "2", label: "2" }]} testId="sidebar-columns-select" />
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
                options={localize(PHOTO_SHAPES)}
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
