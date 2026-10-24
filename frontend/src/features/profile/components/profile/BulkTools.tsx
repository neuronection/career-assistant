import { useTranslation } from "react-i18next";
import { CheckIndicator, SelectionBar } from "@neuronection/assistant-ui";

/** Card-level selection checkbox. Lives outside the card's open-button
 * (a button may not nest a button) — place it as a sibling, absolutely
 * positioned like the card's other corner actions. */
export function SelectionToggle({
  selected,
  label,
  onToggle,
}: {
  selected: boolean;
  label: string;
  onToggle: () => void;
}) {
  return (
    <CheckIndicator
      checked={selected}
      label={label}
      onToggle={onToggle}
      mixed={false}
    />
  );
}

/** Bulk toolbar over the library SelectionBar: a count, optional
 * select-all/clear actions, and the workspace-specific bulk buttons
 * (children — Set active/draft, Delete, …). Renders via SelectionBar
 * (null at count 0); `testid` anchors the container for tests. */
export function BulkBar({
  count,
  total,
  onClear,
  onSelectAll,
  children,
  testid = "bulk-bar",
}: {
  count: number;
  total: number;
  onClear: () => void;
  onSelectAll?: () => void;
  children: React.ReactNode;
  testid?: string;
}) {
  const { t } = useTranslation();
  if (count === 0) return null;
  return (
    <div data-testid={testid}>
      <SelectionBar
        count={count}
        countLabel={t("common.selectedCount", { count })}
        onClear={onClear}
      >
        {onSelectAll && count < total && (
          <button
            type="button"
            onClick={onSelectAll}
            className="text-xs text-[var(--as-accent)] underline-offset-2 hover:underline"
            data-testid={`${testid}-select-all`}
          >
            {t("common.selectAll")}
          </button>
        )}
        <span className="mx-1 h-4 w-px bg-[var(--as-border)]" aria-hidden />
        {children}
      </SelectionBar>
    </div>
  );
}

/** Simple pill filter chips (multi-select), aria-pressed based — the
 * same recipe as the SegmentedRow chips but standalone. */
export function FilterChips({
  options,
  selected,
  onToggle,
  testidPrefix,
}: {
  options: { value: string; label: string }[];
  selected: string[];
  onToggle: (value: string) => void;
  testidPrefix: string;
}) {
  return (
    <div className="flex flex-wrap gap-1.5" data-testid={`${testidPrefix}-kinds`}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={selected.includes(option.value)}
          onClick={() => onToggle(option.value)}
          className={`cursor-pointer rounded-full border px-2 py-0.5 text-xs transition-colors ${
            selected.includes(option.value)
              ? "border-[var(--as-accent)] bg-[var(--as-accent)] text-white"
              : "border-[var(--as-border)] text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
          }`}
          data-testid={`${testidPrefix}-kind-${option.value}`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
