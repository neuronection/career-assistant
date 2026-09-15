import { useMemo, useState } from "react";
import { Pencil, Plus, ChevronDown, Search, Star, Wand2 } from "lucide-react";
import { CheckIndicator } from "@neuronection/assistant-ui";
import type { CvContextSourceOut, CvSynthItem } from "@/types/cv";

interface ContextPanelProps {
  sources: CvContextSourceOut[];
  selected: Set<string>;
  onToggle: (sourceKey: string, itemId: string) => void;
  onToggleGroup: (source: CvContextSourceOut, includeAll: boolean) => void;
  onBullet: (sourceKey: string, itemId: string, label: string) => void;
  /** Plan 72: the caller's draft + active variants, nested under their items (archived excluded upstream). */
  variants?: CvSynthItem[];
  onAddVariant?: (sourceKey: string) => void;
  /** Plan 72 follow-up: per-item variant pinning (`context.synth_pins`). */
  synthPins?: Record<string, string>;
  onPinVariant?: (sourceKey: string, itemId: string, synthId: string | null) => void;
  onEditVariant?: (variant: CvSynthItem) => void;
  onActivateVariant?: (variant: CvSynthItem) => void;
}

function refKeyOf(sourceKey: string, itemId: string): string {
  return `${sourceKey}:${itemId}`;
}

function variantText(variant: CvSynthItem): string {
  const payload = variant.payload || {};
  return payload.description || payload.summary || "";
}

function PinStar({
  pinned,
  variant,
  sourceKey,
  itemId,
  onPin,
}: {
  pinned: boolean;
  variant: CvSynthItem;
  sourceKey: string;
  itemId: string;
  onPin?: (sourceKey: string, itemId: string, synthId: string | null) => void;
}) {
  const active = variant.status === "active";
  return (
    <button
      type="button"
      aria-pressed={pinned}
      disabled={!active}
      aria-label={
        pinned
          ? `Unpin variant ${variant.variant_key} for this item`
          : `Make variant ${variant.variant_key} the default for this item`
      }
      title={
        !active
          ? "Activate the draft before starring it"
          : pinned
            ? "Unpin — the best matching variant applies again"
            : "Make default for this item"
      }
      data-testid={`context-pin-star-${variant.id}`}
      onClick={() => onPin?.(sourceKey, itemId, pinned ? null : variant.id)}
      className={`shrink-0 cursor-pointer rounded p-0.5 transition-colors hover:bg-[var(--as-muted)] ${active ? "" : "opacity-40"}`}
    >
      <Star
        className={`h-3.5 w-3.5 ${pinned ? "fill-[var(--as-accent)] text-[var(--as-accent)]" : "text-[var(--as-muted-fg)]"}`}
        aria-hidden
      />
    </button>
  );
}

function AmberBadge({ children, testId }: { children: string; testId: string }) {
  return (
    <span
      className="shrink-0 rounded-full bg-amber-100 px-1.5 text-[10px] font-medium text-amber-800"
      data-testid={testId}
    >
      {children}
    </span>
  );
}

function VariantsForItem({
  sourceKey,
  itemId,
  variants,
  pinnedId,
  onPinVariant,
  onEditVariant,
  onActivateVariant,
}: {
  sourceKey: string;
  itemId: string;
  variants: CvSynthItem[];
  pinnedId: string | undefined;
  onPinVariant?: (sourceKey: string, itemId: string, synthId: string | null) => void;
  onEditVariant?: (variant: CvSynthItem) => void;
  onActivateVariant?: (variant: CvSynthItem) => void;
}) {
  const rows = variants.filter((variant) =>
    variant.source_refs.some(
      (ref) => ref.source_key === sourceKey && ref.item_id === itemId,
    ),
  );
  const pinned = pinnedId ? variants.find((v) => v.id === pinnedId) : undefined;
  const pinInactive =
    pinnedId !== undefined &&
    (pinned === undefined ||
      pinned.status !== "active" ||
      !rows.some((variant) => variant.id === pinnedId));
  if (rows.length === 0 && !pinInactive) return null;
  return (
    <div className="ml-5 space-y-0.5">
      {pinInactive && (
        <p
          className="flex items-center gap-1.5 px-0.5 py-1 text-xs text-[var(--as-muted-fg)]"
          data-testid="context-pin-inactive"
        >
          <AmberBadge testId="context-pin-inactive-badge">pin inactive</AmberBadge>
          The starred variant isn't active for this item — activate it or
          re-star.
        </p>
      )}
      {rows.length > 0 && (
        <ul className="space-y-0.5 border-l border-dashed border-[var(--as-border)] pl-2">
      {rows.map((variant) => (
        <li
          key={`${sourceKey}-${itemId}-${variant.id}`}
          className="flex items-center gap-1.5 rounded px-0.5 py-1 text-xs hover:bg-[var(--as-muted)]"
          data-testid={`context-variant-${variant.id}`}
        >
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1">
              <span
                className="shrink-0 rounded-full bg-[color-mix(in_srgb,var(--as-accent)_12%,transparent)] px-1.5 text-[10px] font-medium text-[var(--as-accent)]"
                data-testid="context-variant-badge"
              >
                variant
              </span>
              {variant.status === "draft" && (
                <span
                  className="shrink-0 rounded-full bg-amber-100 px-1.5 text-[10px] font-medium text-amber-800"
                  data-testid="context-variant-draft"
                >
                  draft
                </span>
              )}
              <span className="truncate text-[var(--as-muted-fg)]">
                {variant.variant_key}
              </span>
              {variant.stale && <AmberBadge testId="context-variant-stale">stale</AmberBadge>}
              {variant.orphaned && <AmberBadge testId="context-variant-orphan">gone</AmberBadge>}
            </span>
            {variantText(variant) && (
              <span className="line-clamp-2 text-[var(--as-muted-fg)]">
                {variantText(variant)}
              </span>
            )}
          </span>
          <PinStar
            pinned={pinnedId === variant.id}
            variant={variant}
            sourceKey={sourceKey}
            itemId={itemId}
            onPin={onPinVariant}
          />
          {variant.status === "draft" && onActivateVariant && (
            <button
              type="button"
              className="shrink-0 cursor-pointer rounded-full border border-[var(--as-border)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--as-accent)] transition-colors hover:bg-[var(--as-muted)] disabled:opacity-40"
              aria-label={`Activate variant ${variant.variant_key}`}
              title="Use it"
              data-testid={`context-variant-activate-${variant.id}`}
              onClick={() => onActivateVariant(variant)}
            >
              Activate
            </button>
          )}
          {onEditVariant && (
            <button
              type="button"
              className="shrink-0 cursor-pointer rounded p-0.5 text-[var(--as-accent)] transition-colors hover:bg-[var(--as-muted)]"
              aria-label={`Edit variant ${variant.variant_key}`}
              title="Edit text"
              data-testid={`context-variant-edit-${variant.id}`}
              onClick={() => onEditVariant(variant)}
            >
              <Pencil className="h-3 w-3" />
            </button>
          )}
        </li>
      ))}
        </ul>
      )}
    </div>
  );
}

