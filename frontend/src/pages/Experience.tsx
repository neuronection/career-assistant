import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Trash2 } from "lucide-react";
import {
  ArrowLeft,
  CalendarRange,
  Plus,
  Search,
  ChevronRight,
} from "lucide-react";
import { Button, ConfirmationModal, SegmentedTabs } from "@/components/ui";
import { UndoNotice } from "@neuronection/assistant-ui";
import { apiDetail } from "@/api/client";
import { fetchSkillOntology } from "@/api/skills";
import type { SkillSummary } from "@/api/skills";
import {
  applyDerivation,
  createExperienceItem,
  deleteExperienceItem,
  fetchDerivation,
  fetchExperience,
  updateExperienceItem,
} from "@/api/experience";
import type {
  DerivedSkillOut,
  ExperienceItemIn,
  ExperienceItemOut,
} from "@/types/experience";
import {
  BulkBar,
  FilterChips,
  SelectionToggle,
} from "@/components/profile/BulkTools";
import {
  EMPTY_FORM,
  ExperienceEditor,
  KIND_ICONS,
  formFromItem,
  validateExperience,
} from "@/components/experience/ExperienceEditor";
import { ExperienceItemCard } from "@/components/experience/ExperienceItemCard";

function toIn(item: ExperienceItemOut): ExperienceItemIn {
  return {
    title: item.title,
    kind: item.kind,
    org_name: item.org_name,
    start: item.start,
    end: item.open_ended ? null : item.end,
    open_ended: item.open_ended,
    hours_per_week: item.hours_per_week,
    onsite_policy: (item.onsite_policy as ExperienceItemIn["onsite_policy"]) ?? null,
    description: item.description,
    links: item.links,
    source: "self_report",
    status: item.status,
    skills: item.skills.map((s) => ({
      skill_key: s.skill_key,
      role_in_item: s.role_in_item,
      level_claim: s.level_claim,
      last_used: s.last_used,
    })),
    achievements: item.achievements.map((a) => ({ text: a.text, metric: null })),
  };
}

function sortByRecency(items: ExperienceItemOut[]): ExperienceItemOut[] {
  return [...items].sort((a, b) => {
    if (a.open_ended !== b.open_ended) return a.open_ended ? -1 : 1;
    return (b.start ?? "").localeCompare(a.start ?? "");
  });
}

/** Experience workspace: full-bleed master-detail with an
 * editor pane, optimistic delete + undo, per-item + bulk selection
 * (set status / delete), duplicates and search/status/kind filters. */
