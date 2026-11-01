import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Bot, EyeOff } from "lucide-react";

import { dismissRunFindings, fetchRunDetail } from "@/api/autopilot";
import { Button, ConfirmationModal, Spinner } from "@/components/ui";
import { RunDetail } from "@/features/growth/components/RunDetail";

export function AutopilotRunPage() {
  const { t } = useTranslation();
  const { runId } = useParams();
  const [detail, setDetail] = useState<Awaited<ReturnType<typeof fetchRunDetail>> | null>(
    null
  );
  const [missing, setMissing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    if (!runId) {
      setMissing(true);
      return;
    }
    setMissing(false);
    fetchRunDetail(runId)
      .then(setDetail)
      .catch(() => setMissing(true));
  }, [runId]);

  useEffect(load, [load]);

  const dismissAll = async () => {
    if (!runId) return;
    setBusy(true);
    try {
      await dismissRunFindings(runId);
      load();
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  };

  const openFindings = detail?.findings.some((f) => f.dismissed_at == null) ?? false;

  return (
    <div
      className="ca-stats-page mx-auto max-w-5xl space-y-4"
      data-testid="autopilot-run-page"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
          <Bot className="h-6 w-6 text-primary-600" /> {t("autopilot.runDetail.title")}
        </h1>
        <div className="flex items-center gap-2">
          {detail && openFindings ? (
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => setConfirming(true)}
              data-testid="run-dismiss-all"
            >
              <EyeOff className="mr-1 h-4 w-4" />
              {t("autopilot.runDetail.dismissAll")}
            </Button>
          ) : null}
          <Link
            to="/autopilot"
            className="flex items-center gap-1 text-sm text-[var(--as-accent)] hover:underline"
            data-testid="run-page-back"
          >
            <ArrowLeft className="h-4 w-4" /> {t("autopilot.runDetail.backToFeed")}
          </Link>
        </div>
      </div>

      {missing ? (
        <p className="text-sm text-[var(--as-muted-fg)]" data-testid="run-detail-missing">
          {t("autopilot.runDetail.missing")}
        </p>
      ) : detail === null ? (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      ) : (
        <RunDetail
          detail={detail}
          findingsFeedHref={`/autopilot?run_id=${detail.run.id}`}
        />
      )}

      {confirming && (
        <ConfirmationModal
          open
          title={t("autopilot.runDetail.dismissAllTitle")}
          description={t("autopilot.runDetail.dismissAllBody")}
          confirmLabel={t("autopilot.runDetail.dismissAll")}
          onConfirm={() => void dismissAll()}
          onOpenChange={(open) => (open ? undefined : setConfirming(false))}
        />
      )}
    </div>
  );
}
