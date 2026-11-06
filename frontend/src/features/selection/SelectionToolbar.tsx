import { useEffect, useRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, SquareCheck } from "lucide-react";
import { CheckIndicator, SelectionBar } from "@neuronection/assistant-ui";
import {
  Button,
  Menu,
  MenuContent,
  MenuItem,
  MenuTrigger,
} from "@/components/ui";
import type { ListSelection } from "./useListSelection";

/** One select-all scope offered by a surface (partition, status, …). */
export interface SelectionScopeOption {
  key: string;
  label: string;
  ids: string[];
}

export interface SelectionEntryProps {
  prefix: string;
  selection: ListSelection;
  disabled?: boolean;
  className?: string;
}

export interface SelectionToolbarProps {
  prefix: string;
  selection: ListSelection;
  /** Every id the listing holds; `matchingIds` pass the current filter. */
  allIds: string[];
  matchingIds: string[];
  scopes?: SelectionScopeOption[];
  actions?: ReactNode;
  busy?: boolean;
  /** Name the loaded scope when it is a partition (e.g. "All 40 in DE"). */
  loadedLabel?: string;
  /** Reveal the rows hidden by the current filter (clears search + filters). */
  onShowHidden?: () => void;
  /** Wrapper testid override (surfaces that kept their pre-plan-200 id). */
  barTestId?: string;
  className?: string;
}

const BAR_FRAME =
  "flex flex-wrap items-center gap-2 rounded-[var(--as-radius)] border border-[color-mix(in_srgb,var(--as-primary)_30%,var(--as-border))] bg-[color-mix(in_srgb,var(--as-primary)_10%,var(--as-surface))] px-3 py-1.5 text-sm text-[var(--as-fg)]";
const HIDDEN_CHIP =
  "inline-flex items-center gap-1.5 rounded-full border border-[color-mix(in_srgb,var(--as-warning)_45%,var(--as-border))] bg-[color-mix(in_srgb,var(--as-warning)_14%,var(--as-surface))] px-2 py-0.5 text-[11px] text-[var(--as-fg)]";
const MICRO_LINK =
  "cursor-pointer text-[11px] text-[var(--as-accent)] underline-offset-2 hover:underline";
const ICON_BUTTON =
  "flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-[var(--as-radius-sm)] text-[var(--as-muted-fg)] transition-colors hover:text-[var(--as-fg)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)]";

/**
 * The selection entry: one button, same slot and variant on every listing.
 * Toggles between "Select" and "Done" — place it in the listing toolbar and
 * render `SelectionToolbar` (below the toolbar) while `selection.active`.
 */
export function SelectionEntry({
  prefix,
  selection,
  disabled = false,
  className,
}: SelectionEntryProps) {
  const { t } = useTranslation();
  return (
    <Button
      type="button"
      size="sm"
      variant={selection.active ? "secondary" : "outline"}
      disabled={disabled}
      onClick={() => (selection.active ? selection.exit() : selection.enter())}
      data-testid={`${prefix}-select`}
      className={className}
    >
      {selection.active ? (
        t("selection.exit")
      ) : (
        <>
          <SquareCheck className="mr-1 h-3.5 w-3.5" aria-hidden />
          {t("selection.entry")}
        </>
      )}
    </Button>
  );
}

/**
 * The active selection bar (plan 200): count, named-scope select-all, the
 * hidden-by-filter chip, the surface's bulk actions and the exit path.
 * Renders nothing while the mode is inactive.
 */
