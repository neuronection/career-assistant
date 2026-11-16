import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { fetchParseView } from "@/api/cv";
import { apiDetail } from "@/api/client";
import { Badge, EmptyState, Modal, ModalContent, ModalHeader, ModalTitle } from "@/components/ui";
import { CopyButton } from "@/components/ui/copy-button";
import type { CvParseViewFinding, CvParseViewOut } from "@/types/cv";

const FINDING_VARIANT: Record<CvParseViewFinding["level"], "success" | "warning" | "danger"> = {
  info: "success",
  warn: "warning",
  fail: "danger",
};

/**
 * "What a parser sees" (plan 212 S1.2): the raw text our extractor
 * reads from the printed PDF plus its deterministic findings. Read-only;
 * the disclaimer is part of the contract — this is our extractor, never
 * a vendor simulation, and there is no score anywhere on this surface.
 */
export function ParseViewDialog({
  cvId,
  open,
  onOpenChange,
}: {
  cvId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const [view, setView] = useState<CvParseViewOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    if (!open) return;
    setBusy(true);
    setError("");
    void fetchParseView(cvId)
      .then((next) => {
        setView(next);
        setBusy(false);
      })
      .catch((err) => {
        setError(apiDetail(err));
        setBusy(false);
      });
  }, [cvId, open]);

  useEffect(() => {
    if (open) load();
    else setView(null);
  }, [load, open]);

  const allText = (view?.pages ?? []).map((page) => page.text).join("\n\n");

  return (
    <Modal open={open} onOpenChange={(next) => !next && onOpenChange(false)}>
      <ModalContent size="xl" className="w-[min(880px,96vw)]" aria-describedby={undefined}>
        <ModalHeader>
          <ModalTitle>{t("cvBuilder.parseView.title")}</ModalTitle>
          <p className="text-xs text-[var(--as-muted-fg)]" data-testid="parse-view-disclaimer">
            {t("cvBuilder.parseView.disclaimer")}
          </p>
        </ModalHeader>
        <div className="space-y-3" data-testid="parse-view-body">
          {busy && <p className="text-sm text-[var(--as-muted-fg)]">{t("cvBuilder.parseView.loading")}</p>}
          {error && (
            <p role="alert" className="text-sm text-red-700" data-testid="parse-view-error">
              {error}
            </p>
          )}
          {!busy && !error && view && (
            <>
              <div className="flex flex-wrap items-center gap-2" data-testid="parse-view-facts">
                <Badge variant="outline">{t("cvBuilder.parseView.engine", { engine: view.engine })}</Badge>
                <Badge variant={view.text_layer ? "success" : "danger"} data-testid="parse-view-text-layer">
                  {view.text_layer
                    ? t("cvBuilder.parseView.textLayerOk")
                    : t("cvBuilder.parseView.textLayerMissing")}
                </Badge>
                <span className="text-xs text-[var(--as-muted-fg)]">
                  {t("cvBuilder.parseView.pageCount", { count: view.page_count })}
                </span>
                <span className="flex-1" aria-hidden />
                <CopyButton value={allText} label={t("cvBuilder.parseView.copy")} />
              </div>
              {view.findings.length > 0 ? (
                <ul className="space-y-1.5" data-testid="parse-view-findings">
                  {view.findings.map((finding) => (
                    <li
                      key={finding.id}
                      className="flex items-start gap-2 text-sm"
                      data-testid={`parse-view-finding-${finding.id}`}
                    >
                      <Badge variant={FINDING_VARIANT[finding.level]}>{finding.level}</Badge>
                      <span className="min-w-0 text-[var(--as-fg)]">{finding.message}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState title={t("cvBuilder.parseView.noFindings")} />
              )}
              {view.pages.map((page) => (
                <div key={page.index} className="space-y-1">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                    {t("cvBuilder.parseView.pageHeading", {
                      number: page.index + 1,
                      lines: page.line_count,
                    })}
                  </p>
                  <pre
                    className="max-h-64 overflow-auto whitespace-pre-wrap rounded border border-[var(--as-border)] bg-[var(--as-muted)] p-2 font-mono text-xs text-[var(--as-fg)]"
                    data-testid={`parse-view-page-${page.index}`}
                  >
                    {page.text || t("cvBuilder.parseView.emptyPage")}
                  </pre>
                </div>
              ))}
            </>
          )}
        </div>
      </ModalContent>
    </Modal>
  );
}
