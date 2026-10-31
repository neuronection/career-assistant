import { Download } from "lucide-react";

import { downloadStatsCsv, type CsvRows } from "../statsExport";

/** One card's CSV export affordance (plan 170 slice 4): a quiet icon
 * button for the `ChartCard` actions slot that downloads that card's
 * data rows. */
export function ChartExport({
  name,
  rows,
  title,
  testId,
}: {
  name: string;
  rows: CsvRows;
  title: string;
  testId: string;
}) {
  return (
    <button
      type="button"
      onClick={() => downloadStatsCsv(name, rows)}
      className="inline-flex items-center gap-1 rounded-full border border-[var(--as-border)] px-2 py-1 text-xs font-medium text-[var(--as-muted-fg)]"
      data-testid={testId}
      title={title}
    >
      <Download className="size-3" aria-hidden />
      {title}
    </button>
  );
}
