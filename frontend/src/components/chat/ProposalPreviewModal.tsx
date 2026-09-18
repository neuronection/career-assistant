import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Eye } from "lucide-react";

import { PanelModal, SegmentedTabs, Spinner } from "@/components/ui";
import type { ProfileProposalCardData } from "@/types";
import { useProfileProposalsStore, PREVIEW_KINDS } from "@/stores/profileProposalsStore";
import { ExperienceItemCard } from "@/components/experience/ExperienceItemCard";
import { ProfileSnapshotCard } from "@/components/chat/ProfileSnapshotCard";
import { normalizeProse } from "@/lib/prose";
import type {
  CvSynthSourceRow,
  ProfileProposalPreviewData,
  ProfileProposalPreviewEdits,
} from "@/api/profileProposals";

/** CV source key → snapshot-card kind (plan 101: stacked source rows use
 * the same per-kind renderers as the edit preview). */
const SYNTH_PROFILE_KINDS: Record<string, string> = {
  experience: "experience_item",
  projects: "experience_item",
  volunteer: "experience_item",
  education: "education_item",
  certifications: "certification",
  achievements: "profile_achievement",
};

const SNAPSHOT_FIELDS: Record<string, string[]> = {
  education_item: [
    "institution",
    "program",
    "level",
    "start",
    "end",
    "in_progress",
    "description",
  ],
  certification: ["name", "issuer", "issued", "expires", "credential_id", "link"],
  profile_achievement: ["kind", "title", "issuer", "date", "detail", "link"],
};

/** Description spans each side highlights (plan 99): `replace` marks the
 * find in before / the replacement in after, appends/prepends mark the
 * inserted sentence in after only (first line — long appends fold). */
export function markTerms(
  edits: ProfileProposalPreviewEdits | undefined,
  side: "before" | "after",
): string[] {
  const terms: string[] = [];
  for (const edit of edits?.text_edits ?? []) {
    if (side === "before") {
      if (edit.op === "replace" && edit.find) terms.push(edit.find);
    } else {
      terms.push(edit.text.split("\n")[0]);
    }
  }
  return [...new Set(terms.filter(Boolean))];
}

type Snapshot = Record<string, unknown>;

function experienceCardData(snapshot: Snapshot | null) {
  if (!snapshot) return null;
  const skillsRaw = Array.isArray(snapshot.skills)
    ? (snapshot.skills as Snapshot[])
    : [];
  return {
    id: "preview",
    title: String(snapshot.title ?? ""),
    kind: String(snapshot.kind ?? ""),
    org_name: (snapshot.org_name as string | undefined) ?? null,
    start: (snapshot.start as string | undefined) ?? null,
    end: (snapshot.end as string | undefined) ?? null,
    open_ended: Boolean(snapshot.open_ended),
    hours_per_week: (snapshot.hours_per_week as number | undefined) ?? null,
    status: String(snapshot.status ?? "active"),
    description: (snapshot.description as string | undefined) ?? "",
    achievements: Array.isArray(snapshot.achievements)
      ? (snapshot.achievements as { text: string }[])
      : [],
    skills: skillsRaw.map((row) => ({
      skill_key: String(row.skill_key ?? ""),
      skill_label: String(row.skill_label ?? row.skill_key ?? ""),
      role_in_item: row.role_in_item as string | undefined,
    })),
  };
}

