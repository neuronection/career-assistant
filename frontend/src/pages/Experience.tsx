import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import i18next from "i18next";
import {
  ArrowLeft,
  Briefcase,
  CalendarRange,
  Coins,
  GraduationCap,
  Hammer,
  HeartHandshake,
  Plus,
  Trash2,
} from "lucide-react";
import { Button, ConfirmationModal } from "@/components/ui";
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
  EMPTY_FORM,
  ExperienceEditor,
  ExperienceEditorEmpty,
  formFromItem,
  validateExperience,
} from "@/components/experience/ExperienceEditor";

const KIND_ICONS: Record<ExperienceItemIn["kind"], typeof Briefcase> = {
  job: Briefcase,
  internship: GraduationCap,
  project: Hammer,
  freelance: Coins,
  volunteer: HeartHandshake,
};

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

function formatPeriod(item: ExperienceItemOut): string {
  return `${item.start.slice(0, 7)} → ${periodEnd(item)}`;
}

function periodEnd(item: ExperienceItemOut): string {
  return item.open_ended ? i18next.t("experience.present") : (item.end ?? "").slice(0, 7);
}

/** Experience workspace: full-bleed master-detail with an
 * editor pane, optimistic delete + undo and a derivation panel. */
export function Experience() {
  const { t } = useTranslation();
  const [items, setItems] = useState<ExperienceItemOut[]>([]);
  const [years, setYears] = useState(0);
  const [derived, setDerived] = useState<DerivedSkillOut[]>([]);
  const [skillOptions, setSkillOptions] = useState<
    { key: string; label: string }[]
  >([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [isNew, setIsNew] = useState(false);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [dirty, setDirty] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [applyState, setApplyState] = useState<string | null>(null);
  const [derivationOpen, setDerivationOpen] = useState(true);
  const [deleted, setDeleted] = useState<ExperienceItemOut | null>(null);
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
    setItems(sortByRecency(list.items));
    setYears(list.years_of_experience);
    setDerived(derivation.skills);
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

  useEffect(() => {
    void load().catch((err) => setError(apiDetail(err)));
    void fetchSkillOntology()
      .then((rows: SkillSummary[]) =>
        setSkillOptions(rows.map((s) => ({ key: s.key, label: s.label })))
      )
      .catch(() => setSkillOptions([]));
  }, [load]);

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
  };

  const openCreate = () => {
    setForm({ ...EMPTY_FORM });
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
        links: [],
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
      void refreshDerived();
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
      if (selectedId === item.id) closeEditor();
      setDeleted(item);
      void refreshDerived();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const undoDelete = async () => {
    if (!deleted) return;
    setError("");
    try {
      const restored = await createExperienceItem(toIn(deleted));
      if (restored) {
        setItems((prev) => sortByRecency([restored, ...prev]));
        setDeleted(null);
        void refreshDerived();
      }
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const apply = async () => {
    setError("");
    try {
      const result = await applyDerivation();
      setApplyState(
        result.conflicts.length > 0
          ? t("experience.appliedWithConflicts", {
              count: result.applied,
              conflicts: result.conflicts.length,
            })
          : t("experience.appliedClean", { count: result.applied })
      );
      await load();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  return (
    <div className="flex min-h-0 flex-col gap-3 lg:h-full" data-testid="experience-page">
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
          <Button variant="default" onClick={openCreate} data-testid="add-experience">
            <Plus className="mr-1 h-4 w-4" aria-hidden /> {t("experience.addEntry")}
          </Button>
        </div>
      </div>

      {error && (
        <p role="alert" className="shrink-0 text-sm text-[var(--as-danger)]">
          {error}
        </p>
      )}

      <div
        className="mb-2 flex shrink-0 gap-1 lg:hidden"
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

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[minmax(260px,340px)_minmax(0,1fr)] lg:gap-4">
        <div
          ref={railRef}
          tabIndex={-1}
          className={`${
            activePane === "list" ? "flex" : "hidden"
          } cv-pane-enter min-h-0 flex-col gap-3 overflow-y-auto outline-none lg:flex`}
          data-testid="experience-rail"
        >
          {derived.length > 0 && (
            <section
              className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
              data-testid="derivation-panel"
            >
              <button
                type="button"
                onClick={() => setDerivationOpen((v) => !v)}
                aria-expanded={derivationOpen}
                className="flex w-full cursor-pointer items-center justify-between gap-2"
                data-testid="derivation-toggle"
              >
                <span className="flex items-center gap-1.5 text-sm font-semibold text-[var(--as-fg)]">
                  {t("experience.derivedTitle")}
                </span>
                <span className="text-xs text-[var(--as-muted-fg)]">
                  {derivationOpen ? t("common.hide") : t("common.show")}
                </span>
              </button>
              <div className="cv-collapse" data-open={derivationOpen}>
                <div className="overflow-hidden">
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
                  <div className="mt-3 flex items-center justify-between gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void apply()}
                      data-testid="apply-derivation"
                    >
                      {t("experience.applySkills")}
                    </Button>
                    {applyState && (
                      <span className="text-xs text-emerald-600" data-testid="apply-state">
                        {applyState}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </section>
          )}

          <section className="space-y-2.5" data-testid="experience-list">
            {items.length === 0 && (
              <p className="px-2 py-6 text-center text-sm text-[var(--as-muted-fg)]">
                {t("experience.empty")}
              </p>
            )}
            {items.map((item) => {
              const Icon = KIND_ICONS[item.kind] ?? Briefcase;
              const active = item.id === selectedId;
              return (
                <article
                  key={item.id}
                  className={`group relative cursor-pointer rounded-xl border p-3 transition-colors duration-150 ${
                    active
                      ? "border-[var(--as-accent)] bg-[color-mix(in_srgb,var(--as-accent)_8%,transparent)]"
                      : "border-[var(--as-border)] bg-[var(--as-surface)] hover:border-[var(--as-accent)]"
                  }`}
                  data-testid={`experience-item-${item.id}`}
                >
                  <button
                    type="button"
                    onClick={() => guard(() => openEdit(item))}
                    className="flex w-full cursor-pointer items-start justify-between gap-2 pr-8 text-left"
                    data-testid="experience-item"
                    aria-current={active ? "true" : undefined}
                  >
                    <span className="flex min-w-0 items-start gap-2.5">
                      <span
                        className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
                          active
                            ? "bg-[color-mix(in_srgb,var(--as-accent)_15%,transparent)] text-[var(--as-accent)]"
                            : "bg-[var(--as-muted)] text-[var(--as-muted-fg)]"
                        }`}
                      >
                        <Icon className="h-4 w-4" aria-hidden />
                      </span>
                      <span className="block min-w-0">
                        <span className="block truncate text-sm font-medium text-[var(--as-fg)]">
                          {item.title}
                          {item.status === "draft" && (
                            <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
                              {t("experience.draft")}
                            </span>
                          )}
                        </span>
                        <span className="mt-0.5 block truncate text-xs text-[var(--as-muted-fg)]">
                          {t(`experience.kind.${item.kind}`, {
                            defaultValue: item.kind,
                          })}
                          {item.org_name ? ` · ${item.org_name}` : ""} ·{" "}
                          {formatPeriod(item)}
                          {item.hours_per_week
                            ? ` · ${t("experience.hoursShort", { hours: item.hours_per_week })}`
                            : ""}
                        </span>
                      </span>
                    </span>
                  </button>
                  <button
                    type="button"
                    aria-label={t("experience.deleteAria", { title: item.title })}
                    className="absolute right-2 top-2 cursor-pointer rounded p-1 text-slate-300 transition-colors hover:text-[var(--as-danger)] group-hover:text-slate-400"
                    data-testid={`delete-experience-${item.id}`}
                    onClick={() => void remove(item)}
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </article>
              );
            })}
          </section>
        </div>

        <div
          ref={editorPaneRef}
          tabIndex={-1}
          className={`${
            activePane === "editor" ? "flex" : "hidden"
          } cv-pane-enter min-h-0 flex-col rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] outline-none lg:flex`}
        >
          {editorOpen ? (
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
          ) : (
            <ExperienceEditorEmpty onAdd={openCreate} />
          )}
        </div>
      </div>

      {deleted && (
        <div
          className="fixed bottom-6 left-6 z-[var(--as-z-modal)]"
          data-testid="undo-experience"
        >
          <UndoNotice
            message={t("experience.deletedNotice", { title: deleted.title })}
            actionLabel={t("common.undo")}
            duration={8000}
            onUndo={() => void undoDelete()}
            onDismiss={() => setDeleted(null)}
          />
        </div>
      )}

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
