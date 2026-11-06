import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Briefcase, Clock, ExternalLink, Search, Sparkles } from "lucide-react";
import {
  Badge,
  Button,
  ConfirmationModal,
  Modal,
  ModalContent,
  ModalFooter,
  Spinner,
} from "@/components/ui";
import {
  applyJobProposal,
  dismissJobProposal,
  mapJobProposal,
  remapPosting,
} from "@/api/taxonomy";
import { fetchJobs } from "@/api/jobs";
import type { Job } from "@/types/wire";
import { CheckIndicator } from "@neuronection/assistant-ui";
import {
  SelectionEntry,
  SelectionToolbar,
  useListSelection,
} from "@/features/selection";
import type {
  JobProposalCatalogCandidate,
  JobProposalDuplicateCandidate,
  JobProposalRow,
} from "@/api/taxonomy";
import { apiDetail } from "@/api/client";
import { formatAbsolute, formatRelativeTime } from "@/lib/time";

interface FamilyOption {
  key: string;
  label: string;
  depth: number;
}

const SKILL_GROUP_ORDER = ["must_have", "nice_to_have", "bonus"] as const;
const SKILL_GROUP_LABEL: Record<string, string> = {
  must_have: "taxonomy.jobProposals.skillsMust",
  nice_to_have: "taxonomy.jobProposals.skillsNice",
  bonus: "taxonomy.jobProposals.skillsBonus",
};

function errorData(err: unknown): Record<string, unknown> {
  return ((err as { response?: { data?: Record<string, unknown> } })?.response?.data ??
    {}) as Record<string, unknown>;
}

function skillGroups(row: JobProposalRow) {
  const groups: Record<string, NonNullable<JobProposalRow["proposal"]>["skills"]> = {};
  for (const skill of row.proposal?.skills ?? []) {
    const key = SKILL_GROUP_ORDER.includes(skill.priority as never)
      ? (skill.priority as string)
      : "bonus";
    groups[key] = [...(groups[key] ?? []), skill];
  }
  return groups;
}