function GenericSnapshot({
  snapshot,
  kind,
}: {
  snapshot: Snapshot | null;
  kind: string;
}) {
  const { t } = useTranslation();
  const fields = SNAPSHOT_FIELDS[kind] ?? [];
  if (!snapshot) return null;
  const rows = Object.entries(snapshot).filter(
    ([key, value]) =>
      value !== null &&
      value !== "" &&
      !(Array.isArray(value) && value.length === 0) &&
      (fields.length === 0
        ? !Array.isArray(value) && typeof value !== "object"
        : fields.includes(key)),
  );
  if (rows.length === 0) {
    return null;
  }
  return (
    <ul className="flex flex-col gap-1.5 rounded-xl border border-[var(--as-border)] p-2.5 text-xs">
      {rows.map(([key, value]) => (
        <li key={key} className="grid grid-cols-[7rem_1fr] items-baseline gap-2">
          <span
            className="truncate text-[var(--as-muted-fg)]"
            title={key}
            data-testid={`hitl-preview-field-${key}`}
          >
            {t(`chat.proposals.fields.${key}`, {
              defaultValue: key.replace(/_/g, " "),
            })}
          </span>
          <span className="break-words whitespace-pre-line text-[var(--as-fg)]">
            {typeof value === "string" ? normalizeProse(value) : String(value)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState<boolean>(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(query).matches
      : false,
  );
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return undefined;
    }
    const list = window.matchMedia(query);
    const onChange = () => setMatches(list.matches);
    setMatches(list.matches);
    list.addEventListener?.("change", onChange);
    return () => list.removeEventListener?.("change", onChange);
  }, [query]);
  return matches;
}

/**
 * The plan-99 rendered before/after preview (ADR-006 tier 3): the
 * library owns the preview slot, the app owns what a preview IS. Shows
 * the real item card(s) with the changed span highlighted; before/after
 * side-by-side when the viewport is wide, a SegmentedTabs toggle
 * otherwise. Creates render after-only, deletes before-only with the
 * destructive tint. Payloads lazy-fetch through the store's transient
 * cache; a 404 shows "unavailable".
 */
export function ProposalPreviewModal({
  proposal,
  onClose,
}: {
  proposal: ProfileProposalCardData | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const loadPreview = useProfileProposalsStore((s) => s.loadPreview);
  const entry = useProfileProposalsStore((s) =>
    proposal ? s.previews[proposal.id] : undefined,
  );
  const wide = useMediaQuery("(min-width: 64rem)");
  const [side, setSide] = useState<"before" | "after">("after");

  useEffect(() => {
    if (proposal) {
      setSide("after");
      void loadPreview(proposal.id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [proposal?.id]);

  const data: ProfileProposalPreviewData | null =
    entry?.state === "ready" ? entry.data : null;
  const isCreate = proposal?.action === "create";
  const isDelete = proposal?.action === "delete";
  const kind = proposal?.kind ?? "";
  // Plan 101 AD2: the cv_synth preview branches on KIND, not action —
  // its create action would otherwise render the before-only payload
  // through the "after-only" path with nothing to show.
  const isSynth =
    kind === "cv_synth" && Array.isArray(data?.before)
      ? ((data?.before ?? []) as CvSynthSourceRow[])
      : null;
  const singleSide = Boolean(isCreate || isDelete) && !isSynth;
  const usesItemCard = kind === "experience_item";
  const usesProfileCard = ["education_item", "certification", "profile_achievement"].includes(
    kind,
  );

  const hasBefore = useMemo(
    () => Boolean(!isCreate && data?.before),
    [isCreate, data],
  );
  void hasBefore;
  const hasAfter = useMemo(() => Boolean(!isDelete || !data), [isDelete, data]);
  void hasAfter;

  const highlightBefore = markTerms(data?.edits, "before");
  const highlightAfter = markTerms(data?.edits, "after");

  const renderSide = (which: "before" | "after") => {
    const raw = which === "before" ? data?.before : data?.after;
    const snapshot: Snapshot | null =
      raw && !Array.isArray(raw) ? (raw as Snapshot) : null;
    const highlight = which === "before" ? highlightBefore : highlightAfter;
    const destructive = Boolean(isDelete && which === "before");
    const label =
      which === "before"
        ? t("chat.proposals.previewBefore")
        : t("chat.proposals.previewAfter");
    return (
      <section
        className={`min-w-0 rounded-xl border p-2.5 ${
          destructive
            ? "border-[var(--as-danger)] bg-[color-mix(in_srgb,var(--as-danger)_6%,transparent)]"
            : "border-[var(--as-border)]"
        }`}
        data-testid={`hitl-preview-${which}`}
      >
        <h3
          className={`mb-2 flex items-center gap-1 text-xs font-semibold uppercase tracking-wide ${
            destructive ? "text-[var(--as-danger)]" : "text-[var(--as-muted-fg)]"
          }`}
        >
          {label}
        </h3>
        {usesProfileCard && snapshot ? (
          <ProfileSnapshotCard
            snapshot={snapshot}
            kind={kind}
            highlight={highlight}
            testId={`hitl-preview-${which}-card`}
          />
        ) : usesItemCard && snapshot ? (
          <ExperienceItemCard
            item={experienceCardData(snapshot)!}
            highlight={highlight}
            showAchievements
            testId={`hitl-preview-${which}-card`}
          />
        ) : (
          <GenericSnapshot snapshot={snapshot} kind={kind} />
        )}
      </section>
    );
  };

  const renderSynthRow = (row: CvSynthSourceRow, index: number) => {
    const highlight = highlightBefore;
    const snapshot = (row.snapshot ?? null) as Snapshot | null;
    const itemCard =
      ["experience", "projects", "volunteer"].includes(row.source_key) &&
      snapshot
        ? (
          <ExperienceItemCard
            item={experienceCardData(snapshot)!}
            highlight={highlight}
            showAchievements
            testId={`hitl-preview-card-${index}`}
          />
        )
        : null;
    return (
      <section
        key={`${row.source_key}-${row.item_id}`}
        className="min-w-0 rounded-xl border border-[var(--as-border)] p-2.5"
        data-testid={`hitl-preview-source-${row.source_key}`}
      >
        <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
          {row.label}
          {row.snapshot ? (
            <span className="text-[var(--as-border)]">·</span>
          ) : null}
          {row.snapshot ? (
            <span className="font-normal normal-case tracking-normal">
              {t(`chat.proposals.sourceKinds.${row.source_key}`, {
                defaultValue: row.source_key,
              })}
            </span>
          ) : null}
        </h3>
        {snapshot ? (
          row.source_key === "posting" ? (
            <GenericSnapshot snapshot={snapshot} kind="posting" />
          ) : itemCard ?? (
            <ProfileSnapshotCard
              snapshot={snapshot}
              kind={SYNTH_PROFILE_KINDS[row.source_key] ?? kind}
              highlight={highlight}
              testId={`hitl-preview-card-${index}`}
            />
          )
        ) : (
          <p className="text-[var(--as-muted-fg)]">
            {t("chat.proposals.previewSourceMissing")}
          </p>
        )}
      </section>
    );
  };

  return (
    <PanelModal
      open={proposal !== null}
      onOpenChange={(open) => !open && onClose()}
      title={
        <span className="inline-flex items-center gap-1.5">
          <Eye className="size-3.5" aria-hidden />
          {proposal ? proposal.title : ""}
        </span>
      }
      size="xl"
      data-testid="hitl-preview-modal"
    >
      {!entry ? (
        <p
          className="flex items-center justify-center gap-2 py-10 text-sm text-[var(--as-muted-fg)]"
          data-testid="hitl-preview-loading"
        >
          <Spinner size="sm" /> {t("chat.proposals.previewLoading")}
        </p>
      ) : entry.state === "missing" || !data ? (
        <p
          className="py-10 text-center text-sm text-[var(--as-muted-fg)]"
          data-testid="hitl-preview-missing"
        >
          {t("chat.proposals.previewUnavailable")}
        </p>
      ) : isSynth ? (
        <div className="flex min-h-0 flex-col gap-3">
          <h2
            className="text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]"
            data-testid="hitl-preview-sources-heading"
          >
            {t("chat.proposals.previewVariantSources")}
          </h2>
          <div className="flex flex-col gap-3" data-testid="hitl-preview-content">
            {isSynth.map(renderSynthRow)}
          </div>
          <p className="text-xs text-[var(--as-muted-fg)]" data-testid="hitl-preview-variant-note">
            {t("chat.proposals.previewVariantNote")}
          </p>
        </div>
      ) : (
        <div className="flex min-h-0 flex-col gap-3">
          {!singleSide ? (
            <SegmentedTabs
              ariaLabel={t("chat.proposals.previewToggleAria")}
              items={[
                { value: "before", label: t("chat.proposals.previewBefore") },
                { value: "after", label: t("chat.proposals.previewAfter") },
              ]}
              value={side}
              onValueChange={(next) => setSide(next as "before" | "after")}
              className="max-w-xs"
            />
          ) : null}
          {singleSide && isDelete ? (
            <div className="flex flex-col gap-3" data-testid="hitl-preview-content">
              {renderSide("before")}
            </div>
          ) : singleSide ? (
            <div className="flex flex-col gap-3" data-testid="hitl-preview-content">
              {renderSide("after")}
            </div>
          ) : wide ? (
            <div
              className="grid grid-cols-2 items-start gap-3"
              data-testid="hitl-preview-content"
            >
              {hasBefore ? renderSide("before") : null}
              {renderSide("after")}
            </div>
          ) : (
            <div className="flex flex-col gap-3" data-testid="hitl-preview-content">
              {side === "before" && hasBefore ? renderSide("before") : null}
              {side === "after" ? renderSide("after") : null}
            </div>
          )}
        </div>
      )}
    </PanelModal>
  );
}

export { PREVIEW_KINDS };
