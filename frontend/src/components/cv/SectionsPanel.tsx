import { useRef, useState, type ReactNode } from "react";
import {
  ArrowDown,
  ArrowUp,
  Copy,
  Settings2,
  Trash2,
} from "lucide-react";
import type { CvBlock } from "@/types/cv";
import {
  ACHIEVEMENT_KIND_OPTIONS,
  blockTypeOf,
  DATE_FORMAT_OPTIONS,
  ITEM_SOURCE_OPTIONS,
  SKILLS_DISPLAY_OPTIONS,
} from "@/components/cv/blockTypes";
import {
  ChipTogglesRow,
  SegmentedRow,
  StepperRow,
  ToggleRow,
} from "@/components/cv/formPrimitives";
import { CustomTextEditor, CustomTextToggle } from "@/components/cv/CustomTextEditor";
import { BlockTypePicker } from "@/components/cv/BlockTypePicker";

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
  onUpdate: (patch: Record<string, unknown>) => void
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
  onAddBlock: (kind: string) => void;
  onMoveBlock: (index: number, delta: number) => void;
  onDuplicateBlock: (index: number) => void;
  onRemoveBlock: (index: number) => void;
  onUpdateBlockProps: (index: number, patch: Record<string, unknown>) => void;
  dragIndexRef: { current: number | null };
  onDragReorder: (target: number) => void;
}

export function SectionsPanel({
  blocks,
  onAddBlock,
  onMoveBlock,
  onDuplicateBlock,
  onRemoveBlock,
  onUpdateBlockProps,
  dragIndexRef,
  onDragReorder,
}: SectionsPanelProps) {
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const [draggingIndex, setDraggingIndex] = useState<number | null>(null);
  const ghostRef = useRef<HTMLElement | null>(null);

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
  };

  return (
    <div className="space-y-2">
      <BlockTypePicker onAdd={onAddBlock} />
      <ul className="space-y-1.5" data-testid="sections-list">
        {blocks.map((block, index) => {
          const type = blockTypeOf(block.kind);
          const Icon = type?.icon;
          const isCustomText = block.kind === "custom_text";
          const hasConfig = !isCustomText;
          const open = openIndex === index;
          return (
            <li
              key={`${block.kind}-${index}`}
              draggable
              onDragStart={(event) => handleDragStart(event, index)}
              onDragEnd={handleDragEnd}
              onDragOver={(event) => {
                event.preventDefault();
                setDragOverIndex(index);
              }}
              onDragLeave={() => setDragOverIndex((current) => (current === index ? null : current))}
              onDrop={(event) => {
                event.preventDefault();
                if (dragIndexRef.current !== null) onDragReorder(index);
                handleDragEnd();
              }}
              className={`rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] p-2 transition-colors ${
                dragOverIndex === index ? "cv-drop-slot" : ""
              } ${draggingIndex === index ? "opacity-40" : ""}`}
              data-testid={`section-card-${index}`}
            >
              <div className="flex items-center gap-1">
                <span
                  draggable
                  className={`select-none px-0.5 text-[var(--as-muted-fg)] ${
                    draggingIndex === index ? "cursor-grabbing" : "cursor-grab"
                  }`}
                  title="Drag to reorder"
                  aria-label="Drag to reorder"
                >
                  ⠿
                </span>
                {Icon && (
                  <Icon className="h-3.5 w-3.5 shrink-0 text-[var(--as-accent)]" aria-hidden />
                )}
                {block.kind === "items" || block.kind === "custom_text" ? (
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
                  <CustomTextToggle
                    open={open}
                    onToggle={() => setOpenIndex((current) => (current === index ? null : index))}
                  />
                )}
                {hasConfig && (
                  <button
                    type="button"
                    aria-expanded={open}
                    aria-label="Configure section"
                    title="Configure"
                    data-testid={`configure-section-${index}`}
                    onClick={() => setOpenIndex((current) => (current === index ? null : index))}
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
                  className="cursor-pointer rounded p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)]"
                >
                  <Copy className="h-3.5 w-3.5" aria-hidden />
                </button>
                <button
                  className="rounded p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)]"
                  aria-label="Move up"
                  title="Move up"
                  onClick={() => onMoveBlock(index, -1)}
                >
                  <ArrowUp className="h-3 w-3" aria-hidden />
                </button>
                <button
                  className="rounded p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)]"
                  aria-label="Move down"
                  title="Move down"
                  onClick={() => onMoveBlock(index, 1)}
                >
                  <ArrowDown className="h-3 w-3" aria-hidden />
                </button>
                <button
                  className="rounded p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)]"
                  aria-label="Remove section"
                  title="Remove"
                  onClick={() => onRemoveBlock(index)}
                >
                  <Trash2 className="h-3 w-3 text-red-600" aria-hidden />
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
                    {configFor(block, (patch) => onUpdateBlockProps(index, patch))}
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {blocks.length === 0 && (
        <p className="text-xs text-[var(--as-muted-fg)]">
          No sections yet — add one above to start building.
        </p>
      )}
    </div>
  );
}
