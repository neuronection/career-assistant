/**
 * The removable-chip row above a filtered list (plan 208/209): one button
 * per applied filter, rendered only when at least one exists. Pages own
 * the labels and the removal patch; the chrome is the family `FilterPills`.
 */

import { FilterPills } from "@neuronection/assistant-ui/filters";

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
  return (
    <FilterPills items={chips} onRemove={onRemove} testId={testId} itemTestId={chipTestId} />
  );
}
