/**
 * The organization picker (plan 141): the SkillPicker recipe over the
 * companies catalog — a server-search `MultiSelectPicker`. Values are
 * company NAMES (the explore `org` axis matches organization names via
 * the postings' resolved organizations).
 */

import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { fetchCompanies } from "@/api/companies";
import {
  MultiSelectPicker,
  type PickerOption,
  type PickerSelection,
} from "@/components/ui";

interface OrgPickerProps {
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  className?: string;
  /** Render the selected chips as excluded values (rose, `−` prefix). */
  exclude?: boolean;
}

export function OrgPicker({
  value,
  onChange,
  placeholder,
  className,
  exclude = false,
}: OrgPickerProps) {
  const { t } = useTranslation();

  const search = useCallback(
    async (query: string): Promise<PickerOption[]> => {
      const companies = await fetchCompanies(query ? { q: query, limit: 25 } : { limit: 25 });
      return (companies.items ?? []).map((company) => ({
        value: company.name,
        label: company.name,
      }));
    },
    [],
  );

  const selection: PickerSelection[] = value.map((name) => ({ value: name, label: name }));

  return (
    <MultiSelectPicker
      className={exclude ? `ca-picker-exclude ${className ?? ""}`.trim() : className}
      renderChipExtra={exclude ? () => <span aria-hidden>−</span> : undefined}
      value={selection}
      onChange={(next: PickerSelection[]) =>
        onChange(next.map((entry: PickerSelection) => entry.value))
      }
      onSearch={search}
      placeholder={placeholder ?? t("explore.orgPlaceholder")}
      labels={{
        browseLabel: t("explore.browseCompanies"),
        browseTitle: t("explore.browseCompanies"),
        searchPlaceholder: t("explore.searchCompanies"),
        emptyLabel: t("explore.noCompaniesFound"),
        removeLabel: t("common.remove"),
        selectedCountLabel: (count: number) => t("filters.selectedCount", { count }),
      }}
    />
  );
}
