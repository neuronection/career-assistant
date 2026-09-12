import { useTranslation } from "react-i18next";
import type { CvPolishTrace, CvVersionOut } from "@/types/cv";

type Trace = NonNullable<CvPolishTrace>;
type Iteration = NonNullable<Trace["iterations"]>[number];

function issuesOf(
  iteration: Iteration,
  ...levels: Array<"fail" | "warn" | "info">
): NonNullable<Iteration["issues"]> {
  return (iteration.issues ?? []).filter((issue) => levels.includes(issue.level));
}

function opEntriesOf(iteration: Iteration, ok: boolean): Iteration["ops"] {
  return (iteration.ops ?? []).filter((entry) => Boolean(entry.ok) === ok);
}

function missingLabels(iteration: Iteration): string[] {
  return (iteration.coverage?.missing ?? []).map(
    (ref) => ref.label || ref.item_id,
  );
}

/** One polish trace (issues/ops/coverage per iteration), severity-grouped
 * into Errors/Warnings/Info, with the user's prompt on top (§0.10–11).
 * Serves the builder's review-log card (trace from the final version's
 * payload); the live progress card uses PolishTimeline + the preview. */
export function PolishTraceCard({ version }: { version?: CvVersionOut }) {
  const { t } = useTranslation();
  const trace = (version?.content as { polish?: CvPolishTrace } | undefined)?.polish;
  if (!trace?.iterations?.length) return null;
  return (
    <div
      className="space-y-3 rounded-lg border border-[var(--as-border)] p-3"
      data-testid="polish-trace-card"
    >
      <PolishRequestPanel trace={trace} />
      {trace.outcome && (
        <p className="text-xs text-[var(--as-muted-fg)]" data-testid="polish-outcome">
          {t(`cvGenerate.polishOutcome.${trace.outcome.status}`, {
            defaultValue: trace.outcome.status,
          })}
        </p>
      )}
      {trace.iterations.map((iteration) => (
        <div className="space-y-1" data-testid="polish-iteration" key={iteration.n}>
          <p className="text-xs font-medium">
            {t("cvGenerate.polish.iteration", { n: iteration.n + 1 })}
            {iteration.summary ? ` — ${iteration.summary}` : ""}
          </p>
          <IssueList
            label={t("cvGenerate.polish.errors")}
            issues={issuesOf(iteration, "fail")}
          />
          <IssueList
            label={t("cvGenerate.polish.warnings")}
            issues={issuesOf(iteration, "warn", "info")}
          />
          <OpsList
            label={t("cvGenerate.polish.appliedOps")}
            entries={opEntriesOf(iteration, true)}
          />
          <RejectedOps entries={opEntriesOf(iteration, false)} />
          <CoverageDrops labels={missingLabels(iteration)} />
        </div>
      ))}
    </div>
  );
}

function PolishRequestPanel({ trace }: { trace: Trace }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-1" data-testid="polish-request">
      <p className="text-xs font-medium">{t("cvGenerate.request.title")}</p>
      {trace.request?.notes && (
        <p className="text-xs text-[var(--as-muted-fg)]">“{trace.request.notes}”</p>
      )}
      <p className="text-xs text-[var(--as-muted-fg)]">
        {t("cvGenerate.request.meta", {
          length: trace.request?.length || "standard",
          language: trace.request?.language || "en",
          maxPages: trace.request?.max_pages ?? 1,
        })}
      </p>
    </div>
  );
}

function IssueList({
  label,
  issues,
}: {
  label: string;
  issues: NonNullable<Iteration["issues"]>;
}) {
  if (issues.length === 0) return null;
  return (
    <div>
      <p className="text-xs font-medium text-amber-700">{label}</p>
      <ul className="list-inside list-disc text-xs text-[var(--as-muted-fg)]">
        {issues.map((issue, index) => (
          <li key={index}>{issue.message}</li>
        ))}
      </ul>
    </div>
  );
}

function OpsList({
  label,
  entries,
}: {
  label: string;
  entries: Iteration["ops"];
}) {
  if (!entries || entries.length === 0) return null;
  return (
    <div>
      <p className="text-xs font-medium">{label}</p>
      <ul className="list-inside list-disc text-xs text-[var(--as-muted-fg)]">
        {entries.map((entry, index) => (
          <li key={index}>{entry.detail || entry.op}</li>
        ))}
      </ul>
    </div>
  );
}

function RejectedOps({ entries }: { entries: Iteration["ops"] }) {
  const { t } = useTranslation();
  if (!entries || entries.length === 0) return null;
  return (
    <ul className="list-inside list-disc text-xs text-red-700">
      {entries.map((entry, index) => (
        <li key={index}>
          {t("cvGenerate.polish.opRejected", {
            op: entry.op,
            detail: entry.detail ?? "",
          })}
        </li>
      ))}
    </ul>
  );
}

function CoverageDrops({ labels }: { labels: string[] }) {
  const { t } = useTranslation();
  if (labels.length === 0) return null;
  return (
    <p className="text-xs text-amber-700">
      {t("cvGenerate.polish.coverageDrops", { items: labels.join(", ") })}
    </p>
  );
}

/** Live preview iframe over the committed working state (plan 64.5). */
export function PolishPreviewIframe({
  html,
  title,
  testId,
  fill = false,
}: {
  html: string;
  title: string;
  testId?: string;
  /** "fill" = full-height scroll pane (the progress modal's preview
   * column); the default keeps the A4 aspect-ratio page look. */
  fill?: boolean;
}) {
  if (!html) return null;
  if (!fill) {
    return (
      <iframe
        title={title}
        srcDoc={html}
        sandbox=""
        className="w-full rounded-lg border border-[var(--as-border)] bg-white"
        style={{ aspectRatio: "210mm / 297mm" }}
        data-testid={testId}
      />
    );
  }
  return (
    <div
      className="flex h-full min-h-0 w-full justify-center overflow-hidden rounded-lg border border-[var(--as-border)] bg-[var(--as-muted)]"
      data-testid={testId ? `${testId}-holder` : undefined}
    >
      <iframe
        title={title}
        srcDoc={html}
        sandbox=""
        className="h-full w-full bg-white"
        data-testid={testId}
      />
    </div>
  );
}
