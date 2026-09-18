import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { FieldChips } from "@/components/ui/chat";

type Snapshot = Record<string, unknown>;

const FIELD_ORDER: Record<string, string[]> = {
  education_item: [
    "institution",
    "program",
    "level",
    "grade_band",
    "focus_subjects",
    "start",
    "end",
    "open_ended",
    "in_progress",
    "status",
    "description",
  ],
  certification: [
    "name",
    "issuer",
    "issued",
    "expires",
    "credential_id",
    "link",
    "language_code",
    "status",
  ],
  profile_achievement: [
    "kind",
    "title",
    "issuer",
    "date",
    "detail",
    "link",
    "status",
  ],
};

/** Prose fields that receive the highlight spans (plan 99.2 vocabulary:
 * anchored text edits target description/detail). */
const PROSE_FIELDS: Record<string, string[]> = {
  education_item: ["description"],
  certification: [],
  profile_achievement: ["detail"],
};

function highlightText(text: string, terms: string[]): ReactNode[] {
  if (!terms.length) {
    return [text];
  }
  const escaped = terms
    .filter(Boolean)
    .map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const parts = text.split(new RegExp(`(${escaped.join("|")})`, "g"));
  return parts.map((part, index) =>
    terms.includes(part) ? (
      <mark
        key={index}
        data-testid="hitl-highlight"
        className="rounded-[var(--as-radius)] bg-[color-mix(in_srgb,var(--as-accent)_18%,transparent)] text-[var(--as-fg)]"
      >
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

function formatValue(key: string, value: unknown): ReactNode {
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  if (
    typeof value === "string" &&
    /^\d{4}-\d{2}(-\d{2})?$/.test(value) &&
    ["start", "end", "issued", "expires", "date"].includes(key)
  ) {
    const [year, month] = value.split("-");
    const monthLabel = new Intl.DateTimeFormat(undefined, {
      month: "long",
    }).format(new Date(Number(year), Number(month) - 1, 15));
    return `${monthLabel} ${year}`;
  }
  return String(value);
}

/**
 * Per-kind snapshot renderer (plan 101 AD3): education / certification /
 * achievement previews as their edit surface renders them —
 * deterministic labelled rows, scalar lists as chips, prose with the
 * changed span highlighted. Mirrors the app KIND_SPECS label keys
 * (`chat.proposals.fields.*`); unknown keys fall back to the raw key so
 * a future field never renders empty.
 */
export function ProfileSnapshotCard({
  snapshot,
  kind,
  highlight = [],
  testId = "hitl-snapshot-card",
}: {
  snapshot: Snapshot | null;
  kind: string;
  highlight?: string[];
  testId?: string;
}) {
  const { t } = useTranslation();
  if (!snapshot) {
    return null;
  }
  const order = FIELD_ORDER[kind] ?? [];
  const rows = order
    .map((key) => ({ key, value: snapshot[key] }))
    .filter(
      ({ value }) =>
        value !== null &&
        value !== undefined &&
        value !== "" &&
        !(Array.isArray(value) && value.length === 0),
    )
    .concat(
      Object.entries(snapshot)
        .filter(
          ([key, value]) =>
            !order.includes(key) &&
            value !== null &&
            value !== undefined &&
            value !== "" &&
            !(Array.isArray(value) && value.length === 0) &&
            typeof value !== "object",
        )
        .map(([key, value]) => ({ key, value })),
    );
  if (rows.length === 0) {
    return null;
  }
  const prose = new Set(PROSE_FIELDS[kind] ?? []);
  return (
    <ul
      className="flex flex-col gap-1.5 rounded-xl border border-[var(--as-border)] p-2.5 text-xs"
      data-testid={testId}
    >
      {rows.map(({ key, value }) => (
        <li
          key={key}
          className="grid min-w-0 grid-cols-[7rem_1fr] items-baseline gap-2"
        >
          <span
            className="truncate text-[var(--as-muted-fg)]"
            title={key}
            data-testid={`hitl-preview-field-${key}`}
          >
            {t(`chat.proposals.fields.${key}`, {
              defaultValue:
                key === "open_ended"
                  ? "Open-ended"
                  : key === "in_progress"
                    ? "In progress"
                    : key === "grade_band"
                      ? "Grade band"
                      : key === "focus_subjects"
                        ? "Focus subjects"
                        : key === "language_code"
                          ? "Language"
                          : key.replace(/_/g, " "),
            })}
          </span>
          <span className="break-words text-[var(--as-fg)]" data-testid={`hitl-preview-value-${key}`}>
            {Array.isArray(value) ? (
              <FieldChips
                value={value.map((entry) => ({
                  label: typeof entry === "string" ? entry : "",
                }))}
              />
            ) : prose.has(key) && typeof value === "string" ? (
              <>
                {highlightText(value, highlight)}
              </>
            ) : (
              formatValue(key, value)
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}
