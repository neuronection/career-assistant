import { useTranslation } from "react-i18next";
import i18next from "i18next";
import type { CvIntakeSection, DraftHistoryRow } from "@/types/cvIntake";

type CvReport = DraftHistoryRow["report"];

/** Sections whose applied items carry the profile's draft/active
 * status. Basics, skills, languages and interests have no status. */
export const STATUS_SECTIONS: CvIntakeSection[] = [
  "education",
  "experience",
  "certifications",
  "awards",
];

export function isStatusSection(section: CvIntakeSection): boolean {
  return STATUS_SECTIONS.includes(section);
}

/** i18n key of the human label for a history row's state — shared by the
 * status chip and any surface that narrates import state. */
export function statusLabelKey(row: DraftHistoryRow): string {
  if (row.document.status === "error" || row.document.status === "failed") {
    return "profileImport.status.failed";
  }
  if (row.status === "pending") {
    return row.section_count === 0
      ? "profileImport.status.noDetails"
      : "profileImport.status.draftReady";
  }
  if (row.status === "applied") {
    return "profileImport.status.imported";
  }
  return row.status === "discarded" && !row.updated_at
    ? "profileImport.status.parsed"
    : "profileImport.status.discarded";
}

const TONE_CLASSES: Record<string, string> = {
  "profileImport.status.failed": "bg-rose-100 text-rose-700",
  "profileImport.status.noDetails": "bg-amber-100 text-amber-700",
  "profileImport.status.draftReady": "bg-primary-100 text-primary-700",
  "profileImport.status.imported": "bg-emerald-100 text-emerald-700",
};

/** Colored state chip for a CV history row (Imported / Draft ready / …). */
export function StatusChip({ row }: { row: DraftHistoryRow }) {
  const { t } = useTranslation();
  const key = statusLabelKey(row);
  const tone = TONE_CLASSES[key] ?? "bg-slate-200 text-slate-600";
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}
      data-testid="cv-status-chip"
    >
      {t(key)}
    </span>
  );
}

const CREATED_LABEL_KEYS: Record<string, string> = {
  skills: "profileImport.created.skills",
  education_items: "profileImport.created.education",
  experience_items: "profileImport.created.experience",
  certifications: "profileImport.created.certifications",
  profile_achievements: "profileImport.created.achievements",
};

/** One-line "what did this import add" summary from the apply report. */
export function reportSummary(report: CvReport): string | null {
  const t = i18next.t;
  const created = report.created ?? {};
  const parts = Object.entries(created)
    .filter(([, n]) => n > 0)
    .map(([key, n]) =>
      t("profileImport.createdCount", {
        count: n,
        label: t(CREATED_LABEL_KEYS[key] ?? key.replace(/_/g, " ")),
      })
    );
  if (!parts.length) return null;
  return t("profileImport.reportSummary", { parts: parts.join(", ") });
}

/** The apply-report block: created counts, proposed skills, kept
 * conflicts, and (with `updatedAt`) when the import ran. */
export function ReportLines({
  report,
  updatedAt,
  testid,
}: {
  report: CvReport;
  updatedAt: string | null;
  testid: string;
}) {
  const { t } = useTranslation();
  const summary = reportSummary(report);
  const proposed = report.proposed_skills?.length ?? 0;
  const conflicts = report.skill_conflicts?.length ?? 0;
  if (!summary && !proposed && !conflicts) return null;
  return (
    <div
      className="rounded-lg border border-[var(--as-border)] p-3 text-sm text-[var(--as-muted-fg)]"
      data-testid={testid}
    >
      {summary && <p>{summary}</p>}
      {proposed > 0 && (
        <p className={summary ? "mt-1" : ""}>
          {t("profileImport.suggestedSkills", {
            skills: report.proposed_skills?.join(", "),
          })}
        </p>
      )}
      {conflicts > 0 && (
        <p className="mt-1">
          {t("profileImport.levelConflicts", {
            conflicts: (report.skill_conflicts as string[]).join("; "),
          })}
        </p>
      )}
      <p className="mt-1">
        {t("profileImport.importedAt", {
          date: updatedAt
            ? new Date(updatedAt).toLocaleDateString(undefined, {
                year: "numeric",
                month: "short",
                day: "numeric",
              })
            : t("profileImport.earlier"),
        })}
      </p>
    </div>
  );
}
