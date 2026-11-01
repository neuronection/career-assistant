import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Bot } from "lucide-react";

import { fetchRunDetail } from "@/api/autopilot";
import { Spinner } from "@/components/ui";
import { RunDetail } from "@/features/growth/components/RunDetail";

export function AutopilotRunPage() {
  const { t } = useTranslation();
  const { runId } = useParams();
  const [detail, setDetail] = useState<Awaited<ReturnType<typeof fetchRunDetail>> | null>(
    null
  );
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let live = true;
    setDetail(null);
    setMissing(false);
    if (!runId) {
      setMissing(true);
      return () => {
        live = false;
      };
    }
    fetchRunDetail(runId)
      .then((result) => {
        if (live) setDetail(result);
      })
      .catch(() => {
        if (live) setMissing(true);
      });
    return () => {
      live = false;
    };
  }, [runId]);

  return (
    <div className="ca-stats-page mx-auto max-w-5xl space-y-4" data-testid="autopilot-run-page">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
          <Bot className="h-6 w-6 text-primary-600" /> {t("autopilot.runDetail.title")}
        </h1>
        <Link
          to="/autopilot"
          className="flex items-center gap-1 text-sm text-[var(--as-accent)] hover:underline"
          data-testid="run-page-back"
        >
          <ArrowLeft className="h-4 w-4" /> {t("autopilot.runDetail.backToFeed")}
        </Link>
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
    </div>
  );
}
