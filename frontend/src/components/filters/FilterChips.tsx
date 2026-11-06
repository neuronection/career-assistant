/** Simple pill filter chips (multi-select), aria-pressed based — the same
 * recipe as the SegmentedRow chips but standalone. */
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
