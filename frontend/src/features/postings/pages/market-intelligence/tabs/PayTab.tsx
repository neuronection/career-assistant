import { SalaryCard } from "../cards";
import type { TabProps } from "./shared";

export function PayTab({ data, view, loading, compact, refresh, onDrill }: TabProps) {
  return (
    <SalaryCard
      salary={data.salary}
      loading={loading}
      error={data.errors.salary ?? null}
      onRetry={refresh}
      onBucket={(floor) => onDrill(`salary_min=${Math.round(floor)}`)}
      compact={compact}
      windowName={view.window}
    />
  );
}
