import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { LucideIcon } from "lucide-react";
import {
  Award,
  Briefcase,
  ChevronRight,
  Circle,
  GraduationCap,
  History,
  Milestone,
  Route,
  Wrench,
} from "lucide-react";
import { Badge, Button, ConfirmationModal } from "@/components/ui";
import { CheckIndicator } from "@neuronection/assistant-ui";
import {
  SelectionEntry,
  SelectionToolbar,
  useListSelection,
} from "@/features/selection";

/** One step as the admin paths endpoint returns it (PathStepOut). */
export interface PathStep {
  id: string;
  position: number;
  kind: string;
  label: string;
  optional: boolean;
  family_key: string | null;
  family_label: string | null;
  skill_key: string | null;
  skill_label: string | null;
  education_level: string | null;
  edge_label: string;
}

/** A draft career path awaiting moderation (CareerPathOut). */
export interface PathRow {
  id: string;
  title: string;
  description: string;
  source: string;
  status: string;
  job_code: string | null;
  job_title: string | null;
  steps: PathStep[];
}

/** Path step kinds (the backend's PathStepIn pattern) → icons. */
const STEP_KIND_ICONS: Record<string, LucideIcon> = {
  job: Briefcase,
  skill: Wrench,
  education: GraduationCap,
  certification: Award,
  experience: History,
  milestone: Milestone,
};

const STATUS_VARIANT: Record<string, "success" | "secondary" | "warning"> = {
  active: "success",
  draft: "secondary",
  deprecated: "warning",
};

const STEP_CHIP =
  "inline-flex max-w-full items-center gap-1 rounded-full border border-[var(--as-border)] bg-[var(--as-muted)] px-2 py-0.5 text-[11px] text-[var(--as-fg)]";

/** The step's display label: the resolved skill or family wins over the
 * free-text label, the kind is the last fallback. */
function stepLabel(step: PathStep): string {
  return step.skill_label ?? step.family_label ?? (step.label || step.kind);
}

function StepChip({ step }: { step: PathStep }) {
  const { t } = useTranslation();
  const Icon = STEP_KIND_ICONS[step.kind] ?? Circle;
  return (
    <span
      className={STEP_CHIP}
      title={t(`taxonomy.step.kind.${step.kind}`, { defaultValue: step.kind })}
      data-testid={`path-step-chip-${step.position}`}
    >
      <span className="tabular-nums text-[var(--as-muted-fg)]">{step.position + 1}</span>
      <Icon className="h-3 w-3 shrink-0 text-[var(--as-accent)]" aria-hidden />
      <span className="truncate">{stepLabel(step)}</span>
      {step.optional && (
        <Badge variant="outline" className="text-[10px]">
          {t("taxonomy.step.optional")}
        </Badge>
      )}
    </span>
  );
}

/** Paths review (plan 150 phase 3): draft-path cards in the taxonomy
 * listing language — route icon, status badge, mono target-job code,
 * description, source chip — with the steps as compact chips and the
 * full step list collapsed behind an expand toggle. Publish applies
 * immediately; reject is destructive and confirmed first. */
