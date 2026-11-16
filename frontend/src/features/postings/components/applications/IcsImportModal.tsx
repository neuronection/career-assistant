import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ImportReviewCard } from "@neuronection/assistant-ui/import-review-card";

import { Button, Modal, ModalContent } from "@/components/ui";
import { apiDetail } from "@/api/client";
import {
  importApplicationsIcs,
  type IcsImportReport,
} from "@/api/applications";

export function IcsImportModal({
  open,
  onClose,
  onApplied,
}: {
  open: boolean;
  onClose: () => void;
  onApplied: () => void;
}) {
  const { t } = useTranslation();
  const [ics, setIcs] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [report, setReport] = useState<IcsImportReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const reset = () => {
    setIcs("");
    setFileName(null);
    setReport(null);
    setError("");
  };

  const choose = async (file: File) => {
    setBusy(true);
    setError("");
    setFileName(file.name);
    try {
      const text = await file.text();
      setIcs(text);
      setReport(await importApplicationsIcs(text));
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!ics) return;
    setBusy(true);
    setError("");
    try {
      const result = await importApplicationsIcs(ics, true);
      setReport(result);
      onApplied();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          reset();
          onClose();
        }
      }}
    >
      <ModalContent
        size="lg"
        data-testid="ics-import-modal"
        aria-label={t("icsImport.title")}
        aria-describedby={undefined}
      >
        <ImportReviewCard
          title={t("icsImport.title")}
          description={t("icsImport.intro")}
          accept="text/calendar,.ics"
          fileName={fileName}
          status={busy ? "loading" : error ? "error" : report ? "preview" : "idle"}
          report={
            report
              ? {
                  groups: [
                    { label: t("icsImport.events"), count: report.proposals.length },
                  ],
                  warnings: report.warnings,
                  applied: report.applied,
                  created: report.created,
                }
              : null
          }
          error={error || null}
          busy={busy}
          labels={{
            choose: t("icsImport.choose"),
            apply: t("icsImport.apply"),
            applied: t("icsImport.applied", { count: report?.created ?? 0 }),
            drop: t("icsImport.drop"),
            warnings: t("icsImport.warnings"),
            conflicts: t("icsImport.conflicts"),
            mapped: t("icsImport.events"),
            created: t("icsImport.created"),
          }}
          onFileSelected={(file) => void choose(file)}
          onApply={() => void apply()}
          onReset={reset}
        />

        {report !== null && report.proposals.length > 0 && (
          <ul className="mt-3 space-y-1" data-testid="ics-report">
            {report.proposals.map((proposal) => (
              <li
                key={`${proposal.uid}-${proposal.start}`}
                className="rounded border border-[var(--as-border)] p-2 text-xs"
                data-testid={`ics-proposal-${proposal.uid}`}
              >
                <p className="font-medium text-[var(--as-fg)]">{proposal.summary}</p>
                <p className="text-[var(--as-muted-fg)]">
                  {proposal.all_day
                    ? new Date(proposal.start).toLocaleDateString(undefined, {
                        timeZone: "UTC",
                      })
                    : new Date(proposal.start).toLocaleString()}
                  {proposal.all_day ? ` · ${t("icsImport.allDay")}` : ""}
                </p>
                <p className="text-[var(--as-muted-fg)]">
                  {proposal.application_label || t("icsImport.unmatched")}
                  {proposal.duplicate ? ` · ${t("icsImport.duplicate")}` : ""}
                </p>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-3 flex justify-end">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t("common.close")}
          </Button>
        </div>
      </ModalContent>
    </Modal>
  );
}