function GroupRow({
  source,
  selected,
  onToggle,
  onToggleGroup,
  onBullet,
  variants,
  onAddVariant,
  synthPins,
  onPinVariant,
  onEditVariant,
  onActivateVariant,
  open,
  onOpenChange,
}: {
  source: CvContextSourceOut;
  selected: Set<string>;
  onToggle: (sourceKey: string, itemId: string) => void;
  onToggleGroup: (source: CvContextSourceOut, includeAll: boolean) => void;
  onBullet: (sourceKey: string, itemId: string, label: string) => void;
  variants: CvSynthItem[];
  onAddVariant?: (sourceKey: string) => void;
  synthPins: Record<string, string>;
  onPinVariant?: (sourceKey: string, itemId: string, synthId: string | null) => void;
  onEditVariant?: (variant: CvSynthItem) => void;
  onActivateVariant?: (variant: CvSynthItem) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const items = source.items ?? [];
  const includedCount = items.filter((item) => selected.has(refKeyOf(source.key, item.item_id))).length;
  const allIncluded = items.length > 0 && includedCount === items.length;
  const someIncluded = includedCount > 0 && !allIncluded;

  return (
    <div className="overflow-hidden rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)]">
      <div className="flex items-center gap-2 px-2 py-1.5">
        {items.length > 0 && (
          <CheckIndicator
            checked={allIncluded}
            mixed={someIncluded}
            label={`Include all ${source.label}`}
            onToggle={() => onToggleGroup(source, !allIncluded)}
          />
        )}
        <button
          type="button"
          className="flex flex-1 items-center gap-2 py-0.5 text-left"
          aria-expanded={open}
          onClick={() => onOpenChange(!open)}
          data-testid={`context-group-header-${source.key}`}
        >
          <span className="flex-1 truncate text-xs font-semibold uppercase tracking-wide text-[var(--as-fg)]">
            {source.label}
          </span>
          <span
            className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium tabular-nums ${
              allIncluded
                ? "bg-[color-mix(in_srgb,var(--as-accent)_14%,transparent)] text-[var(--as-accent)]"
                : "bg-[var(--as-muted)] text-[var(--as-muted-fg)]"
            }`}
            data-testid={`context-group-count-${source.key}`}
          >
            {includedCount}/{items.length}
          </span>
          <ChevronDown
            className={`h-3.5 w-3.5 text-[var(--as-muted-fg)] transition-transform duration-200 ${
              open ? "" : "-rotate-90"
            }`}
          />
        </button>
      </div>
      {items.length === 0 ? (
        <div className="border-t border-[var(--as-border)] px-2" data-testid={`context-group-body-${source.key}`}>
          <p className="py-1.5 text-xs text-[var(--as-muted-fg)]">Nothing recorded yet</p>
        </div>
      ) : (
        <div className="cv-collapse" data-open={open} data-testid={`context-group-body-${source.key}`}>
          <div className="border-t border-[var(--as-border)] px-2 pb-1.5 pt-0.5">
            {items.map((item) => {
              const key = refKeyOf(source.key, item.item_id);
              const writable =
                source.key === "experience" ||
                source.key === "projects" ||
                source.key === "volunteer";
              return (
                <div key={key}>
                  <label className="flex items-center gap-2 rounded px-0.5 py-1 text-sm hover:bg-[var(--as-muted)]">
                    <input
                      type="checkbox"
                      role="switch"
                      checked={selected.has(key)}
                      onChange={() => onToggle(source.key, item.item_id)}
                      data-testid={`context-toggle-${key}`}
                      className="as-switch shrink-0"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="line-clamp-2">{item.label}</span>
                      {item.detail && (
                        <span className="line-clamp-2 text-xs text-[var(--as-muted-fg)]">{item.detail}</span>
                      )}
                    </span>
                    {writable && (
                      <span className="flex shrink-0 items-center gap-0.5">
                        {onAddVariant && (
                          <button
                            type="button"
                            className="rounded p-1 text-[var(--as-accent)] hover:bg-[var(--as-muted)]"
                            aria-label={`Write a variant for ${item.label}`}
                            title="Add variant"
                            data-testid={`ai-add-variant-${item.item_id}`}
                            onClick={() => onAddVariant(source.key)}
                          >
                            <Plus className="h-3.5 w-3.5" />
                          </button>
                        )}
                        <button
                          type="button"
                          className="rounded p-1 text-[var(--as-accent)] hover:bg-[var(--as-muted)]"
                          aria-label={`Improve bullet for ${item.label}`}
                          title="Improve with AI"
                          data-testid={`ai-bullet-${item.item_id}`}
                          onClick={() => onBullet(source.key, item.item_id, item.label)}
                        >
                          <Wand2 className="h-3.5 w-3.5" />
                        </button>
                      </span>
                    )}
                  </label>
                  <VariantsForItem
                    sourceKey={source.key}
                    itemId={item.item_id}
                    variants={variants}
                    pinnedId={synthPins[key]}
                    onPinVariant={onPinVariant}
                    onEditVariant={onEditVariant}
                    onActivateVariant={onActivateVariant}
                  />
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export function ContextPanel({
  sources,
  selected,
  onToggle,
  onToggleGroup,
  onBullet,
  variants = [],
  onAddVariant,
  synthPins = {},
  onPinVariant,
  onEditVariant,
  onActivateVariant,
}: ContextPanelProps) {
  const [query, setQuery] = useState("");
  const [closedGroups, setClosedGroups] = useState<Set<string>>(new Set());

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return sources;
    return sources
      .map((source) => {
        const items = (source.items ?? []).filter(
          (item) =>
            item.label.toLowerCase().includes(needle) ||
            (item.detail ?? "").toLowerCase().includes(needle)
        );
        return { ...source, items, originalCount: (source.items ?? []).length };
      })
      .filter((source) => source.items.length > 0 || source.originalCount === 0);
  }, [sources, query]);

  const isEmpty = (source: CvContextSourceOut) => (source.items ?? []).length === 0;

  const { totalItems, includedItems } = useMemo(() => {
    let total = 0;
    let included = 0;
    for (const source of sources) {
      for (const item of source.items ?? []) {
        total += 1;
        if (selected.has(refKeyOf(source.key, item.item_id))) included += 1;
      }
    }
    return { totalItems: total, includedItems: included };
  }, [sources, selected]);

  return (
    <div className="flex min-h-0 flex-col" data-testid="context-panel">
      <p
        className="mb-1.5 shrink-0 px-0.5 text-xs text-[var(--as-muted-fg)]"
        data-testid="context-summary"
      >
        <span className="font-semibold tabular-nums text-[var(--as-accent)]">{includedItems}</span>
        {" / "}
        <span className="font-semibold tabular-nums">{totalItems}</span>
        {" items on the CV"}
      </p>
      <div className="relative mb-2 shrink-0">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--as-muted-fg)]" />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Filter context…"
          aria-label="Filter context items"
          data-testid="context-search"
          className="w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] py-1.5 pl-8 pr-2 text-sm outline-none transition-colors focus:border-[var(--as-accent)]"
        />
      </div>
      <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-0.5">
        {filtered.map((source) => (
          <GroupRow
            key={source.key}
            source={source}
            selected={selected}
            onToggle={onToggle}
            onToggleGroup={onToggleGroup}
            onBullet={onBullet}
            variants={variants}
            onAddVariant={onAddVariant}
            synthPins={synthPins}
            onPinVariant={onPinVariant}
            onEditVariant={onEditVariant}
            onActivateVariant={onActivateVariant}
            open={query.trim() !== "" ? true : !closedGroups.has(source.key) && !isEmpty(source)}
            onOpenChange={(open) =>
              setClosedGroups((previous) => {
                const next = new Set(previous);
                if (open) next.delete(source.key);
                else next.add(source.key);
                return next;
              })
            }
          />
        ))}
        {query.trim() !== "" && filtered.every((source) => (source.items ?? []).length === 0) && (
          <p className="px-1 py-2 text-xs text-[var(--as-muted-fg)]" data-testid="context-no-match">
            No context matches “{query}”.
          </p>
        )}
      </div>
    </div>
  );
}
