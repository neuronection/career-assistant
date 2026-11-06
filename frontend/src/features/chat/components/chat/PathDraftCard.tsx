import { useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { CheckCircle2, Route as RouteIcon, Save } from "lucide-react";

import { Button } from "@/components/ui";
import { createPath } from "@/api/paths";
import { PathRenderer } from "@/features/paths/PathRenderer";
import { buildPathView } from "@/features/paths/viewModel";
import type { ChatMessage, ChatPathDraftMeta, ChatPathDraftStep } from "@/types";
import type { PathStepInput } from "@/types";

function draftStepsToInput(steps: ChatPathDraftStep[]): PathStepInput[] {
  return steps.map((step, index) => ({
    id: `d${index}`,
    position: index,
    kind: step.kind,
    label: step.label || step.kind,
    optional: step.optional === true,
    skill_key: step.skill_key ?? null,
    family_key: step.family_key ?? null,
    education_level: step.education_level ?? null,
    parent_step_id: step.parent != null ? `d${step.parent}` : null,
    edge_label: step.edge_label || null,
  }));
}

/** The chat-side review artifact (plan 125): the assistant's grounded
path draft renders as an embedded PathRenderer preview with an explicit
"Save to my paths" action — the save creates a DRAFT path the user
activates on /paths; nothing is auto-applied. */
export function MessagePathDraft({ message }: { message: ChatMessage }) {
  const { t } = useTranslation();
  const meta: ChatPathDraftMeta | null = message.metadata_json?.path_draft ?? null;
  const draft = meta?.draft;
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  if (!draft || draft.steps.length === 0) {
    return null;
  }
  const view = buildPathView({
    id: "chat-draft",
    title: draft.title,
    description: draft.description ?? "",
    source: "ai",
    status: "draft",
    job_code: draft.job_code ?? null,
    job_title: draft.job_title ?? null,
    steps: draftStepsToInput(draft.steps),
  });
  const save = async () => {
    setBusy(true);
    setError(false);
    try {
      await createPath({
        job_ref: draft.job_code ?? draft.title,
        title: draft.title,
        description: draft.description ?? "",
        steps: draft.steps.map((step) => ({
          kind: step.kind,
          label: step.label || step.kind,
          skill_key: step.skill_key ?? undefined,
          family_key: step.family_key ?? undefined,
          education_level: step.education_level ?? undefined,
          optional: step.optional === true,
          parent: step.parent ?? undefined,
          edge_label: step.edge_label || undefined,
        })),
      });
      setSaved(true);
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div
      className="mt-1 w-full rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
      data-testid="path-draft-card"
    >
      <p className="flex items-center gap-2 text-sm font-medium text-[var(--as-fg)]">
        <RouteIcon className="size-4 text-[var(--as-accent)]" aria-hidden />
        {view.title}
      </p>
      {meta?.note ? (
        <p className="mt-0.5 text-xs text-[var(--as-muted-fg)]">{meta.note}</p>
      ) : null}
      <p className="mt-1 text-xs text-[var(--as-muted-fg)]">
        {t("chat.pathDraft.reviewHint")}
      </p>
      <div className="mt-2">
        <PathRenderer view={view} compact />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {saved ? (
          <>
            <span
              className="flex items-center gap-1 text-xs font-medium text-emerald-600"
              data-testid="path-draft-saved"
            >
              <CheckCircle2 className="size-3.5" aria-hidden />
              {t("chat.pathDraft.saved")}
            </span>
            <Link
              to="/paths"
              className="text-xs font-medium text-[var(--as-accent)] hover:underline"
              data-testid="path-draft-open"
            >
              {t("chat.pathDraft.openPaths")}
            </Link>
          </>
        ) : (
          <>
            <Button
              size="sm"
              variant="default"
              disabled={busy}
              data-testid="path-draft-save"
              onClick={() => void save()}
            >
              <Save className="mr-1 size-3.5" aria-hidden />
              {t("chat.pathDraft.save")}
            </Button>
            <span className="text-xs text-[var(--as-muted-fg)]">
              {t("chat.pathDraft.saveHint")}
            </span>
          </>
        )}
        {error ? (
          <span className="text-xs text-[var(--as-danger)]" data-testid="path-draft-error">
            {t("chat.pathDraft.saveError")}
          </span>
        ) : null}
      </div>
    </div>
  );
}
