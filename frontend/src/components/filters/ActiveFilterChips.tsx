/**
 * The removable-chip row above a filtered list (plan 208/209): one button
 * per applied filter, rendered only when at least one exists. Pages own
 * the labels and the removal patch; this is the one chrome — token-only,
 * wrapping, never a card of its own.
 */

import { X } from "lucide-react";

export interface ActiveFilterChipItem {
  key: string;
  label: string;
}

export function ActiveFilterChips({
  chips,
  onRemove,
  testId,
  chipTestId,
}: {
  chips: ActiveFilterChipItem[];
  onRemove: (key: string) => void;
  testId?: string;
  chipTestId?: (key: string) => string;
}) {
  if (chips.length === 0) return null;
  return (
    <div
      className="flex flex-wrap items-center gap-1 text-xs text-[var(--as-muted-fg)]"
      data-testid={testId}
    >
      {chips.map((chip) => (
        <button
          key={chip.key}
          type="button"
          onClick={() => onRemove(chip.key)}
          data-testid={chipTestId ? chipTestId(chip.key) : undefined}
          className="inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-0.5"
        >
          {chip.label}
          <X aria-hidden className="h-3 w-3" />
        </button>
      ))}
    </div>
  );
}
