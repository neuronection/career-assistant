import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import i18next from "i18next";
import {
  ArrowLeft,
  ChevronDown,
  Download,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { Button, ConfirmationModal, EmptyState } from "@neuronection/assistant-ui";
import { CvIntakeFlow } from "@/components/intake/CvIntakeFlow";
import { useProfileStore } from "@/stores/profileStore";
import {
  deleteCvDocument,
  fetchCvFileUrl,
  listCvDocuments,
  listCvDraftHistory,
} from "@/api/cvIntake";
import { apiDetail } from "@/api/client";
import type { DocumentRecord } from "@/types";
import type { DraftHistoryRow } from "@/types/cvIntake";

interface ActiveImport {
  documentId: string;
  reprocess?: boolean;
}

function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function createdLabel(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const CREATED_LABEL_KEYS: Record<string, string> = {
  skills: "profileImport.created.skills",
  education_items: "profileImport.created.education",
  experience_items: "profileImport.created.experience",
  certifications: "profileImport.created.certifications",
  profile_achievements: "profileImport.created.achievements",
};

function reportSummary(row: DraftHistoryRow): string | null {
  const t = i18next.t;
  const created = row.report.created ?? {};
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

function StatusChip({ row }: { row: DraftHistoryRow }) {
  const { t } = useTranslation();
  if (row.document.status === "error" || row.document.status === "failed") {
    return (
      <span className="rounded-full bg-rose-100 px-2 py-0.5 text-xs font-medium text-rose-700">
        {t("profileImport.status.failed")}
      </span>
    );
  }
  if (row.status === "pending") {
    if (row.section_count === 0) {
      return (
        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
          {t("profileImport.status.noDetails")}
        </span>
      );
    }
    return (
      <span className="rounded-full bg-primary-100 px-2 py-0.5 text-xs font-medium text-primary-700">
        {t("profileImport.status.draftReady")}
      </span>
    );
  }
  if (row.status === "applied") {
    return (
      <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
        {t("profileImport.status.imported")}
      </span>
    );
  }
  return (
    <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-medium text-slate-600">
      {row.status === "discarded" && !row.updated_at
        ? t("profileImport.status.parsed")
        : t("profileImport.status.discarded")}
    </span>
  );
}

function HistoryRow({
  row,
  busy,
  onReview,
  onReprocess,
  onDelete,
}: {
  row: DraftHistoryRow;
  busy: boolean;
  onReview: () => void;
  onReprocess: () => void;
  onDelete: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const { t } = useTranslation();
  const summary = reportSummary(row);
  return (
    <li
      className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
      data-testid="cv-history-row"
    >
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-medium text-[var(--as-fg)]">
              {row.document.filename}
            </p>
            <StatusChip row={row} />
          </div>
          <p className="text-xs text-[var(--as-muted-fg)]">
            {createdLabel(row.document.created_at)} ·{" "}
            {fileSize(row.document.size_bytes)}
            {row.document.page_count > 0 &&
              ` · ${t("profileImport.pages", { count: row.document.page_count })}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {row.status === "pending" && row.section_count !== 0 && (
            <Button size="sm" onClick={onReview} disabled={busy} data-testid="cv-history-review">
              {t("profileImport.reviewDraft")}
            </Button>
          )}
          {row.document.status !== "error" && (
            <Button
              variant="outline"
              size="sm"
              onClick={onReprocess}
              disabled={busy}
              data-testid="cv-history-reprocess"
            >
              <RefreshCw className="mr-1 h-3.5 w-3.5" aria-hidden />
              {t("profileImport.reprocess")}
            </Button>
          )}
          <DownloadButton documentId={row.document.id} filename={row.document.filename} />
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("profileImport.deleteAria", { name: row.document.filename })}
            title={t("profileImport.deleteCv")}
            onClick={onDelete}
            disabled={busy}
            data-testid="cv-history-delete"
          >
            <Trash2 className="h-4 w-4" />
          </Button>
          {summary && (
            <button
              type="button"
              aria-expanded={expanded}
              aria-label={t("profileImport.toggleReport")}
              onClick={() => setExpanded((v) => !v)}
              className="rounded-lg p-2 text-[var(--as-muted-fg)] hover:bg-[var(--as-muted)]"
              data-testid="cv-history-report-toggle"
            >
              <ChevronDown
                className={`h-4 w-4 transition-transform ${expanded ? "rotate-180" : ""}`}
              />
            </button>
          )}
        </div>
      </div>
      {expanded && summary && (
        <div
          className="mt-3 rounded-lg border border-[var(--as-border)] p-3 text-sm text-[var(--as-muted-fg)]"
          data-testid="cv-history-report"
        >
          <p>{summary}</p>
          {(row.report.proposed_skills?.length ?? 0) > 0 && (
            <p className="mt-1">
              {t("profileImport.suggestedSkills", {
                skills: row.report.proposed_skills?.join(", "),
              })}
            </p>
          )}
          {(row.report.skill_conflicts?.length ?? 0) > 0 && (
            <p className="mt-1">
              {t("profileImport.levelConflicts", {
                conflicts: (row.report.skill_conflicts as string[]).join("; "),
              })}
            </p>
          )}
          <p className="mt-1">
            {t("profileImport.importedAt", {
              date: createdLabel(row.updated_at) || t("profileImport.earlier"),
            })}
          </p>
        </div>
      )}
    </li>
  );
}

function DownloadButton({
  documentId,
  filename,
}: {
  documentId: string;
  filename: string;
}) {
  const [busy, setBusy] = useState(false);
  const { t } = useTranslation();
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={t("profileImport.downloadAria", { name: filename })}
      title={t("profileImport.downloadOriginal")}
      disabled={busy}
      onClick={() => {
        setBusy(true);
        fetchCvFileUrl(documentId)
          .then((url) => {
            const anchor = document.createElement("a");
            anchor.href = url;
            anchor.download = filename;
            anchor.click();
            URL.revokeObjectURL(url);
          })
          .finally(() => setBusy(false));
      }}
      data-testid="cv-history-download"
    >
      <Download className="h-4 w-4" />
    </Button>
  );
}

/** /profile/import: the CV-import workspace — upload a CV,
 * revisit drafts, re-process older CVs, download originals, and trace
 * what each import added. */
export function ProfileImport() {
  const { t } = useTranslation();
  const { load } = useProfileStore();
  const [active, setActive] = useState<ActiveImport | null>(null);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [rows, setRows] = useState<DraftHistoryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<DraftHistoryRow | null>(null);
  const [refreshed, setRefreshed] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [docs, history] = await Promise.all([
        listCvDocuments(),
        listCvDraftHistory(),
      ]);
      setDocuments(docs);
      setRows(history);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const historyDocIds = new Set(rows.map((row) => row.document_id));
  const orphans = documents.filter((doc) => !historyDocIds.has(doc.id));

  const openReview = (documentId: string, reprocess = false) => {
    setError("");
    setActive({ documentId, reprocess });
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setBusy(true);
    setError("");
    try {
      await deleteCvDocument(deleteTarget.document_id);
      setDeleteTarget(null);
      await refresh();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="mx-auto flex w-full max-w-3xl flex-col gap-6"
      data-testid="profile-import"
    >
      <div>
        {active ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setActive(null)}
            data-testid="import-back"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden />
            {t("profileImport.backToCvs")}
          </Button>
        ) : (
          <Link
            to="/profile"
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm text-[var(--as-fg)] hover:border-[var(--as-accent)]"
            data-testid="import-back"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden />
            {t("profileImport.backToProfile")}
          </Link>
        )}
        <h1 className="mt-3 text-2xl font-bold text-[var(--as-fg)]">
          {t("profileImport.title")}
        </h1>
        <p className="mt-1 text-sm text-[var(--as-muted-fg)]">
          {t("profileImport.subtitle")}
        </p>
      </div>

      {error && <p className="text-sm text-rose-600">{error}</p>}

      {active ? (
        <CvIntakeFlow
          key={`${active.documentId}:${active.reprocess ? "re" : "view"}`}
          initialDocumentId={active.documentId}
          reprocess={active.reprocess}
          onExit={() => {
            setActive(null);
            setRefreshed(true);
            void refresh();
          }}
          onApplied={() => {
            setRefreshed(true);
            void load();
            void refresh();
          }}
        />
      ) : (
        <>
          <CvIntakeFlow
            onApplied={() => {
              setRefreshed(true);
              void load();
              void refresh();
            }}
          />

          <section aria-label={t("profileImport.yourCvs")}>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
              {t("profileImport.yourCvs")}
            </h2>
            {loading ? (
              <p className="mt-2 text-sm text-[var(--as-muted-fg)]">{t("common.loading")}</p>
            ) : rows.length === 0 && orphans.length === 0 ? (
              <EmptyState
                compact
                className="mt-2"
                title={t("profileImport.noCvsTitle")}
                description={t("profileImport.noCvsBody")}
              />
            ) : (
              <ul className="mt-2 space-y-2">
                {rows.map((row) => (
                  <HistoryRow
                    key={row.document_id}
                    row={row}
                    busy={busy}
                    onReview={() => openReview(row.document_id)}
                    onReprocess={() => openReview(row.document_id, true)}
                    onDelete={() => setDeleteTarget(row)}
                  />
                ))}
                {orphans.map((doc) => (
                  <HistoryRow
                    key={doc.id}
                    busy={busy}
                    row={{
                      document_id: doc.id,
                      status: "discarded",
                      updated_at: null,
                      report: {},
                      document: {
                        id: doc.id,
                        filename: doc.filename,
                        mime: doc.mime,
                        size_bytes: doc.size_bytes,
                        page_count: doc.page_count,
                        status: doc.status,
                        error: doc.error,
                        created_at: null,
                      },
                    }}
                    onReview={() => openReview(doc.id)}
                    onReprocess={() => openReview(doc.id, true)}
                    onDelete={() =>
                      setDeleteTarget({
                        document_id: doc.id,
                        status: "discarded",
                        updated_at: null,
                        report: {},
                        document: {
                          id: doc.id,
                          filename: doc.filename,
                          mime: doc.mime,
                          size_bytes: doc.size_bytes,
                          page_count: doc.page_count,
                          status: doc.status,
                          error: doc.error,
                          created_at: null,
                        },
                      })
                    }
                  />
                ))}
              </ul>
            )}
            {refreshed && !active && (
              <p className="mt-2 text-sm text-emerald-600" data-testid="import-refreshed">
                {t("profileImport.updated")}
              </p>
            )}
          </section>
        </>
      )}

      <ConfirmationModal
        open={deleteTarget != null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        onConfirm={() => void confirmDelete()}
        title={t("profileImport.deleteTitle", {
          name: deleteTarget?.document.filename ?? "",
        })}
        description={t("profileImport.deleteBody")}
        confirmLabel={t("profileImport.deleteCv")}
        destructive
      />
    </div>
  );
}
