import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Building2, Plus, X } from "lucide-react";
import {
  acceptSuggestion,
  addAlias,
  createExclusion,
  deleteExclusion,
  dismissSuggestion,
  fetchAliasRows,
  fetchExclusions,
  fetchOrganizations,
  fetchPairs,
  fetchSuggestions,
  fetchThresholds,
  removeAlias,
  saveThresholds,
  setAliasState,
  type MatchPairRow,
  type MatchThresholds,
  type MergeSuggestionRow,
  type OrgAliasRow,
  type OrgExclusionRow,
  type OrgRow,
} from "@/api/companyRules";
import { EmptyState, SegmentedTabs, SearchableDropdown, Spinner } from "@/components/ui";

export type CompanyTab = "suggestions" | "aliases" | "exclusions" | "queue" | "thresholds";

// Exported for the settings-tab conformance tests.
export const COMPANY_TABS: readonly CompanyTab[] = [
  "suggestions",
  "aliases",
  "exclusions",
  "queue",
  "thresholds",
];

export function parseCompanyTab(raw: string | null): CompanyTab {
  return (COMPANY_TABS as readonly string[]).includes(raw ?? "")
    ? (raw as CompanyTab)
    : "suggestions";
}

const TAB_LABEL_KEYS: Record<CompanyTab, string> = {
  suggestions: "companyRules.tabSuggestions",
  aliases: "companyRules.tabAliases",
  exclusions: "companyRules.tabExclusions",
  queue: "companyRules.tabQueue",
  thresholds: "companyRules.tabThresholds",
};

/** Admin company rules: aliases, exclusions, the gray-band queue, merge
 * suggestions and matcher thresholds (plan 135). */
export function CompanyRules() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = parseCompanyTab(searchParams.get("tab"));

  useEffect(() => {
    const expected = tab === "suggestions" ? null : tab;
    if (searchParams.get("tab") === expected) return;
    const next = new URLSearchParams(searchParams);
    if (expected) next.set("tab", expected);
    else next.delete("tab");
    setSearchParams(next, { replace: true });
  }, [tab, searchParams, setSearchParams]);

  const tabs = useMemo(
    () => COMPANY_TABS.map((value) => ({ value, label: t(TAB_LABEL_KEYS[value]) })),
    [t]
  );

  return (
    <div className="space-y-6" data-testid="company-rules-page">
      <div>
        <h2 className="text-xl font-bold text-slate-900">{t("companyRules.title")}</h2>
        <p className="text-sm text-slate-500 mt-1">{t("companyRules.intro")}</p>
      </div>
      <SegmentedTabs
        ariaLabel={t("companyRules.title")}
        items={tabs}
        value={tab}
        onValueChange={(value) => {
          const nextParams = new URLSearchParams(searchParams);
          if (value === "suggestions") nextParams.delete("tab");
          else nextParams.set("tab", value);
          setSearchParams(nextParams, { replace: true });
        }}
      />
      {tab === "suggestions" && <SuggestionsTab />}
      {tab === "aliases" && <AliasesTab />}
      {tab === "exclusions" && <ExclusionsTab />}
      {tab === "queue" && <QueueTab />}
      {tab === "thresholds" && <ThresholdsTab />}
    </div>
  );
}

function SuggestionsTab() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<MergeSuggestionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await fetchSuggestions("open"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (id: string, action: "accept" | "dismiss") => {
    try {
      if (action === "accept") {
        await acceptSuggestion(id);
        setNote(t("companyRules.merged"));
      } else {
        await dismissSuggestion(id);
        setNote(t("companyRules.excluded"));
      }
      await load();
    } catch {
      setNote(t("companyRules.actionFailed"));
    }
  };

  if (loading) return <Spinner />;
  if (rows.length === 0)
    return (
      <EmptyState
        icon={Building2}
        compact
        title={t("companyRules.noSuggestionsTitle")}
        description={t("companyRules.noSuggestionsBody")}
      />
    );
  return (
    <div className="space-y-3">
      {note && <p className="text-sm text-primary-700">{note}</p>}
      {rows.map((row) => (
        <div
          key={row.id}
          className="bg-white border border-slate-200 rounded-xl p-4 space-y-2"
          data-testid={`suggestion-card-${row.id}`}
        >
          <div className="flex items-center justify-between gap-2">
            <p className="font-medium text-slate-900">
              {row.org_a?.name ?? row.label}
              <span className="text-slate-400 mx-2">→</span>
              {row.org_b?.name}
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => act(row.id, "accept")}
                className="text-sm px-3 py-1.5 rounded-lg bg-primary-600 text-white"
                data-testid={`suggestion-accept-${row.id}`}
              >
                {t("companyRules.merge")}
              </button>
              <button
                onClick={() => act(row.id, "dismiss")}
                className="text-sm px-3 py-1.5 rounded-lg border border-slate-200"
                data-testid={`suggestion-dismiss-${row.id}`}
              >
                {t("companyRules.keepSeparate")}
              </button>
            </div>
          </div>
          <p className="text-sm text-slate-500">
            {t("companyRules.label")}: {row.label}
            {row.score ? ` · ${t("companyRules.confidence")}: ${Math.round(row.score * 100)}%` : ""}
            {row.reason ? ` · ${row.reason}` : ""}
          </p>
          <p className="text-xs text-slate-400">{t("companyRules.dismissHint")}</p>
        </div>
      ))}
    </div>
  );
}

