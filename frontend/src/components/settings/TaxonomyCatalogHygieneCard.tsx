import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Merge } from "lucide-react";

import {
  Button,
  ConfirmationModal,
  Spinner,
} from "@/components/ui";
import {
  fetchDuplicateJobTypes,
  mergeJobTypes,
  type DuplicateJobTypeGroup,
} from "@/api/taxonomy";
import { apiDetail } from "@/api/client";

/** Catalog hygiene (plan 202 S7): duplicate published job types retired
 * into a survivor with every dependent repointed. Admin-only. */
export function TaxonomyCatalogHygieneCard({ onDone }: { onDone?: (note: string) => void }) {
  const { t } = useTranslation();
  const [groups, setGroups] = useState<DuplicateJobTypeGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [survivors, setSurvivors] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState<{
    group: DuplicateJobTypeGroup;
    sourceId: string;
    targetId: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await fetchDuplicateJobTypes();
      setGroups(payload.groups);
      setSurvivors((previous) => {
        const next = { ...previous };
        for (const group of payload.groups) {
          if (!next[group.normalized_title]) {
            next[group.normalized_title] = group.jobs[0]?.id ?? "";
          }
        }
        return next;
      });
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const submit = async () => {
    if (!confirming) return;
    setBusy(true);
    setError("");
    try {
      const result = await mergeJobTypes(confirming.sourceId, confirming.targetId);
      setConfirming(null);
      onDone?.(
        t("taxonomy.catalogHygiene.mergedNote", {
          count: result.postings,
          remap: result.remap_queued,
        }),
      );
      await load();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-[var(--as-muted-fg)]">
        <Spinner size="sm" /> {t("common.loading")}
      </div>
    );
  }
  if (groups.length === 0) return null;

  return (
    <section className="space-y-2" data-testid="catalog-hygiene">
      <h2 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
        {t("taxonomy.catalogHygiene.title")}
      </h2>
      {error ? <p className="text-sm text-rose-600">{error}</p> : null}
      {groups.map((group) => {
        const survivor = survivors[group.normalized_title] ?? "";
        return (
          <div
            key={group.normalized_title}
            className="space-y-2 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
            data-testid={`catalog-hygiene-group-${group.normalized_title}`}
          >
            <p className="text-sm font-medium text-[var(--as-fg)]">
              {t("taxonomy.catalogHygiene.groupHeading", {
                title: group.jobs[0]?.title ?? group.normalized_title,
              })}
            </p>
            <div className="flex flex-wrap items-center gap-3">
              {group.jobs.map((job) => (
                <label
                  key={job.id}
                  className="flex items-center gap-1.5 text-xs text-[var(--as-fg)]"
                >
                  <input
                    type="radio"
                    name={`survivor-${group.normalized_title}`}
                    checked={survivor === job.id}
                    onChange={() =>
                      setSurvivors((previous) => ({
                        ...previous,
                        [group.normalized_title]: job.id,
                      }))
                    }
                    data-testid={`catalog-hygiene-survivor-${job.code}`}
                  />
                  <span className="font-mono">{job.code}</span>
                  <span className="text-[var(--as-muted-fg)]">
                    {t("taxonomy.catalogHygiene.postings", { count: job.posting_count })}
                  </span>
                </label>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              {group.jobs
                .filter((job) => job.id !== survivor)
                .map((job) => (
                  <Button
                    key={job.code}
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      setConfirming({
                        group,
                        sourceId: job.id,
                        targetId: survivor,
                      })
                    }
                    data-testid={`catalog-hygiene-merge-${job.code}`}
                  >
                    <Merge className="h-3.5 w-3.5" aria-hidden />
                    {t("taxonomy.catalogHygiene.mergeInto", {
                      code: group.jobs.find((entry) => entry.id === survivor)?.code ?? "",
                    })}
                  </Button>
                ))}
            </div>
          </div>
        );
      })}

      <ConfirmationModal
        open={confirming !== null}
        onOpenChange={(open) => (!open ? setConfirming(null) : undefined)}
        onConfirm={() => void submit()}
        title={t("taxonomy.catalogHygiene.confirmTitle")}
        description={t("taxonomy.catalogHygiene.confirmBody", {
          source:
            confirming?.group.jobs.find((job) => job.id === confirming.sourceId)?.code ?? "",
          target:
            confirming?.group.jobs.find((job) => job.id === confirming.targetId)?.code ?? "",
        })}
        confirmLabel={t("taxonomy.catalogHygiene.confirm")}
        destructive
        busy={busy}
      />
    </section>
  );
}