export function Experience() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [items, setItems] = useState<ExperienceItemOut[]>([]);
  const [years, setYears] = useState(0);
  const [derived, setDerived] = useState<DerivedSkillOut[]>([]);
  const [skillOptions, setSkillOptions] = useState<
    { key: string; label: string }[]
  >([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [isNew, setIsNew] = useState(false);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [dirty, setDirty] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [applyState, setApplyState] = useState<string | null>(null);
  const [tab, setTab] = useState<"entries" | "skills">("entries");
  const [deleted, setDeleted] = useState<ExperienceItemOut[] | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [bulkConfirm, setBulkConfirm] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [filters, setFilters] = useState<{ query: string; statuses: string[]; kinds: string[] }>({
    query: "",
    statuses: [],
    kinds: [],
  });
  const [collapsedGroups, setCollapsedGroups] = useState<string[]>([]);

  const shouldGroup = filters.kinds.length === 0;

  const visible = useMemo(() => {
    const query = filters.query.trim().toLowerCase();
    return items.filter((item) => {
      if (query &&
        !`${item.title} ${item.org_name}`.toLowerCase().includes(query)
      ) {
        return false;
      }
      if (filters.statuses.length && !filters.statuses.includes(item.status)) {
        return false;
      }
      if (filters.kinds.length && !filters.kinds.includes(item.kind)) {
        return false;
      }
      return true;
    });
  }, [items, filters]);

  const renderCard = (item: ExperienceItemOut) => (
    <ExperienceItemCard
      key={item.id}
      item={item}
      active={item.id === selectedId}
      focused={item.id === focusedId}
      onOpen={() => guard(() => openEdit(item))}
      onDuplicate={() => void duplicate(item)}
      onDelete={() => void remove(item)}
      selectSlot={
        <SelectionToggle
          selected={selectedIds.includes(item.id)}
          label={t("experience.selectAria", { title: item.title })}
          onToggle={() => toggleSelect(item.id)}
        />
      }
    />
  );
  const [confirmAction, setConfirmAction] = useState<(() => void) | null>(null);
  const [activePane, setActivePane] = useState<"list" | "editor">("list");
  const railRef = useRef<HTMLDivElement>(null);
  const editorPaneRef = useRef<HTMLDivElement>(null);

  const switchPane = (pane: "list" | "editor") => {
    setActivePane(pane);
    requestAnimationFrame(() => {
      (pane === "list" ? railRef.current : editorPaneRef.current)?.focus();
    });
  };

  const load = useCallback(async () => {
    const [list, derivation] = await Promise.all([
      fetchExperience(),
      fetchDerivation(),
    ]);
    const sorted = sortByRecency(list.items);
    setItems(sorted);
    setYears(list.years_of_experience);
    setDerived(derivation.skills);
    return sorted;
  }, []);

  const refreshDerived = useCallback(async () => {
    try {
      const derivation = await fetchDerivation();
      setYears(derivation.years_of_experience);
      setDerived(derivation.skills);
    } catch {
      void undefined;
    }
  }, []);

  /** Skill estimates apply themselves after any experience mutation —
   * the panel is a summary, not a manual action surface (plan 68.4). */
  const syncDerivation = useCallback(async () => {
    try {
      const result = await applyDerivation();
      setApplyState(
        result.conflicts.length > 0
          ? t("experience.appliedWithConflicts", {
              count: result.applied,
              conflicts: result.conflicts.length,
            })
          : result.applied > 0
            ? t("experience.appliedClean", { count: result.applied })
            : null
      );
      await refreshDerived();
    } catch {
      void undefined;
    }
  }, [t, refreshDerived]);

  useEffect(() => {
    let cancelled = false;
    void load()
      .then((sorted) => {
        if (cancelled) return;
        const focusId = searchParams.get("focus");
        if (!focusId) return;
        const item = sorted.find((row) => row.id === focusId);
        if (item) {
          openEdit(item);
          setFocusedId(item.id);
        }
        setSearchParams({}, { replace: true });
      })
      .catch((err) => setError(apiDetail(err)));
    void fetchSkillOntology()
      .then((rows: SkillSummary[]) =>
        setSkillOptions(rows.map((s) => ({ key: s.key, label: s.label })))
      )
      .catch(() => setSkillOptions([]));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load]);

  useEffect(() => {
    if (!focusedId) return;
    const timer = setTimeout(() => setFocusedId(null), 2500);
    return () => clearTimeout(timer);
  }, [focusedId]);

  const skillChoices = useMemo(() => {
    const base = skillOptions.map((o) => ({ value: o.key, label: o.label }));
    const known = new Set(base.map((o) => o.value));
    for (const item of items) {
      for (const s of item.skills) {
        if (!known.has(s.skill_key)) {
          base.push({ value: s.skill_key, label: s.skill_label });
          known.add(s.skill_key);
        }
      }
    }
    return base;
  }, [skillOptions, items]);

  const guard = (action: () => void) => {
    if (dirty) setConfirmAction(() => action);
    else action();
  };

  const discardAnd = (action: () => void) => {
    setConfirmAction(null);
    action();
  };

  const closeEditor = () => {
    setEditorOpen(false);
    setSelectedId(null);
    setIsNew(false);
    setForm({ ...EMPTY_FORM });
    setDirty(false);
    setShowErrors(false);
    setActivePane("list");
  };

  const openCreate = (kind?: ExperienceItemIn["kind"]) => {
    setForm({ ...EMPTY_FORM, ...(kind ? { kind } : {}) });
    setSelectedId(null);
    setIsNew(true);
    setEditorOpen(true);
    setDirty(false);
    setShowErrors(false);
    setActivePane("editor");
  };

  const openEdit = (item: ExperienceItemOut) => {
    setForm(formFromItem(item));
    setSelectedId(item.id);
    setIsNew(false);
    setEditorOpen(true);
    setDirty(false);
    setShowErrors(false);
    setActivePane("editor");
    requestAnimationFrame(() => {
      railRef.current
        ?.querySelector(`[data-testid="experience-item-${item.id}"]`)
        ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
  };

  const patchForm = (patch: Partial<typeof form>) => {
    setForm((prev) => ({ ...prev, ...patch }));
    setDirty(true);
  };

  const save = async () => {
    setShowErrors(true);
    if (
      validateExperience(form).title ||
      validateExperience(form).start ||
      validateExperience(form).end ||
      validateExperience(form).hours ||
      validateExperience(form).links.some(Boolean) ||
      validateExperience(form).achievements.some(Boolean)
    ) {
      return;
    }
    setSaving(true);
    setError("");
    try {
      const payload: ExperienceItemIn = {
        ...form,
        start: form.start || null,
        end: form.open_ended ? null : form.end || null,
        links: form.links
          .filter((l) => l.url.trim())
          .map((l) => ({ ...l, url: l.url.trim() })),
        source: "self_report",
      };
      if (isNew) {
        const created = await createExperienceItem(payload);
        if (created) {
          setItems((prev) => sortByRecency([created, ...prev]));
          setSelectedId(created.id);
          setForm(formFromItem(created));
          setIsNew(false);
        }
      } else if (selectedId) {
        const updated = await updateExperienceItem(selectedId, payload);
        if (updated) {
          setItems((prev) =>
            sortByRecency(prev.map((i) => (i.id === selectedId ? updated : i)))
          );
          setForm(formFromItem(updated));
        }
      }
      setDirty(false);
      setShowErrors(false);
      void syncDerivation();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (item: ExperienceItemOut) => {
    setError("");
    try {
      await deleteExperienceItem(item.id);
      setItems((prev) => prev.filter((i) => i.id !== item.id));
      setSelectedIds((prev) => prev.filter((id) => id !== item.id));
      if (selectedId === item.id) closeEditor();
      setDeleted([item]);
      void syncDerivation();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const undoDelete = async () => {
    if (!deleted) return;
    setError("");
    try {
      for (const item of deleted) {
        const restored = await createExperienceItem(toIn(item));
        if (restored) {
          setItems((prev) => sortByRecency([restored, ...prev]));
        }
      }
      setDeleted(null);
      void syncDerivation();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((v) => v !== id) : [...prev, id]
    );
  };

  const selectAllVisible = () =>
    setSelectedIds(visible.map((item) => item.id));

  const bulkSetStatus = async (status: "draft" | "active") => {
    setBulkBusy(true);
    setError("");
    try {
      let changed = [...items];
      for (const id of selectedIds) {
        const updated = await updateExperienceItem(id, { status });
        if (updated) {
          changed = changed.map((item) =>
            item.id === id ? { ...item, status } : item
          );
        }
      }
      setItems(changed);
      setSelectedIds([]);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBulkBusy(false);
    }
  };

  const bulkDelete = async () => {
    setBulkConfirm(false);
    setBulkBusy(true);
    setError("");
    try {
      const removed: ExperienceItemOut[] = [];
      for (const id of selectedIds) {
        const target = items.find((item) => item.id === id);
        if (!target) continue;
        await deleteExperienceItem(id);
        removed.push(target);
      }
      const gone = new Set(selectedIds);
      setItems((prev) => prev.filter((item) => !gone.has(item.id)));
      if (selectedId != null && gone.has(selectedId)) closeEditor();
      setDeleted(removed);
      setSelectedIds([]);
      void syncDerivation();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBulkBusy(false);
    }
  };

  const duplicate = async (item: ExperienceItemOut) => {
    setError("");
    try {
      const created = await createExperienceItem({
        ...toIn(item),
        title: `${item.title} ${t("experience.copySuffix")}`,
      });
      if (created) {
        setItems((prev) => sortByRecency([created, ...prev]));
      }
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  return (
    <div className="ca-workspace flex min-h-0 flex-col gap-3 lg:h-full" data-testid="experience-page">
      <div
        className="flex shrink-0 flex-wrap items-center justify-between gap-3"
        data-testid="experience-toolbar"
      >
        <div>
          <Link
            to="/profile"
            className="inline-flex items-center gap-1 text-xs text-[var(--as-muted-fg)] transition-colors hover:text-[var(--as-fg)]"
            data-testid="experience-back"
          >
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> {t("nav.profile")}
          </Link>
          <h1 className="flex items-center gap-2 text-lg font-semibold text-[var(--as-fg)]">
            <CalendarRange className="h-5 w-5" aria-hidden /> {t("experience.title")}
          </h1>
          <p className="mt-0.5 text-xs text-[var(--as-muted-fg)]">
            {t("experience.subtitle")}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span
            className="text-sm text-[var(--as-muted-fg)]"
            data-testid="years-of-experience"
          >
            {t("experience.yearsDerived", { years })}
          </span>
          <Button variant="default" onClick={() => openCreate()} data-testid="add-experience">
            <Plus className="mr-1 h-4 w-4" aria-hidden /> {t("experience.addEntry")}
          </Button>
        </div>
      </div>

      {error && (
        <p role="alert" className="shrink-0 text-sm text-[var(--as-danger)]">
          {error}
        </p>
      )}

      {editorOpen && (
        <div
          className="ca-ws-switcher mb-2 flex shrink-0 gap-1"
          role="group"
          aria-label={t("experience.panesAria")}
          data-testid="pane-switcher"
        >
        {(
          [
            ["list", t("experience.pane.list")],
            ["editor", t("experience.pane.editor")],
          ] as const
        ).map(([paneId, label]) => (
          <button
            key={paneId}
            type="button"
            aria-pressed={activePane === paneId}
            onClick={() => switchPane(paneId)}
            data-testid={`pane-${paneId}`}
            className={`flex-1 cursor-pointer rounded-lg border border-[var(--as-border)] px-2 py-1.5 text-xs font-medium transition-colors duration-150 ${
              activePane === paneId
                ? "bg-[var(--as-surface-raised)] text-[var(--as-fg)]"
                : "bg-[var(--as-surface)] text-[var(--as-muted-fg)]"
            }`}
          >
            {label}
          </button>
        ))}
        </div>
      )}

      <div
        className="shrink-0"
        data-testid="experience-tabs"
      >
        <SegmentedTabs
          ariaLabel={t("experience.tabsAria")}
          items={[
            { value: "entries", label: t("experience.tab.entries") },
            { value: "skills", label: t("experience.tab.skills") },
          ]}
          value={tab}
          onValueChange={(next) => setTab(next as "entries" | "skills")}
          className="max-w-xs"
        />
      </div>

      <div
        className={`${editorOpen ? "ca-ws-grid ca-ws-grid-wide" : ""} grid min-h-0 flex-1 grid-cols-1 gap-3`}
        data-testid="experience-grid"
      >
        <div
          ref={railRef}
          tabIndex={-1}
          className={`${
            activePane === "list" ? "flex" : "hidden"
          } ca-ws-pane cv-pane-enter min-h-0 flex-col gap-3 overflow-y-auto outline-none`}
          data-testid="experience-rail"
        >
          {tab === "skills" ? (
            <section
              className={`rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-3 ${
                editorOpen ? "" : "mx-auto w-full max-w-3xl"
              }`}
              data-testid="derivation-panel"
            >
              <h2 className="text-sm font-semibold text-[var(--as-fg)]">
                {t("experience.derivedTitle")}
              </h2>
              {derived.length === 0 ? (
                <p className="mt-3 text-sm text-[var(--as-muted-fg)]">
                  {t("experience.derivedEmpty")}
                </p>
              ) : (
                <>
                  <div className="mt-3 space-y-2">
                    {derived.map((d) => (
                      <div key={d.skill_id} className="flex items-center gap-3 text-xs">
                        <span className="w-28 truncate text-[var(--as-fg)]">
                          {d.skill_label}
                        </span>
                        <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-[var(--as-muted)]">
                          <div
                            className="h-full rounded-full bg-[var(--as-accent)]"
                            style={{ width: `${(d.level / 10) * 100}%` }}
                          />
                        </div>
                        <span className="w-24 shrink-0 text-right text-[var(--as-muted-fg)]">
                          {t("experience.levelOf", {
                            level: d.level.toFixed(1),
                            months: Math.round(d.months),
                          })}
                        </span>
                      </div>
                    ))}
                  </div>
                  <div className="mt-3 flex items-start gap-2">
                    {applyState && (
                      <span className="text-xs text-emerald-600" data-testid="apply-state">
                        {applyState}
                      </span>
                    )}
                    <p className="text-xs text-[var(--as-muted-fg)]">
                      {t("experience.derivedHint")}
                    </p>
                  </div>
                </>
              )}
            </section>
          ) : (
            <>
          <section className="space-y-2.5" data-testid="experience-list">
            <div className="space-y-2 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-3" data-testid="experience-filters">
              <div className="relative">
                <Search
                  className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--as-muted-fg)]"
                  aria-hidden
                />
                <input
                  type="search"
                  value={filters.query}
                  onChange={(event) =>
                    setFilters((prev) => ({ ...prev, query: event.target.value }))
                  }
                  placeholder={t("experience.searchPlaceholder")}
                  className="w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] py-1.5 pl-7 pr-2 text-sm outline-none focus:border-[var(--as-accent)]"
                  data-testid="experience-search"
                />
              </div>
              <div className="flex gap-1.5" data-testid="experience-filter-statuses">
                {(["all", "active", "draft"] as const).map((mode) => {
                  const on =
                    mode === "all"
                      ? filters.statuses.length === 0
                      : filters.statuses[0] === mode;
                  return (
                    <button
                      key={mode}
                      type="button"
                      aria-pressed={on}
                      onClick={() =>
                        setFilters((prev) => ({
                          ...prev,
                          statuses: mode === "all" ? [] : [mode],
                        }))
                      }
                      className={`cursor-pointer rounded-full border px-2.5 py-0.5 text-xs ${
                        on
                          ? "border-[var(--as-accent)] bg-[var(--as-accent)] text-white"
                          : "border-[var(--as-border)] text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
                      }`}
                      data-testid={`experience-filter-${mode}`}
                    >
                      {t(`experience.filter.${mode}`)}
                    </button>
                  );
                })}
              </div>
              <FilterChips
                testidPrefix="experience"
                options={(Object.keys(KIND_ICONS) as ExperienceItemOut["kind"][]).map(
                  (kind) => ({
                    value: kind,
                    label: t(`experience.kind.${kind}`, { defaultValue: kind }),
                  })
                )}
                selected={filters.kinds}
                onToggle={(kind) =>
                  setFilters((prev) => ({
                    ...prev,
                    kinds: prev.kinds.includes(kind)
                      ? prev.kinds.filter((value) => value !== kind)
                      : [...prev.kinds, kind],
                  }))
                }
              />
            </div>
            <BulkBar
              count={selectedIds.length}
              total={visible.length}
              onClear={() => setSelectedIds([])}
              onSelectAll={selectAllVisible}
            >
              <Button
                variant="outline"
                size="sm"
                disabled={bulkBusy}
                onClick={() => void bulkSetStatus("active")}
                data-testid="bulk-set-active"
              >
                {t("experience.bulk.activate")}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={bulkBusy}
                onClick={() => void bulkSetStatus("draft")}
                data-testid="bulk-set-draft"
              >
                {t("experience.bulk.draft")}
              </Button>
              <Button
                variant="destructive"
                size="sm"
                disabled={bulkBusy}
                onClick={() => setBulkConfirm(true)}
                data-testid="bulk-delete"
              >
                <Trash2 className="mr-1 h-3.5 w-3.5" aria-hidden />
                {t("common.delete")}
              </Button>
            </BulkBar>
            {visible.length === 0 && items.length > 0 && (
              <p className="px-2 py-6 text-center text-sm text-[var(--as-muted-fg)]">
                {t("common.noFilterMatches")}
              </p>
            )}
            {visible.length === 0 && items.length === 0 && (
              <p className="px-2 py-6 text-center text-sm text-[var(--as-muted-fg)]">
                {t("experience.empty")}
              </p>
            )}
            {shouldGroup
              ? (
                  Object.keys(KIND_ICONS) as ExperienceItemOut["kind"][]
                )
                  .map((kind) => ({
                    kind,
                    list: visible.filter((item) => item.kind === kind),
                  }))
                  .filter((entry) => entry.list.length > 0)
                  .map(({ kind, list }) => (
                    <div key={kind} data-testid={`experience-group-${kind}`}>
                      <div className="flex items-center gap-2 rounded-xl border border-[var(--as-border)] bg-[var(--as-muted)] px-3 py-1.5">
                        <button
                          type="button"
                          aria-expanded={!collapsedGroups.includes(kind)}
                          onClick={() =>
                            setCollapsedGroups((prev) =>
                              prev.includes(kind)
                                ? prev.filter((value) => value !== kind)
                                : [...prev, kind]
                            )
                          }
                          className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 text-left"
                          data-testid={`experience-group-toggle-${kind}`}
                        >
                          {(() => {
                            const GroupIcon = KIND_ICONS[kind];
                            return (
                              <GroupIcon className="h-3.5 w-3.5 shrink-0 text-[var(--as-accent)]" aria-hidden />
                            );
                          })()}
                          <span className="min-w-0 flex-1 truncate text-xs font-semibold text-[var(--as-fg)]">
                            {t(`experience.kind.${kind}`, { defaultValue: kind })}
                          </span>
                          <span className="rounded-full bg-[var(--as-surface)] px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-[var(--as-muted-fg)]" data-testid={`experience-group-count-${kind}`}>
                            {list.length}
                          </span>
                          <ChevronRight
                            className={`h-3.5 w-3.5 text-[var(--as-muted-fg)] transition-transform ${
                              collapsedGroups.includes(kind) ? "" : "rotate-90"
                            }`}
                            aria-hidden
                          />
                        </button>
                        <button
                          type="button"
                          onClick={() => openCreate(kind)}
                          className="flex cursor-pointer items-center gap-1 rounded-lg border border-dashed border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1 text-[11px] font-medium text-[var(--as-muted-fg)] transition-colors hover:border-[var(--as-accent)] hover:text-[var(--as-fg)]"
                          data-testid={`experience-group-add-${kind}`}
                          title={t(`experience.kind.${kind}`, { defaultValue: kind })}
                        >
                          <Plus className="h-3 w-3" aria-hidden />
                          {t("experience.groupAdd")}
                        </button>
                      </div>
                      {!collapsedGroups.includes(kind) && (
                        <div
                          className={
                            editorOpen
                              ? "mt-2 space-y-2.5"
                              : "mt-2 grid grid-cols-[repeat(auto-fill,minmax(270px,1fr))] gap-2.5"
                          }
                        >
                          {list.map(renderCard)}
                        </div>
                      )}
                    </div>
                  ))
              : (
                  <div
                    className={
                      editorOpen
                        ? "space-y-2.5"
                        : "grid grid-cols-[repeat(auto-fill,minmax(270px,1fr))] gap-2.5"
                    }
                  >
                    {visible.map((item) => renderCard(item))}
                  </div>
                )}
          </section>
            </>
          )}
        </div>

        {editorOpen && (
          <div
            ref={editorPaneRef}
            tabIndex={-1}
            className={`${
              activePane === "editor" ? "flex" : "hidden"
            } ca-ws-pane cv-pane-enter min-h-0 flex-col rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] outline-none`}
          >
            <ExperienceEditor
              form={form}
              onChange={patchForm}
              onSave={() => void save()}
              onCancel={() => guard(closeEditor)}
              onDismissErrors={() => setShowErrors(false)}
              showErrors={showErrors}
              skillOptions={skillChoices}
              saving={saving}
              isNew={isNew}
            />
          </div>
        )}
      </div>

      {deleted && deleted.length > 0 && (
        <div
          className="fixed bottom-6 left-6 z-[var(--as-z-modal)]"
          data-testid="undo-experience"
        >
          <UndoNotice
            message={
              deleted.length === 1
                ? t("experience.deletedNotice", { title: deleted[0].title })
                : t("experience.bulkDeletedNotice", { count: deleted.length })
            }
            actionLabel={t("common.undo")}
            duration={8000}
            onUndo={() => void undoDelete()}
            onDismiss={() => setDeleted(null)}
          />
        </div>
      )}

      <ConfirmationModal
        open={bulkConfirm}
        onOpenChange={setBulkConfirm}
        onConfirm={() => void bulkDelete()}
        title={t("experience.bulkDeleteTitle", { count: selectedIds.length })}
        description={t("experience.bulkDeleteBody")}
        confirmLabel={t("common.delete")}
        destructive
      />

      <ConfirmationModal
        open={confirmAction !== null}
        onOpenChange={(open) => !open && setConfirmAction(null)}
        title={t("experience.discardTitle")}
        description={t("experience.discardBody")}
        confirmLabel={t("experience.discard")}
        destructive
        onConfirm={() => confirmAction && discardAnd(confirmAction)}
      />
    </div>
  );
}
