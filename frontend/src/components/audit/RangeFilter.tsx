import { useTranslation } from "react-i18next";
import type { AuditWindow } from "@/api/audit";

/** A window preset with an optional explicit custom range — the shape
 * every audit tab's time filter resolves to (`from`/`to` win over the
 * preset; `""` means all time where the endpoint allows it). */
export interface RangeValue {
  window: AuditWindow | "custom" | "";
  from: string;
  to: string;
}

export const EMPTY_RANGE: RangeValue = { window: "", from: "", to: "" };

export function rangeParams(range: RangeValue): {
  window?: AuditWindow;
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
  return range.window ? { window: range.window } : {};
}

const selectClass =
  "rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-3 py-2 text-sm text-[var(--as-fg)]";

/** The shared time-window control (plan 152): presets, all-time (when
 * `allowAllTime`) and a custom `from`/`to` date pair. */
export function RangeFilter({
  value,
  onChange,
  allowAllTime = false,
  testId = "audit-range",
}: {
  value: RangeValue;
  onChange: (next: RangeValue) => void;
  allowAllTime?: boolean;
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
        <option value="24h">{t("audit.window.24h")}</option>
        <option value="7d">{t("audit.window.7d")}</option>
        <option value="30d">{t("audit.window.30d")}</option>
        <option value="custom">{t("audit.window.custom")}</option>
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
