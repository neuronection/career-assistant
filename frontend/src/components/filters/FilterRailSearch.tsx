/**
 * The rail's search field (plan C1.1): the shared `FilterRail` takes a
 * `search` slot, so career keeps only this small labelled wrapper around its
 * own `SearchInput`. There is no shared equivalent — the module owns no
 * search field of its own — so it stays here rather than being re-invented
 * per page.
 */

import { SearchInput } from "@/components/ui";

export function FilterRailSearch({
  value,
  onChange,
  placeholder,
  testId,
  label,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  testId?: string;
  label?: string;
}) {
  return (
    <div>
      {label ? (
        <span className="mb-1 block text-xs font-medium text-[var(--as-muted-fg)]">
          {label}
        </span>
      ) : null}
      <SearchInput
        ref={(node) => {
          if (node && testId) node.setAttribute("data-testid", testId);
        }}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        ariaLabel={label ?? placeholder}
      />
    </div>
  );
}
