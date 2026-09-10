import { useTranslation } from "react-i18next";
import { FlowStatusCard, type FlowStepStatus } from "@/components/ui";
import type { BackgroundJob } from "@/api/backgroundJobs";

/** Map a polled background job onto the family flow-status card
 *. */
export function JobFlowStatus({
  job,
  title,
  testId,
}: {
  job: BackgroundJob;
  title: string;
  testId?: string;
}) {
  const { t } = useTranslation();
  const status: FlowStepStatus =
    job.status === "succeeded"
      ? "done"
      : job.status === "failed" || job.status === "cancelled"
        ? "failed"
        : "running";
  return (
    <div data-testid={testId}>
      <FlowStatusCard
        title={title}
        status={status}
        steps={[
          {
            id: "run",
            label: job.stage ?? t("shared.queued"),
            status,
          },
        ]}
        detail={<span className="text-xs tabular-nums">{job.progress}%</span>}
      />
    </div>
  );
}
