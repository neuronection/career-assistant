import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { fetchModerationQueue } from "@/api/admin";
import type { MappingCandidate } from "@/api/mappings";
import { Input } from "@neuronection/assistant-ui";
import type { Job } from "@/types/wire";

/** One selectable catalog type: the trace's candidates first, then the
 * published catalog (deduped). */
interface PickerOption {
  id: string;
  code: string;
  title: string;
  candidate: boolean;
}

/**
 * The shared job-type picker (plan 205 AD6): pick ANY published catalog
 * type for one posting — the trace candidates are pinned first, the rest
 * of the published catalog follows. Used by the triage trace so a
 * `no_skills`/`no_candidate` posting is still mappable (the candidate
 * shortcuts alone would leave it stuck).
 */
export function JobTypePicker({
  value,
  onChange,
  candidates = [],
  disabled = false,
}: {
  value: string | null;
  onChange: (jobId: string | null) => void;
  candidates?: MappingCandidate[];
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [query, setQuery] = useState("");
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    fetchModerationQueue("published", 200)
      .then(setJobs)
      .catch(() => setLoadError(true));
  }, []);

  const options = useMemo<PickerOption[]>(() => {
    const seen = new Set<string>();
    const rows: PickerOption[] = [];
    for (const candidate of candidates) {
      if (seen.has(candidate.job_id)) continue;
      seen.add(candidate.job_id);
      rows.push({
        id: candidate.job_id,
        code: candidate.job_code,
        title: "",
        candidate: true,
      });
    }
    for (const job of jobs) {
      if (seen.has(job.id)) continue;
      seen.add(job.id);
      rows.push({ id: job.id, code: job.code, title: job.title, candidate: false });
    }
    const needle = query.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter(
      (row) =>
        row.code.toLowerCase().includes(needle) || row.title.toLowerCase().includes(needle),
    );
  }, [candidates, jobs, query]);

  return (
    <div className="space-y-1" data-testid="job-type-picker">
      <Input
        label={t("mappingsConsole.triage.pickerSearch")}
        value={query}
        onChange={(event: { target: { value: string } }) => setQuery(event.target.value)}
        placeholder={t("mappingsConsole.triage.pickerPlaceholder")}
        data-testid="job-type-picker-search"
      />
      {loadError && (
        <p className="text-xs text-amber-700" data-testid="job-type-picker-error">
          {t("mappingsConsole.triage.pickerLoadError")}
        </p>
      )}
      {jobs.length >= 200 && (
        <p className="text-xs text-slate-500" data-testid="job-type-picker-truncated">
          {t("mappingsConsole.triage.pickerTruncated")}
        </p>
      )}
      <select
        className="w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1.5 text-sm text-[var(--as-fg)]"
        value={value ?? ""}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value || null)}
        aria-label={t("mappingsConsole.triage.pickerLabel")}
        data-testid="job-type-picker-select"
      >
        <option value="">{t("mappingsConsole.triage.pickerEmpty")}</option>
        {options.map((option) => (
          <option key={option.id} value={option.id}>
            {option.code}
            {option.title ? ` — ${option.title}` : ""}
            {option.candidate ? ` (${t("mappingsConsole.triage.pickerCandidate")})` : ""}
          </option>
        ))}
      </select>
    </div>
  );
}
