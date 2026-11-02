import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Briefcase, Clock, Sparkles } from "lucide-react";
import {
  Badge,
  Button,
  ConfirmationModal,
  Modal,
  ModalContent,
  ModalFooter,
  Spinner,
} from "@/components/ui";
import { applyJobProposal, dismissJobProposal } from "@/api/taxonomy";
import type { JobProposalRow } from "@/api/taxonomy";
import { formatAbsolute, formatRelativeTime } from "@/lib/time";

interface FamilyOption {
  key: string;
  label: string;
}

/** One signal candidate from the join trace (plan 185 S6.2): the admin's
 * "apply or write a better job" context — what the join already considered
 * and how close it landed. */
function SignalCandidates({ row }: { row: JobProposalRow }) {
  const { t } = useTranslation();
  const candidates = Array.isArray(
    (row.mapping_signals as { semantic?: { candidates?: unknown[] } } | null)?.semantic
      ?.candidates,
  )
    ? ((row.mapping_signals as { semantic: { candidates: Array<{ code: string; score: number }> } })
        .semantic.candidates)
    : [];
  if (candidates.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid={`proposal-signals-${row.id}`}>
      <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
        {t("taxonomy.jobProposals.signalsLabel")}
      </span>
      {candidates.slice(0, 3).map((candidate) => (
        <span
          key={candidate.code}
          className="inline-flex items-center gap-1 rounded-full border border-[var(--as-border)] bg-[var(--as-muted)] px-2 py-0.5 font-mono text-[10px] text-[var(--as-fg)]"
        >
          {candidate.code} · {candidate.score.toFixed(2)}
        </span>
      ))}
    </div>
  );
}

/** Job proposals (plan 185 S4.4): the HITL "create the job" queue on the
 * Taxonomy settings tab, next to the enrichment cards — same moderation
 * grammar: apply merges immediately through the dialog, dismissal is
 * destructive and confirmed first. */
