/**
 * The skill picker (plan 136): a thin mapping wrapper over the shared
 * `MultiSelectPicker` (promoted to @neuronection/assistant-ui, plan 137) —
 * the ontology fetch stays app-side and maps onto the generic option shape.
 * Two discovery paths: inline type-ahead + browse-modal catalog, fully
 * controlled (`value: string[]` skill keys + `onChange`).
 */

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { fetchSkillOntology } from "@/api/skills";
import {
  MultiSelectPicker,
  type PickerOption,
  type PickerSelection,
} from "@/components/ui";

export interface SkillItem {
  key: string;
  label: string;
  category?: string | null;
}

interface SkillPickerProps {
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  className?: string;
  /** Render the selected chips as excluded values (rose, `−` prefix). */
  exclude?: boolean;
}

export function SkillPicker({
  value,
  onChange,
  placeholder,
  className,
  exclude = false,
}: SkillPickerProps) {
  const { t } = useTranslation();
  const [skills, setSkills] = useState<SkillItem[]>([]);

  useEffect(() => {
    fetchSkillOntology()
      .then((list) =>
        setSkills(
          list
            // the /skills endpoint serves active rows and may omit
            // `status` — treat a missing status as active
            .filter((s) => (s.status ?? "active") === "active")
            .map((s) => ({
              key: s.key,
              label: s.label,
              category: (s as { category?: string }).category ?? null,
            })),
        ),
      )
      .catch(() => setSkills([]));
  }, []);

  const options = useMemo<PickerOption[]>(
    () => skills.map((s) => ({ value: s.key, label: s.label, category: s.category })),
    [skills],
  );

  const selection = useMemo<PickerSelection[]>(
    () =>
      value.map((key) => ({
        value: key,
        label: skills.find((s) => s.key === key)?.label ?? key,
      })),
    [value, skills],
  );

  return (
    <MultiSelectPicker
      className={exclude ? `ca-picker-exclude ${className ?? ""}`.trim() : className}
      renderChipExtra={exclude ? () => <span aria-hidden>−</span> : undefined}
      options={options}
      value={selection}
      onChange={(next: PickerSelection[]) =>
        onChange(next.map((entry: PickerSelection) => entry.value))
      }
      placeholder={placeholder ?? t("filters.skillsPlaceholder")}
      labels={{
        browseLabel: t("filters.browseCatalog"),
        browseTitle: t("filters.browseCatalog"),
        searchPlaceholder: t("filters.searchSkills"),
        categoryLabel: t("filters.category"),
        allCategoriesLabel: t("filters.allCategories"),
        emptyLabel: t("filters.noSkillsFound"),
        addLabel: t("filters.add"),
        addedLabel: t("filters.added"),
        loadMoreLabel: t("filters.loadMore"),
        doneLabel: t("filters.done"),
        removeLabel: t("common.remove"),
        selectedCountLabel: (count: number) =>
          t("filters.selectedCount", { count }),
      }}
    />
  );
}