export function SelectionToolbar({
  prefix,
  selection,
  allIds,
  matchingIds,
  scopes = [],
  actions,
  busy = false,
  loadedLabel,
  onShowHidden,
  barTestId,
  className,
}: SelectionToolbarProps) {
  const { t } = useTranslation();
  const handler = useRef<(event: KeyboardEvent) => void>(() => {});
  const barRef = useRef<HTMLDivElement | null>(null);
  const lastCount = useRef(selection.count);

  useEffect(() => {
    if (lastCount.current === selection.count) return;
    lastCount.current = selection.count;
    const root = barRef.current;
    if (!root) return;
    const active = document.activeElement;
    const lost =
      active === null ||
      active === document.body ||
      (active instanceof HTMLElement && !active.isConnected);
    if (!lost) return;
    root
      .querySelector<HTMLElement>('[data-as="check-indicator"]')
      ?.focus();
  }, [selection.count]);

  handler.current = (event: KeyboardEvent) => {
    if (!selection.active || event.defaultPrevented) return;
    if (event.key === "Escape") {
      selection.exit();
      return;
    }
    const mod = event.metaKey || event.ctrlKey;
    if (!mod || event.key.toLowerCase() !== "a") return;
    const target = event.target as HTMLElement | null;
    const tag = target?.tagName;
    if (
      tag === "INPUT" ||
      tag === "TEXTAREA" ||
      tag === "SELECT" ||
      target?.isContentEditable
    ) {
      return;
    }
    event.preventDefault();
    selection.setSelection(matchingIds, true);
  };

  useEffect(() => {
    const listener = (event: KeyboardEvent) => handler.current(event);
    document.addEventListener("keydown", listener);
    return () => document.removeEventListener("keydown", listener);
  }, []);

  if (!selection.active) return null;

  const loaded = allIds.length;
  const matching = matchingIds.length;
  const narrowed = matching !== loaded;
  const tri = selection.triState(matchingIds);
  const selectAllLabel = narrowed
    ? t("selection.selectAllMatching", { count: matching })
    : t("selection.selectAll", { count: loaded });

  const selectAll = (
    <span
      className="flex shrink-0 items-center gap-1.5"
      data-testid={`${prefix}-bulk-bar-select-all`}
    >
      <CheckIndicator
        checked={tri.checked}
        mixed={tri.mixed}
        label={selectAllLabel}
        onToggle={() => selection.setSelection(matchingIds, !tri.checked)}
      />
      <Menu>
        <MenuTrigger asChild>
          <button
            type="button"
            className={ICON_BUTTON}
            aria-label={t("selection.scopeMenu")}
            data-testid={`${prefix}-bulk-scope`}
          >
            <ChevronDown className="h-3.5 w-3.5" aria-hidden />
          </button>
        </MenuTrigger>
        <MenuContent align="start">
          {narrowed && (
            <MenuItem
              data-testid={`${prefix}-bulk-scope-matching`}
              onSelect={() => selection.setSelection(matchingIds, true)}
            >
              {t("selection.scopeMatching", { count: matching })}
            </MenuItem>
          )}
          {scopes.map((scope) => (
            <MenuItem
              key={scope.key}
              data-testid={`${prefix}-bulk-scope-${scope.key}`}
              onSelect={() => selection.setSelection(scope.ids, true)}
            >
              {scope.label}
            </MenuItem>
          ))}
          {narrowed && (
            <MenuItem
              data-testid={`${prefix}-bulk-scope-loaded`}
              onSelect={() => selection.setSelection(allIds, true)}
            >
              {loadedLabel ?? t("selection.scopeLoaded", { count: loaded })}
            </MenuItem>
          )}
          <MenuItem
            data-testid={`${prefix}-bulk-scope-none`}
            onSelect={selection.clear}
          >
            {t("selection.deselectAll")}
          </MenuItem>
        </MenuContent>
      </Menu>
    </span>
  );

  const hiddenChip =
    selection.hiddenCount > 0 ? (
      <span className={HIDDEN_CHIP} data-testid={`${prefix}-bulk-hidden`}>
        {t("selection.hidden", { count: selection.hiddenCount })}
        {onShowHidden && (
          <button
            type="button"
            className={MICRO_LINK}
            onClick={onShowHidden}
            data-testid={`${prefix}-bulk-hidden-show`}
          >
            {t("selection.show")}
          </button>
        )}
        <button
          type="button"
          className={MICRO_LINK}
          onClick={selection.dropHidden}
          data-testid={`${prefix}-bulk-hidden-drop`}
        >
          {t("selection.drop")}
        </button>
      </span>
    ) : null;

  return (
    <div
      ref={barRef}
      className={`space-y-1.5 ${className ?? ""}`}
      data-testid={barTestId ?? `${prefix}-bulk-bar`}
    >
      <div aria-busy={busy}>
        {selection.count > 0 ? (
          <SelectionBar
            count={selection.count}
            countLabel={
              <span data-testid={`${prefix}-bulk-count`}>
                {t("selection.count", { count: selection.count })}
              </span>
            }
            clearLabel={t("selection.clear")}
            onClear={selection.clear}
          >
            {selectAll}
            {hiddenChip}
            {actions}
          </SelectionBar>
        ) : (
          <div className={BAR_FRAME}>
            <span
              className="font-medium text-[var(--as-primary)]"
              data-testid={`${prefix}-bulk-mode`}
            >
              {t("selection.modeFrame", { count: matching })}
            </span>
            {selectAll}
            {hiddenChip}
            {actions}
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={selection.exit}
              data-testid={`${prefix}-bulk-exit`}
            >
              {t("selection.exit")}
            </Button>
          </div>
        )}
      </div>
      <span className="sr-only" role="status" aria-live="polite">
        {t("selection.count", { count: selection.count })}
      </span>
    </div>
  );
}