export function TaxonomyJobProposalCards({
  rows,
  families,
  onDone,
}: {
  rows: JobProposalRow[];
  families: FamilyOption[];
  onDone: (note: string) => void;
}) {
  const { t } = useTranslation();
  const [applying, setApplying] = useState<JobProposalRow | null>(null);
  const [dismissing, setDismissing] = useState<JobProposalRow | null>(null);
  const [familyKey, setFamilyKey] = useState("");
  const [title, setTitle] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const openApply = (row: JobProposalRow) => {
    setApplying(row);
    setFamilyKey(families[0]?.key ?? "");
    setTitle(row.proposal?.title_norm ?? row.title);
    setCode("");
    setError("");
  };

  const submitApply = async () => {
    if (!applying || !familyKey) return;
    setBusy(true);
    setError("");
    try {
      const result = await applyJobProposal(applying.id, {
        family_key: familyKey,
        title: title.trim() || undefined,
        code: code.trim() || undefined,
      });
      setApplying(null);
      onDone(t("taxonomy.jobProposals.appliedNote", { code: result.job_code }));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("taxonomy.jobProposals.applyFailed"));
    } finally {
      setBusy(false);
    }
  };

  const submitDismiss = async () => {
    if (!dismissing) return;
    setBusy(true);
    try {
      await dismissJobProposal(dismissing.id);
      setDismissing(null);
      onDone(t("taxonomy.jobProposals.dismissedNote"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("taxonomy.jobProposals.dismissFailed"));
      setDismissing(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3" data-testid="job-proposal-queue">
      {error && <p className="text-sm text-rose-600">{error}</p>}
      {rows.map((row) => {
        const proposal = row.proposal ?? {};
        const relative = row.proposed_at ? formatRelativeTime(row.proposed_at) : null;
        return (
          <div
            key={row.id}
            className="space-y-2.5 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
            data-testid={`job-proposal-row-${row.id}`}
          >
            <div className="flex items-start gap-3">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--as-muted)]">
                <Briefcase className="h-4 w-4 text-[var(--as-accent)]" aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-[var(--as-fg)]">
                  {proposal.title_norm ?? row.title}
                </span>
                {relative && (
                  <span
                    className="mt-0.5 inline-flex items-center gap-1 text-[11px] text-[var(--as-muted-fg)]"
                    title={row.proposed_at ? formatAbsolute(row.proposed_at) : undefined}
                  >
                    <Clock className="h-3 w-3" aria-hidden />
                    {t(relative.key, { count: relative.count })}
                  </span>
                )}
              </div>
              <div className="flex shrink-0 gap-2">
                <Button size="sm" onClick={() => openApply(row)} data-testid={`proposal-apply-${row.id}`}>
                  {t("taxonomy.jobProposals.apply")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setDismissing(row)}
                  data-testid={`proposal-dismiss-${row.id}`}
                >
                  {t("taxonomy.jobProposals.dismiss")}
                </Button>
              </div>
            </div>
            {proposal.short_description && (
              <p className="text-xs text-[var(--as-muted-fg)]">{proposal.short_description}</p>
            )}
            <div className="flex flex-wrap items-center gap-1.5">
              {(proposal.skills ?? []).map((skill, index) => (
                <span
                  key={`${skill.skill_key ?? skill.raw_label}-${index}`}
                  className="inline-flex items-center gap-1 rounded-full border border-[var(--as-border)] bg-[var(--as-muted)] px-2 py-0.5 text-[11px] text-[var(--as-fg)]"
                >
                  {skill.skill_key ?? skill.raw_label}
                  {skill.priority != null && (
                    <span className="font-mono text-[10px] text-[var(--as-muted-fg)]">
                      {skill.priority}
                    </span>
                  )}
                </span>
              ))}
              {proposal.seniority && (
                <Badge variant="outline" className="text-[10px]">
                  {proposal.seniority}
                </Badge>
              )}
            </div>
            <SignalCandidates row={row} />
          </div>
        );
      })}

      <Modal
        open={applying !== null}
        onOpenChange={(open) => (!open ? setApplying(null) : undefined)}
        aria-label={t("taxonomy.jobProposals.applyTitle")}
      >
        <ModalContent className="space-y-3">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-[var(--as-accent)]" aria-hidden />
            <h2 className="text-sm font-semibold text-[var(--as-fg)]">
              {t("taxonomy.jobProposals.applyTitle")}
            </h2>
          </div>
          <p className="text-xs text-[var(--as-muted-fg)]">
            {t("taxonomy.jobProposals.applyHint")}
          </p>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-[var(--as-fg)]">
              {t("taxonomy.jobProposals.family")}
            </span>
            <select
              value={familyKey}
              onChange={(event) => setFamilyKey(event.target.value)}
              className="w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm text-[var(--as-fg)]"
              data-testid="proposal-family-picker"
            >
              {families.map((family) => (
                <option key={family.key} value={family.key}>
                  {family.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-[var(--as-fg)]">
              {t("taxonomy.jobProposals.jobTitle")}
            </span>
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              className="w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm text-[var(--as-fg)]"
              data-testid="proposal-title-input"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-[var(--as-fg)]">
              {t("taxonomy.jobProposals.jobCode")}
            </span>
            <input
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder={t("taxonomy.jobProposals.jobCodePlaceholder")}
              className="w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm text-[var(--as-fg)]"
              data-testid="proposal-code-input"
            />
          </label>
        </ModalContent>
        <ModalFooter className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={() => setApplying(null)}>
            {t("common.cancel")}
          </Button>
          <Button
            size="sm"
            onClick={() => void submitApply()}
            disabled={busy || !familyKey}
            data-testid="proposal-apply-confirm"
          >
            {busy ? <Spinner size="sm" /> : t("taxonomy.jobProposals.applyConfirm")}
          </Button>
        </ModalFooter>
      </Modal>

      <ConfirmationModal
        open={dismissing !== null}
        onOpenChange={(open) => (!open ? setDismissing(null) : undefined)}
        onConfirm={() => {
          if (dismissing) void submitDismiss();
          setDismissing(null);
        }}
        title={t("taxonomy.jobProposals.dismissTitle")}
        description={t("taxonomy.jobProposals.dismissMessage", {
          title: dismissing?.proposal?.title_norm ?? dismissing?.title ?? "",
        })}
        confirmLabel={t("taxonomy.jobProposals.dismiss")}
        destructive
      />
    </div>
  );
}
