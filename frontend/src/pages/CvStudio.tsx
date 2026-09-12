import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { FileText, Plus, Copy, Trash2, MailPlus, Sparkles, Wand2 } from "lucide-react";
import { Button, Card, ConfirmationModal, EmptyState, Modal, ModalContent, ModalHeader, ModalTitle } from "@/components/ui";
import { apiDetail } from "@/api/client";
import { listCvDraftHistory } from "@/api/cvIntake";
import { StatusChip } from "@/components/intake/CvStatus";
import type { DraftHistoryRow } from "@/types/cvIntake";
import {
  createCoverLetter,
  createCv,
  deleteCv,
  duplicateCv,
  fetchContextSources,
  fetchCvs,
} from "@/api/cv";
import { fetchPostings } from "@/api/postings";
import { TemplateGallery } from "@/components/cv/TemplateGallery";
import { TemplatePreviewFrame } from "@/components/cv/TemplateGallery";
import { suggestTemplates, fetchTemplates } from "@/api/cvTemplates";
import type { TemplatePickSummary } from "@/api/cvTemplates";
import { GenerateCvFlow } from "@/components/cv/GenerateCvFlow";
import { GenerateCvModal } from "@/components/cv/GenerateCvModal";
import { SegmentedRow } from "@/components/cv/formPrimitives";
import type { CvDocumentOut } from "@/types/cv";
import type { CvTemplateSummary } from "@/types/cvTemplate";

