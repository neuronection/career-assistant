import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowDown,
  ArrowUp,
  Save,
  Settings2,
  Trash2,
} from "lucide-react";
import { Button, Card, EmptyState } from "@/components/ui";
import { apiDetail } from "@/api/client";
import { fetchTemplates } from "@/api/cvTemplates";
import type { CvTheme } from "@/api/cvTemplateDraft";
import {
  createTemplate,
  fetchThemes,
  previewTemplateDraft,
  publishTemplateVersion,
} from "@/api/cvTemplateDraft";
import { useToastStore } from "@/stores/toastStore";
import type { CvTemplateSummary, TemplateContent } from "@/types/cvTemplate";
import {
  blockTypeOf,
  type BlockTypeSpec,
} from "@/components/cv/blockTypes";
import {
  ChipTogglesRow,
  RangeField,
  SegmentedRow,
  SelectField,
  StepperRow,
  ToggleRow,
} from "@/components/cv/formPrimitives";
import { DesignTokenEditor } from "@/components/cv/DesignTokenEditor";
import { ContainerEditor } from "@/components/cv/ContainerEditor";
import { BlockTypePicker } from "@/components/cv/BlockTypePicker";
import { CustomTextEditor } from "@/components/cv/CustomTextEditor";

const ITEM_SOURCES = [
  { value: "Experience", label: "experience", labelKey: "templateEditor.item_sources.experience" },
  { value: "Education", label: "education", labelKey: "templateEditor.item_sources.education" },
  { value: "Certifications", label: "certifications", labelKey: "templateEditor.item_sources.certifications" },
  { value: "Projects", label: "projects", labelKey: "templateEditor.item_sources.projects" },
];
const ITEM_STYLES = [
  { value: "List", label: "list", labelKey: "templateEditor.item_styles.list" },
  { value: "Timeline", label: "timeline", labelKey: "templateEditor.item_styles.timeline" },
];
const DATE_FORMATS = [
  { value: "mon_yyyy", label: "Jun 2024" },
  { value: "iso", label: "2024-06" },
  { value: "eu", label: "06/2024" },
  { value: "year", label: "2024" },
];
const OVERFLOW_POLICIES = [
  { value: "Warn", label: "warn", labelKey: "templateEditor.overflow_policies.warn" },
  { value: "Shrink to fit", label: "shrink", labelKey: "templateEditor.overflow_policies.shrink" },
  { value: "Truncate", label: "truncate", labelKey: "templateEditor.overflow_policies.truncate" },
];
const HEADER_BLOCK: BlockTypeSpec = {
  value: "header",
  label: "templateEditor.header.label",
  description: "templateEditor.header.description",
  icon: blockTypeOf("summary")!.icon,
  props: {},
};

const EMPTY_CONTENT: TemplateContent = {
  blocks: [{ kind: "header" }, { kind: "summary" }],
  design: {
    accent_color: "#1d4ed8",
    text_color: "#111827",
    muted_color: "#6b7280",
    heading_color: "#0f172a",
    background_color: "#ffffff",
    font_stack: "sans",
    base_size_pt: 10,
    line_height: 1.35,
    spacing_scale: 1,
    header_style: "left",
    show_photo: false,
    density: "normal",
    margin_mm: null,
    section_style: "flat",
    corner_radius: 0,
    heading_case: "uppercase",
    heading_weight: 600,
    heading_rule: "line",
    show_icons: true,
    icon_size_mm: 3.2,
    photo_shape: "circle",
    photo_size_mm: 22,
    section_gap_mm: null,
    item_gap_mm: null,
    border_color: "#e5e7eb",
    layout: "single",
    sidebar_side: "left",
    sidebar_color: "#16324f",
    sidebar_text_color: "#ffffff",
    sidebar_width_pct: 34,
    main_padding_mm: null,
    sidebar_padding_mm: null,
  },
  pages: { default_max_pages: 1, overflow_policy: "warn" },
  prompts: { field_prompts: {}, field_handling: "" },
};

