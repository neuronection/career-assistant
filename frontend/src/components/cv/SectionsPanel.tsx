import { useRef, useState, type ReactNode } from "react";
import {
  ArrowDown,
  ArrowUp,
  Columns2,
  Copy,
  Settings2,
  Trash2,
} from "lucide-react";
import type { CvBlock, CvAreaId } from "@/types/cv";
import {
  ACHIEVEMENT_KIND_OPTIONS,
  blockTypeOf,
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
        <StepperRow
          label="Max characters"
          value={asNumber(props.max_chars, 600)}
          min={200}
          max={1200}
          step={50}
          onChange={(max_chars) => onUpdate({ max_chars })}
        />
      );
    case "items":
      return (
        <div className="space-y-2.5">
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
          {String(props.source_key) === "certifications" && (
            <ToggleRow
              label="Hide proficiency certificates"
              checked={props.exclude_proficiency === true}
              onChange={(exclude_proficiency) => onUpdate({ exclude_proficiency })}
            />
          )}
          {itemOptions.length > 0 && (
            <ItemsOrderEditor
              options={itemOptions}
              order={Array.isArray(props.order) ? (props.order as string[]) : []}
              onChange={(order) => onUpdate({ order })}
            />
          )}
        </div>
      );
    case "synth_items":
      return (
        <div className="space-y-2.5">
          {synthOptions.length > 0 && (
            <ChipTogglesRow
              label="Limit to variants"
              values={Array.isArray(props.selected) ? (props.selected as string[]) : []}
              options={synthOptions.map((entry) => ({
                value: entry.id,
                label: entry.stale ? `${entry.label} (changed)` : entry.label,
              }))}
              onChange={(selected) => onUpdate({ selected })}
            />
          )}
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
        </div>
      );
    case "skills":
      return (
        <div className="space-y-2.5">
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
        </div>
      );
    case "languages":
      return (
        <div className="space-y-2.5">
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
        </div>
      );
    case "achievements": {
      const kinds = Array.isArray(props.kinds)
        ? (props.kinds as string[])
        : ACHIEVEMENT_KIND_OPTIONS.map((option) => option.value);
      return (
        <ChipTogglesRow
          label="Types"
          values={kinds}
          options={ACHIEVEMENT_KIND_OPTIONS}
          onChange={(kinds) => onUpdate({ kinds })}
        />
      );
    }
    case "interests":
      return (
        <StepperRow
          label="Max items"
          value={asNumber(props.max_items, 6)}
          min={1}
          max={20}
          onChange={(max_items) => onUpdate({ max_items })}
        />
      );
    case "spacer":
      return (
        <StepperRow
          label="Height"
          value={asNumber(props.height_mm, 4)}
          min={2}
          max={20}
          onChange={(height_mm) => onUpdate({ height_mm })}
          suffix="mm"
        />
      );
    case "header":
      return (
        <div className="space-y-2.5">
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
        </div>
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
  dragIndexRef: { current: number | null };
  onDragReorder: (target: number) => void;
}

