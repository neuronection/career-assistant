import { useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  Columns2,
  Copy,
  Eye,
  EyeOff,
  GripVertical,
  MoreHorizontal,
  Trash2,
} from "lucide-react";
import {
  Menu,
  MenuContent,
  MenuItem,
  MenuSeparator,
  MenuTrigger,
} from "@neuronection/assistant-ui";
import type { CvBlock, CvAreaId } from "@/types/cv";
import {
  ACHIEVEMENT_KIND_OPTIONS,
  blockHasTitle,
  blockIconOf,
  blockLabelOf,
  DATE_FORMAT_OPTIONS,
  EXPERIENCE_KIND_OPTIONS,
  ITEM_SOURCE_OPTIONS,
  SKILLS_DISPLAY_OPTIONS,
} from "@/components/cv/blockTypes";
import { areaOf, areasForDesign, type CvArea } from "@/components/cv/areas";
import {
  ChipTogglesRow,
  SegmentedRow,
  StepperRow,
  ToggleRow,
} from "@/components/cv/formPrimitives";
import { CustomTextEditor, CustomTextToggle } from "@/components/cv/CustomTextEditor";
import { ContainerEditor } from "@/components/cv/ContainerEditor";
import { BlockTypePicker } from "@/components/cv/BlockTypePicker";
import { ItemsOrderEditor } from "@/components/cv/ItemsOrderEditor";

const DRAG_GHOST_CLASS =
  "pointer-events-none fixed -left-[9999px] -top-[9999px] z-[-1] rounded-lg border-2 border-[var(--as-accent)] bg-[var(--as-surface-raised)] p-2 shadow-xl";

function makeDragGhost(card: HTMLElement, maxWidth: number): HTMLElement {
  const ghost = card.cloneNode(true) as HTMLElement;
  ghost.querySelectorAll("button, input, .cv-collapse, [data-no-drag-ghost]").forEach((node) => node.remove());
  ghost.className = DRAG_GHOST_CLASS;
  ghost.style.width = `${Math.min(card.offsetWidth || maxWidth, maxWidth)}px`;
  return ghost;
}