export function CvTemplateEditor() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const pushToast = useToastStore((state) => state.push);
  const [source, setSource] = useState<CvTemplateSummary | null>(null);
  const [content, setContent] = useState<TemplateContent>(EMPTY_CONTENT);
  const [themes, setThemes] = useState<CvTheme[]>([]);
  const [title, setTitle] = useState("");
  const [html, setHtml] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  const dragIndex = useRef<number | null>(null);
  const previewTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [rows, themeRows] = await Promise.all([
          fetchTemplates(),
          fetchThemes(),
        ]);
        if (cancelled) return;
        setThemes(themeRows);
        const template = rows.find((row) => row.id === id);
        if (!template) {
          setError(t("templateEditor.notFound"));
          return;
        }
        setSource(template);
        setTitle(template.title);
        setContent({
          ...EMPTY_CONTENT,
          ...template.content,
          design: { ...EMPTY_CONTENT.design, ...(template.content.design ?? {}) },
          pages: { ...EMPTY_CONTENT.pages, ...(template.content.pages ?? {}) },
          prompts: { ...EMPTY_CONTENT.prompts, ...(template.content.prompts ?? {}) },
        } as TemplateContent);
      } catch (err) {
        if (!cancelled) setError(apiDetail(err));
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const refreshPreview = useCallback(async (draft: TemplateContent) => {
    try {
      setHtml(await previewTemplateDraft(draft));
    } catch (err) {
      setError(apiDetail(err));
    }
  }, []);

  useEffect(() => {
    if (!loaded) return;
    if (previewTimer.current) clearTimeout(previewTimer.current);
    previewTimer.current = setTimeout(() => void refreshPreview(content), 400);
    return () => {
      if (previewTimer.current) clearTimeout(previewTimer.current);
    };
  }, [content, loaded, refreshPreview]);

  const setDesign = (patch: Partial<TemplateContent["design"]>) =>
    setContent((current) => ({ ...current, design: { ...current.design, ...patch } }));
  const setPages = (patch: Partial<TemplateContent["pages"]>) =>
    setContent((current) => ({ ...current, pages: { ...current.pages, ...patch } }));
  const setBlocks = (next: TemplateContent["blocks"]) =>
    setContent((current) => ({ ...current, blocks: next }));
  const setBlockProps = (index: number, patch: Record<string, unknown>) =>
    setContent((current) => ({
      ...current,
      blocks: current.blocks.map((block, position) =>
        position === index
          ? { ...block, props: { ...(block.props ?? {}), ...patch } }
          : block
      ),
    }));

  function moveBlock(from: number, to: number) {
    if (to < 0 || to >= content.blocks.length) return;
    const next = [...content.blocks];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    setBlocks(next);
  }

  async function save() {
    setSaving(true);
    setError("");
    try {
      if (source && source.author_key !== "bank") {
        await publishTemplateVersion(source.id, {
          title,
          content,
          description: source.description,
        });
      } else {
        const created = await createTemplate({
          title: `${title} (custom)`,
          content,
          description: source ? `Based on ${source.title}` : "",
        });
        navigate(`/cv/templates/${created.id}`, { replace: true });
      }
      pushToast({
        title: t("templateEditor.savedTitle"),
        body: t("templateEditor.savedBody", { title }),
        severity: "success",
        link: "",
      });
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setSaving(false);
    }
  }

  if (!loaded) {
    return (
      <div className="p-6 text-sm text-[var(--as-muted-fg)]">
        {t("templateEditor.loadingEditor")}
      </div>
    );
  }
  if (!source) {
    return (
      <div className="p-6">
        <EmptyState title={t("templateEditor.notFound")} description={error} />
      </div>
    );
  }
  const isBank = source.author_key === "bank";

  return (
    <div className="flex min-h-0 flex-col gap-3 lg:h-full" data-testid="cv-template-editor">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-48 max-w-md flex-1 basis-64">
          <input
            aria-label={t("templateEditor.titleAria")}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            className="-mx-1.5 w-full rounded-md border border-transparent px-1.5 py-0.5 text-xl font-semibold outline-none transition-colors duration-150 hover:border-[var(--as-border)] focus:border-[var(--as-accent)] focus:bg-[var(--as-surface)]"
            data-testid="template-title"
          />
          <p className="px-1.5 text-xs text-[var(--as-muted-fg)]">
            {isBank
              ? t("templateEditor.bankNote")
              : t("templateEditor.versionNote")}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => navigate(-1)}>{t("templateEditor.back")}</Button>
          <Button onClick={save} disabled={saving} data-testid="save-template">
            <Save className="mr-1 h-4 w-4" aria-hidden />
            {isBank ? t("templateEditor.saveAsCopy") : t("templateEditor.saveVersion")}
          </Button>
        </div>
      </div>

      {error && (
        <p role="alert" className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </p>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[minmax(330px,400px)_minmax(0,1fr)] lg:gap-4">
        <div
          className="min-h-0 space-y-3 lg:overflow-y-auto lg:pr-1"
          data-testid="template-editor-side"
        >
          <Card className="space-y-3 p-3">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">{t("templateEditor.theme")}</h2>
            <div className="grid grid-cols-2 gap-1.5">
              {themes.map((theme) => (
                <button
                  key={theme.key}
                  type="button"
                  title={theme.description}
                  onClick={() => setDesign(theme.design)}
                  className="flex cursor-pointer items-center gap-2 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] p-2 text-left text-xs text-[var(--as-fg)] transition-colors duration-150 hover:border-[var(--as-accent)]"
                  data-testid={`theme-${theme.key}`}
                >
                  <span
                    className="h-5 w-5 shrink-0 rounded-full border border-[var(--as-border)]"
                    style={{ backgroundColor: theme.accent_color }}
                  />
                  <span className="truncate">{theme.label}</span>
                </button>
              ))}
            </div>
            <div className="space-y-2 border-t border-[var(--as-border)] pt-2" data-testid="custom-colors">
              <DesignTokenEditor design={content.design} onChange={setDesign} showPhotoControls={false} showLayout={false} />
            </div>
          </Card>

          <Card className="space-y-2.5 p-3">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">{t("templateEditor.typography")}</h2>
            <DesignTokenEditor design={content.design} onChange={setDesign} />
            <RangeField label={t("templateEditor.maxPages")} value={content.pages.default_max_pages} min={1} max={3} onChange={(default_max_pages) => setPages({ default_max_pages })} />
            <SelectField label={t("templateEditor.overflowPolicy")} value={content.pages.overflow_policy} onChange={(overflow_policy) => setPages({ overflow_policy: overflow_policy as TemplateContent["pages"]["overflow_policy"] })} options={OVERFLOW_POLICIES.map((o) => ({ value: o.value, label: t(o.labelKey, { defaultValue: o.label }) }))} />
          </Card>

          <Card className="space-y-2 p-3">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">{t("templateEditor.sections")}</h2>
              <span className="text-xs text-[var(--as-muted-fg)]">{content.blocks.length}</span>
            </div>
            <BlockTypePicker
              extraTypes={[HEADER_BLOCK]}
              onAdd={(kind) => setBlocks([...content.blocks, { kind }])}
            />
            <ul className="space-y-1.5">
              {content.blocks.map((block, index) => {
                const bp = (block.props ?? {}) as Record<string, unknown>;
                const type = blockTypeOf(block.kind);
                const Icon = type?.icon ?? HEADER_BLOCK.icon;
                const box = (bp.container ?? {}) as Record<string, unknown>;
                const open = openIndex === index;
                return (
                  <li
                    key={`${block.kind}-${index}`}
                    draggable
                    onDragStart={() => {
                      dragIndex.current = index;
                    }}
                    onDragOver={(event) => {
                      event.preventDefault();
                      setDragOverIndex(index);
                    }}
                    onDragLeave={() => setDragOverIndex((current) => (current === index ? null : current))}
                    onDrop={(event) => {
                      event.preventDefault();
                      if (dragIndex.current !== null) moveBlock(dragIndex.current, index);
                      dragIndex.current = null;
                      setDragOverIndex(null);
                    }}
                    className={`rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-sm transition-colors ${
                      dragOverIndex === index ? "cv-drop-slot" : ""
                    }`}
                    data-testid={`block-row-${index}`}
                  >
                    <div className="flex items-center gap-1">
                      <span
                        draggable
                        className="cursor-grab select-none px-0.5 text-[var(--as-muted-fg)]"
                        title={t("templateEditor.dragToReorder")}
                        aria-label={t("templateEditor.dragToReorder")}
                      >
                        ⠿
                      </span>
                      <Icon className="h-3.5 w-3.5 shrink-0 text-[var(--as-accent)]" aria-hidden />
                      <input
                        aria-label={t("templateEditor.sectionTitleAria")}
                        className="min-w-0 flex-1 rounded border border-transparent bg-transparent px-1 py-0.5 font-medium outline-none transition-colors hover:border-[var(--as-border)] focus:border-[var(--as-accent)]"
                        value={String(bp.title ?? block.kind)}
                        onChange={(event) => setBlockProps(index, { title: event.target.value })}
                      />
                      <button
                        type="button"
                        aria-expanded={open}
                        aria-label={t("templateEditor.configureSection")}
                        title={t("templateEditor.configure")}
                        onClick={() => setOpenIndex((current) => (current === index ? null : index))}
                        className={`cursor-pointer rounded p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)] ${
                          open ? "bg-[var(--as-muted)] text-[var(--as-fg)]" : ""
                        }`}
                      >
                        <Settings2 className="h-3.5 w-3.5" aria-hidden />
                      </button>
                      <button
                        className="cursor-pointer rounded p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)]"
                        aria-label={t("interviews.moveUp")}
                        onClick={() => moveBlock(index, index - 1)}
                      >
                        <ArrowUp className="h-3 w-3" aria-hidden />
                      </button>
                      <button
                        className="cursor-pointer rounded p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)]"
                        aria-label={t("interviews.moveDown")}
                        onClick={() => moveBlock(index, index + 1)}
                      >
                        <ArrowDown className="h-3 w-3" aria-hidden />
                      </button>
                      <button
                        className="cursor-pointer rounded p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)]"
                        aria-label={t("templateEditor.removeSection")}
                        onClick={() => setBlocks(content.blocks.filter((_, position) => position !== index))}
                      >
                        <Trash2 className="h-3 w-3 text-red-600" aria-hidden />
                      </button>
                    </div>

                    {open && (
                      <div className="cv-collapse mt-1.5" data-open="true">
                        <div className="space-y-2.5 border-t border-[var(--as-border)] pt-2 text-xs">
                          {block.kind !== "header" && block.kind !== "spacer" && (
                            <ContainerEditor
                              box={box}
                              fallbackBackground={content.design.background_color}
                              fallbackBorder={content.design.border_color}
                              onChange={(patch) => setBlockProps(index, patch)}
                              testId={`container-${index}`}
                            />
                          )}
                          {content.design.layout === "sidebar" && block.kind !== "header" && (
                            <div data-testid={`area-${index}`}>
                              <SegmentedRow
                                label={t("templateEditor.column")}
                                value={block.area ?? block.column ?? "main"}
                                onChange={(area) =>
                                  setBlocks(
                                    content.blocks.map((row, position) =>
                                      position === index
                                        ? { ...row, area: area as "main" | "sidebar", column: area as "main" | "sidebar" }
                                        : row
                                    )
                                  )
                                }
                                options={[
                                  { value: "main", label: t("templateEditor.areaMain") },
                                  { value: "sidebar", label: t("templateEditor.areaSidebar") },
                                ]}
                              />
                            </div>
                          )}
                          {block.kind === "items" && (
                            <div className="space-y-2">
                              <SelectField label={t("templateEditor.dataSource")} value={String(bp.source_key ?? "experience")} onChange={(source_key) => setBlockProps(index, { source_key })} options={ITEM_SOURCES.map((o) => ({ value: o.value, label: t(o.labelKey, { defaultValue: o.label }) }))} />
                              {String(bp.source_key ?? "experience") === "experience" && (
                                <ChipTogglesRow
                                  label={t("templateEditor.kinds", { defaultValue: "Include kinds" })}
                                  values={Array.isArray(bp.kinds) ? (bp.kinds as string[]) : []}
                                  options={[
                                    { value: "job", label: "Jobs" },
                                    { value: "internship", label: "Internships" },
                                    { value: "freelance", label: "Freelance" },
                                  ]}
                                  onChange={(kinds) => setBlockProps(index, { kinds })}
                                />
                              )}
                              {String(bp.source_key) === "certifications" && (
                                <ToggleRow label={t("templateEditor.excludeProficiency", { defaultValue: "Hide proficiency certificates" })} checked={bp.exclude_proficiency === true} onChange={(exclude_proficiency) => setBlockProps(index, { exclude_proficiency })} />
                              )}
                              <SelectField label={t("templateEditor.styleLabel")} value={String(bp.style ?? "list")} onChange={(style) => setBlockProps(index, { style })} options={ITEM_STYLES.map((o) => ({ value: o.value, label: t(o.labelKey, { defaultValue: o.label }) }))} />
                              <SelectField label={t("templateEditor.datesLabel")} value={String(bp.date_format ?? "mon_yyyy")} onChange={(date_format) => setBlockProps(index, { date_format })} options={DATE_FORMATS} testId={`date-format-${index}`} />
                              <ToggleRow label={t("templateEditor.showOrg")} checked={bp.show_org !== false} onChange={(show_org) => setBlockProps(index, { show_org })} />
                              <ToggleRow label={t("templateEditor.showDescription")} checked={bp.show_description !== false} onChange={(show_description) => setBlockProps(index, { show_description })} />
                              <ToggleRow label={t("templateEditor.showSkills")} checked={bp.show_skills !== false} onChange={(show_skills) => setBlockProps(index, { show_skills })} />
                              <ToggleRow label={t("templateEditor.showAchievements")} checked={bp.show_achievements !== false} onChange={(show_achievements) => setBlockProps(index, { show_achievements })} />
                            </div>
                          )}
                          {block.kind === "languages" && (
                            <div className="space-y-2">
                              <ToggleRow label={t("templateEditor.showCefr", { defaultValue: "Show CEFR band" })} checked={bp.show_cefr === true} onChange={(show_cefr) => setBlockProps(index, { show_cefr })} />
                              <ToggleRow label={t("templateEditor.showProficiency", { defaultValue: "Latest proficiency certificate" })} checked={bp.show_proficiency === true} onChange={(show_proficiency) => setBlockProps(index, { show_proficiency })} />
                            </div>
                          )}
                          {block.kind === "header" && (
                            <div className="space-y-2">
                              <ToggleRow label={t("templateEditor.showLinks", { defaultValue: "Show contact links" })} checked={bp.show_links === true} onChange={(show_links) => setBlockProps(index, { show_links })} />
                              <ToggleRow label={t("templateEditor.showLocation", { defaultValue: "Show location" })} checked={bp.show_location === true} onChange={(show_location) => setBlockProps(index, { show_location })} />
                            </div>
                          )}
                          {block.kind === "skills" && (
                            <div className="space-y-2">
                              <SelectField label="Display" value={String(bp.display ?? "chips")} onChange={(display) => setBlockProps(index, { display })} options={[
                                { value: "chips", label: "Chips" },
                                { value: "list", label: "List" },
                                { value: "grouped", label: "Grouped" },
                                { value: "bars", label: "Bars" },
                              ]} testId={`skills-display-${index}`} />
                              <ToggleRow label={t("templateEditor.showLevels")} checked={bp.show_levels !== false} onChange={(show_levels) => setBlockProps(index, { show_levels })} />
                              <StepperRow label={t("templateEditor.maxItems")} value={Number(bp.max_items ?? 18)} min={1} max={40} onChange={(max_items) => setBlockProps(index, { max_items })} />
                            </div>
                          )}
                          {block.kind === "synth_items" && (
                            <div className="space-y-2">
                              <ToggleRow
                                label={t("cvSynth.block.sourceChips", {
                                  defaultValue: "Show source chips",
                                })}
                                checked={bp.show_source_chips !== false}
                                onChange={(show_source_chips) =>
                                  setBlockProps(index, { show_source_chips })
                                }
                              />
                              <StepperRow
                                label={t("templateEditor.maxItems")}
                                value={Number(bp.max_items ?? 6)}
                                min={1}
                                max={20}
                                onChange={(max_items) => setBlockProps(index, { max_items })}
                              />
                            </div>
                          )}
                          {block.kind === "custom_text" && (
                            <CustomTextEditor
                              value={String(bp.text ?? "")}
                              onChange={(text) => setBlockProps(index, { text })}
                            />
                          )}
                        </div>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </Card>

          <Card className="space-y-2 p-3">
            <h2
              className="text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]"
              title={t("templateEditor.aiInstructionsTitle")}
            >
              {t("templateEditor.aiInstructions")}
            </h2>
            <textarea
              placeholder={t("templateEditor.handlingPlaceholder")}
              value={content.prompts.field_handling}
              onChange={(event) =>
                setContent((current) => ({
                  ...current,
                  prompts: { ...current.prompts, field_handling: event.target.value },
                }))
              }
              className="h-20 w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-xs outline-none transition-colors focus:border-[var(--as-accent)]"
              data-testid="template-handling"
            />
            <textarea
              placeholder={t("templateEditor.summaryPromptPlaceholder")}
              value={content.prompts.field_prompts.summary ?? ""}
              onChange={(event) =>
                setContent((current) => ({
                  ...current,
                  prompts: {
                    ...current.prompts,
                    field_prompts: { ...current.prompts.field_prompts, summary: event.target.value },
                  },
                }))
              }
              className="h-16 w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-xs outline-none transition-colors focus:border-[var(--as-accent)]"
              data-testid="template-summary-prompt"
            />
          </Card>
        </div>

        <div className="min-h-0 lg:overflow-hidden" data-testid="template-editor-canvas">
          <Card className="flex min-h-0 flex-col p-3 lg:h-full">
            <p className="mb-2 shrink-0 px-1 text-xs text-[var(--as-muted-fg)]">
              {t("templateEditor.livePreview")}
            </p>
            <div className="relative min-h-0 flex-1">
              <iframe
                title={t("templateEditor.previewTitle")}
                srcDoc={html}
                sandbox=""
                className="absolute inset-0 h-full w-full rounded border border-[var(--as-border)] bg-white"
                data-testid="template-preview-frame"
              />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
