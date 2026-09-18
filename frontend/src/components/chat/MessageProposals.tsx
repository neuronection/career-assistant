import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Undo2 } from "lucide-react";

import {
  HitlProposalCard,
  type HitlProposalAction as ProfileProposalCardAction,
} from "@/components/ui/chat";
import type {
  ChatMessage,
  ProfileProposalCardData,
  ProfileProposalStatus,
} from "@/types";
import {
  PREVIEW_KINDS,
  useProfileProposalsStore,
} from "@/stores/profileProposalsStore";
import { ProposalPreviewModal } from "@/components/chat/ProposalPreviewModal";

/** Drop-reason copy (plan 99.6): the pipeline reason codes get friendly
 * one-liners (i18n keys `chat.proposals.reasons.*`); unknown reasons
 * render the raw backend text as before. */
const REASON_KEYS: Record<string, string> = {
  unread_target: "chat.proposals.reasons.unreadTarget",
  anchor_mismatch: "chat.proposals.reasons.anchorMismatch",
  anchor_ambiguous: "chat.proposals.reasons.anchorAmbiguous",
  conflicting_edit: "chat.proposals.reasons.conflictingEdit",
  duplicate_target: "chat.proposals.reasons.duplicateTarget",
};

export function reasonCopy(
  reason: string,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string {
  const code = reason.split(":", 1)[0].trim();
  const key = REASON_KEYS[code];
  if (!key) {
    return reason;
  }
  return t(key, { defaultValue: reason });
}

function cardStatus(
  card: ProfileProposalCardData,
  override?: { status?: ProfileProposalStatus; error?: string; busy?: boolean },
): {
  status: ProfileProposalStatus;
  error?: string;
  busy?: boolean;
} {
  if (override?.status) {
    return { status: override.status, error: override.error, busy: override.busy };
  }
  return { status: card.status };
}

function mapRevertError(
  detail: string,
  t: (key: string) => string,
): string {
  return detail.toLowerCase().includes("changed since it was applied")
    ? t("chat.proposals.revertError")
    : detail;
}

/** One card: resolve actions, the preview slot (snapshot-backed kinds;
 * 404 hides the button) and the approved-card revert row. */
function ProposalCard({
  card,
  onOpenPreview,
}: {
  card: ProfileProposalCardData;
  onOpenPreview: (card: ProfileProposalCardData) => void;
}) {
  const { t } = useTranslation();
  const override = useProfileProposalsStore(
    (state) => state.overrides[card.id],
  );
  const previewEntry = useProfileProposalsStore(
    (state) => state.previews[card.id],
  );
  const setBusy = useProfileProposalsStore((state) => state.setBusy);
  const revertCard = useProfileProposalsStore((state) => state.revert);
  const [armed, setArmed] = useState(false);

  const state = cardStatus(card, override);
  const variantCard = card.kind === "cv_synth";
  const bulletsCard = card.kind === "cv_set_bullets";
  const showPreviewButton =
    PREVIEW_KINDS.has(card.kind) && previewEntry?.state !== "missing";
  // Plan 101 AD2: a create op is not revertible — variant cards are
  // retracted via the Synth Library, never this row (the backend
  // rejects cv_synth anyway). Plan 107: bullet cards revert without a
  // snapshot preview (the diff rows show the before/after bullets).
  const reversible =
    (PREVIEW_KINDS.has(card.kind) || bulletsCard) &&
    !variantCard &&
    state.status === "approved";

  return (
    <div data-testid={`hitl-card-${card.id}`}>
      <HitlProposalCard
        title={card.title}
        status={state.status}
        action={card.action as ProfileProposalCardAction}
        diff={card.diff}
        destructive={card.destructive}
        busy={state.busy}
        error={state.error ? mapRevertError(state.error, t) : undefined}
        onPreview={showPreviewButton ? () => onOpenPreview(card) : undefined}
        previewTestId={showPreviewButton ? `hitl-preview-${card.id}` : undefined}
        onApprove={() => {
          setBusy(card.id, true);
          void useProfileProposalsStore.getState().resolve(card.id, "approve");
        }}
        onReject={() => {
          setBusy(card.id, true);
          void useProfileProposalsStore.getState().resolve(card.id, "reject");
        }}
        labels={{
          approve: variantCard
            ? t("chat.proposals.approveVariants")
            : t("chat.proposals.approve"),
          reject: t("chat.proposals.reject"),
          confirm: t("chat.proposals.confirmDelete"),
          cancel: t("chat.proposals.cancel"),
          preview: t("chat.proposals.preview"),
          pending: t("chat.proposals.pending"),
          approved: variantCard
            ? t("chat.proposals.approvedVariants")
            : t("chat.proposals.approved"),
          rejected: t("chat.proposals.rejected"),
          conflict: t("chat.proposals.conflict"),
          expired: t("chat.proposals.expired"),
          reverted: t("chat.proposals.reverted"),
          conflictHint: t("chat.proposals.conflictHint"),
        }}
      />
      {reversible ? (
        <div className="mt-1 flex items-center gap-2 text-xs">
          <button
            type="button"
            onClick={() => {
              if (armed) {
                setArmed(false);
                void revertCard(card.id);
                return;
              }
              setArmed(true);
            }}
            data-testid={`hitl-revert-${card.id}`}
            data-armed={armed || undefined}
            className={`inline-flex items-center gap-1 rounded-[var(--as-radius)] border px-2.5 py-1 font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)] ${
              armed
                ? "border-[var(--as-danger)] bg-[var(--as-danger)] text-[var(--as-danger-fg)]"
                : "border-[var(--as-border)] text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
            }`}
          >
            <Undo2 className="size-3" aria-hidden />
            {armed ? t("chat.proposals.confirmRevert") : t("chat.proposals.revert")}
          </button>
          {armed ? (
            <button
              type="button"
              onClick={() => setArmed(false)}
              className="rounded-[var(--as-radius)] px-2.5 py-1 font-medium text-[var(--as-muted-fg)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--as-focus-ring)]"
            >
              {t("chat.proposals.cancel")}
            </button>
          ) : null}
          <span className="text-[var(--as-muted-fg)]">
            {t("chat.proposals.revertHint")}
          </span>
        </div>
      ) : null}
    </div>
  );
}

/**
 * The HITL card stack (plan 77) — live-turn cards (store) or persisted
 * cards (message metadata) both render through this; resolve state comes
 * from the shared store so every chat surface flips in sync. Approve and
 * reject hit the proposal endpoints — the apply itself is server-side
 * (never in the chat turn). Plan 99.6 adds the preview slot (lazy
 * snapshot fetch, 404 hides the button) and the approved-card revert row
 * (armed confirm → server inverse-apply; `reverted` is terminal).
 */
export function ProposalCards({
  cards,
  droppedCount = 0,
  droppedReasons = [],
}: {
  cards: ProfileProposalCardData[];
  droppedCount?: number;
  droppedReasons?: { kind?: string | null; reason: string }[];
}) {
  const { t } = useTranslation();
  const [previewCard, setPreviewCard] =
    useState<ProfileProposalCardData | null>(null);

  if (cards.length === 0 && droppedCount === 0) {
    return null;
  }
  return (
    <div className="mt-1 flex w-full flex-col gap-1.5" data-testid="hitl-cards">
      {cards.map((card) => (
        <ProposalCard key={card.id} card={card} onOpenPreview={setPreviewCard} />
      ))}
      {droppedCount > 0 ? (
        <p
          className="text-xs text-[var(--as-muted-fg)]"
          data-testid="hitl-dropped-note"
        >
          {t("chat.proposals.dropped", { count: droppedCount })}
        </p>
      ) : null}
      {droppedCount > 0 && droppedReasons.length > 0 ? (
        <ul
          className="flex flex-col gap-0.5 text-xs text-[var(--as-muted-fg)]"
          data-testid="hitl-dropped-reasons"
        >
          {droppedReasons.map((drop, index) => (
            <li key={index} className="break-words">
              {t("chat.proposals.droppedReason", {
                kind: drop.kind ?? "",
                reason: reasonCopy(drop.reason, t),
              })}
            </li>
          ))}
        </ul>
      ) : null}
      <ProposalPreviewModal
        proposal={previewCard}
        onClose={() => setPreviewCard(null)}
      />
    </div>
  );
}

export function MessageProposals({ message }: { message: ChatMessage }) {
  const pipelineErrors = (message.metadata_json?.profile_op_errors ?? []).map(
    (error) =>
      ({
        kind: error.kind,
        reason: `${error.code}: prepared edit was skipped`,
      }) as { kind: string | null; reason: string },
  );
  return (
    <ProposalCards
      cards={message.metadata_json?.proposals ?? []}
      droppedCount={message.metadata_json?.proposals_dropped ?? 0}
      droppedReasons={[
        ...(message.metadata_json?.proposals_dropped_reasons ?? []),
        ...pipelineErrors,
      ]}
    />
  );
}