function asNumber(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function isOn(value: unknown): boolean {
  return value === true;
}

function optionLabel(
  options: { value: string; label: string }[],
  value: unknown,
  fallback: string
): string {
  const match = options.find((option) => option.value === String(value));
  return match ? match.label : fallback;
}

export function summaryFor(block: CvBlock): string | null {
  const props = (block.props ?? {}) as Record<string, unknown>;
  switch (block.kind) {
    case "items": {
      const parts = [
        optionLabel(ITEM_SOURCE_OPTIONS, props.source_key ?? "experience", "Items"),
        String(props.style ?? "list") === "timeline" ? "Timeline" : "List",
        optionLabel(DATE_FORMAT_OPTIONS, props.date_format ?? "mon_yyyy", "Jan 2025"),
        `max ${asNumber(props.max_items, 10)}`,
      ];
      return parts.join(" · ");
    }
    case "skills": {
      const parts = [
        optionLabel(SKILLS_DISPLAY_OPTIONS, props.display ?? "chips", "Chips"),
        `max ${asNumber(props.max_items, 18)}`,
      ];
      if (isOn(props.show_levels)) parts.push("levels");
      return parts.join(" · ");
    }
    case "languages": {
      const parts = [String(props.display ?? "chips") === "list" ? "Lines" : "Chips"];
      if (isOn(props.show_cefr)) parts.push("CEFR");
      if (isOn(props.show_proficiency)) parts.push("certificate");
      return parts.join(" · ");
    }
    case "summary":
      return `max ${asNumber(props.max_chars, 600)} characters`;
    case "synth_items": {
      const selected = Array.isArray(props.selected) ? props.selected.length : 0;
      const parts = [
        selected > 0 ? `${selected} variant${selected === 1 ? "" : "s"}` : "All variants",
        `max ${asNumber(props.max_items, 6)}`,
      ];
      if (isOn(props.show_source_chips)) parts.push("source chips");
      return parts.join(" · ");
    }
    case "achievements": {
      const kinds = Array.isArray(props.kinds)
        ? (props.kinds as string[])
        : ACHIEVEMENT_KIND_OPTIONS.map((option) => option.value);
      if (kinds.length === ACHIEVEMENT_KIND_OPTIONS.length) return "All types";
      return kinds
        .map((kind) => optionLabel(ACHIEVEMENT_KIND_OPTIONS, kind, kind))
        .join(" · ");
    }
    case "interests":
      return `max ${asNumber(props.max_items, 6)}`;
    case "spacer":
      return `${asNumber(props.height_mm, 4)} mm`;
    case "custom_text": {
      const text = String(props.text ?? "")
        .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
        .replace(/[*_`>#]/g, "")
        .trim();
      if (!text) return null;
      return text.split("\n")[0];
    }
    case "header": {
      const parts: string[] = [];
      if (isOn(props.show_links)) parts.push("Contact links");
      if (isOn(props.show_location)) parts.push("Location");
      return parts.length > 0 ? parts.join(" · ") : null;
    }
    default:
      return null;
  }
}

function FieldGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
        {label}
      </p>
      {children}
    </div>
  );
}

function configFor(
  block: CvBlock,
  onUpdate: (patch: Record<string, unknown>) => void,
  skillOptions: { id: string; label: string }[] = [],
  itemOptions: { id: string; label: string }[] = [],
  synthOptions: { id: string; label: string; stale?: boolean }[] = []
): ReactNode {
  const props = block.props ?? {};
  switch (block.kind) {
    case "summary":
      return (
        <FieldGroup label="Content">
          <StepperRow
            label="Max characters"
            value={asNumber(props.max_chars, 600)}
            min={200}
            max={1200}
            step={50}
            onChange={(max_chars) => onUpdate({ max_chars })}
          />
        </FieldGroup>
      );
    case "items":
      return (
        <>
          <FieldGroup label="Content">
            <SegmentedRow
              label="Data source"
              value={String(props.source_key ?? "experience")}
              options={ITEM_SOURCE_OPTIONS}
              onChange={(source_key) => onUpdate({ source_key })}
            />
            {String(props.source_key) === "experience" && (
              <ChipTogglesRow
                label="Include kinds"
                values={Array.isArray(props.kinds) ? (props.kinds as string[]) : []}
                options={EXPERIENCE_KIND_OPTIONS}
                onChange={(kinds) => onUpdate({ kinds })}
              />
            )}
            {itemOptions.length > 0 && (
              <ItemsOrderEditor
                options={itemOptions}
                order={Array.isArray(props.order) ? (props.order as string[]) : []}
                onChange={(order) => onUpdate({ order })}
              />
            )}
          </FieldGroup>
          <FieldGroup label="Display">
            <SegmentedRow
              label="Style"
              value={String(props.style ?? "list")}
              options={[
                { value: "list", label: "List" },
                { value: "timeline", label: "Timeline" },
              ]}
              onChange={(style) => onUpdate({ style })}
            />
            <SegmentedRow
              label="Dates"
              value={String(props.date_format ?? "mon_yyyy")}
              options={DATE_FORMAT_OPTIONS}
              onChange={(date_format) => onUpdate({ date_format })}
            />
            <StepperRow
              label="Max items"
              value={asNumber(props.max_items, 10)}
              min={1}
              max={30}
              onChange={(max_items) => onUpdate({ max_items })}
            />
            <ToggleRow
              label="Show organization"
              checked={props.show_org !== false}
              onChange={(show_org) => onUpdate({ show_org })}
            />
            <ToggleRow
              label="Show description"
              checked={props.show_description !== false}
              onChange={(show_description) => onUpdate({ show_description })}
            />
            <ToggleRow
              label="Show skills"
              checked={props.show_skills !== false}
              onChange={(show_skills) => onUpdate({ show_skills })}
            />
            <ToggleRow
              label="Show achievements"
              checked={props.show_achievements !== false}
              onChange={(show_achievements) => onUpdate({ show_achievements })}
            />
            <ToggleRow
              label="Show links (repo, demo…)"
              checked={props.show_links === true}
              onChange={(show_links) => onUpdate({ show_links })}
            />
            {String(props.source_key) === "certifications" && (
              <ToggleRow
                label="Hide proficiency certificates"
                checked={props.exclude_proficiency === true}
                onChange={(exclude_proficiency) => onUpdate({ exclude_proficiency })}
              />
            )}
          </FieldGroup>
        </>
      );
    case "synth_items":
      return (
        <>
          {synthOptions.length > 0 && (
            <FieldGroup label="Content">
              <ChipTogglesRow
                label="Limit to variants"
                values={Array.isArray(props.selected) ? (props.selected as string[]) : []}
                options={synthOptions.map((entry) => ({
                  value: entry.id,
                  label: entry.stale ? `${entry.label} (changed)` : entry.label,
                }))}
                onChange={(selected) => onUpdate({ selected })}
              />
            </FieldGroup>
          )}
          <FieldGroup label="Display">
            <ToggleRow
              label="Show source chips"
              checked={props.show_source_chips !== false}
              onChange={(show_source_chips) => onUpdate({ show_source_chips })}
            />
            <StepperRow
              label="Max items"
              value={asNumber(props.max_items, 6)}
              min={1}
              max={20}
              onChange={(max_items) => onUpdate({ max_items })}
            />
          </FieldGroup>
        </>
      );
    case "skills":
      return (
        <FieldGroup label="Display">
          <SegmentedRow
            label="Display"
            value={String(props.display ?? "chips")}
            options={SKILLS_DISPLAY_OPTIONS}
            onChange={(display) => onUpdate({ display })}
          />
          <ToggleRow
            label="Show levels"
            checked={props.show_levels === true}
            onChange={(show_levels) => onUpdate({ show_levels })}
          />
          <StepperRow
            label="Max items"
            value={asNumber(props.max_items, 18)}
            min={1}
            max={40}
            onChange={(max_items) => onUpdate({ max_items })}
          />
          {skillOptions.length > 0 && (
            <ChipTogglesRow
              label="Limit to skills"
              values={Array.isArray(props.selected) ? (props.selected as string[]) : []}
              options={skillOptions.map((skill) => ({ value: skill.id, label: skill.label }))}
              onChange={(selected) => onUpdate({ selected })}
            />
          )}
        </FieldGroup>
      );
    case "languages":
      return (
        <FieldGroup label="Display">
          <SegmentedRow
            label="Format"
            value={String(props.display ?? "chips")}
            options={[
              { value: "chips", label: "Chips" },
              { value: "list", label: "Lines" },
            ]}
            onChange={(display) => onUpdate({ display })}
          />
          <ToggleRow
            label="Show CEFR band"
            checked={props.show_cefr === true}
            onChange={(show_cefr) => onUpdate({ show_cefr })}
          />
          <ToggleRow
            label="Latest proficiency certificate"
            checked={props.show_proficiency === true}
            onChange={(show_proficiency) => onUpdate({ show_proficiency })}
          />
        </FieldGroup>
      );
    case "achievements": {
      const kinds = Array.isArray(props.kinds)
        ? (props.kinds as string[])
        : ACHIEVEMENT_KIND_OPTIONS.map((option) => option.value);
      return (
        <FieldGroup label="Types">
          <ChipTogglesRow
            label="Types"
            values={kinds}
            options={ACHIEVEMENT_KIND_OPTIONS}
            onChange={(kinds) => onUpdate({ kinds })}
          />
        </FieldGroup>
      );
    }
    case "interests":
      return (
        <FieldGroup label="Display">
          <StepperRow
            label="Max items"
            value={asNumber(props.max_items, 6)}
            min={1}
            max={20}
            onChange={(max_items) => onUpdate({ max_items })}
          />
        </FieldGroup>
      );
    case "spacer":
      return (
        <FieldGroup label="Size">
          <StepperRow
            label="Height"
            value={asNumber(props.height_mm, 4)}
            min={2}
            max={20}
            onChange={(height_mm) => onUpdate({ height_mm })}
            suffix="mm"
          />
        </FieldGroup>
      );
    case "header":
      return (
        <FieldGroup label="Display">
          <ToggleRow
            label="Show contact links"
            checked={props.show_links === true}
            onChange={(show_links) => onUpdate({ show_links })}
          />
          <ToggleRow
            label="Show location"
            checked={props.show_location === true}
            onChange={(show_location) => onUpdate({ show_location })}
          />
        </FieldGroup>
      );
    default:
      return (
        <p className="text-xs text-[var(--as-muted-fg)]">
          Nothing to configure — content comes from your profile.
        </p>
      );
  }
}

export interface SectionsPanelProps {
  blocks: CvBlock[];
  areas?: CvArea[];
  skillOptions?: { id: string; label: string }[];
  itemOptions?: Record<string, { id: string; label: string }[]>;
  synthOptions?: { id: string; label: string; stale?: boolean }[];
  onAddBlock: (kind: string, area?: CvAreaId) => void;
  onMoveBlock: (index: number, delta: number) => void;
  onAssignArea?: (index: number, area: CvAreaId) => void;
  onDuplicateBlock: (index: number) => void;
  onRemoveBlock: (index: number) => void;
  onUpdateBlockProps: (index: number, patch: Record<string, unknown>) => void;
  onSetBlockHidden: (index: number, hidden: boolean) => void;
  dragIndexRef: { current: number | null };
  onDragReorder: (target: number) => void;
}

const actionButton =
  "cursor-pointer rounded p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)]";

function SectionCard({
  block,
  index,
  first,
  last,
  dragging,
  dropTarget,
  open,
  onToggle,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
  onMoveBlock,
  onDuplicateBlock,
  onRemoveBlock,
  onUpdateBlockProps,
  onSetBlockHidden,
  skillOptions = [],
  itemOptions = [],
  synthOptions = [],
}: {
  block: CvBlock;
  index: number;
  first: boolean;
  last: boolean;
  dragging: boolean;
  dropTarget: boolean;
  open: boolean;
  onToggle: () => void;
  onDragStart: (event: React.DragEvent<HTMLElement>) => void;
  onDragOver: (event: React.DragEvent<HTMLElement>) => void;
  onDrop: (event: React.DragEvent<HTMLElement>) => void;
  onDragEnd: () => void;
  onMoveBlock: (index: number, delta: number) => void;
  onDuplicateBlock: (index: number) => void;
  onRemoveBlock: (index: number) => void;
  onUpdateBlockProps: (index: number, patch: Record<string, unknown>) => void;
  onSetBlockHidden: (index: number, hidden: boolean) => void;
  skillOptions?: { id: string; label: string }[];
  itemOptions?: { id: string; label: string }[];
  synthOptions?: { id: string; label: string; stale?: boolean }[];
}) {
  const { t } = useTranslation();
  const Icon = blockIconOf(block.kind);
  const isCustomText = block.kind === "custom_text";
  const hasConfig = !isCustomText;
  const hidden = block.hidden === true;
  const titled = blockHasTitle(block.kind) || "title" in (block.props ?? {});
  const labelKey = blockLabelOf(block.kind);
  const fallbackTitle = String(block.props?.title ?? t(labelKey, { defaultValue: labelKey }));

  let summary: string | null = null;
  if (hidden) {
    summary = "Hidden";
  } else {
    summary = summaryFor(block);
  }

  return (
    <li
      draggable
      data-group-card
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragOver={onDragOver}
      onDrop={onDrop}
      className={`group rounded-xl border bg-[var(--as-surface)] transition-colors ${
        dropTarget ? "cv-drop-slot" : ""
      } ${dragging ? "opacity-40" : ""} ${
        hidden ? "border-dashed border-[var(--as-border)] opacity-60" : "border-[var(--as-border)]"
      }`}
      data-testid={`section-card-${index}`}
    >
      <div className="flex items-center gap-0.5 px-1 py-1">
        <span
          draggable
          role="button"
          tabIndex={0}
          onKeyDown={(event) => {
            if (event.key === "ArrowUp") {
              event.preventDefault();
              onMoveBlock(index, -1);
            }
            if (event.key === "ArrowDown") {
              event.preventDefault();
              onMoveBlock(index, 1);
            }
          }}
          className={`flex shrink-0 cursor-grab items-center rounded px-0.5 py-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)] focus-visible:outline focus-visible:outline-[var(--as-accent)] ${
            dragging ? "cursor-grabbing" : ""
          }`}
          aria-label="Drag to reorder — use up and down arrow keys"
          title="Drag, or focus and use ↑/↓"
          data-testid={`section-handle-${index}`}
        >
          <GripVertical className="h-3.5 w-3.5" aria-hidden />
        </span>
        <span
          aria-hidden
          className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-[color-mix(in_srgb,var(--as-accent)_12%,transparent)]"
        >
          <Icon className="h-3 w-3 text-[var(--as-accent)]" />
        </span>
        {titled ? (
          <input
            aria-label="Section title"
            className="min-w-0 flex-1 rounded border border-transparent bg-transparent px-0.5 py-0.5 text-sm font-medium outline-none transition-colors placeholder:text-[var(--as-muted-fg)] hover:border-[var(--as-border)] focus:border-[var(--as-accent)]"
            value={String(block.props?.title ?? "")}
            placeholder={t(labelKey, { defaultValue: labelKey })}
            onChange={(event) => onUpdateBlockProps(index, { title: event.target.value })}
          />
        ) : (
          <span className="min-w-0 flex-1 truncate px-0.5 text-sm font-medium">
            {fallbackTitle}
          </span>
        )}
        <button
          type="button"
          aria-pressed={hidden}
          aria-label={hidden ? "Show section" : "Hide section"}
          title={hidden ? "Show section" : "Hide section"}
          data-testid={`section-hide-${index}`}
          onClick={() => onSetBlockHidden(index, !hidden)}
          className={`${actionButton} ${hidden ? "text-[var(--as-accent)]" : ""}`}
        >
          {hidden ? (
            <EyeOff className="h-3.5 w-3.5" aria-hidden />
          ) : (
            <Eye className="h-3.5 w-3.5" aria-hidden />
          )}
        </button>
        <Menu>
          <MenuTrigger asChild>
            <button
              type="button"
              aria-label="Section actions"
              title="More actions"
              data-testid={`section-menu-${index}`}
              className={actionButton}
            >
              <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
            </button>
          </MenuTrigger>
          <MenuContent align="end" className="w-40">
            <MenuItem
              data-testid={`section-move-up-${index}`}
              disabled={first}
              onSelect={() => onMoveBlock(index, -1)}
            >
              <ArrowUp className="mr-2 h-3.5 w-3.5" aria-hidden />
              Move up
            </MenuItem>
            <MenuItem
              data-testid={`section-move-down-${index}`}
              disabled={last}
              onSelect={() => onMoveBlock(index, 1)}
            >
              <ArrowDown className="mr-2 h-3.5 w-3.5" aria-hidden />
              Move down
            </MenuItem>
            <MenuSeparator />
            <MenuItem
              data-testid={`section-duplicate-${index}`}
              onSelect={() => onDuplicateBlock(index)}
            >
              <Copy className="mr-2 h-3.5 w-3.5" aria-hidden />
              Duplicate
            </MenuItem>
            <MenuSeparator />
            <MenuItem
              data-testid={`section-remove-${index}`}
              className="text-red-600 focus:bg-[var(--as-muted)] focus:text-red-700"
              onSelect={() => onRemoveBlock(index)}
            >
              <Trash2 className="mr-2 h-3.5 w-3.5" aria-hidden />
              Remove
            </MenuItem>
          </MenuContent>
        </Menu>
        {isCustomText ? (
          <CustomTextToggle open={open} onToggle={onToggle} />
        ) : (
          hasConfig && (
            <button
              type="button"
              aria-expanded={open}
              aria-label="Configure section"
              title={open ? "Collapse" : "Configure"}
              data-testid={`configure-section-${index}`}
              onClick={onToggle}
              className={`${actionButton} ${
                open ? "bg-[var(--as-muted)] text-[var(--as-fg)]" : ""
              }`}
            >
              <ChevronDown
                className={`h-3.5 w-3.5 transition-transform duration-200 ${
                  open ? "" : "-rotate-90"
                }`}
                aria-hidden
              />
            </button>
          )
        )}
      </div>

      {summary && (
        <p
          className="truncate px-2 pb-1.5 text-[11px] leading-tight text-[var(--as-muted-fg)]"
          data-testid={`section-summary-${index}`}
        >
          {summary}
        </p>
      )}

      {isCustomText && open && (
        <div className="cv-collapse mt-1.5" data-open="true">
          <div>
            <CustomTextEditor
              value={String(block.props?.text ?? "")}
              onChange={(text) => onUpdateBlockProps(index, { text })}
            />
          </div>
        </div>
      )}
      {hasConfig && open && (
        <div className="cv-collapse mt-1.5" data-open="true">
          <div className="space-y-3 border-t border-[var(--as-border)] px-2 pt-2 pb-2">
            {configFor(
              block,
              (patch) => onUpdateBlockProps(index, patch),
              skillOptions,
              itemOptions,
              synthOptions
            )}
            {block.kind !== "header" && block.kind !== "spacer" && (
              <FieldGroup label="Container">
                <ContainerEditor
                  box={(block.props?.container ?? {}) as Record<string, unknown>}
                  fallbackBackground="#ffffff"
                  fallbackBorder="#e5e7eb"
                  onChange={(patch) => onUpdateBlockProps(index, patch)}
                  testId={`container-${index}`}
                />
              </FieldGroup>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

export function SectionsPanel({
  blocks,
  areas = areasForDesign(null),
  skillOptions = [],
  itemOptions = {},
  synthOptions = [],
  onAddBlock,
  onMoveBlock,
  onAssignArea,
  onDuplicateBlock,
  onRemoveBlock,
  onUpdateBlockProps,
  onSetBlockHidden,
  dragIndexRef,
  onDragReorder,
}: SectionsPanelProps) {
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  const [dragOverArea, setDragOverArea] = useState<CvAreaId | null>(null);
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const [draggingIndex, setDraggingIndex] = useState<number | null>(null);
  const ghostRef = useRef<HTMLElement | null>(null);
  const grouped = areas.length > 1 && Boolean(onAssignArea);

  const handleDragStart = (event: React.DragEvent<HTMLElement>, index: number) => {
    dragIndexRef.current = index;
    setDraggingIndex(index);
    const transfer = event.dataTransfer;
    if (!transfer) return;
    transfer.effectAllowed = "move";
    transfer.setData("text/plain", "Section");
    try {
      const card = event.currentTarget;
      const ghost = makeDragGhost(card, 320);
      document.body.appendChild(ghost);
      ghostRef.current = ghost;
      const rect = card.getBoundingClientRect();
      transfer.setDragImage(
        ghost,
        Math.max(16, Math.min(event.clientX - rect.left, rect.width - 16)),
        Math.max(12, Math.min(event.clientY - rect.top, rect.height - 12))
      );
    } catch {
      ghostRef.current?.remove();
      ghostRef.current = null;
    }
  };

  const handleDragEnd = () => {
    setDraggingIndex(null);
    dragIndexRef.current = null;
    ghostRef.current?.remove();
    ghostRef.current = null;
    setDragOverIndex(null);
    setDragOverArea(null);
  };

  const dropOnCard = (index: number) => {
    const from = dragIndexRef.current;
    if (from === null) return;
    if (grouped && areaOf(blocks[from]) !== areaOf(blocks[index])) {
      onAssignArea?.(from, areaOf(blocks[index]));
    } else {
      onDragReorder(index);
    }
    handleDragEnd();
  };

  const card = (block: CvBlock, index: number) => (
    <SectionCard
      key={`${block.kind}-${index}`}
      block={block}
      index={index}
      first={index === 0}
      last={index === blocks.length - 1}
      dragging={draggingIndex === index}
      dropTarget={dragOverIndex === index}
      open={openIndex === index}
      onToggle={() => setOpenIndex((current) => (current === index ? null : index))}
      onDragStart={(event) => handleDragStart(event, index)}
      onDragOver={(event) => {
        event.preventDefault();
        setDragOverIndex(index);
      }}
      onDrop={(event) => {
        event.preventDefault();
        dropOnCard(index);
      }}
      onDragEnd={handleDragEnd}
      onMoveBlock={onMoveBlock}
      onDuplicateBlock={onDuplicateBlock}
      onRemoveBlock={onRemoveBlock}
      onUpdateBlockProps={onUpdateBlockProps}
      onSetBlockHidden={onSetBlockHidden}
      skillOptions={skillOptions}
      itemOptions={
        block.kind === "items" ? itemOptions[String(block.props?.source_key ?? "")] ?? [] : []
      }
      synthOptions={block.kind === "synth_items" ? synthOptions : []}
    />
  );

  if (grouped) {
    return (
      <div className="space-y-3" data-testid="sections-list">
        <BlockTypePicker onAdd={onAddBlock} areas={areas} />
        {areas.map((area) => {
          const indexes = blocks
            .map((block, index) => (areaOf(block) === area.id ? index : -1))
            .filter((index) => index !== -1);
          return (
            <section
              key={area.id}
              onDragOver={(event) => {
                event.preventDefault();
                setDragOverArea(area.id);
              }}
              onDragLeave={() => setDragOverArea((current) => (current === area.id ? null : current))}
              onDrop={(event) => {
                event.preventDefault();
                const from = dragIndexRef.current;
                if (from === null) return;
                if (areaOf(blocks[from]) !== area.id) onAssignArea?.(from, area.id);
                setDragOverArea(null);
                handleDragEnd();
              }}
              data-testid={`area-group-${area.id}`}
              className={`rounded-xl border transition-colors ${
                dragOverArea === area.id
                  ? "border-dashed border-[var(--as-accent)] bg-[color-mix(in_srgb,var(--as-accent)_6%,transparent)]"
                  : "border-[var(--as-border)] bg-[var(--as-surface)]"
              }`}
            >
              <div className="flex items-center gap-1.5 border-b border-[var(--as-border)] px-2 py-1.5">
                <Columns2 className="h-3.5 w-3.5 shrink-0 text-[var(--as-accent)]" aria-hidden />
                <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                  {area.label}
                </span>
                <span
                  className="rounded-full bg-[var(--as-muted)] px-1.5 text-[10px] font-medium tabular-nums text-[var(--as-muted-fg)]"
                  data-testid={`area-count-${area.id}`}
                >
                  {indexes.length}
                </span>
                <span className="flex-1" />
                <BlockTypePicker
                  onAdd={onAddBlock}
                  areas={areas}
                  presetArea={area.id}
                  testId={`add-section-${area.id}`}
                  iconOnly
                />
              </div>
              <div className="space-y-1.5 p-1.5">
                {indexes.length === 0 ? (
                  <p
                    className="rounded-lg border border-dashed border-[var(--as-border)] px-2 py-2.5 text-center text-[11px] text-[var(--as-muted-fg)]"
                    data-testid={`area-empty-${area.id}`}
                  >
                    Drop a section here
                  </p>
                ) : (
                  indexes.map((index) => card(blocks[index], index))
                )}
              </div>
            </section>
          );
        })}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <BlockTypePicker onAdd={onAddBlock} />
      <ul className="space-y-1.5" data-testid="sections-list">
        {blocks.map((block, index) => card(block, index))}
      </ul>
      {blocks.length === 0 && (
        <p className="text-xs text-[var(--as-muted-fg)]">
          No sections yet — add one above to start building.
        </p>
      )}
    </div>
  );
}
