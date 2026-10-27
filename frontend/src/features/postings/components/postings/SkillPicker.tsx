/**
 * The skill picker (plan 136): one controlled multi-select with two
 * discovery paths, mirroring health-assistant's CatalogItemPicker:
 *
 *   1. **Inline type-ahead** — debounced client-side search over the
 *      skill ontology; results render as chips you click to add.
 *   2. **Browse button** (grid icon in the input) — opens a modal with
 *      the full skill catalog: search, category filter, and per-row
 *      Add/Added toggles.
 *
 * Fully controlled: `value: string[]` (skill keys) + `onChange`.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, LayoutGrid, Plus, Search, X } from "lucide-react";

import { fetchSkillOntology } from "@/api/skills";

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
}

export function SkillPicker({ value, onChange, placeholder, className }: SkillPickerProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SkillItem[]>([]);
  const [open, setOpen] = useState(false);
  const [browseOpen, setBrowseOpen] = useState(false);
  const [allSkills, setAllSkills] = useState<SkillItem[]>([]);
  const inputWrapRef = useRef<HTMLDivElement>(null);
  const blurTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // load the full ontology once (shared by both paths)
  useEffect(() => {
    fetchSkillOntology()
      .then((skills) =>
        setAllSkills(
          skills
            .filter((s) => s.status === "active")
            .map((s) => ({ key: s.key, label: s.label, category: (s as { category?: string }).category ?? null })),
        ),
      )
      .catch(() => setAllSkills([]));
  }, []);

  // debounced type-ahead (250ms, min 1 char)
  useEffect(() => {
    const q = query.trim().toLowerCase();
    if (q.length < 1) {
      setResults([]);
      setOpen(false);
      return;
    }
    const timer = setTimeout(() => {
      const matches = allSkills
        .filter(
          (s) =>
            s.label.toLowerCase().includes(q) ||
            s.key.toLowerCase().includes(q),
        )
        .filter((s) => !value.includes(s.key))
        .slice(0, 10);
      setResults(matches);
      setOpen(matches.length > 0);
    }, 250);
    return () => clearTimeout(timer);
  }, [query, allSkills, value]);

  const addSkill = useCallback(
    (key: string) => {
      if (!value.includes(key)) {
        onChange([...value, key]);
      }
      setQuery("");
      setOpen(false);
    },
    [value, onChange],
  );

  const removeSkill = useCallback(
    (key: string) => onChange(value.filter((v) => v !== key)),
    [value, onChange],
  );

  return (
    <div className={className}>
      <div ref={inputWrapRef} className="relative flex items-center gap-1.5">
        <div className="relative flex-1">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
          <input
            className="w-full text-sm border border-slate-200 rounded-lg pl-7 pr-8 py-1.5"
            placeholder={placeholder ?? t("filters.skillsPlaceholder")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => {
              if (query.trim()) setOpen(true);
            }}
            onBlur={() => {
              blurTimer.current = setTimeout(() => setOpen(false), 150);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && results.length > 0) {
                e.preventDefault();
                addSkill(results[0].key);
              }
              if (e.key === "Escape") setOpen(false);
            }}
            role="combobox"
            aria-expanded={open}
            aria-controls="skill-picker-listbox"
            data-testid="skill-picker-input"
          />
          <button
            type="button"
            className="absolute right-1.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
            onClick={() => setBrowseOpen(true)}
            title={t("filters.browseCatalog")}
            data-testid="skill-picker-browse"
          >
            <LayoutGrid className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* inline type-ahead dropdown */}
      {open && results.length > 0 ? (
        <ul
          id="skill-picker-listbox"
          role="listbox"
          className="absolute z-50 mt-1 w-full max-h-60 overflow-auto rounded-lg border border-slate-200 bg-white shadow-lg"
        >
          {results.map((item) => (
            <li
              key={item.key}
              role="option"
              aria-selected={false}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => addSkill(item.key)}
              className="px-3 py-1.5 text-sm cursor-pointer hover:bg-slate-50 flex items-center gap-2"
            >
              <Plus className="w-3 h-3 text-slate-400" />
              <span className="flex-1 truncate">{item.label}</span>
              {item.category ? (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">
                  {item.category}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      {/* selected chips */}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1.5">
          {value.map((key) => {
            const item = allSkills.find((s) => s.key === key);
            return (
              <span
                key={key}
                className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border border-primary-200 bg-primary-50 text-primary-700"
              >
                {item?.label ?? key}
                <button type="button" onClick={() => removeSkill(key)} className="hover:text-slate-500">
                  <X className="w-3 h-3" />
                </button>
              </span>
            );
          })}
        </div>
      )}

      {/* full-catalog browse modal */}
      {browseOpen ? (
        <SkillBrowseModal
          skills={allSkills}
          picked={value}
          onToggle={(key) => {
            if (value.includes(key)) removeSkill(key);
            else onChange([...value, key]);
          }}
          onClose={() => setBrowseOpen(false)}
        />
      ) : null}
    </div>
  );
}

function SkillBrowseModal({
  skills,
  picked,
  onToggle,
  onClose,
}: {
  skills: SkillItem[];
  picked: string[];
  onToggle: (key: string) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [visible, setVisible] = useState(50);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const categories = [...new Set(skills.map((s) => s.category).filter(Boolean))] as string[];
  const filtered = skills.filter((s) => {
    const q = search.trim().toLowerCase();
    const matchSearch = !q || s.label.toLowerCase().includes(q) || s.key.toLowerCase().includes(q);
    const matchCategory = !category || s.category === category;
    return matchSearch && matchCategory;
  });
  const shown = filtered.slice(0, visible);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={t("filters.browseCatalog")}
    >
      <div
        className="bg-white rounded-xl shadow-2xl w-full max-w-lg max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
        data-testid="skill-browse-modal"
      >
        <div className="flex items-center gap-2 p-3 border-b border-slate-200">
          <div className="relative flex-1">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
            <input
              ref={inputRef}
              className="w-full text-sm border border-slate-200 rounded-lg pl-7 pr-2 py-1.5"
              placeholder={t("filters.searchSkills")}
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setVisible(50);
              }}
            />
          </div>
          <select
            className="text-sm border border-slate-200 rounded-lg px-2 py-1.5"
            value={category}
            onChange={(e) => {
              setCategory(e.target.value);
              setVisible(50);
            }}
            aria-label={t("filters.category")}
          >
            <option value="">{t("filters.allCategories")}</option>
            {categories.map((cat) => (
              <option key={cat} value={cat}>{cat}</option>
            ))}
          </select>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2" data-testid="skill-browse-list">
          {shown.length === 0 ? (
            <p className="text-sm text-slate-400 text-center py-8">{t("filters.noSkillsFound")}</p>
          ) : (
            shown.map((item) => {
              const isPicked = picked.includes(item.key);
              return (
                <div
                  key={item.key}
                  className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-slate-50"
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-slate-700 truncate">{item.label}</div>
                    {item.category ? (
                      <div className="text-xs text-slate-400">{item.category}</div>
                    ) : null}
                  </div>
                  <button
                    type="button"
                    onClick={() => onToggle(item.key)}
                    className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                      isPicked
                        ? "border-primary-300 bg-primary-50 text-primary-700 font-medium"
                        : "border-slate-200 text-slate-600 hover:bg-slate-100"
                    }`}
                  >
                    {isPicked ? (
                      <><Check className="w-3 h-3 inline" /> {t("filters.added")}</>
                    ) : (
                      <><Plus className="w-3 h-3 inline" /> {t("filters.add")}</>
                    )}
                  </button>
                </div>
              );
            })
          )}
          {filtered.length > visible ? (
            <button
              type="button"
              className="w-full text-sm text-primary-600 hover:text-primary-700 py-2"
              onClick={() => setVisible((v) => v + 50)}
            >
              {t("filters.loadMore")}
            </button>
          ) : null}
        </div>
        <div className="flex items-center justify-between p-3 border-t border-slate-200">
          <span className="text-xs text-slate-500">
            {t("filters.selectedCount", { count: picked.length })}
          </span>
          <button
            type="button"
            className="text-sm px-4 py-1.5 rounded-lg bg-primary-600 text-white"
            onClick={onClose}
          >
            {t("filters.done")}
          </button>
        </div>
      </div>
    </div>
  );
}
