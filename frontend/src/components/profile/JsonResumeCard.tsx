import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Download } from "lucide-react";
import { ImportReviewCard } from "@neuronection/assistant-ui/import-review-card";

import { Button } from "@/components/ui";
import { apiDetail } from "@/api/client";
import {
  exportJsonResume,
  importJsonResume,
  type JsonResumeReport,
} from "@/api/jsonResume";

export function JsonResumeCard() {
  const { t } = useTranslation();
  const [resume, setResume] = useState<Record<string, unknown> | null>(null);
  const [report, setReport] = useState<JsonResumeReport | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const download = async () => {
    setBusy(true);
    setError("");
    try {
      const data = await exportJsonResume();
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "career-assistant-resume.json";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const preview = async (file: File) => {
    setBusy(true);
    setError("");
    setReport(null);
    setFileName(file.name);
    try {
      const parsed = JSON.parse(await file.text()) as Record<string, unknown>;
      const result = await importJsonResume(parsed);
      setResume(parsed);
      setReport(result);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (resume === null) return;
    setBusy(true);
    setError("");
    try {
      const result = await importJsonResume(resume, true);
      setReport(result);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    setResume(null);
    setReport(null);
    setFileName(null);
    setError("");
  };

  return (
    <section className="space-y-2" data-testid="json-resume-card">
      <div className="flex justify-end">
        <Button
          variant="outline"
          size="sm"
          onClick={() => void download()}
          disabled={busy}
          data-testid="json-resume-export"
        >
          <Download className="mr-1 size-3.5" aria-hidden />
          {t("jsonResume.export")}
        </Button>
      </div>
      <ImportReviewCard
        title={t("jsonResume.title")}
        description={t("jsonResume.intro")}
        accept="application/json,.json"
        fileName={fileName}
        status={
          busy ? "loading" : error ? "error" : report ? "preview" : "idle"
        }
        report={
          report
            ? {
                groups: [
                  {
                    label: t("jsonResume.basics"),
                    count: Object.keys(report.mapped.basics).length,
                  },
                  { label: t("jsonResume.work"), count: report.mapped.work.length },
                  {
                    label: t("jsonResume.education"),
                    count: report.mapped.education.length,
                  },
                ],
                dropped: report.dropped,
                warnings: report.warnings,
                conflicts: report.basics_conflicts.map((row) => ({
                  field: row.field,
                  current: String(row.current),
                  incoming: String(row.incoming),
                })),
                applied: report.applied,
                created:
                  report.created.work + report.created.education,
              }
            : null
        }
        error={error || null}
        busy={busy}
        labels={{
          choose: t("jsonResume.choose"),
          apply: t("jsonResume.apply"),
          applied: t("jsonResume.applied"),
          drop: t("jsonResume.droppedLabel"),
          warnings: t("jsonResume.warnings"),
          conflicts: t("jsonResume.conflicts"),
          mapped: t("jsonResume.mapped"),
          created: t("jsonResume.created"),
        }}
        onFileSelected={(file) => void preview(file)}
        onApply={() => void apply()}
        onReset={reset}
      />
      {report?.applied && (
        <p className="text-sm text-[var(--as-success)]" data-testid="json-resume-done">
          {t("jsonResume.done")}
        </p>
      )}
    </section>
  );
}
