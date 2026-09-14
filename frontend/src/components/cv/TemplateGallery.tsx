import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, GitCompare, Pencil, Sparkles, X } from "lucide-react";
import { Button, Card, Modal, ModalContent, ModalHeader, ModalTitle } from "@/components/ui";
import { apiDetail } from "@/api/client";
import {
  draftTemplateAi,
  fetchTemplatePreview,
  fetchTemplatePreviewWith,
  fetchTemplates,
  type PreviewMetrics,
} from "@/api/cvTemplates";
import type { CvTemplateSummary } from "@/types/cvTemplate";

type GalleryFilter = "all" | "sidebar" | "single" | "one-page" | "ats-safe";

const FILTERS: { value: GalleryFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "sidebar", label: "Two-column" },
  { value: "single", label: "Single" },
  { value: "one-page", label: "One page" },
  { value: "ats-safe", label: "ATS-safe" },
];

export function galleryFilter(template: CvTemplateSummary, filter: GalleryFilter): boolean {
  const design = (template.content?.design ?? {}) as Record<string, unknown>;
  const pages = template.content?.pages ?? {};
  if (filter === "sidebar") return design["layout"] === "sidebar";
  if (filter === "single") return design["layout"] !== "sidebar";
  if (filter === "one-page") return pages["default_max_pages"] === 1;
  if (filter === "ats-safe") return template.ats_safe;
  return true;
}

