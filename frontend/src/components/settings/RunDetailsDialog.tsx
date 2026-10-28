import { useTranslation } from "react-i18next";

import { Button, Modal, ModalContent, ModalFooter, ModalHeader, ModalTitle } from "@/components/ui";
import { CopyButton } from "@/components/ui/copy-button";
import { RunSummaryStrip } from "@/components/settings/RunSummaryStrip";
import type { SourceRun } from "@/api/sources";

/**
 * Full run details (plan 134 UX): the untruncated error plus the typed
 * error rows from the run report — with a copy button — because the
 * history table shows at most three lines of the error.
 */

export function RunDetailsDialog({
  run,
  onClose,
}: {
  run: SourceRun;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const reportErrors = (run.report?.errors ?? []) as { code?: string; detail?: unknown }[];
  const copyValue = [run.error, ...reportErrors.map((entry) => JSON.stringify(entry))]
    .filter(Boolean)
    .join("\n");

  return (
    <Modal open onOpenChange={onClose}>
      <ModalContent size="md" closeLabel={t("sourceDetail.runDetailsClose")}>
        <ModalHeader>
          <ModalTitle>
            {t("sourceDetail.runDetailsTitle", { time: new Date(run.started_at ?? "").toLocaleString() })}
          </ModalTitle>
        </ModalHeader>
        <div className="space-y-4 px-6 pb-6" data-testid="run-details">
          <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs font-medium text-[var(--as-muted-fg)]">
                {t("sourceDetail.runStatus")}
              </dt>
              <dd>{run.status}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-[var(--as-muted-fg)]">
                {t("sourceDetail.runTrigger")}
              </dt>
              <dd>{run.trigger}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-[var(--as-muted-fg)]">
                {t("sourceDetail.runDuration")}
              </dt>
              <dd>{run.duration_ms} ms</dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-[var(--as-muted-fg)]">
                {t("sourceDetail.runItems")}
              </dt>
              <dd>{run.items_synced}</dd>
            </div>
          </dl>
          {run.report?.run_summary ? <RunSummaryStrip summary={run.report.run_summary} /> : null}
          {run.error ? (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <p className="text-xs font-medium text-[var(--as-fg)]">
                  {t("sourceDetail.runError")}
                </p>
                <CopyButton value={copyValue} label={t("sourceDetail.copy")} />
              </div>
              <pre
                className="max-h-64 overflow-y-auto whitespace-pre-wrap break-words rounded-[var(--as-radius-sm)] border border-[var(--as-border)] bg-[var(--as-surface)] p-3 text-xs"
                data-testid="run-details-error"
              >
                {run.error}
              </pre>
            </div>
          ) : null}
          {reportErrors.length > 0 ? (
            <div className="space-y-2">
              <p className="text-xs font-medium text-[var(--as-fg)]">
                {t("sourceDetail.runReportErrors")}
              </p>
              <ul className="space-y-1">
                {reportErrors.map((entry, index) => (
                  <li
                    key={index}
                    className="rounded-[var(--as-radius-sm)] border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-xs"
                  >
                    <span className="font-medium">{entry.code}</span>{" "}
                    {typeof entry.detail === "string"
                      ? entry.detail
                      : ((entry.detail as { message?: string } | null)?.message ?? "")}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
        <ModalFooter>
          <Button size="sm" variant="outline" onClick={onClose}>
            {t("sourceDetail.runDetailsClose")}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
