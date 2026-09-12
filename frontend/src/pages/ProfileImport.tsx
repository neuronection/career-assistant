import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  ChevronDown,
  Download,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { Button, ConfirmationModal, EmptyState } from "@neuronection/assistant-ui";
import { CvIntakeFlow } from "@/components/intake/CvIntakeFlow";
import { CvDraftViewer } from "@/components/intake/CvDraftViewer";
import { ReportLines, StatusChip } from "@/components/intake/CvStatus";
import { useProfileStore } from "@/stores/profileStore";
import {
  deleteCvDocument,
  fetchCvFileUrl,
  getCvDrafts,
  listCvDocuments,
  listCvDraftHistory,
} from "@/api/cvIntake";
import { apiDetail } from "@/api/client";
import type { DocumentRecord } from "@/types";
import type { CvDraft, DraftHistoryRow } from "@/types/cvIntake";

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

function MetaLine({ row }: { row: DraftHistoryRow }) {
  const { t } = useTranslation();
  const parts = [
    createdLabel(row.document.created_at),
    fileSize(row.document.size_bytes),
  ];
  if (row.document.page_count > 0) {
    parts.push(t("profileImport.pages", { count: row.document.page_count }));
  }
  return (
    <p className="text-xs text-[var(--as-muted-fg)]">
      {parts.filter(Boolean).join(" · ")}
    </p>
  );
}

function orphanRow(doc: DocumentRecord): DraftHistoryRow {
  return {
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
  };
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
  const hasReport =
    Object.keys(row.report.created ?? {}).length > 0 ||
    (row.report.proposed_skills?.length ?? 0) > 0;
  return (
    <li
      className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
      data-testid="cv-history-row"
    >
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Link
              to={`/profile/import/${row.document.id}`}
              className="truncate text-sm font-medium text-[var(--as-fg)] hover:underline"
              data-testid="cv-history-open"
            >
              {row.document.filename}
            </Link>
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
          {hasReport && (
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
      {expanded && (
        <div className="mt-3">
          <ReportLines report={row.report} updatedAt={row.updated_at} testid="cv-history-report" />
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
 * what each import added. /profile/import/:documentId shows one CV:
 * pending drafts open the interactive review flow, applied ones a
 * read-only view of what was extracted and imported. */
export function ProfileImport() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { documentId } = useParams<{ documentId: string }>();
  const [search] = useSearchParams();
  const reprocess = search.get("re") === "1";
  const { load } = useProfileStore();
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [rows, setRows] = useState<DraftHistoryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<DraftHistoryRow | null>(null);
  const [refreshed, setRefreshed] = useState(false);
  const [viewerDraft, setViewerDraft] = useState<CvDraft | null>(null);
  const [viewerLoading, setViewerLoading] = useState(false);

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

  const detailRow = useMemo(() => {
    if (!documentId) return undefined;
    const hit = rows.find((row) => row.document_id === documentId);
    if (hit) return hit;
    const doc = documents.find((candidate) => candidate.id === documentId);
    return doc ? orphanRow(doc) : undefined;
  }, [documentId, rows, documents]);

  const viewerApplicable =
    !!documentId && !!detailRow && detailRow.status !== "pending" && !reprocess;

  useEffect(() => {
    setViewerDraft(null);
    if (!viewerApplicable || !documentId) return;
    let cancelled = false;
    setViewerLoading(true);
    getCvDrafts(documentId)
      .then((draft) => {
        if (!cancelled) setViewerDraft(draft);
      })
      .catch(() => {
        /* draft gone — the metadata card + report still render */
      })
      .finally(() => {
        if (!cancelled) setViewerLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [viewerApplicable, documentId]);

  const openDetail = (id: string) => {
    setError("");
    navigate(`/profile/import/${id}`);
  };

  const openReprocess = (id: string) => {
    setError("");
    navigate(`/profile/import/${id}?re=1`);
  };

  const exitDetail = () => {
    setRefreshed(true);
    navigate("/profile/import");
    void refresh();
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setBusy(true);
    setError("");
    try {
      await deleteCvDocument(deleteTarget.document_id);
      const fromDetail = deleteTarget.document_id === documentId;
      setDeleteTarget(null);
      if (fromDetail) {
        navigate("/profile/import", { replace: true });
      }
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
        {documentId ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() => exitDetail()}
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

      {documentId ? (
        loading ? (
          <p className="text-sm text-[var(--as-muted-fg)]">{t("common.loading")}</p>
        ) : !detailRow ? (
          <EmptyState
            title={t("profileImport.detail.notFoundTitle")}
            description={t("profileImport.detail.notFoundBody")}
            action={
              <Button size="sm" onClick={() => exitDetail()} data-testid="cv-detail-back-list">
                {t("profileImport.backToCvs")}
              </Button>
            }
          />
        ) : (
          <>
            <div
              className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
              data-testid="cv-detail-meta"
            >
              <div className="flex flex-wrap items-center gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h2 className="truncate text-sm font-semibold text-[var(--as-fg)]">
                      {detailRow.document.filename}
                    </h2>
                    <StatusChip row={detailRow} />
                  </div>
                  <MetaLine row={detailRow} />
                </div>
                <div className="flex items-center gap-2">
                  {detailRow.document.status !== "error" && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => openReprocess(documentId)}
                      disabled={busy}
                      data-testid="cv-detail-reprocess"
                    >
                      <RefreshCw className="mr-1 h-3.5 w-3.5" aria-hidden />
                      {t("profileImport.reprocess")}
                    </Button>
                  )}
                  <DownloadButton
                    documentId={detailRow.document.id}
                    filename={detailRow.document.filename}
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t("profileImport.deleteAria", {
                      name: detailRow.document.filename,
                    })}
                    title={t("profileImport.deleteCv")}
                    onClick={() => setDeleteTarget(detailRow)}
                    disabled={busy}
                    data-testid="cv-detail-delete"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </div>
            {detailRow.status === "pending" || reprocess ? (
              <CvIntakeFlow
                key={`${documentId}:${reprocess ? "re" : "view"}`}
                initialDocumentId={documentId}
                reprocess={reprocess}
                onExit={exitDetail}
                onApplied={() => {
                  setRefreshed(true);
                  void load();
                  void refresh();
                }}
              />
            ) : (
              <CvDraftViewer
                payload={viewerDraft?.payload ?? null}
                row={detailRow}
                documentId={documentId}
                applied={viewerDraft?.applied ?? []}
                loading={viewerLoading}
              />
            )}
          </>
        )
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
                    onReview={() => openDetail(row.document_id)}
                    onReprocess={() => openReprocess(row.document_id)}
                    onDelete={() => setDeleteTarget(row)}
                  />
                ))}
                {orphans.map((doc) => {
                  const row = orphanRow(doc);
                  return (
                    <HistoryRow
                      key={doc.id}
                      row={row}
                      busy={busy}
                      onReview={() => openDetail(doc.id)}
                      onReprocess={() => openReprocess(doc.id)}
                      onDelete={() => setDeleteTarget(row)}
                    />
                  );
                })}
              </ul>
            )}
            {refreshed && !documentId && (
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
