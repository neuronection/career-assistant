import { useTranslation } from "react-i18next";

import { HitlProposalCard } from "@/components/ui/chat";
import type {
  ChatMessage,
  ProfileProposalCardData,
  ProfileProposalStatus,
} from "@/types";
import { useProfileProposalsStore } from "@/stores/profileProposalsStore";

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

/**
 * The HITL card stack (plan 77) — live-turn cards (store) or persisted
 * cards (message metadata) both render through this; resolve state comes
 * from the shared store so every chat surface flips in sync. Approve and
 * reject hit the proposal endpoints — the apply itself is server-side
 * (never in the chat turn).
 */
export function ProposalCards({
  cards,
  droppedCount = 0,
}: {
  cards: ProfileProposalCardData[];
  droppedCount?: number;
}) {
  const { t } = useTranslation();
  const overrides = useProfileProposalsStore((state) => state.overrides);
  const resolve = useProfileProposalsStore((state) => state.resolve);
  const setBusy = useProfileProposalsStore((state) => state.setBusy);
  if (cards.length === 0 && droppedCount === 0) {
    return null;
  }
  return (
    <div className="mt-1 flex w-full flex-col gap-1.5" data-testid="hitl-cards">
      {cards.map((card) => {
        const state = cardStatus(card, overrides[card.id]);
        return (
          <HitlProposalCard
            key={card.id}
            title={card.title}
            status={state.status}
            diff={card.diff}
            destructive={card.destructive}
            busy={state.busy}
            error={state.error}
            onApprove={() => {
              setBusy(card.id, true);
              void resolve(card.id, "approve");
            }}
            onReject={() => {
              setBusy(card.id, true);
              void resolve(card.id, "reject");
            }}
            labels={{
              approve: t("chat.proposals.approve"),
              reject: t("chat.proposals.reject"),
              confirm: t("chat.proposals.confirmDelete"),
              cancel: t("chat.proposals.cancel"),
              pending: t("chat.proposals.pending"),
              approved: t("chat.proposals.approved"),
              rejected: t("chat.proposals.rejected"),
              conflict: t("chat.proposals.conflict"),
              expired: t("chat.proposals.expired"),
              conflictHint: t("chat.proposals.conflictHint"),
            }}
          />
        );
      })}
      {droppedCount > 0 ? (
        <p className="text-xs text-[var(--as-muted-fg)]" data-testid="hitl-dropped-note">
          {t("chat.proposals.dropped", { count: droppedCount })}
        </p>
      ) : null}
    </div>
  );
}

export function MessageProposals({ message }: { message: ChatMessage }) {
  return (
    <ProposalCards
      cards={message.metadata_json?.proposals ?? []}
      droppedCount={message.metadata_json?.proposals_dropped ?? 0}
    />
  );
}