function SectionCard({
  block,
  index,
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
  skillOptions = [],
  itemOptions = [],
  synthOptions = [],
}: {
  block: CvBlock;
  index: number;
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
  skillOptions?: { id: string; label: string }[];
  itemOptions?: { id: string; label: string }[];
  synthOptions?: { id: string; label: string; stale?: boolean }[];
}) {
  const type = blockTypeOf(block.kind);
  const Icon = type?.icon;
  const isCustomText = block.kind === "custom_text";
  const hasConfig = !isCustomText;

  return (
    <li
      draggable
      data-group-card
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragOver={onDragOver}
      onDrop={onDrop}
      className={`group rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] p-2 transition-colors ${
        dropTarget ? "cv-drop-slot" : ""
      } ${dragging ? "opacity-40" : ""}`}
      data-testid={`section-card-${index}`}
    >
      <div className="flex items-center gap-1">
        <span
          draggable
          className={`select-none px-0.5 text-[var(--as-muted-fg)] ${
            dragging ? "cursor-grabbing" : "cursor-grab"
          }`}
          title="Drag to reorder"
          aria-label="Drag to reorder"
        >
          ⠿
        </span>
        {Icon && (
          <Icon className="h-3.5 w-3.5 shrink-0 text-[var(--as-accent)]" aria-hidden />
        )}
        {block.kind === "items" ||
        block.kind === "custom_text" ||
        block.kind === "synth_items" ? (
          <input
            aria-label="Section title"
            className="min-w-0 flex-1 rounded border border-transparent bg-transparent px-1 py-0.5 text-sm font-medium outline-none transition-colors hover:border-[var(--as-border)] focus:border-[var(--as-accent)]"
            value={String(block.props?.title ?? "")}
            onChange={(event) => onUpdateBlockProps(index, { title: event.target.value })}
          />
        ) : (
          <span className="min-w-0 flex-1 truncate px-1 text-sm font-medium">
            {String(block.props?.title ?? type?.label ?? block.kind)}
          </span>
        )}
        {isCustomText && (
          <CustomTextToggle open={open} onToggle={onToggle} />
        )}
        {/* hover-reveal secondary actions keep the title as wide as possible */}
        {hasConfig && (
          <button
            type="button"
            aria-expanded={open}
            aria-label="Configure section"
            title="Configure"
            data-testid={`configure-section-${index}`}
            onClick={onToggle}
            className={`cursor-pointer rounded p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)] ${
              open ? "bg-[var(--as-muted)] text-[var(--as-fg)]" : ""
            }`}
          >
            <Settings2 className="h-3.5 w-3.5" aria-hidden />
          </button>
        )}
        <button
          type="button"
          aria-label="Duplicate section"
          title="Duplicate"
          onClick={() => onDuplicateBlock(index)}
          className="cursor-pointer rounded p-1 text-[var(--as-muted-fg)] opacity-0 transition-opacity duration-150 hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)] focus-visible:opacity-100 group-hover:opacity-100 group-focus-within:opacity-100"
        >
          <Copy className="h-3.5 w-3.5" aria-hidden />
        </button>
        <button
          className="cursor-pointer rounded p-1 text-[var(--as-muted-fg)] opacity-0 transition-opacity duration-150 hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)] focus-visible:opacity-100 group-hover:opacity-100 group-focus-within:opacity-100"
          aria-label="Move up"
          title="Move up"
          onClick={() => onMoveBlock(index, -1)}
        >
          <ArrowUp className="h-3 w-3" aria-hidden />
        </button>
        <button
          className="cursor-pointer rounded p-1 text-[var(--as-muted-fg)] opacity-0 transition-opacity duration-150 hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)] focus-visible:opacity-100 group-hover:opacity-100 group-focus-within:opacity-100"
          aria-label="Move down"
          title="Move down"
          onClick={() => onMoveBlock(index, 1)}
        >
          <ArrowDown className="h-3 w-3" aria-hidden />
        </button>
        <button
          className="cursor-pointer rounded p-1 text-[var(--as-muted-fg)] opacity-0 transition-opacity duration-150 hover:bg-[var(--as-muted)] focus-visible:opacity-100 group-hover:opacity-100 group-focus-within:opacity-100"
          aria-label="Remove section"
          title="Remove"
          onClick={() => onRemoveBlock(index)}
        >
          <Trash2 className="h-3.5 w-3.5 text-red-600" aria-hidden />
        </button>
      </div>

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
          <div className="space-y-2 border-t border-[var(--as-border)] pt-2">
            {configFor(
              block,
              (patch) => onUpdateBlockProps(index, patch),
              skillOptions,
              itemOptions,
              synthOptions
            )}
            {block.kind !== "header" && block.kind !== "spacer" && (
              <ContainerEditor
                box={(block.props?.container ?? {}) as Record<string, unknown>}
                fallbackBackground="#ffffff"
                fallbackBorder="#e5e7eb"
                onChange={(patch) => onUpdateBlockProps(index, patch)}
                testId={`container-${index}`}
              />
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
    const type = blockTypeOf(blocks[index]?.kind ?? "");
    transfer.setData("text/plain", type?.label ?? "Section");
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
      skillOptions={skillOptions}
      itemOptions={
        block.kind === "items" ? itemOptions[String(block.props?.source_key ?? "")] ?? [] : []
      }
      synthOptions={block.kind === "synth_items" ? synthOptions : []}
    />
  );

  if (grouped) {
    return (
      <div className="space-y-2" data-testid="sections-list">
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
              className={`rounded-lg border border-dashed p-1.5 transition-colors ${
                dragOverArea === area.id
                  ? "border-[var(--as-accent)] bg-[color-mix(in_srgb,var(--as-accent)_6%,transparent)]"
                  : "border-[var(--as-border)]"
              }`}
            >
              <div className="flex items-center justify-between px-1 pb-1 pt-0.5">
                <span className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                  <Columns2 className="h-3 w-3" aria-hidden />
                  {area.label}
                </span>
                <span
                  className="rounded-full bg-[var(--as-muted)] px-1.5 text-[10px] font-medium tabular-nums text-[var(--as-muted-fg)]"
                  data-testid={`area-count-${area.id}`}
                >
                  {indexes.length}
                </span>
              </div>
              {indexes.length === 0 ? (
                <p
                  className="rounded-md border border-dashed border-[var(--as-border)] px-2 py-2 text-center text-[11px] text-[var(--as-muted-fg)]"
                  data-testid={`area-empty-${area.id}`}
                >
                  Drop a section here
                </p>
              ) : (
                <ul className="space-y-1.5">
                  {indexes.map((index) => card(blocks[index], index))}
                </ul>
              )}
              <div className="pt-1.5">
                <BlockTypePicker
                  onAdd={onAddBlock}
                  areas={areas}
                  presetArea={area.id}
                  testId={`add-section-${area.id}`}
                />
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