function AliasesTab() {
  const { t } = useTranslation();
  const [orgs, setOrgs] = useState<OrgRow[]>([]);
  const [orgId, setOrgId] = useState("");
  const [rows, setRows] = useState<OrgAliasRow[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void fetchOrganizations()
      .then(setOrgs)
      .catch(() => setError(t("companyRules.loadFailed")));
  }, [t]);

  const orgOptions = useMemo(
    () => orgs.map((org) => ({ value: org.id, label: org.name })),
    [orgs]
  );

  const load = useCallback(async (id: string) => {
    if (!id) {
      setRows([]);
      return;
    }
    setLoading(true);
    try {
      setRows(await fetchAliasRows(id));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(orgId);
  }, [orgId, load]);

  const selected = orgs.find((org) => org.id === orgId);

  const mutate = async (action: () => Promise<unknown>) => {
    try {
      await action();
      await load(orgId);
    } catch {
      setError(t("companyRules.actionFailed"));
    }
  };

  return (
    <div className="space-y-4" data-testid="rules-aliases">
      <SearchableDropdown
        options={orgOptions}
        value={orgId}
        onChange={setOrgId}
        placeholder={t("companyRules.pickCompany")}
      />
      {selected && (
        <p className="text-xs text-slate-400">
          {selected.name} · {selected.status} · {selected.posting_count}{" "}
          {t("companyRules.postings")}
        </p>
      )}
      {error && <p className="text-sm text-rose-600">{error}</p>}
      {orgId && (
        <div className="flex gap-2">
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={t("companyRules.newAlias")}
            className="flex-1 text-sm border border-slate-200 rounded-lg px-3 py-2"
            data-testid="alias-input"
          />
          <button
            onClick={() =>
              mutate(async () => {
                if (!draft.trim()) return;
                setRows(await addAlias(orgId, draft.trim()));
                setDraft("");
              })
            }
            className="text-sm px-3 py-2 rounded-lg bg-primary-600 text-white flex items-center gap-1"
            data-testid="alias-add"
          >
            <Plus className="w-4 h-4" /> {t("companyRules.add")}
          </button>
        </div>
      )}
      {loading ? (
        <Spinner />
      ) : (
        rows.map((row) => (
          <div
            key={row.id}
            className={`bg-white border rounded-xl px-4 py-3 flex items-center justify-between gap-2 ${
              row.state === "excluded" ? "border-slate-200 opacity-60" : "border-slate-200"
            }`}
            data-testid={`alias-row-${row.alias}`}
          >
            <div>
              <p className="text-sm font-medium text-slate-900">{row.alias}</p>
              <p className="text-xs text-slate-400">
                {row.source} · {row.state}
              </p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() =>
                  mutate(() =>
                    setAliasState(orgId, row.id, row.state === "active" ? "excluded" : "active")
                  )
                }
                className="text-xs px-2 py-1 rounded-lg border border-slate-200"
                data-testid={`alias-toggle-${row.id}`}
              >
                {row.state === "active"
                  ? t("companyRules.exclude")
                  : t("companyRules.reactivate")}
              </button>
              <button
                onClick={() => mutate(() => removeAlias(orgId, row.id))}
                className="text-xs px-2 py-1 rounded-lg border border-slate-200"
                data-testid={`alias-remove-${row.id}`}
                aria-label={t("companyRules.remove")}
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        ))
      )}
      {orgId && !loading && rows.length === 0 && (
        <p className="text-sm text-slate-500">{t("companyRules.noAliases")}</p>
      )}
    </div>
  );
}