export function CvStudio() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [cvs, setCvs] = useState<CvDocumentOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
    const [createMode, setCreateMode] = useState<"scratch" | "generate" | "import">(
    "scratch"
  );
  const [generateOpen, setGenerateOpen] = useState(
    searchParams.get("generate") === "1"
  );
  const [newTitle, setNewTitle] = useState("");
  const [chosenTemplate, setChosenTemplate] = useState<CvTemplateSummary | null>(null);
  const [galleryOpen, setGalleryOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<CvDocumentOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [letterOpen, setLetterOpen] = useState(false);
  const [letterPostingId, setLetterPostingId] = useState("");
  const [letterBaseCvId, setLetterBaseCvId] = useState("");
  const [letterPostings, setLetterPostings] = useState<
    { id: string; title: string; org: string }[]
  >([]);
  const [letterBusy, setLetterBusy] = useState(false);
  const [suggestions, setSuggestions] = useState<TemplatePickSummary[] | null>(null);
  const [suggesting, setSuggesting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setCvs(await fetchCvs());
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (searchParams.get("generate") === "1") {
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  function openNewCv() {
    setNewTitle("");
    setChosenTemplate(null);
    setCreateMode("scratch");
    setSuggestions(null);
    setCreating(true);
    fetchContextSources()
      .then((out) => {
        const hasContent = out.sources.some(
          (source) => source.key !== "basics" && source.items.length > 0
        );
        setCreateMode(hasContent ? "generate" : "scratch");
      })
      .catch(() => {});
  }

  async function askAiChoose() {
    setSuggesting(true);
    setError("");
    try {
      const result = await suggestTemplates();
      setSuggestions(result.picks);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setSuggesting(false);
    }
  }

  async function applySuggestion(templateId: string) {
    try {
      const templates = await fetchTemplates();
      const match = templates.find((row) => row.id === templateId);
      if (match) {
        setChosenTemplate(match);
        setSuggestions(null);
      }
    } catch (err) {
      setError(apiDetail(err));
    }
  }

  async function handleCreate() {
    if (!newTitle.trim()) return;
    setBusy(true);
    setError("");
    try {
      const cv = await createCv({
        title: newTitle.trim(),
        template_id: chosenTemplate?.id ?? undefined,
      });
      setCreating(false);
      navigate(`/cv/${cv.id}`);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleDuplicate(cv: CvDocumentOut) {
    setError("");
    try {
      const copy = await duplicateCv(cv.id);
      navigate(`/cv/${copy.id}`);
    } catch (err) {
      setError(apiDetail(err));
    }
  }

  function openLetterModal() {
    setLetterPostingId("");
    setLetterBaseCvId("");
    setLetterOpen(true);
    fetchPostings({ saved: true })
      .then((page) =>
        setLetterPostings(
          page.items.map((row) => ({
            id: String(row.id),
            title: row.title,
            org: row.org,
          }))
        )
      )
      .catch(() => setLetterPostings([]));
  }

  async function handleCreateLetter() {
    if (!letterPostingId) return;
    setLetterBusy(true);
    setError("");
    try {
      const letter = await createCoverLetter({
        posting_id: letterPostingId,
        base_cv_id: letterBaseCvId || undefined,
      });
      setLetterOpen(false);
      navigate(`/cv/${letter.id}`);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setLetterBusy(false);
    }
  }

  async function handleDelete(cv: CvDocumentOut) {
    setError("");
    try {
      await deleteCv(cv.id);
      setCvs((rows) => rows.filter((row) => row.id !== cv.id));
    } catch (err) {
      setError(apiDetail(err));
    }
  }

  return (
    <div className="mx-auto w-full max-w-5xl p-6" data-testid="cv-studio">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--as-fg)]">{t("cvStudio.title")}</h1>
          <p className="text-sm text-[var(--as-muted-fg)]">
            {t("cvStudio.subtitle")}
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            to="/cv/synth"
            data-testid="synth-library-link"
            className="text-sm px-3 py-2 flex items-center gap-1 rounded-md border border-slate-200 bg-white hover:bg-slate-50 text-slate-700"
          >
            <Wand2 className="h-4 w-4" /> {t("cvSynth.title")}
          </Link>
          <Button variant="outline" onClick={openLetterModal} data-testid="new-letter">
            <MailPlus className="mr-1 h-4 w-4" /> {t("cvStudio.newLetter")}
          </Button>
          <Button onClick={openNewCv} data-testid="new-cv">
            <Plus className="mr-1 h-4 w-4" /> {t("cvStudio.newCv")}
          </Button>
        </div>
      </div>

      {error && (
        <p role="alert" className="mb-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </p>
      )}

      <ImportedCvsPanel />

      {loading ? (
        <p className="text-sm text-[var(--as-muted-fg)]">{t("common.loading")}</p>
      ) : cvs.length === 0 ? (
        <EmptyState
          icon={FileText}
          title={t("cvStudio.emptyTitle")}
          description={t("cvStudio.emptyBody")}
          action={<Button onClick={openNewCv}>{t("cvStudio.createCv")}</Button>}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {cvs.map((cv) => (
            <Card key={cv.id} className="flex flex-col justify-between p-4">
              <div>
                <div className="flex items-center gap-2">
                  <button
                    className="text-left text-lg font-medium hover:underline"
                    onClick={() => navigate(`/cv/${cv.id}`)}
                  >
                    {cv.title}
                  </button>
                  {cv.kind === "cover_letter" && (
                    <span
                      className="rounded bg-[var(--as-muted)] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[var(--as-muted-fg)]"
                      data-testid="cv-kind"
                    >
                      {t("cvStudio.coverLetter")}
                    </span>
                  )}
                  {cv.working_content?.generated_by === "cv_draft" && (
                    <span
                      className="inline-flex items-center gap-1 rounded bg-[color-mix(in_srgb,var(--as-accent)_12%,transparent)] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[var(--as-accent)]"
                      data-testid="cv-generated"
                    >
                      <Sparkles className="h-3 w-3" aria-hidden />
                      {t("cvStudio.aiDraft")}
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs text-[var(--as-muted-fg)]">
                  {t("cvStudio.cardMeta", {
                    count: cv.max_pages,
                    status: cv.status,
                    language: cv.language.toUpperCase(),
                    version:
                      cv.latest_version != null
                        ? `v${cv.latest_version}`
                        : t("cvStudio.notCompiled"),
                  })}
                </p>
              </div>
              <div className="mt-3 flex gap-2">
                <Button variant="outline" onClick={() => navigate(`/cv/${cv.id}`)}>
                  {t("cvStudio.open")}
                </Button>
                <Button variant="ghost" onClick={() => handleDuplicate(cv)} aria-label={t("cvStudio.duplicateAria", { title: cv.title })}>
                  <Copy className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => setDeleteTarget(cv)}
                  aria-label={t("cvStudio.deleteAria", { title: cv.title })}
                  data-testid={`delete-cv-${cv.id}`}
                >
                  <Trash2 className="h-4 w-4 text-red-600" />
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      <ConfirmationModal
        open={deleteTarget !== null}
        onOpenChange={(next) => !next && setDeleteTarget(null)}
        title={t("cvStudio.deleteTitle", { title: deleteTarget?.title ?? "" })}
        description={t("cvStudio.deleteBody")}
        confirmLabel={t("cvStudio.deleteConfirm")}
        destructive
        busy={busy}
        onConfirm={async () => {
          if (deleteTarget) await handleDelete(deleteTarget);
          setDeleteTarget(null);
        }}
      />

      <TemplateGallery
        open={galleryOpen}
        onClose={() => setGalleryOpen(false)}
        actionLabel={t("cvStudio.useForNewCv")}
        onUse={(template) => {
          setChosenTemplate(template);
          setNewTitle("");
          setCreateMode("scratch");
          setCreating(true);
        }}
      />

      <Modal open={letterOpen} onOpenChange={(open) => !open && setLetterOpen(false)}>
        <ModalContent size="sm" aria-describedby={undefined}>
          <ModalHeader>
            <ModalTitle>{t("cvStudio.newLetter")}</ModalTitle>
          </ModalHeader>
          <div className="space-y-4 p-4 pt-0">
            <label className="block text-sm">
              <span className="mb-1 block font-medium">{t("cvStudio.targetPosting")}</span>
              <select
                autoFocus
                value={letterPostingId}
                onChange={(event) => setLetterPostingId(event.target.value)}
                className="w-full rounded border p-2"
                data-testid="letter-posting-select"
              >
                <option value="">{t("cvStudio.pickSavedPosting")}</option>
                {letterPostings.map((posting) => (
                  <option key={posting.id} value={posting.id}>
                    {posting.title}
                    {posting.org ? ` — ${posting.org}` : ""}
                  </option>
                ))}
              </select>
            </label>
            {letterPostings.length === 0 && (
              <p className="text-xs text-[var(--as-muted-fg)]">
                {t("cvStudio.noSavedPostings")}
              </p>
            )}
            <label className="block text-sm">
              <span className="mb-1 block font-medium">{t("cvStudio.baseCv")}</span>
              <select
                value={letterBaseCvId}
                onChange={(event) => setLetterBaseCvId(event.target.value)}
                className="w-full rounded border p-2"
                data-testid="letter-base-cv-select"
              >
                <option value="">{t("cvStudio.wholeProfile")}</option>
                {cvs
                  .filter((cv) => cv.kind === "resume")
                  .map((cv) => (
                    <option key={cv.id} value={cv.id}>
                      {cv.title} — {t("cvStudio.sameContext")}
                    </option>
                  ))}
              </select>
            </label>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setLetterOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button
                onClick={handleCreateLetter}
                disabled={letterBusy || !letterPostingId}
                data-testid="create-letter"
              >
                {t("cvStudio.create")}
              </Button>
            </div>
          </div>
        </ModalContent>
      </Modal>

      <Modal open={creating} onOpenChange={(open) => !open && setCreating(false)}>
        <ModalContent
          size={createMode === "generate" ? "xl" : "sm"}
          className={
            createMode === "generate"
              ? "w-[min(1500px,96vw)] max-w-none"
              : undefined
          }
          aria-describedby={undefined}
        >
          <ModalHeader>
            <ModalTitle>
              {createMode === "scratch" && chosenTemplate
                ? t("cvStudio.newCvFromTemplate", { title: chosenTemplate.title })
                : t("cvStudio.newCv")}
            </ModalTitle>
          </ModalHeader>
          <div className="space-y-4 p-4 pt-0">
            {!chosenTemplate && (
              <SegmentedRow
                label={t("cvStudio.modeLabel")}
                value={createMode}
                onChange={(value) => setCreateMode(value as "scratch" | "generate" | "import")}
                options={[
                  { value: "scratch", label: t("cvStudio.modeScratch") },
                  { value: "generate", label: t("cvStudio.modeGenerate") },
                  { value: "import", label: t("cvStudio.modeImport") },
                ]}
              />
            )}
            {createMode === "generate" ? (
              <GenerateCvFlow onClose={() => setCreating(false)} />
            ) : createMode === "import" ? (
              <div className="space-y-3" data-testid="cv-import-mode">
                <p className="text-sm text-[var(--as-muted-fg)]">
                  {t("cvStudio.importBody")}
                </p>
                <div className="flex justify-end">
                  <Button
                    onClick={() => {
                      setCreating(false);
                      navigate("/profile/import");
                    }}
                    data-testid="import-cv-go"
                  >
                    {t("cvStudio.importAction")}
                  </Button>
                </div>
              </div>
            ) : (
              <>
                <label className="block text-sm">
                  <span className="mb-1 block font-medium">{t("cvStudio.titleLabel")}</span>
                  <input
                    autoFocus
                    value={newTitle}
                    onChange={(event) => setNewTitle(event.target.value)}
                    placeholder={t("cvStudio.titlePlaceholder")}
                    className="w-full rounded border p-2"
                    data-testid="new-cv-title"
                  />
                </label>
                <div className="space-y-2" data-testid="new-cv-template-section">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium">{t("cvStudio.templateLabel")}</p>
                    <div className="flex gap-1">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={askAiChoose}
                        disabled={suggesting}
                        data-testid="ask-ai-choose"
                      >
                        <Sparkles className="mr-1 h-3 w-3" aria-hidden />
                        {suggesting ? t("cvStudio.askingAi") : t("cvStudio.askAiChoose")}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setGalleryOpen(true)}
                        data-testid="choose-template"
                      >
                        {t("cvStudio.chooseTemplate")}
                      </Button>
                    </div>
                  </div>
                  {chosenTemplate ? (
                    <Card className="flex items-center gap-3 p-3">
                      <div className="w-20 shrink-0 overflow-hidden rounded border">
                        <TemplatePreviewFrame template={chosenTemplate} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">{chosenTemplate.title}</p>
                        <p className="text-xs text-[var(--as-muted-fg)]">
                          {chosenTemplate.ats_safe ? t("cvStudio.atsSafe") : t("cvStudio.decorative")}
                          {" · "}
                          <button
                            className="text-[var(--as-accent)] hover:underline"
                            onClick={() => setChosenTemplate(null)}
                            data-testid="clear-template"
                          >
                            {t("cvStudio.useNoTemplate")}
                          </button>
                        </p>
                      </div>
                    </Card>
                  ) : (
                    <p className="text-xs text-[var(--as-muted-fg)]" data-testid="no-template-note">
                      {t("cvStudio.noTemplateNote")}
                    </p>
                  )}
                  {suggestions && suggestions.length > 0 && (
                    <ul className="space-y-1" data-testid="ai-suggestions">
                      {suggestions.slice(0, 3).map((pick) => (
                        <li
                          key={pick.template_id}
                          className="flex items-start gap-2 rounded border border-[var(--as-border)] p-2 text-xs"
                        >
                          <button
                            className="font-semibold text-[var(--as-accent)] hover:underline"
                            onClick={() => void applySuggestion(pick.template_id)}
                            data-testid={`use-suggestion-${pick.template_id}`}
                          >
                            {pick.title}
                          </button>
                          <span className="min-w-0 flex-1 text-[var(--as-muted-fg)]">{pick.reason}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <p className="text-xs text-[var(--as-muted-fg)]">
                  {chosenTemplate
                    ? t("cvStudio.fromTemplateBody", { title: chosenTemplate.title })
                    : t("cvStudio.fromScratchBody")}
                </p>
                <div className="flex justify-end gap-2">
                  <Button variant="ghost" onClick={() => setCreating(false)}>{t("common.cancel")}</Button>
                  <Button onClick={handleCreate} disabled={busy || !newTitle.trim()} data-testid="create-cv">
                    {t("cvStudio.create")}
                  </Button>
                </div>
              </>
            )}
          </div>
        </ModalContent>
      </Modal>

      <GenerateCvModal open={generateOpen} onOpenChange={setGenerateOpen} />
    </div>
  );
}

/** "Your imported CVs": the kind=cv source files uploaded through
 * /profile/import. Kept light — a bridge to the import workspace, not
 * a second history list. */
function ImportedCvsPanel() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<DraftHistoryRow[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    listCvDraftHistory()
      .then((history) => {
        if (!cancelled) setRows(history);
      })
      .catch(() => {
        if (!cancelled) setRows([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  if (rows === null || rows.length === 0) return null;
  return (
    <section
      className="mb-6 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
      data-testid="cvstudio-imports-panel"
    >
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-[var(--as-fg)]">
          {t("cvStudio.importedCvsTitle")}
        </h2>
        <Link
          to="/profile/import"
          className="text-xs text-[var(--as-accent)] hover:underline"
          data-testid="cvstudio-imports-open"
        >
          {t("cvStudio.importedCvsOpen")}
        </Link>
      </div>
      <ul className="mt-2 divide-y divide-[var(--as-border)]">
        {rows.slice(0, 3).map((row) => (
          <li key={row.document_id}>
            <Link
              to={`/profile/import/${row.document_id}`}
              className="flex items-center gap-2 py-2 text-sm hover:underline"
              data-testid={`cvstudio-import-${row.document_id}`}
            >
              <FileText className="h-4 w-4 shrink-0 text-[var(--as-muted-fg)]" aria-hidden />
              <span className="min-w-0 flex-1 truncate text-[var(--as-fg)]">
                {row.document.filename}
              </span>
              <StatusChip row={row} />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