function SourceBlock({ row }: { row: JobProposalRow }) {
  const { t } = useTranslation();
  return (
    <div className="min-w-0 space-y-0.5" data-testid={`proposal-source-${row.id}`}>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
        {t("taxonomy.jobProposals.sourceLabel")}
      </p>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-[var(--as-fg)]">
        <span className="font-medium">{row.title}</span>
        {row.org ? <span className="text-[var(--as-muted-fg)]">· {row.org}</span> : null}
        {row.proposal?.seniority ? (
          <Badge variant="outline" className="text-[10px]">
            {row.proposal.seniority}
          </Badge>
        ) : null}
        {row.url ? (
          <a
            href={row.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-0.5 text-[var(--as-accent)] hover:underline"
            data-testid={`proposal-source-link-${row.id}`}
          >
            {t("taxonomy.jobProposals.openPosting")}
            <ExternalLink className="h-3 w-3" aria-hidden />
          </a>
        ) : null}
      </div>
    </div>
  );
}

function SkillGroups({ row }: { row: JobProposalRow }) {
  const { t } = useTranslation();
  const [showAll, setShowAll] = useState(false);
  const groups = useMemo(() => skillGroups(row), [row]);
  const total = Object.values(groups).reduce((count, list) => count + (list?.length ?? 0), 0);
  if (!total) return null;
  let rendered = 0;
  return (
    <div className="space-y-1" data-testid={`proposal-skills-${row.id}`}>
      {SKILL_GROUP_ORDER.map((group) => {
        const list = groups[group] ?? [];
        if (!list.length) return null;
        const visible = showAll ? list : list.slice(0, Math.max(0, 8 - rendered));
        rendered += visible.length;
        if (!visible.length) return null;
        return (
          <div key={group} className="flex flex-wrap items-center gap-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
              {t(SKILL_GROUP_LABEL[group])}
            </span>
            {visible.map((skill, index) => (
              <span
                key={`${skill.skill_key ?? skill.raw_label}-${index}`}
                className="inline-flex items-center gap-1 rounded-full border border-[var(--as-border)] bg-[var(--as-muted)] px-2 py-0.5 text-[11px] text-[var(--as-fg)]"
              >
                {skill.skill_key ?? skill.raw_label}
                {skill.required_level != null ? (
                  <span className="font-mono text-[10px] text-[var(--as-muted-fg)]">
                    {skill.required_level}
                  </span>
                ) : null}
              </span>
            ))}
          </div>
        );
      })}
      {total > 8 ? (
        <button
          type="button"
          className="text-[11px] text-[var(--as-accent)] hover:underline"
          onClick={() => setShowAll((value) => !value)}
          data-testid={`proposal-skills-toggle-${row.id}`}
        >
          {showAll ? t("taxonomy.jobProposals.showLess") : t("taxonomy.jobProposals.showAll")}
        </button>
      ) : null}
    </div>
  );
}

function CandidateButtons({
  row,
  onMap,
  onBrowse,
}: {
  row: JobProposalRow;
  onMap: (candidate: JobProposalCatalogCandidate) => void;
  onBrowse: () => void;
}) {
  const { t } = useTranslation();
  const candidates = row.catalog_candidates ?? [];
  if (!candidates.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid={`proposal-candidates-${row.id}`}>
      <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
        {t("taxonomy.jobProposals.closestTypes")}
      </span>
      {candidates.slice(0, 3).map((candidate) => (
        <Button
          key={candidate.code}
          size="sm"
          variant="outline"
          onClick={() => onMap(candidate)}
          data-testid={`proposal-candidate-${row.id}-${candidate.code}`}
        >
          {t("taxonomy.jobProposals.mapTo", { title: candidate.title })}
        </Button>
      ))}
      <Button
        size="sm"
        variant="ghost"
        onClick={onBrowse}
        data-testid={`proposal-browse-${row.id}`}
      >
        <Search className="h-3.5 w-3.5" aria-hidden />
        {t("taxonomy.jobProposals.browseCatalog")}
      </Button>
    </div>
  );
}

export function TaxonomyJobProposalCards({
  rows,
  families,
  onDone,
  onDecided,
  onRefresh,
  onBulkDismiss,
}: {
  rows: JobProposalRow[];
  families: FamilyOption[];
  onDone: (note: string) => void;
  onDecided?: (id: string) => void;
  onRefresh?: () => void | Promise<void>;
  onBulkDismiss: (ids: string[]) => Promise<boolean>;
}) {
  const { t } = useTranslation();
  const [applying, setApplying] = useState<JobProposalRow | null>(null);
  const [mapping, setMapping] = useState<{ row: JobProposalRow; code: string; title: string } | null>(
    null,
  );
  const [browsing, setBrowsing] = useState<JobProposalRow | null>(null);
  const [browseQuery, setBrowseQuery] = useState("");
  const [browseResults, setBrowseResults] = useState<Job[]>([]);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [dismissing, setDismissing] = useState<JobProposalRow | null>(null);
  const [confirmingBulkDismiss, setConfirmingBulkDismiss] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);

  const ids = rows.map((row) => row.id);
  const selection = useListSelection({ allIds: ids, matchingIds: ids });

  const runBulkDismiss = async () => {
    setBulkBusy(true);
    const done = await onBulkDismiss(Array.from(selection.ids));
    setBulkBusy(false);
    if (done) selection.clear();
  };
  const [familyKey, setFamilyKey] = useState("");
  const [title, setTitle] = useState("");
  const [code, setCode] = useState("");
  const [description, setDescription] = useState("");
  const [allowDuplicate, setAllowDuplicate] = useState(false);
  const [allowInvalidTitle, setAllowInvalidTitle] = useState(false);
  const [duplicateConflict, setDuplicateConflict] = useState<JobProposalDuplicateCandidate[]>([]);
  const [busy, setBusy] = useState(false);
  const [remapping, setRemapping] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [queued, setQueued] = useState<Set<string>>(() => new Set());
  const [error, setError] = useState("");

  useEffect(() => {
    setQueued((previous) => {
      const next = new Set(previous);
      for (const id of previous) {
        const current = rows.find((row) => row.id === id);
        if (!current) next.delete(id);
      }
      return next;
    });
  }, [rows]);

  const refresh = async () => {
    if (!onRefresh || refreshing) return;
    setRefreshing(true);
    setError("");
    try {
      await onRefresh();
    } catch (err) {
      setError(apiDetail(err) || t("taxonomy.jobProposals.refreshFailed"));
    } finally {
      setRefreshing(false);
    }
  };

  const openCreate = (row: JobProposalRow) => {
    setApplying(row);
    setFamilyKey(row.suggested_family_key ?? row.proposal?.family_key ?? "");
    setTitle(row.proposal?.job_type ?? row.title);
    setCode("");
    setDescription(row.proposal?.short_description ?? "");
    setAllowDuplicate(false);
    setAllowInvalidTitle(false);
    setDuplicateConflict(row.duplicate_candidates ?? []);
    setError("");
  };

  const submitCreate = async () => {
    if (!applying) return;
    setBusy(true);
    setError("");
    try {
      const result = await applyJobProposal(applying.id, {
        family_key: familyKey || undefined,
        title: title.trim() || undefined,
        code: code.trim() || undefined,
        short_description: description.trim() || undefined,
        allow_duplicate: allowDuplicate,
        allow_invalid_title: allowInvalidTitle,
      });
      setApplying(null);
      onDecided?.(applying.id);
      onDone(t("taxonomy.jobProposals.appliedNote", { code: result.job_code }));
    } catch (err) {
      const data = errorData(err);
      if (data.code === "duplicate_job_type") {
        setDuplicateConflict((data.existing as JobProposalDuplicateCandidate[]) ?? []);
        setError(t("taxonomy.jobProposals.duplicateError"));
      } else if (data.code === "invalid_job_type_title") {
        setError(t("taxonomy.jobProposals.invalidTitleError"));
      } else if (data.code === "family_required") {
        setError(t("taxonomy.jobProposals.familyRequired"));
      } else {
        setError(apiDetail(err) || t("taxonomy.jobProposals.applyFailed"));
      }
    } finally {
      setBusy(false);
    }
  };

  const submitMap = async () => {
    if (!mapping) return;
    setBusy(true);
    setError("");
    try {
      await mapJobProposal(mapping.row.id, mapping.code);
      setMapping(null);
      onDone(t("taxonomy.jobProposals.mappedNote", { title: mapping.title }));
    } catch (err) {
      setError(apiDetail(err) || t("taxonomy.jobProposals.mapFailed"));
      setMapping(null);
    } finally {
      setBusy(false);
    }
  };

  const submitDismiss = async () => {
    if (!dismissing) return;
    setBusy(true);
    try {
      await dismissJobProposal(dismissing.id);
      onDecided?.(dismissing.id);
      setDismissing(null);
      onDone(t("taxonomy.jobProposals.dismissedNote"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("taxonomy.jobProposals.dismissFailed"));
      setDismissing(null);
    } finally {
      setBusy(false);
    }
  };

  const redecide = async (id: string) => {
    setRemapping(id);
    setError("");
    try {
      await remapPosting(id);
      setQueued((previous) => new Set(previous).add(id));
      onDone(t("taxonomy.jobProposals.remapQueuedNote"));
    } catch (err) {
      setError(apiDetail(err) || t("taxonomy.jobProposals.remapFailed"));
    } finally {
      setRemapping(null);
    }
  };

  const loadBrowse = async (query: string) => {
    setBrowseLoading(true);
    try {
      const page = await fetchJobs({ q: query || undefined, page_size: 10 });
      setBrowseResults(page.items ?? []);
    } catch {
      setBrowseResults([]);
    } finally {
      setBrowseLoading(false);
    }
  };

  const openBrowse = (row: JobProposalRow) => {
    setBrowsing(row);
    setBrowseQuery("");
    void loadBrowse("");
  };

  return (
    <div className="space-y-3" data-testid="job-proposal-queue">
      <div className="flex items-center justify-end">
        <SelectionEntry prefix="proposals" selection={selection} />
      </div>
      <SelectionToolbar
        prefix="proposals"
        selection={selection}
        allIds={ids}
        matchingIds={ids}
        busy={bulkBusy}
        actions={
          <button
            type="button"
            onClick={() => setConfirmingBulkDismiss(true)}
            disabled={bulkBusy || selection.count === 0}
            className="text-xs text-rose-600 hover:text-rose-500 disabled:opacity-40"
            data-testid="proposals-bulk-dismiss"
          >
            {t("taxonomy.jobProposals.dismiss")} ({selection.count})
          </button>
        }
      />
      {error && <p className="text-sm text-rose-600">{error}</p>}
      {rows.map((row) => {
        const proposal = row.proposal ?? {};
        const relative = row.proposed_at ? formatRelativeTime(row.proposed_at) : null;
        const isQueued = queued.has(row.id);
        const mapTarget = row.existing_job ?? null;
        const action = proposal.action ?? "create";
        return (
          <div
            key={row.id}
            className="space-y-2.5 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
            data-testid={`job-proposal-row-${row.id}`}
          >
            <div className="flex items-start gap-3">
              {selection.active && (
                <div className="flex shrink-0 items-center pt-1.5">
                  <CheckIndicator
                    checked={selection.isSelected(row.id)}
                    label={t("taxonomy.bulk.selectOne", {
                      label: proposal.job_type ?? row.title,
                    })}
                    onToggle={() => selection.toggle(row.id)}
                  />
                </div>
              )}
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--as-muted)]">
                <Briefcase className="h-4 w-4 text-[var(--as-accent)]" aria-hidden />
              </span>
              <div className="min-w-0 flex-1 space-y-1.5">
                <SourceBlock row={row} />
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className="text-sm font-semibold text-[var(--as-fg)]"
                    data-testid={`proposal-type-${row.id}`}
                  >
                    {proposal.job_type ?? row.title}
                  </span>
                  {proposal.needs_edit ? (
                    <Badge variant="outline" className="text-[10px] text-amber-600">
                      {t("taxonomy.jobProposals.needsEdit")}
                    </Badge>
                  ) : null}
                  {relative && (
                    <span
                      className="inline-flex items-center gap-1 text-[11px] text-[var(--as-muted-fg)]"
                      title={row.proposed_at ? formatAbsolute(row.proposed_at) : undefined}
                    >
                      <Clock className="h-3 w-3" aria-hidden />
                      {t(relative.key, { count: relative.count })}
                    </span>
                  )}
                </div>
                {action === "map_existing" && mapTarget ? (
                  <p className="text-xs text-[var(--as-muted-fg)]">
                    {t("taxonomy.jobProposals.existingTypeHint", { title: mapTarget.title })}
                  </p>
                ) : proposal.short_description ? (
                  <p className="text-xs text-[var(--as-muted-fg)]">{proposal.short_description}</p>
                ) : null}
                {proposal.rationale ? (
                  <p className="text-[11px] italic text-[var(--as-muted-fg)]">
                    {proposal.rationale}
                  </p>
                ) : null}
              </div>
              <div className="flex shrink-0 gap-2">
                {action === "map_existing" && mapTarget ? (
                  <Button
                    size="sm"
                    onClick={() =>
                      setMapping({
                        row,
                        code: mapTarget.code,
                        title: mapTarget.title,
                      })
                    }
                    data-testid={`proposal-apply-${row.id}`}
                  >
                    {t("taxonomy.jobProposals.mapTo", { title: mapTarget.title })}
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    onClick={() => openCreate(row)}
                    data-testid={`proposal-apply-${row.id}`}
                  >
                    {t("taxonomy.jobProposals.createType")}
                  </Button>
                )}
                {action !== "map_existing" ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => openBrowse(row)}
                    data-testid={`proposal-browse-action-${row.id}`}
                  >
                    {t("taxonomy.jobProposals.browseCatalog")}
                  </Button>
                ) : null}
                <Button
                  size="sm"
                  variant="outline"
                  disabled={remapping === row.id || isQueued}
                  onClick={() => void redecide(row.id)}
                  title={t("taxonomy.jobProposals.remapTitle")}
                  data-testid={`proposal-remap-${row.id}`}
                >
                  {remapping === row.id ? (
                    <Spinner size="sm" />
                  ) : isQueued ? (
                    t("taxonomy.jobProposals.remapQueued")
                  ) : (
                    t("taxonomy.jobProposals.remap")
                  )}
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

            {isQueued && (
              <div
                className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--as-border)] bg-[var(--as-muted)] px-2.5 py-1.5"
                data-testid={`proposal-pending-${row.id}`}
              >
                <span className="inline-flex items-center gap-1 rounded-full bg-[var(--as-surface-raised)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--as-fg)]">
                  <Clock className="h-3 w-3" aria-hidden />
                  {t("taxonomy.jobProposals.pendingChip")}
                </span>
                <span className="min-w-0 flex-1 text-[11px] text-[var(--as-muted-fg)]">
                  {t("taxonomy.jobProposals.pendingNotice", {
                    reason: t("taxonomy.jobProposals.pendingReasonUnknown"),
                  })}
                </span>
                {onRefresh && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={refreshing}
                    onClick={() => void refresh()}
                    data-testid={`proposal-refresh-${row.id}`}
                  >
                    {refreshing ? <Spinner size="sm" /> : t("taxonomy.jobProposals.checkAgain")}
                  </Button>
                )}
              </div>
            )}

            <SkillGroups row={row} />
            <CandidateButtons
              row={row}
              onMap={(candidate) =>
                setMapping({ row, code: candidate.code, title: candidate.title })
              }
              onBrowse={() => openBrowse(row)}
            />
            {action === "map_existing" && row.existing_job?.short_description ? (
              <p className="text-[11px] text-[var(--as-muted-fg)]">
                {row.existing_job.short_description}
              </p>
            ) : null}
          </div>
        );
      })}

      <Modal
        open={applying !== null}
        onOpenChange={(open) => (!open ? setApplying(null) : undefined)}
        aria-label={t("taxonomy.jobProposals.createTitle")}
      >
        <ModalContent className="space-y-3">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-[var(--as-accent)]" aria-hidden />
            <h2 className="text-sm font-semibold text-[var(--as-fg)]">
              {t("taxonomy.jobProposals.createTitle")}
            </h2>
          </div>
          <p className="text-xs text-[var(--as-muted-fg)]">
            {t("taxonomy.jobProposals.createHint")}
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
              <option value="">{t("taxonomy.jobProposals.familyPlaceholder")}</option>
              {families.map((family) => (
                <option key={family.key} value={family.key}>
                  {`${"\u00a0".repeat(family.depth * 3)}${family.label}`}
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
              {t("taxonomy.jobProposals.description")}
            </span>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              rows={3}
              className="w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm text-[var(--as-fg)]"
              data-testid="proposal-description-input"
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
          {duplicateConflict.length > 0 ? (
            <div
              className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-2.5"
              data-testid="proposal-duplicate-warning"
            >
              <p className="text-xs font-medium text-amber-800">
                {t("taxonomy.jobProposals.duplicateWarning", {
                  title: duplicateConflict[0].title,
                })}
              </p>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    if (!applying) return;
                    setApplying(null);
                    setMapping({
                      row: applying,
                      code: duplicateConflict[0].code,
                      title: duplicateConflict[0].title,
                    });
                  }}
                  data-testid="proposal-duplicate-map"
                >
                  {t("taxonomy.jobProposals.mapTo", { title: duplicateConflict[0].title })}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setAllowDuplicate(true)}
                  data-testid="proposal-duplicate-create"
                >
                  {t("taxonomy.jobProposals.createAnyway")}
                </Button>
              </div>
            </div>
          ) : null}
          {allowInvalidTitle ? (
            <p className="text-[11px] text-amber-700">
              {t("taxonomy.jobProposals.invalidTitleOverride")}
            </p>
          ) : (
            <button
              type="button"
              className="text-[11px] text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
              onClick={() => setAllowInvalidTitle(true)}
              data-testid="proposal-invalid-override"
            >
              {t("taxonomy.jobProposals.allowInvalidTitle")}
            </button>
          )}
          <ModalFooter className="mt-4 flex items-center justify-end gap-2 border-t border-[var(--as-border)] pt-3">
            <Button variant="outline" size="sm" onClick={() => setApplying(null)}>
              {t("common.cancel")}
            </Button>
            <Button
              size="sm"
              onClick={() => void submitCreate()}
              disabled={busy || !familyKey}
              data-testid="proposal-apply-confirm"
            >
              {busy ? <Spinner size="sm" /> : t("taxonomy.jobProposals.applyConfirm")}
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>

      <Modal
        open={browsing !== null}
        onOpenChange={(open) => (!open ? setBrowsing(null) : undefined)}
        aria-label={t("taxonomy.jobProposals.browseCatalog")}
      >
        <ModalContent className="space-y-3">
          <div className="flex items-center gap-2">
            <Search className="h-4 w-4 text-[var(--as-accent)]" aria-hidden />
            <h2 className="text-sm font-semibold text-[var(--as-fg)]">
              {t("taxonomy.jobProposals.browseCatalog")}
            </h2>
          </div>
          <input
            value={browseQuery}
            onChange={(event) => {
              setBrowseQuery(event.target.value);
              void loadBrowse(event.target.value);
            }}
            placeholder={t("taxonomy.jobProposals.browseSearch")}
            className="w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm text-[var(--as-fg)]"
            data-testid="proposal-browse-search"
          />
          <div className="max-h-72 space-y-1 overflow-y-auto" data-testid="proposal-browse-results">
            {browseLoading ? (
              <Spinner size="sm" />
            ) : (
              browseResults.map((job) => (
                <Button
                  key={job.code}
                  variant="ghost"
                  size="sm"
                  className="w-full justify-start"
                  onClick={() => {
                    if (!browsing) return;
                    setBrowsing(null);
                    setMapping({ row: browsing, code: job.code, title: job.title });
                  }}
                  data-testid={`proposal-browse-job-${job.code}`}
                >
                  {job.title}
                  {job.family_label ? (
                    <span className="ml-2 text-[11px] text-[var(--as-muted-fg)]">
                      {job.family_label}
                    </span>
                  ) : null}
                </Button>
              ))
            )}
          </div>
        </ModalContent>
      </Modal>

      <ConfirmationModal
        open={mapping !== null}
        onOpenChange={(open) => (!open ? setMapping(null) : undefined)}
        onConfirm={() => void submitMap()}
        title={t("taxonomy.jobProposals.mapTitle")}
        description={t("taxonomy.jobProposals.mapMessage", {
          type: mapping?.row.proposal?.job_type ?? "",
          title: mapping?.title ?? "",
        })}
        confirmLabel={t("taxonomy.jobProposals.mapConfirm")}
      />

      <ConfirmationModal
        open={confirmingBulkDismiss}
        onOpenChange={setConfirmingBulkDismiss}
        onConfirm={() => {
          setConfirmingBulkDismiss(false);
          void runBulkDismiss();
        }}
        title={t("taxonomy.jobProposals.bulkDismissTitle", { count: selection.count })}
        description={t("taxonomy.jobProposals.bulkDismissBody")}
        confirmLabel={t("taxonomy.jobProposals.dismiss")}
        destructive
      />

      <ConfirmationModal
        open={dismissing !== null}
        onOpenChange={(open) => (!open ? setDismissing(null) : undefined)}
        onConfirm={() => {
          if (dismissing) void submitDismiss();
          setDismissing(null);
        }}
        title={t("taxonomy.jobProposals.dismissTitle")}
        description={t("taxonomy.jobProposals.dismissMessage", {
          title: dismissing?.proposal?.job_type ?? dismissing?.title ?? "",
        })}
        confirmLabel={t("taxonomy.jobProposals.dismiss")}
        destructive
      />
    </div>
  );
}
