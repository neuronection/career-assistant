import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Pencil,
  Plus,
  ChevronDown,
  Search,
  Star,
  ExternalLink,
  ListChecks,
} from "lucide-react";
import { CheckIndicator } from "@neuronection/assistant-ui";
import type { CvContextSourceOut, CvSynthItem } from "@/types/cv";
import { CONTEXT_SOURCE_LINKS, contextSourceLink } from "@/lib/entityLinks";

interface ContextPanelProps {
  sources: CvContextSourceOut[];
  selected: Set<string>;
  onToggle: (sourceKey: string, itemId: string) => void;
  onToggleGroup: (source: CvContextSourceOut, includeAll: boolean) => void;
  /** Plan 72: the caller's draft + active variants, nested under their items. */
  variants?: CvSynthItem[];
  /** Archived variants under the same items — read-only history rows. */
  archivedVariants?: CvSynthItem[];
  onAddVariant?: (sourceKey: string) => void;
  /** Plan 72 follow-up: per-item variant pinning (`context.synth_pins`). */
  synthPins?: Record<string, string>;
  /** The applied-variant truth from the preview (`resolution
   * .synth_applied`) — null before the first resolution lands. A star
   * whose pin is missing here is inactive (amber), never silently
   * dead. */
  appliedPins?: Record<string, string> | null;
  onPinVariant?: (
    sourceKey: string,
    itemId: string,
    synthId: string | null,
    slot?: "text" | "bullets"
  ) => void;
  onEditVariant?: (variant: CvSynthItem) => void;
  /** Plan 102: re-snapshot a stale variant's source hashes (review button). */
  onResetVariant?: (variant: CvSynthItem) => void;
  /** Plan 105: create a profile entity for this source group. */
  onAddItem?: (sourceKey: string) => void;
  /** Plan 105: edit the profile entity behind a context item. */
  onEditItem?: (sourceKey: string, itemId: string) => void;
  /** Plan 106: edit the item's bullets (the pinned bullets variant). */
  onEditBullets?: (sourceKey: string, itemId: string) => void;
}

function refKeyOf(sourceKey: string, itemId: string): string {
  return `${sourceKey}:${itemId}`;
}

function variantText(variant: CvSynthItem): string {
  const payload = variant.payload || {};
  if (variant.scope === "bullets") {
    return (payload.achievements ?? [])
      .map((entry) => entry.text)
      .filter(Boolean)
      .join(" · ");
  }
  return payload.description || payload.summary || "";
}

type PinSlot = "text" | "bullets";

