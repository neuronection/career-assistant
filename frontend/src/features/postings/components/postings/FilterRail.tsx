/**
 * The postings filter rail (plan 136): one collapsible section per axis,
 * three-valued include/exclude/don't-care everywhere, open numeric
 * bounds for salary and match score. Collapsed by default — only axes
 * with active filters expand.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, X } from "lucide-react";

import type { FilterSpec, SkillExpandMode } from "@/api/postings";
import { SegmentedTabs } from "@neuronection/assistant-ui";
import {
  AXIS_DEFINITIONS,
  countActiveFilters,
} from "@/features/postings/components/postings/filterState";
import {
  Section,
  TriStateChips,
  triStateToggle,
} from "@/components/filters/filterBits";
import { SkillPicker } from "@/features/postings/components/postings/SkillPicker";

interface FilterRailProps {
  spec: FilterSpec;
  onChange: (next: FilterSpec) => void;
  onClear: () => void;
}

export function FilterRail({ spec, onChange, onClear }: FilterRailProps) {
  const { t } = useTranslation();
  const active = countActiveFilters(spec);

  return (
    <div
      className="bg-white border border-slate-200 rounded-xl p-4 space-y-3"
      data-testid="filter-rail"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-semibold text-slate-700">
          {t("filters.title")}
          {active > 0 ? (
            <span className="ml-2 text-xs text-primary-600" data-testid="filter-count">
              {t("filters.activeCount", { count: active })}
            </span>
          ) : null}
        </div>
        <div className="flex gap-2">
          {active > 0 ? (
            <button
              type="button"
              className="text-xs text-slate-400 hover:text-slate-600"
              onClick={onClear}
              data-testid="filter-clear"
            >
              {t("filters.clearAll")}
            </button>
          ) : null}
        </div>
      </div>

      <SkillsSection spec={spec} onChange={onChange} />
      <SalarySection spec={spec} onChange={onChange} />
      <EnumSection
        spec={spec}
        onChange={onChange}
        axis="work_mode"
        definition={AXIS_DEFINITIONS.work_mode}
      />
      <LocationSection spec={spec} onChange={onChange} />
      <CompaniesSection spec={spec} onChange={onChange} />
      <SenioritySection spec={spec} onChange={onChange} />
      <EnumSection
        spec={spec}
        onChange={onChange}
        axis="employment"
        definition={AXIS_DEFINITIONS.employment}
      />
      <PostedWithinSection spec={spec} onChange={onChange} />
      <MatchScoreSection spec={spec} onChange={onChange} />
      <SavedSection spec={spec} onChange={onChange} />
      <DescriptionSection spec={spec} onChange={onChange} />
    </div>
  );
}

// ------------------------------------------------------------ shared bits

function ChipInput({
  include,
  exclude,
  onIncludeChange,
  onExcludeChange,
  placeholder,
}: {
  include: string[];
  exclude: string[];
  onIncludeChange: (values: string[]) => void;
  onExcludeChange: (values: string[]) => void;
  placeholder: string;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState<"include" | "exclude">("include");

  const add = () => {
    const value = draft.trim();
    if (!value) return;
    if (mode === "include" && !include.includes(value)) {
      onIncludeChange([...include, value]);
    } else if (mode === "exclude" && !exclude.includes(value)) {
      onExcludeChange([...exclude, value]);
    }
    setDraft("");
  };

  return (
    <div className="space-y-1.5">
      <div className="flex gap-1.5">
        <button
          type="button"
          aria-pressed={mode === "include"}
          className={`text-xs px-2 py-0.5 rounded ${mode === "include" ? "bg-primary-50 text-primary-700 font-medium" : "bg-slate-50 text-slate-500"}`}
          onClick={() => setMode("include")}
        >
          {mode === "include" ? "+" : ""} {t("filters.include")}
        </button>
        <button
          type="button"
          aria-pressed={mode === "exclude"}
          className={`text-xs px-2 py-0.5 rounded ${mode === "exclude" ? "bg-rose-50 text-rose-700 font-medium" : "bg-slate-50 text-slate-500"}`}
          onClick={() => setMode("exclude")}
        >
          {mode === "exclude" ? "−" : ""} {t("filters.exclude")}
        </button>
      </div>
      <div className="flex gap-1.5">
        <input
          className="flex-1 text-sm border border-slate-200 rounded-lg px-2 py-1"
          placeholder={placeholder}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <button
          type="button"
          className="text-sm text-slate-400 hover:text-slate-600"
          onClick={add}
          disabled={!draft.trim()}
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>
      {(include.length > 0 || exclude.length > 0) && (
        <div className="flex flex-wrap gap-1">
          {include.map((v) => (
            <Chip key={`inc-${v}`} value={v} tone="include" onRemove={() => onIncludeChange(include.filter((x) => x !== v))} />
          ))}
          {exclude.map((v) => (
            <Chip key={`exc-${v}`} value={v} tone="exclude" onRemove={() => onExcludeChange(exclude.filter((x) => x !== v))} />
          ))}
        </div>
      )}
    </div>
  );
}

function Chip({
  value,
  tone,
  onRemove,
}: {
  value: string;
  tone: "include" | "exclude";
  onRemove: () => void;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border ${
        tone === "include"
          ? "border-primary-200 bg-primary-50 text-primary-700"
          : "border-rose-200 bg-rose-50 text-rose-700"
      }`}
    >
      {tone === "exclude" ? "− " : ""}
      {value}
      <button type="button" onClick={onRemove} className="hover:text-slate-500">
        <X className="w-3 h-3" />
      </button>
    </span>
  );
}

function EnumSection({
  spec,
  onChange,
  axis,
  definition,
}: {
  spec: FilterSpec;
  onChange: (next: FilterSpec) => void;
  axis: "employment" | "work_mode" | "education";
  definition: AxisDef;
}) {
  const { t } = useTranslation();
  const section = spec[axis];
  const active = section.include.length + section.exclude.length > 0;

  return (
    <Section title={t(definition.labelKey)} active={active}>
      <TriStateChips
        values={definition.values.map((value) => ({
          value,
          label: value.replace(/_/g, " "),
        }))}
        include={section.include}
        exclude={section.exclude}
        onToggle={(value, mode) =>
          onChange({
            ...spec,
            [axis]: triStateToggle(section.include, section.exclude, value, mode),
          })
        }
      />
    </Section>
  );
}

// ------------------------------------------------------------- sections

function SkillsSection({ spec, onChange }: { spec: FilterSpec; onChange: (n: FilterSpec) => void }) {
  const { t } = useTranslation();
  const active =
    spec.skills.include.length + spec.skills.exclude.length > 0 || spec.skills.min_level !== null;
  const patchSkills = (patch: Partial<FilterSpec["skills"]>) =>
    onChange({ ...spec, skills: { ...spec.skills, ...patch } });

  return (
    <Section title={t("filters.skills")} active={active}>
      <SkillPicker
        value={spec.skills.include}
        onChange={(v) => patchSkills({ include: v, min_level: v.length ? spec.skills.min_level : null })}
        placeholder={t("filters.skillsPlaceholder")}
      />
      <div className="space-y-1.5" data-testid="skills-expand">
        <span className="text-xs text-slate-500">{t("filters.skillsExpand")}</span>
        <SegmentedTabs
          ariaLabel={t("filters.skillsExpandAria")}
          className="w-full"
          items={[
            { value: "off", label: t("filters.skillsExpandExact") },
            { value: "down", label: t("filters.skillsExpandDown") },
            { value: "related", label: t("filters.skillsExpandRelated") },
          ]}
          value={spec.skills.expand}
          onValueChange={(next) => patchSkills({ expand: next as SkillExpandMode })}
        />
        {spec.skills.expand !== "off" ? (
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-slate-500">{t("filters.skillsHops")}</span>
            {([1, 2] as const).map((hops) => (
              <button
                key={hops}
                type="button"
                aria-pressed={spec.skills.hops === hops}
                className={`text-xs px-2 py-0.5 rounded-full border ${
                  spec.skills.hops === hops
                    ? "border-primary-300 bg-primary-50 text-primary-700 font-medium"
                    : "border-slate-200 text-slate-600 hover:bg-slate-50"
                }`}
                onClick={() => patchSkills({ hops })}
              >
                {hops === 1 ? t("filters.skillsHopsOne") : t("filters.skillsHopsTwo")}
              </button>
            ))}
          </div>
        ) : null}
        {spec.skills.expand !== "off" && spec.skills.include.length > 0 ? (
          <p className="text-xs text-slate-400" data-testid="skills-expand-hint">
            {spec.skills.expand === "related"
              ? t("filters.skillsExpandHintRelated")
              : t("filters.skillsExpandHintDown")}
          </p>
        ) : null}
      </div>
      <div className="flex items-center gap-2">
        <label htmlFor="skill-min-level" className="text-xs text-slate-500">
          {t("filters.minLevel")}
        </label>
        <input
          id="skill-min-level"
          type="number"
          min={1}
          max={10}
          disabled={spec.skills.include.length === 0}
          title={
            spec.skills.include.length === 0 ? t("filters.minLevelNeedsSkills") : undefined
          }
          className="w-16 text-sm border border-slate-200 rounded px-2 py-1 disabled:bg-slate-50 disabled:text-slate-400"
          value={spec.skills.min_level ?? ""}
          onChange={(e) =>
            patchSkills({ min_level: e.target.value ? Number(e.target.value) : null })
          }
        />
      </div>
    </Section>
  );
}

function SenioritySection({ spec, onChange }: { spec: FilterSpec; onChange: (n: FilterSpec) => void }) {
  const { t } = useTranslation();
  const active = spec.seniority.min !== null || spec.seniority.max !== null || spec.seniority.exclude.length > 0;
  const levels = AXIS_DEFINITIONS.seniority.values;
  return (
    <Section title={t("filters.seniority")} active={active}>
      <div className="flex items-center gap-2">
        <select
          className="flex-1 text-sm border border-slate-200 rounded px-2 py-1"
          value={spec.seniority.min ?? ""}
          onChange={(e) =>
            onChange({ ...spec, seniority: { ...spec.seniority, min: e.target.value || null } })
          }
          aria-label={t("filters.seniorityMin")}
        >
          <option value="">{t("filters.anyLevel")}</option>
          {levels.map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
        <span className="text-slate-400 text-sm">–</span>
        <select
          className="flex-1 text-sm border border-slate-200 rounded px-2 py-1"
          value={spec.seniority.max ?? ""}
          onChange={(e) =>
            onChange({ ...spec, seniority: { ...spec.seniority, max: e.target.value || null } })
          }
          aria-label={t("filters.seniorityMax")}
        >
          <option value="">{t("filters.anyLevel")}</option>
          {levels.map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {levels.map((level) => {
          const isExcluded = spec.seniority.exclude.includes(level);
          return (
            <button
              key={level}
              type="button"
              onClick={() => {
                const next = { ...spec.seniority };
                next.exclude = isExcluded
                  ? next.exclude.filter((v) => v !== level)
                  : [...next.exclude, level];
                onChange({ ...spec, seniority: next });
              }}
              className={`text-xs px-2 py-0.5 rounded-full border ${
                isExcluded
                  ? "border-rose-200 bg-rose-50 text-rose-600 line-through"
                  : "border-slate-200 text-slate-500 hover:bg-slate-50"
              }`}
              title={isExcluded ? t("filters.clickToIncludeOnly") : t("filters.clickToExclude")}
            >
              {level}
            </button>
          );
        })}
      </div>
    </Section>
  );
}

function SalarySection({ spec, onChange }: { spec: FilterSpec; onChange: (n: FilterSpec) => void }) {
  const { t } = useTranslation();
  const active = spec.salary.min !== null || spec.salary.max !== null || !!spec.salary.currency;
  return (
    <Section title={t("filters.salary")} active={active}>
      <div className="flex items-center gap-2">
        <input
          type="number"
          className="w-24 text-sm border border-slate-200 rounded px-2 py-1"
          placeholder={t("filters.min")}
          value={spec.salary.min ?? ""}
          onChange={(e) =>
            onChange({ ...spec, salary: { ...spec.salary, min: e.target.value ? Number(e.target.value) : null } })
          }
        />
        <span className="text-slate-400 text-sm">–</span>
        <input
          type="number"
          className="w-24 text-sm border border-slate-200 rounded px-2 py-1"
          placeholder={t("filters.max")}
          value={spec.salary.max ?? ""}
          onChange={(e) =>
            onChange({ ...spec, salary: { ...spec.salary, max: e.target.value ? Number(e.target.value) : null } })
          }
        />
        <input
          className="w-16 text-sm border border-slate-200 rounded px-2 py-1 uppercase"
          placeholder={t("filters.currencyPlaceholder")}
          maxLength={3}
          value={spec.salary.currency ?? ""}
          onChange={(e) =>
            onChange({ ...spec, salary: { ...spec.salary, currency: e.target.value || null } })
          }
        />
      </div>
    </Section>
  );
}

function LocationSection({ spec, onChange }: { spec: FilterSpec; onChange: (n: FilterSpec) => void }) {
  const { t } = useTranslation();
  const active =
    spec.location.include.length + spec.location.exclude.length > 0 ||
    spec.location.remote_only !== null;
  return (
    <Section title={t("filters.location")} active={active}>
      <ChipInput
        include={spec.location.include}
        exclude={spec.location.exclude}
        onIncludeChange={(v) => onChange({ ...spec, location: { ...spec.location, include: v } })}
        onExcludeChange={(v) => onChange({ ...spec, location: { ...spec.location, exclude: v } })}
        placeholder={t("filters.locationPlaceholder")}
      />
      <label className="flex items-center gap-2 text-xs text-slate-500">
        <input
          type="checkbox"
          checked={spec.location.remote_only === true}
          onChange={(e) =>
            onChange({
              ...spec,
              location: {
                ...spec.location,
                remote_only: e.target.checked ? true : null,
              },
            })
          }
        />
        {t("filters.remoteOnly")}
      </label>
    </Section>
  );
}

function CompaniesSection({ spec, onChange }: { spec: FilterSpec; onChange: (n: FilterSpec) => void }) {
  const { t } = useTranslation();
  const active =
    spec.companies.include.length + spec.companies.exclude.length > 0 ||
    spec.companies.industries_include.length > 0;
  return (
    <Section title={t("filters.companies")} active={active}>
      <ChipInput
        include={spec.companies.include}
        exclude={spec.companies.exclude}
        onIncludeChange={(v) => onChange({ ...spec, companies: { ...spec.companies, include: v } })}
        onExcludeChange={(v) => onChange({ ...spec, companies: { ...spec.companies, exclude: v } })}
        placeholder={t("filters.companiesPlaceholder")}
      />
    </Section>
  );
}

function PostedWithinSection({ spec, onChange }: { spec: FilterSpec; onChange: (n: FilterSpec) => void }) {
  const { t } = useTranslation();
  const active = spec.posted_within.days !== null;
  const options = [1, 3, 7, 14, 30, 60, 90];
  return (
    <Section title={t("filters.postedWithin")} active={active}>
      <div className="flex flex-wrap gap-1.5">
        {options.map((days) => (
          <button
            key={days}
            type="button"
            aria-pressed={spec.posted_within.days === days}
            className={`text-xs px-2.5 py-1 rounded-full border ${
              spec.posted_within.days === days
                ? "border-primary-300 bg-primary-50 text-primary-700 font-medium"
                : "border-slate-200 text-slate-600 hover:bg-slate-50"
            }`}
            onClick={() =>
              onChange({
                ...spec,
                posted_within: { days: spec.posted_within.days === days ? null : days },
              })
            }
          >
            {days === 1 ? "24h" : `${days}d`}
          </button>
        ))}
      </div>
    </Section>
  );
}

function MatchScoreSection({ spec, onChange }: { spec: FilterSpec; onChange: (n: FilterSpec) => void }) {
  const { t } = useTranslation();
  const active = spec.match_score.min !== null || spec.match_score.max !== null;
  return (
    <Section title={t("filters.matchScore")} active={active}>
      <div className="flex items-center gap-2">
        <input
          type="number"
          step="0.5"
          min={0}
          max={10}
          className="w-20 text-sm border border-slate-200 rounded px-2 py-1"
          placeholder={t("filters.min")}
          value={spec.match_score.min ?? ""}
          onChange={(e) =>
            onChange({
              ...spec,
              match_score: { ...spec.match_score, min: e.target.value ? Number(e.target.value) : null },
            })
          }
        />
        <span className="text-slate-400 text-sm">–</span>
        <input
          type="number"
          step="0.5"
          min={0}
          max={10}
          className="w-20 text-sm border border-slate-200 rounded px-2 py-1"
          placeholder={t("filters.max")}
          value={spec.match_score.max ?? ""}
          onChange={(e) =>
            onChange({
              ...spec,
              match_score: { ...spec.match_score, max: e.target.value ? Number(e.target.value) : null },
            })
          }
        />
      </div>
    </Section>
  );
}

function SavedSection({ spec, onChange }: { spec: FilterSpec; onChange: (n: FilterSpec) => void }) {
  const { t } = useTranslation();
  const active = spec.saved.value !== null;
  return (
    <Section title={t("filters.saved")} active={active}>
      <div className="flex gap-1.5">
        {[true, false].map((value) => (
          <button
            key={String(value)}
            type="button"
            aria-pressed={spec.saved.value === value}
            className={`text-xs px-2.5 py-1 rounded-full border ${
              spec.saved.value === value
                ? "border-primary-300 bg-primary-50 text-primary-700 font-medium"
                : "border-slate-200 text-slate-600 hover:bg-slate-50"
            }`}
            onClick={() => onChange({ ...spec, saved: { value: spec.saved.value === value ? null : value } })}
          >
            {value ? t("filters.savedOnly") : t("filters.unsavedOnly")}
          </button>
        ))}
      </div>
    </Section>
  );
}

function DescriptionSection({ spec, onChange }: { spec: FilterSpec; onChange: (n: FilterSpec) => void }) {
  const { t } = useTranslation();
  const active = !!spec.description.text;
  return (
    <Section title={t("filters.description")} active={active}>
      <input
        className="w-full text-sm border border-slate-200 rounded-lg px-2 py-1"
        placeholder={t("filters.descriptionPlaceholder")}
        value={spec.description.text ?? ""}
        onChange={(e) => onChange({ ...spec, description: { text: e.target.value || null } })}
      />
    </Section>
  );
}

interface AxisDef {
  key: string;
  labelKey: string;
  values: string[];
}
