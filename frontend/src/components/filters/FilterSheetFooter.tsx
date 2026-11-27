/**
 * The compact filter sheet's footer for pages that know a real result total
 * (plan C1.1, 0.93.0): the shared `FilterRail` `footer` callback hands over
 * the sheet's own `close`, so career can render “Show N jobs” as the primary
 * action and have it close the sheet with the same focus return as the
 * library's Done.
 *
 * A host footer replaces the library default *whole*, so this re-renders the
 * Clear all action the default footer would have shown. Pages without a real
 * total pass no footer at all and keep the library Done — a page size is
 * never turned into a result count.
 */

import { X } from "lucide-react";

import { Button } from "@/components/ui";

export function FilterSheetFooter({
  onClose,
  onClear,
  clearLabel,
  doneLabel,
  testId,
}: {
  /** The sheet close callback the library passes to a function footer. */
  onClose: () => void;
  onClear?: () => void;
  clearLabel: string;
  /** Localized “Show {{count}} jobs”; the caller owns the real total. */
  doneLabel: string;
  testId?: string;
}) {
  return (
    <div
      className={`flex items-center gap-2 ${onClear ? "justify-between" : "justify-end"}`}
    >
      {onClear ? (
        <Button
          type="button"
          variant="ghost"
          onClick={onClear}
          className="min-h-[44px] text-[var(--as-muted-fg)]"
        >
          <X className="size-4" aria-hidden="true" />
          {clearLabel}
        </Button>
      ) : null}
      <Button
        type="button"
        onClick={onClose}
        className="min-h-[44px]"
        data-testid={testId}
      >
        {doneLabel}
      </Button>
    </div>
  );
}