function PinStar({
  pinned,
  inactive = false,
  variant,
  sourceKey,
  itemId,
  slot = "text",
  onPin,
}: {
  pinned: boolean;
  /** Pinned but NOT rendering (draft/language/posting mismatch) — the
   * server's `synth_applied` decides; shown amber, never silently. */
  inactive?: boolean;
  variant: CvSynthItem;
  sourceKey: string;
  itemId: string;
  /** Which per-item pin slot this star controls (plan-106 rework). */
  slot?: PinSlot;
  onPin?: (
    sourceKey: string,
    itemId: string,
    synthId: string | null,
    slot?: PinSlot
  ) => void;
}) {
  const kind = slot === "bullets" ? "bullets variant" : "variant";
  return (
    <button
      type="button"
      aria-pressed={pinned}
      aria-label={
        pinned
          ? `Unpin ${kind} ${variant.variant_key} for this item`
          : `Make ${kind} ${variant.variant_key} the default for this item`
      }
      title={
        inactive
          ? "Pinned but not rendering — language, posting or status mismatch"
          : slot === "bullets"
            ? pinned
              ? "Unpin — profile bullets render again"
              : "Make default bullets for this item"
            : pinned
              ? "Unpin — the best matching variant applies again"
              : "Make default for this item"
      }
      data-testid={`context-pin-star-${variant.id}`}
      data-inactive={inactive ? "true" : undefined}
      onClick={() =>
        onPin?.(sourceKey, itemId, pinned ? null : variant.id, slot)
      }
      className={`shrink-0 cursor-pointer rounded p-0.5 transition-colors hover:bg-[var(--as-muted)] ${variant.status === "active" ? "" : "opacity-70"}`}
    >
      <Star
        className={`h-3.5 w-3.5 ${
          pinned
            ? inactive
              ? "fill-amber-400 text-amber-600"
              : "fill-[var(--as-accent)] text-[var(--as-accent)]"
            : "text-[var(--as-muted-fg)]"
        }`}
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
  archivedVariants = [],
  pinnedId,
  appliedPins,
  onPinVariant,
  onEditVariant,
  onResetVariant,
}: {
  sourceKey: string;
  itemId: string;
  variants: CvSynthItem[];
  /** Archived rows under the same item — read-only history. */
  archivedVariants?: CvSynthItem[];
  pinnedId: string | undefined;
  /** The applied-variant truth map (null before the first resolution). */
  appliedPins?: Record<string, string> | null;
  onPinVariant?: (
    sourceKey: string,
    itemId: string,
    synthId: string | null,
    slot?: PinSlot
  ) => void;
  onEditVariant?: (variant: CvSynthItem) => void;
  /** Plan 102: re-snapshot a stale variant's source hashes (review button). */
  onResetVariant?: (variant: CvSynthItem) => void;
}) {
  const appliedId = appliedPins?.[refKeyOf(sourceKey, itemId)];
  const hasResolution = appliedPins != null;
  const rows = variants.filter((variant) =>
    (variant.source_refs ?? []).some(
      (ref) => ref.source_key === sourceKey && ref.item_id === itemId,
    ),
  );
  const archivedRows = (archivedVariants ?? []).filter((variant) =>
    (variant.source_refs ?? []).some(
      (ref) => ref.source_key === sourceKey && ref.item_id === itemId,
    ),
  );
  if (rows.length === 0 && archivedRows.length === 0) return null;
  return (
    <div className="ml-5 space-y-0.5">
      <ul className="space-y-0.5 border-l border-dashed border-[var(--as-border)] pl-2">
      {rows.map((variant) => (
        <li
          key={`${sourceKey}-${itemId}-${variant.id}`}
          className="flex items-center gap-1.5 rounded px-0.5 py-1 text-xs hover:bg-[var(--as-muted)]"
          data-testid={`context-variant-${variant.id}`}
        >
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1">
              <span className="shrink-0 text-[10px] font-medium text-[var(--as-accent)]">
                {variant.variant_key}
              </span>
              {variant.scope === "bullets" && (
                <span
                  className="shrink-0 rounded-full border border-[var(--as-border)] px-1.5 text-[10px] font-medium text-[var(--as-muted-fg)]"
                  data-testid={`context-variant-bullets-${variant.id}`}
                >
                  bullets
                </span>
              )}
              {variant.stale && <AmberBadge testId="context-variant-stale">stale</AmberBadge>}
              {variant.stale && onResetVariant && (
                <button
                  type="button"
                  className="shrink-0 cursor-pointer rounded-full border border-[var(--as-border)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)]"
                  aria-label={`Mark variant ${variant.variant_key} reviewed`}
                  title="Source changed but the text still fits — mark reviewed"
                  data-testid={`context-variant-reset-${variant.id}`}
                  onClick={() => onResetVariant(variant)}
                >
                  Reset
                </button>
              )}
              {variant.orphaned && <AmberBadge testId="context-variant-orphan">gone</AmberBadge>}
              {pinnedId === variant.id && hasResolution && appliedId !== variant.id && (
                <AmberBadge testId={`context-variant-inactive-${variant.id}`}>
                  not rendering
                </AmberBadge>
              )}
            </span>
            {variantText(variant) && (
              <span className="line-clamp-2 text-[var(--as-muted-fg)]">
                {variantText(variant)}
              </span>
            )}
          </span>
          <PinStar
            pinned={pinnedId === variant.id}
            inactive={
              pinnedId === variant.id && hasResolution && appliedId !== variant.id
            }
            variant={variant}
            sourceKey={sourceKey}
            itemId={itemId}
            slot={variant.scope === "bullets" ? "bullets" : "text"}
            onPin={onPinVariant}
          />
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
      {archivedRows.map((variant) => (
        <li
          key={`archived-${sourceKey}-${itemId}-${variant.id}`}
          className="flex items-center gap-1.5 rounded px-0.5 py-1 text-xs opacity-55"
          data-testid={`context-variant-archived-${variant.id}`}
        >
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1">
              <span className="shrink-0 text-[10px] font-medium text-[var(--as-muted-fg)]">
                {variant.variant_key}
              </span>
              {variant.scope === "bullets" && (
                <span
                  className="shrink-0 rounded-full border border-[var(--as-border)] px-1.5 text-[10px] font-medium text-[var(--as-muted-fg)]"
                  data-testid={`context-variant-archived-bullets-${variant.id}`}
                >
                  bullets
                </span>
              )}
              <span
                className="shrink-0 rounded-full border border-[var(--as-border)] px-1.5 text-[10px] font-medium text-[var(--as-muted-fg)]"
                data-testid={`context-variant-archived-badge-${variant.id}`}
              >
                archived
              </span>
            </span>
            {variantText(variant) && (
              <span className="line-clamp-1 text-[var(--as-muted-fg)]">
                {variantText(variant)}
              </span>
            )}
          </span>
        </li>
      ))}
      </ul>
    </div>
  );
}

function GroupRow({
  source,
  selected,
  onToggle,
  onToggleGroup,
  variants,
  archivedVariants,
  onAddVariant,
  synthPins,
  appliedPins,
  onPinVariant,
  onEditVariant,
  onResetVariant,
  onAddItem,
  onEditItem,
  onEditBullets,
  open,
  onOpenChange,
}: {
  source: CvContextSourceOut;
  selected: Set<string>;
  onToggle: (sourceKey: string, itemId: string) => void;
  onToggleGroup: (source: CvContextSourceOut, includeAll: boolean) => void;
  variants: CvSynthItem[];
  archivedVariants?: CvSynthItem[];
  onAddVariant?: (sourceKey: string) => void;
  synthPins: Record<string, string>;
  appliedPins?: Record<string, string> | null;
  onPinVariant?: (
    sourceKey: string,
    itemId: string,
    synthId: string | null,
    slot?: "text" | "bullets"
  ) => void;
  onEditVariant?: (variant: CvSynthItem) => void;
  onResetVariant?: (variant: CvSynthItem) => void;
  onAddItem?: (sourceKey: string) => void;
  onEditItem?: (sourceKey: string, itemId: string) => void;
  onEditBullets?: (sourceKey: string, itemId: string) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const items = source.items ?? [];
  const includedCount = items.filter((item) => selected.has(refKeyOf(source.key, item.item_id))).length;
  const allIncluded = items.length > 0 && includedCount === items.length;
  const someIncluded = includedCount > 0 && !allIncluded;
  const link = CONTEXT_SOURCE_LINKS[source.key];

  return (
    <div className="overflow-hidden rounded-xl bg-[var(--as-surface)]">
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
          <span className="flex-1 truncate text-xs font-semibold text-[var(--as-fg)]">
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
        {link && !link.focusable && (
          <Link
            to={contextSourceLink(source.key)}
            className="shrink-0 rounded p-0.5 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)]"
            aria-label={`Open ${source.label} in profile`}
            title={`Open in profile`}
            data-testid={`context-open-group-${source.key}`}
          >
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
          </Link>
        )}
        {link?.editor && onAddItem && (
          <button
            type="button"
            className="shrink-0 cursor-pointer rounded p-0.5 text-[var(--as-accent)] transition-colors hover:bg-[var(--as-muted)]"
            aria-label={`Add ${source.label}`}
            title={`Add ${source.label}`}
            data-testid={`context-add-${source.key}`}
            onClick={() => onAddItem(source.key)}
          >
            <Plus className="h-3.5 w-3.5" aria-hidden />
          </button>
        )}
      </div>
      {items.length === 0 ? (
        <div className="border-t border-[var(--as-border)] px-2" data-testid={`context-group-body-${source.key}`}>
          {link?.editor && onAddItem ? (
            <button
              type="button"
              className="flex w-full cursor-pointer items-center gap-1 py-1.5 text-xs text-[var(--as-accent)] transition-colors hover:underline"
              data-testid={`context-add-empty-${source.key}`}
              onClick={() => onAddItem(source.key)}
            >
              <Plus className="h-3 w-3" aria-hidden />
              Add {source.label.toLowerCase()}
            </button>
          ) : (
            <p className="py-1.5 text-xs text-[var(--as-muted-fg)]">Nothing recorded yet</p>
          )}
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
                    {link?.focusable && (
                      <span className="flex shrink-0 items-center gap-0.5">
                        {onEditItem && (
                          <button
                            type="button"
                            className="rounded p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)]"
                            aria-label={`Edit ${item.label}`}
                            title="Edit profile entry"
                            data-testid={`context-edit-item-${key}`}
                            onClick={() => onEditItem(source.key, item.item_id)}
                          >
                            <Pencil className="h-3.5 w-3.5" aria-hidden />
                          </button>
                        )}
                        {onEditBullets && writable && (
                          <button
                            type="button"
                            className="rounded p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)]"
                            aria-label={`Edit the bullets of ${item.label} on this CV`}
                            title="Edit bullets on this CV"
                            data-testid={`context-bullets-${key}`}
                            onClick={() => onEditBullets(source.key, item.item_id)}
                          >
                            <ListChecks className="h-3.5 w-3.5" aria-hidden />
                          </button>
                        )}
                        <Link
                          to={contextSourceLink(source.key, item.item_id)}
                          className="rounded p-1 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)]"
                          aria-label={`Open ${item.label} in profile`}
                          title="Open in profile"
                          data-testid={`context-open-item-${key}`}
                        >
                          <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                        </Link>
                      </span>
                    )}
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
                      </span>
                    )}
                  </label>
                  <VariantsForItem
                    sourceKey={source.key}
                    itemId={item.item_id}
                    variants={variants}
                    archivedVariants={archivedVariants}
                    pinnedId={synthPins[key]}
                    appliedPins={appliedPins}
                    onPinVariant={onPinVariant}
                    onEditVariant={onEditVariant}
                    onResetVariant={onResetVariant}
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
  variants = [],
  archivedVariants = [],
  onAddVariant,
  synthPins = {},
  appliedPins = null,
  onPinVariant,
  onEditVariant,
  onResetVariant,
  onAddItem,
  onEditItem,
  onEditBullets,
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
            variants={variants}
            archivedVariants={archivedVariants}
            onAddVariant={onAddVariant}
            synthPins={synthPins}
            appliedPins={appliedPins}
            onPinVariant={onPinVariant}
            onEditVariant={onEditVariant}
            onResetVariant={onResetVariant}
            onAddItem={onAddItem}
            onEditItem={onEditItem}
            onEditBullets={onEditBullets}
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
