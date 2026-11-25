/** Simple pill filter chips (multi-select) — the family `FacetChip` inline
 * variant. Hosts keep their own selected-value state and receive intents. */
import { FacetChip, type FilterFacet } from "@neuronection/assistant-ui/filters";

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
  const facet: FilterFacet = {
    id: `${testidPrefix}-kinds`,
    label: testidPrefix,
    kind: "multi",
    options,
  };
  return (
    <FacetChip
      facet={facet}
      variant="inline"
      value={{ kind: "multi", values: selected }}
      onToggleOption={(value) => onToggle(value)}
      testId={`${testidPrefix}-kinds`}
      optionTestId={(value) => `${testidPrefix}-kind-${value}`}
    />
  );
}