function OwnSnapshotPreviewFrame({
  template,
  cvId,
}: {
  template: CvTemplateSummary;
  cvId?: string | null;
}) {
  const [html, setHtml] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<PreviewMetrics | null>(null);
  const [failed, setFailed] = useState(false);
  const aspect =
    template.page_size === "letter" ? "aspect-[216/279]" : "aspect-[210/297]";

  useEffect(() => {
    let cancelled = false;
    setHtml(null);
    setMetrics(null);
    setFailed(false);
    fetchTemplatePreviewWith(template.id, cvId || null)
      .then((value) => {
        if (cancelled) return;
        setHtml(value.html);
        setMetrics(value.metrics ?? null);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [template.id, cvId]);

  return (
    <div className="relative">
      {failed ? (
        <div className={`flex ${aspect} w-full items-center justify-center border-b bg-white text-xs text-[var(--as-muted-fg)]`}>
          Preview unavailable
        </div>
      ) : html === null ? (
        <div className={`${aspect} w-full cv-shimmer border-b bg-[var(--as-muted)]`} />
      ) : (
        <iframe
          title={`Preview of ${template.title} with your data`}
          srcDoc={html}
          sandbox=""
          loading="lazy"
          scrolling="no"
          style={{ pointerEvents: "none" }}
          className={`${aspect} w-full overflow-hidden border-b bg-white`}
        />
      )}
      {metrics && metrics.estimated_pages != null && (
        <span
          data-testid="compare-metrics"
          className={`absolute bottom-2 left-2 rounded-full px-2 py-0.5 text-[10px] font-medium shadow ${
            metrics.overflow
              ? "bg-amber-100 text-amber-800"
              : "bg-emerald-100 text-emerald-800"
          }`}
        >
          ~{metrics.estimated_pages} page{metrics.estimated_pages === 1 ? "" : "s"}
          {metrics.overflow ? " · over budget" : " · fits"}
        </span>
      )}
    </div>
  );
}

export function TemplatePreviewFrame({ template }: { template: CvTemplateSummary }) {
  const [html, setHtml] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const aspect =
    template.page_size === "letter" ? "aspect-[216/279]" : "aspect-[210/297]";

  useEffect(() => {
    let cancelled = false;
    setHtml(null);
    setFailed(false);
    fetchTemplatePreview(template.id)
      .then((value) => {
        if (!cancelled) setHtml(value);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [template.id]);

  if (failed) {
    return (
      <div className={`flex ${aspect} w-full items-center justify-center border-b bg-white text-xs text-[var(--as-muted-fg)]`}>
        Preview unavailable
      </div>
    );
  }
  if (html === null) {
    return <div className={`${aspect} w-full cv-shimmer border-b bg-[var(--as-muted)]`} />;
  }
  return (
    <iframe
      title={`Preview of ${template.title}`}
      srcDoc={html}
      sandbox=""
      loading="lazy"
      scrolling="no"
      style={{ pointerEvents: "none" }}
      className={`${aspect} w-full overflow-hidden border-b bg-white`}
    />
  );
}

function TemplateCard({
  template,
  current,
  actionLabel,
  onUse,
  onCustomize,
  compareSelected,
  onToggleCompare,
}: {
  template: CvTemplateSummary;
  current: boolean;
  actionLabel: string;
  onUse: () => void;
  onCustomize: () => void;
  compareSelected: boolean;
  onToggleCompare: () => void;
}) {
  const isBank = template.author_key === "bank";
  return (
    <Card
      className={`group relative overflow-hidden p-0 transition-all duration-150 ${
        current
          ? "border-2 border-[var(--as-accent)] shadow-sm"
          : "hover:-translate-y-0.5 hover:border-[var(--as-accent)] hover:shadow-md"
      }`}
      data-testid="template-card"
    >
      <div className="relative space-y-2">
        <div className="relative" data-testid={`preview-template-${template.id}`}>
          <TemplatePreviewFrame template={template} />
          <button
            type="button"
            onClick={onUse}
            disabled={current}
            aria-label={current ? `${template.title} (current template)` : `Use ${template.title}`}
            title={current ? "Current template" : `Use ${template.title}`}
            className="absolute inset-0 z-10 cursor-pointer"
            data-testid={`use-template-${template.id}`}
          />
          {current && (
            <span className="absolute left-2 top-2 inline-flex items-center gap-1 rounded-full bg-[var(--as-accent)] px-2 py-0.5 text-[10px] font-semibold text-white shadow-sm">
              <Check className="h-3 w-3" aria-hidden /> Current
            </span>
          )}
          {!current && (
            <span className="pointer-events-none absolute inset-0 hidden items-center justify-center bg-black/25 group-hover:flex">
              <span className="rounded-full bg-[var(--as-surface-raised)] px-4 py-1.5 text-xs font-semibold text-[var(--as-fg)] shadow-md">
                {actionLabel}
              </span>
            </span>
          )}
        </div>
        <div className="space-y-2 p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="truncate font-medium text-[var(--as-fg)]">{template.title}</p>
            <span className="flex shrink-0 gap-1 text-[10px] uppercase">
              <span className="rounded bg-[var(--as-muted)] px-1.5 py-0.5 text-[var(--as-muted-fg)]">
                {template.source}
              </span>
              <span
                className={`rounded px-1.5 py-0.5 ${
                  template.ats_safe
                    ? "bg-emerald-100 text-emerald-800"
                    : "bg-amber-100 text-amber-800"
                }`}
              >
                {template.ats_safe ? "ATS-safe" : "decorative"}
              </span>
            </span>
          </div>
          {template.description && (
            <p className="line-clamp-2 text-xs text-[var(--as-muted-fg)]">{template.description}</p>
          )}
          <div className="flex items-center justify-between gap-2">
            <Button
              variant="outline"
              size="sm"
              aria-pressed={compareSelected}
              data-testid={`compare-template-${template.id}`}
              onClick={onToggleCompare}
              title="Add to template comparison"
            >
              <GitCompare className={`mr-1 h-3 w-3 ${compareSelected ? "" : "opacity-60"}`} aria-hidden />
              {compareSelected ? "Selected" : "Compare"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              data-testid={`edit-template-${template.id}`}
              onClick={onCustomize}
              title={isBank ? "Customize a copy of this bank template" : "Customize this template"}
            >
              <Pencil className="mr-1 h-3 w-3" aria-hidden />
              Customize
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
}

interface TemplateGalleryProps {
  open: boolean;
  onClose: () => void;
  actionLabel: string;
  currentTemplateId?: string | null;
  cvId?: string | null;
  onUse: (template: CvTemplateSummary) => void;
}

export function TemplateGallery({
  open,
  onClose,
  actionLabel,
  currentTemplateId,
  cvId,
  onUse,
}: TemplateGalleryProps) {
  const navigate = useNavigate();
  const [templates, setTemplates] = useState<CvTemplateSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<GalleryFilter>("all");
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [compareOpen, setCompareOpen] = useState(false);
  const [draftBrief, setDraftBrief] = useState("");
  const [drafting, setDrafting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setTemplates(await fetchTemplates());
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      void load();
    } else {
      setCompareIds([]);
      setCompareOpen(false);
      setFilter("all");
    }
  }, [open, load]);

  async function handleDraft() {
    if (!draftBrief.trim()) return;
    setDrafting(true);
    setError("");
    try {
      const template = await draftTemplateAi(draftBrief.trim());
      setTemplates((rows) => [template, ...rows]);
      setDraftBrief("");
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setDrafting(false);
    }
  }

  function toggleCompare(id: string) {
    setCompareIds((current) => {
      if (current.includes(id)) return current.filter((item) => item !== id);
      return [...current, id].slice(-2);
    });
  }

  const compared = templates.filter((template) => compareIds.includes(template.id));
  const visible = templates.filter((template) => galleryFilter(template, filter));

  return (
    <Modal open={open} onOpenChange={(next) => !next && onClose()}>
      <ModalContent
        size="xl"
        className="w-[96vw] max-w-[min(1600px,96vw)]"
        aria-describedby={undefined}
      >
        <ModalHeader>
          <div className="flex w-full items-center justify-between pr-6">
            <ModalTitle>
              CV templates
              {templates.length > 0 && (
                <span className="ml-2 text-xs font-normal text-[var(--as-muted-fg)]">
                  {templates.length} available
                </span>
              )}
            </ModalTitle>
          </div>
        </ModalHeader>
        <div className="max-h-[82vh] space-y-4 overflow-y-auto p-4 pt-0">
          <div className="flex flex-wrap gap-1.5" data-testid="gallery-filters">
            {FILTERS.map((item) => (
              <button
                key={item.value}
                type="button"
                aria-pressed={filter === item.value}
                data-testid={`gallery-filter-${item.value}`}
                onClick={() => setFilter(item.value)}
                className={`cursor-pointer rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                  filter === item.value
                    ? "border-[var(--as-accent)] bg-[var(--as-accent)] text-white"
                    : "border-[var(--as-border)] text-[var(--as-muted-fg)] hover:border-[var(--as-accent)] hover:text-[var(--as-fg)]"
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>

          {compared.length > 0 && (
            <div className="flex items-center justify-between rounded-lg border border-[var(--as-border)] bg-[var(--as-muted)] p-2" data-testid="compare-tray">
              <p className="pl-1 text-xs text-[var(--as-muted-fg)]">
                {compared.length === 2
                  ? "Two templates selected"
                  : "Pick one more template to compare"}
              </p>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  disabled={compared.length !== 2}
                  data-testid="compare-open"
                  onClick={() => setCompareOpen(true)}
                >
                  <GitCompare className="mr-1 h-3 w-3" aria-hidden />
                  Compare preview
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  aria-label="Clear template comparison"
                  data-testid="compare-clear"
                  onClick={() => setCompareIds([])}
                >
                  <X className="h-3 w-3" aria-hidden />
                </Button>
              </div>
            </div>
          )}

          <div className="flex gap-2" data-testid="ai-template-draft">
            <input
              value={draftBrief}
              onChange={(event) => setDraftBrief(event.target.value)}
              placeholder="Describe a style: “serif, teal accent, roomy, two-page allowed”"
              className="flex-1 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-sm outline-none transition-colors focus:border-[var(--as-accent)]"
              data-testid="template-brief"
            />
            <Button
              variant="outline"
              onClick={handleDraft}
              disabled={drafting || !draftBrief.trim()}
            >
              <Sparkles className="mr-1 h-4 w-4" aria-hidden />
              {drafting ? "Drafting…" : "Draft with AI"}
            </Button>
          </div>

          {error && (
            <p role="alert" className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700">
              {error}
            </p>
          )}

          {loading ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {[0, 1, 2].map((index) => (
                <Card key={index} className="overflow-hidden p-0">
                  <div className="aspect-[210/297] w-full cv-shimmer" />
                  <div className="space-y-2 p-3">
                    <div className="cv-shimmer h-4 w-2/3 rounded" />
                    <div className="cv-shimmer h-3 w-full rounded" />
                  </div>
                </Card>
              ))}
            </div>
          ) : visible.length === 0 ? (
            <p className="text-sm text-[var(--as-muted-fg)]">
              No templates match this filter.
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3" data-testid="gallery-grid">
              {visible.map((template) => (
                <TemplateCard
                  key={template.id}
                  template={template}
                  current={currentTemplateId === template.id}
                  actionLabel={actionLabel}
                  compareSelected={compareIds.includes(template.id)}
                  onToggleCompare={() => toggleCompare(template.id)}
                  onUse={() => {
                    onUse(template);
                    onClose();
                  }}
                  onCustomize={() => navigate(`/cv/templates/${template.id}`)}
                />
              ))}
            </div>
          )}
        </div>
      </ModalContent>

      <Modal open={compareOpen} onOpenChange={(next) => !next && setCompareOpen(false)}>
        <ModalContent
          size="xl"
          className="w-[96vw] max-w-[min(1600px,96vw)]"
          aria-describedby={undefined}
        >
          <ModalHeader>
            <ModalTitle>Template comparison · your data</ModalTitle>
          </ModalHeader>
          <div
            className="max-h-[82vh] overflow-y-auto p-4 pt-0"
            data-testid="compare-grid"
          >
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {compared.map((template) => (
                <div key={template.id} className="space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate font-medium text-[var(--as-fg)]">{template.title}</p>
                    <Button
                      size="sm"
                      data-testid={`compare-use-${template.id}`}
                      onClick={() => {
                        onUse(template);
                        setCompareOpen(false);
                        onClose();
                      }}
                    >
                      <Check className="mr-1 h-3 w-3" aria-hidden />
                      Use
                    </Button>
                  </div>
                  <OwnSnapshotPreviewFrame template={template} cvId={cvId} />
                </div>
              ))}
            </div>
          </div>
        </ModalContent>
      </Modal>
    </Modal>
  );
}