function ExclusionsTab() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<OrgExclusionRow[]>([]);
  const [draftLabel, setDraftLabel] = useState("");
  const [draftReason, setDraftReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await fetchExclusions());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const globals = rows.filter((row) => row.org_id === null);
  const pairs = rows.filter((row) => row.org_id !== null);

  const add = async () => {
    if (!draftLabel.trim()) return;
    try {
      await createExclusion({ label: draftLabel.trim(), reason: draftReason.trim() });
      setDraftLabel("");
      setDraftReason("");
      await load();
    } catch {
      setError(t("companyRules.actionFailed"));
    }
  };

  if (loading) return <Spinner />;
  return (
    <div className="space-y-6" data-testid="rules-exclusions">
      <div className="space-y-2">
        <p className="text-sm font-medium text-slate-700">{t("companyRules.addExclusion")}</p>
        <div className="flex gap-2">
          <input
            value={draftLabel}
            onChange={(event) => setDraftLabel(event.target.value)}
            placeholder={t("companyRules.exclusionLabel")}
            className="flex-1 text-sm border border-slate-200 rounded-lg px-3 py-2"
            data-testid="exclusion-label-input"
          />
          <input
            value={draftReason}
            onChange={(event) => setDraftReason(event.target.value)}
            placeholder={t("companyRules.exclusionReason")}
            className="w-48 text-sm border border-slate-200 rounded-lg px-3 py-2"
            data-testid="exclusion-reason-input"
          />
          <button
            onClick={add}
            className="text-sm px-3 py-2 rounded-lg bg-primary-600 text-white flex items-center gap-1"
            data-testid="exclusion-add"
          >
            <Plus className="w-4 h-4" /> {t("companyRules.add")}
          </button>
        </div>
        {error && <p className="text-sm text-rose-600">{error}</p>}
      </div>

      <section className="space-y-2">
        <p className="text-sm font-medium text-slate-700">{t("companyRules.globalExclusions")}</p>
        {globals.map((row) => (
          <ExclusionRowCard key={row.id} row={row} onRemove={deleteExclusion} reload={load} />
        ))}
        {globals.length === 0 && <p className="text-sm text-slate-500">{t("companyRules.none")}</p>}
      </section>

      <section className="space-y-2">
        <p className="text-sm font-medium text-slate-700">{t("companyRules.pairExclusions")}</p>
        {pairs.map((row) => (
          <ExclusionRowCard key={row.id} row={row} onRemove={deleteExclusion} reload={load} />
        ))}
        {pairs.length === 0 && <p className="text-sm text-slate-500">{t("companyRules.none")}</p>}
      </section>
    </div>
  );
}

function ExclusionRowCard({
  row,
  onRemove,
  reload,
}: {
  row: OrgExclusionRow;
  onRemove: (id: string) => Promise<void>;
  reload: () => Promise<void>;
}) {
  const { t } = useTranslation();
  return (
    <div
      className="bg-white border border-slate-200 rounded-xl px-4 py-3 flex items-center justify-between gap-2"
      data-testid={`exclusion-row-${row.label_key}`}
    >
      <div>
        <p className="text-sm font-medium text-slate-900">{row.label}</p>
        <p className="text-xs text-slate-400">
          {row.org ? `${t("companyRules.neverLinks")} ${row.org.name}` : t("companyRules.notACompany")}
          {row.reason ? ` · ${row.reason}` : ""}
        </p>
      </div>
      <button
        onClick={async () => {
          await onRemove(row.id);
          await reload();
        }}
        className="text-xs px-2 py-1 rounded-lg border border-slate-200"
        data-testid={`exclusion-remove-${row.id}`}
        aria-label={t("companyRules.remove")}
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

function QueueTab() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<MatchPairRow[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await fetchPairs("pending"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <Spinner />;
  if (rows.length === 0)
    return (
      <EmptyState
        icon={Building2}
        compact
        title={t("companyRules.queueEmptyTitle")}
        description={t("companyRules.queueEmptyBody")}
      />
    );
  return (
    <div className="space-y-3" data-testid="rules-queue">
      {rows.map((row) => (
        <div
          key={row.id}
          className="bg-white border border-slate-200 rounded-xl px-4 py-3"
          data-testid={`pair-row-${row.id}`}
        >
          <p className="text-sm font-medium text-slate-900">{row.label}</p>
          <p className="text-xs text-slate-400">
            {t("companyRules.candidate")}: {row.candidate?.name}
          </p>
        </div>
      ))}
    </div>
  );
}

function ThresholdsTab() {
  const { t } = useTranslation();
  const [values, setValues] = useState<MatchThresholds | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    void fetchThresholds()
      .then(setValues)
      .catch(() => setError(t("companyRules.loadFailed")));
  }, [t]);

  if (!values) return error ? <p className="text-sm text-rose-600">{error}</p> : <Spinner />;

  const fields: { key: keyof MatchThresholds; label: string }[] = [
    { key: "match", label: t("companyRules.thresholdMatch") },
    { key: "gray_low", label: t("companyRules.thresholdGray") },
    { key: "llm_auto", label: t("companyRules.thresholdLlm") },
  ];

  return (
    <div className="space-y-4 max-w-md" data-testid="rules-thresholds">
      {fields.map(({ key, label }) => (
        <label key={key} className="block space-y-1">
          <span className="text-sm text-slate-700">{label}</span>
          <input
            type="number"
            step="0.01"
            min="0"
            max="1"
            value={values[key]}
            onChange={(event) =>
              setValues({ ...values, [key]: Number(event.target.value) } as MatchThresholds)
            }
            className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2"
            data-testid={`threshold-${key}`}
          />
        </label>
      ))}
      <button
        onClick={async () => {
          try {
            setValues(await saveThresholds(values));
            setNote(t("companyRules.saved"));
            setError("");
          } catch {
            setError(t("companyRules.actionFailed"));
            setNote("");
          }
        }}
        className="text-sm px-4 py-2 rounded-lg bg-primary-600 text-white"
        data-testid="thresholds-save"
      >
        {t("companyRules.save")}
      </button>
      {note && <p className="text-sm text-primary-700">{note}</p>}
      {error && <p className="text-sm text-rose-600">{error}</p>}
    </div>
  );
}
