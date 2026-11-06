import { useTranslation } from "react-i18next";
import type { AuditWindow } from "@/api/audit";

/** Every preset the shared control understands. Retrieval adds `90d`;
 * the audit endpoints keep the original `24h|7d|30d` set. */
export type RangePreset = AuditWindow | "90d";

/** A window preset with an optional explicit custom range — the shape
 * every audit tab's time filter resolves to (`from`/`to` win over the
 * preset; `""` means all time where the endpoint allows it). */
export interface RangeValue {
  window: RangePreset | "custom" | "";
  from: string;
  to: string;
}

export const EMPTY_RANGE: RangeValue = { window: "", from: "", to: "" };

/** Presets offered by the legacy audit tabs (unchanged). */
export const AUDIT_WINDOWS: readonly RangePreset[] = ["24h", "7d", "30d"];

/** Presets offered by Audit → Retrieval (the Q1 read model accepts 90d). */
export const RETRIEVAL_WINDOWS: readonly RangePreset[] = [
  "24h",
  "7d",
  "30d",
  "90d",
];

/** Resolve a range into query params. The generic defaults to the audit
 * preset set so existing callers keep their exact param type; retrieval
 * callers pass `rangeParams<RetrievalWindow>(range)` for 90d. */
export function rangeParams<T extends string = AuditWindow>(range: RangeValue): {
  window?: T;
  from?: string;
  to?: string;
} {
  if (range.window === "custom") {
    const params: { from?: string; to?: string } = {};
    if (range.from) params.from = `${range.from}T00:00:00`;
    if (range.to) {
      const dayAfter = new Date(range.to);
      dayAfter.setDate(dayAfter.getDate() + 1);
      params.to = `${dayAfter.toISOString().slice(0, 10)}T00:00:00`;
    }
    return params;
  }
  return range.window ? { window: range.window as T } : {};
}

const selectClass =
  "rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-3 py-2 text-sm text-[var(--as-fg)]";

/** The shared time-window control (plan 152): presets, all-time (when
 * `allowAllTime`), an optional custom `from`/`to` pair and a per-surface
 * preset list (Retrieval adds 90d without widening the audit endpoints). */
export function RangeFilter({
  value,
  onChange,
  allowAllTime = false,
  allowCustom = true,
  windows = AUDIT_WINDOWS,
  testId = "audit-range",
}: {
  value: RangeValue;
  onChange: (next: RangeValue) => void;
  allowAllTime?: boolean;
  allowCustom?: boolean;
  windows?: readonly RangePreset[];
  testId?: string;
}) {
  const { t } = useTranslation();
  return (
    <span className="flex flex-wrap items-center gap-2">
      <select
        aria-label={t("audit.ai.windowFilter")}
        className={selectClass}
        value={value.window}
        onChange={(e) =>
          onChange({ ...value, window: e.target.value as RangeValue["window"] })
        }
        data-testid={testId}
      >
        {allowAllTime && <option value="">{t("audit.ai.allTime")}</option>}
        {windows.map((preset) => (
          <option key={preset} value={preset}>
            {t(`audit.window.${preset}`)}
          </option>
        ))}
        {allowCustom && (
          <option value="custom">{t("audit.window.custom")}</option>
        )}
      </select>
      {value.window === "custom" && (
        <>
          <input
            type="date"
            aria-label={t("audit.window.fromLabel")}
            className={selectClass}
            value={value.from}
            max={value.to || undefined}
            onChange={(e) => onChange({ ...value, from: e.target.value })}
            data-testid={`${testId}-from`}
          />
          <span className="text-xs text-[var(--as-muted-fg)]">→</span>
          <input
            type="date"
            aria-label={t("audit.window.toLabel")}
            className={selectClass}
            value={value.to}
            min={value.from || undefined}
            onChange={(e) => onChange({ ...value, to: e.target.value })}
            data-testid={`${testId}-to`}
          />
        </>
      )}
    </span>
  );
}