export function TaxonomyPathCards({
  paths,
  onModerate,
  onBulkModerate,
}: {
  paths: PathRow[];
  onModerate: (id: string, action: "publish" | "reject") => Promise<void>;
  onBulkModerate: (ids: string[], action: "publish" | "reject") => Promise<boolean>;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [rejecting, setRejecting] = useState<PathRow | null>(null);
  const [confirmingBulkReject, setConfirmingBulkReject] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);

  const ids = paths.map((path) => path.id);
  const selection = useListSelection({ allIds: ids, matchingIds: ids });

  const runBulk = async (action: "publish" | "reject") => {
    setBulkBusy(true);
    const done = await onBulkModerate(Array.from(selection.ids), action);
    setBulkBusy(false);
    if (done) selection.clear();
  };

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="space-y-3" data-testid="paths-list">
      <div className="flex items-center justify-end">
        <SelectionEntry prefix="paths" selection={selection} />
      </div>
      <SelectionToolbar
        prefix="paths"
        selection={selection}
        allIds={ids}
        matchingIds={ids}
        busy={bulkBusy}
        actions={
          <>
            <button
              type="button"
              onClick={() => void runBulk("publish")}
              disabled={bulkBusy || selection.count === 0}
              className="text-xs text-emerald-700 hover:text-emerald-600 disabled:opacity-40"
              data-testid="paths-bulk-publish"
            >
              {t("taxonomy.publish")} ({selection.count})
            </button>
            <button
              type="button"
              onClick={() => setConfirmingBulkReject(true)}
              disabled={bulkBusy || selection.count === 0}
              className="text-xs text-rose-600 hover:text-rose-500 disabled:opacity-40"
              data-testid="paths-bulk-reject"
            >
              {t("taxonomy.reject")} ({selection.count})
            </button>
          </>
        }
      />
      {paths.map((path) => {
        const isOpen = expanded.has(path.id);
        return (
          <div
            key={path.id}
            className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
            data-testid={`path-card-${path.id}`}
          >
            <div className="flex items-start gap-3">
              {selection.active && (
                <div className="flex shrink-0 items-center pt-1.5">
                  <CheckIndicator
                    checked={selection.isSelected(path.id)}
                    label={t("taxonomy.bulk.selectOne", { label: path.title })}
                    onToggle={() => selection.toggle(path.id)}
                  />
                </div>
              )}
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--as-muted)]">
                <Route className="h-4 w-4 text-[var(--as-accent)]" aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                  <span className="truncate text-sm font-medium text-[var(--as-fg)]">
                    {path.title}
                  </span>
                  <Badge variant={STATUS_VARIANT[path.status] ?? "secondary"}>
                    {t(`taxonomy.${path.status}`, { defaultValue: path.status })}
                  </Badge>
                </div>
                <div className="mt-0.5 flex flex-wrap items-baseline gap-x-2 text-xs text-[var(--as-muted-fg)]">
                  <span>{t("taxonomy.targetJob")}</span>
                  {path.job_title && <span>{path.job_title}</span>}
                  {path.job_code && (
                    <span className="ca-tax-key font-mono text-[11px]">{path.job_code}</span>
                  )}
                </div>
                {path.description && (
                  <p className="ca-tax-hint mt-1 line-clamp-2 text-xs text-[var(--as-muted-fg)]">
                    {path.description}
                  </p>
                )}
              </div>
            </div>

            {path.steps.length > 0 && (
              <div
                className="mt-2 flex flex-wrap gap-1.5"
                data-testid={`path-steps-${path.id}`}
              >
                {path.steps.map((step) => (
                  <StepChip key={step.id} step={step} />
                ))}
              </div>
            )}

            <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <Badge variant="outline" className="ca-tax-key font-mono text-[10px]">
                  {path.source}
                </Badge>
                <span className="text-xs tabular-nums text-[var(--as-muted-fg)]">
                  {t("taxonomy.stepsTotal", { count: path.steps.length })}
                </span>
                {path.steps.length > 0 && (
                  <button
                    type="button"
                    aria-expanded={isOpen}
                    onClick={() => toggle(path.id)}
                    className="flex cursor-pointer items-center gap-1 text-xs text-[var(--as-accent)] hover:underline"
                    data-testid={`path-steps-toggle-${path.id}`}
                  >
                    <ChevronRight
                      className={`h-3.5 w-3.5 transition-transform ${isOpen ? "rotate-90" : ""}`}
                      aria-hidden
                    />
                    {isOpen ? t("taxonomy.stepsHide") : t("taxonomy.stepsShow")}
                  </button>
                )}
              </div>
              <div className="flex shrink-0 gap-2">
                <Button
                  size="sm"
                  onClick={() => void onModerate(path.id, "publish")}
                  data-testid={`path-publish-${path.id}`}
                >
                  {t("taxonomy.publish")}
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => setRejecting(path)}
                  data-testid={`path-reject-${path.id}`}
                >
                  {t("taxonomy.reject")}
                </Button>
              </div>
            </div>

            {isOpen && (
              <ol
                className="mt-2 space-y-1 border-t border-[var(--as-border)] pt-2"
                data-testid={`path-steps-full-${path.id}`}
              >
                {path.steps.map((step) => {
                  const Icon = STEP_KIND_ICONS[step.kind] ?? Circle;
                  return (
                    <li
                      key={step.id}
                      className="flex items-start gap-2 text-xs text-[var(--as-muted-fg)]"
                      data-testid={`path-step-${step.position}`}
                    >
                      <span className="w-4 shrink-0 text-right tabular-nums">
                        {step.position + 1}.
                      </span>
                      <Icon
                        className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--as-accent)]"
                        aria-hidden
                      />
                      <span className="min-w-0 flex-1">
                        <span className="font-medium text-[var(--as-fg)]">
                          {step.label || stepLabel(step)}
                        </span>
                        <span>
                          {" "}
                          ·{" "}
                          {t(`taxonomy.step.kind.${step.kind}`, {
                            defaultValue: step.kind,
                          })}
                        </span>
                        {step.edge_label && <span> · {step.edge_label}</span>}
                        {step.education_level && (
                          <span> · {step.education_level.replace(/_/g, " ")}</span>
                        )}
                        {(step.skill_key || step.family_key) && (
                          <span className="ca-tax-key ml-1 font-mono text-[10px]">
                            {step.skill_key ?? step.family_key}
                          </span>
                        )}
                        {step.optional && (
                          <Badge variant="outline" className="ml-1 text-[10px]">
                            {t("taxonomy.step.optional")}
                          </Badge>
                        )}
                      </span>
                    </li>
                  );
                })}
              </ol>
            )}
          </div>
        );
      })}

      <ConfirmationModal
        open={confirmingBulkReject}
        onOpenChange={setConfirmingBulkReject}
        onConfirm={() => {
          setConfirmingBulkReject(false);
          void runBulk("reject");
        }}
        title={t("taxonomy.bulkPaths.rejectTitle", { count: selection.count })}
        description={t("taxonomy.bulkPaths.rejectBody")}
        confirmLabel={t("taxonomy.reject")}
        destructive
      />

      <ConfirmationModal
        open={rejecting !== null}
        onOpenChange={(open) => (!open ? setRejecting(null) : undefined)}
        onConfirm={() => {
          if (rejecting) void onModerate(rejecting.id, "reject");
          setRejecting(null);
        }}
        title={t("taxonomy.rejectTitle")}
        description={t("taxonomy.rejectBody")}
        confirmLabel={t("taxonomy.reject")}
        destructive
      />
    </div>
  );
}
