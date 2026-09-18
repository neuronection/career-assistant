import type { ReactNode } from "react";
import { Briefcase, Copy, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { KIND_ICONS } from "@/components/experience/ExperienceEditor";

/** Minimum shape both the workspace list and the plan-99 preview
 * snapshots render through this card (ExperienceItemOut satisfies it). */
export interface ExperienceItemCardData {
  id: string;
  title: string;
  kind: string;
  org_name?: string | null;
  start?: string | null;
  end?: string | null;
  open_ended?: boolean;
  hours_per_week?: number | null;
  status: string;
  description?: string | null;
  skills: { skill_key: string; skill_label: string }[];
  achievements?: { text: string }[] | null;
}

export interface ExperienceItemCardProps {
  item: ExperienceItemCardData;
  /** Highlighted description spans (plan 99 preview: the anchored edit
   * content, wrapped in the accent-tint `hitl-highlight` mark). */
  highlight?: string[];
  active?: boolean;
  /** One-shot deep-link emphasis (plan 105 `?focus=`): accent ring +
   * `experience-focus-highlight` marker until the caller clears it. */
  focused?: boolean;
  onOpen?: () => void;
  onDuplicate?: () => void;
  onDelete?: () => void;
  selectSlot?: ReactNode;
  testId?: string;
  showAchievements?: boolean;
}

export function periodEnd(
  item: ExperienceItemCardData,
  t: (key: string) => string,
): string {
  return item.open_ended
    ? t("experience.present")
    : (item.end ?? "").slice(0, 7);
}

export function formatPeriod(
  item: ExperienceItemCardData,
  t: (key: string) => string,
): string {
  return `${(item.start ?? "").slice(0, 7)} → ${periodEnd(item, t)}`;
}

/** Wrap each term's first occurrence in an accent-tint mark span. */
function highlightText(text: string, terms: string[]): ReactNode[] {
  const marks: { start: number; end: number }[] = [];
  for (const term of terms) {
    const trimmed = term.trim();
    if (!trimmed) continue;
    const index = text.indexOf(trimmed);
    if (index >= 0) {
      marks.push({ start: index, end: index + trimmed.length });
    }
  }
  if (marks.length === 0) {
    return [text];
  }
  marks.sort((a, b) => a.start - b.start);
  const nodes: ReactNode[] = [];
  let cursor = 0;
  marks.forEach((mark, i) => {
    if (mark.start < cursor) return;
    if (mark.start > cursor) {
      nodes.push(text.slice(cursor, mark.start));
    }
    nodes.push(
      <mark
        key={`mark-${i}`}
        className="rounded bg-[color-mix(in_srgb,var(--as-accent)_25%,transparent)] px-0.5"
        data-testid="hitl-highlight"
      >
        {text.slice(mark.start, mark.end)}
      </mark>,
    );
    cursor = mark.end;
  });
  if (cursor < text.length) {
    nodes.push(text.slice(cursor));
  }
  return nodes;
}

/**
 * One experience list card (plan-99.6 extract of the Experience page) —
 * presentational, shared by the workspace list AND the HITL preview
 * modal: open/duplicate/delete/selection are all optional slots, so the
 * preview renders the same card read-only with highlight spans.
 */
export function ExperienceItemCard({
  item,
  highlight = [],
  active = false,
  focused = false,
  onOpen,
  onDuplicate,
  onDelete,
  selectSlot,
  testId,
  showAchievements = false,
}: ExperienceItemCardProps) {
  const { t } = useTranslation();
  const Icon = KIND_ICONS[item.kind as keyof typeof KIND_ICONS] ?? Briefcase;
  const base = testId ?? `experience-item-${item.id}`;
  const hasHighlight = highlight.some((term) => term && item.description?.includes(term));
  return (
    <article
      className={`group relative rounded-xl border p-2.5 transition-colors duration-150 ${
        active
          ? "border-[var(--as-accent)] bg-[color-mix(in_srgb,var(--as-accent)_8%,transparent)]"
          : "border-[var(--as-border)] bg-[var(--as-surface)] hover:border-[var(--as-accent)]"
      } ${onOpen ? "cursor-pointer" : ""}`}
      data-testid={base}
    >
      {focused && (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-0 rounded-xl ring-1 ring-[var(--as-accent)]"
          data-testid="experience-focus-highlight"
        />
      )}
      <button
        type="button"
        onClick={() => onOpen?.()}
        className={`flex w-full items-start justify-between gap-2 text-left ${
          onOpen ? "cursor-pointer pr-8" : "cursor-default"
        }`}
        data-testid={`${base === `experience-item-${item.id}` ? "experience-item" : `${base}-body`}`}
        aria-current={active ? "true" : undefined}
      >
        <span className="flex min-w-0 items-start gap-2.5">
          <span
            className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${
              active
                ? "bg-[color-mix(in_srgb,var(--as-accent)_15%,transparent)] text-[var(--as-accent)]"
                : "bg-[var(--as-muted)] text-[var(--as-muted-fg)]"
            }`}
          >
            <Icon className="h-4 w-4" aria-hidden />
          </span>
          <span className="block min-w-0">
            <span className="block truncate text-sm font-medium text-[var(--as-fg)]">
              {item.title}
              {item.status === "draft" && (
                <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
                  {t("experience.draft")}
                </span>
              )}
            </span>
            <span className="mt-0.5 block truncate text-xs text-[var(--as-muted-fg)]">
              {t(`experience.kind.${item.kind}`, {
                defaultValue: item.kind,
              })}
              {item.org_name ? ` · ${item.org_name}` : ""} · {formatPeriod(item, t)}
              {item.hours_per_week
                ? ` · ${t("experience.hoursShort", { hours: item.hours_per_week })}`
                : ""}
            </span>
            {item.description ? (
              <span
                className="mt-0.5 line-clamp-1 block text-xs leading-snug text-[var(--as-muted-fg)]/90"
                title={item.description}
              >
                {hasHighlight ? highlightText(item.description, highlight) : item.description}
              </span>
            ) : null}
            {showAchievements && (item.achievements ?? []).length > 0 && (
              <span className="mt-1 flex flex-col gap-0.5 text-xs leading-snug text-[var(--as-muted-fg)]/90">
                {item.achievements!.map((a, i) => (
                  <span key={i}>· {a.text}</span>
                ))}
              </span>
            )}
            {item.skills.length > 0 && (
              <span className="mt-1 flex flex-wrap gap-1">
                {item.skills.slice(0, 3).map((s) => (
                  <span
                    key={s.skill_key}
                    className="rounded-full border border-[var(--as-border)] bg-[var(--as-surface-raised)] px-1.5 py-0.5 text-[10px] text-[var(--as-muted-fg)]"
                  >
                    {s.skill_label}
                  </span>
                ))}
                {item.skills.length > 3 && (
                  <span className="rounded-full border border-[var(--as-border)] px-1.5 py-0.5 text-[10px] text-[var(--as-muted-fg)]">
                    +{item.skills.length - 3}
                  </span>
                )}
              </span>
            )}
          </span>
        </span>
      </button>
      {onDuplicate && (
        <button
          type="button"
          aria-label={t("experience.duplicateAria", { title: item.title })}
          className="absolute right-8 top-2 hidden cursor-pointer rounded p-1 text-slate-300 transition-colors group-hover:text-slate-400 hover:text-[var(--as-accent)] group-hover:block"
          data-testid={`duplicate-experience-${item.id}`}
          onClick={() => onDuplicate()}
        >
          <Copy className="h-3.5 w-3.5" aria-hidden />
        </button>
      )}
      {onDelete && (
        <button
          type="button"
          aria-label={t("experience.deleteAria", { title: item.title })}
          className="absolute right-2 top-2 cursor-pointer rounded p-1 text-slate-300 transition-colors hover:text-[var(--as-danger)] group-hover:text-slate-400"
          data-testid={`delete-experience-${item.id}`}
          onClick={() => onDelete()}
        >
          <Trash2 className="h-3.5 w-3.5" aria-hidden />
        </button>
      )}
      {selectSlot && (
        <div className="absolute bottom-2 right-2">{selectSlot}</div>
      )}
    </article>
  );
}
