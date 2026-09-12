import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import i18next from "i18next";
import {
  ArrowLeft,
  Award,
  BookOpen,
  Copy,
  GraduationCap,
  Medal,
  Plus,
  School,
  Search,
  Trash2,
  Users,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { Button, ConfirmationModal } from "@/components/ui";
import { UndoNotice } from "@neuronection/assistant-ui";
import { apiDetail } from "@/api/client";
import { fetchUniversity, fetchUniversities } from "@/api/universities";
import {
  createAchievement,
  createCertification,
  createEducationItem,
  deleteAchievement,
  deleteCertification,
  deleteEducationItem,
  fetchAchievements,
  fetchCertifications,
  fetchEducation,
  updateAchievement,
  updateCertification,
  updateEducationItem,
} from "@/api/education";
import type {
  AchievementOut,
  CertificationOut,
  EducationItemOut,
  EducationLevel,
} from "@/types/education";
import type { Department, University } from "@/types";
import { EDUCATION_LEVEL_ORDER } from "@/components/profile/sections/options";
import {
  BulkBar,
  FilterChips,
  SelectionToggle,
} from "@/components/profile/BulkTools";
import {
  EMPTY_ACHIEVEMENT_FORM,
  EMPTY_CERTIFICATION_FORM,
  EMPTY_EDUCATION_FORM,
  AchievementEditor,
  CertificationEditor,
  EducationEditor,
  achievementFormFromItem,
  achievementToIn,
  certificationFormFromItem,
  certificationToIn,
  educationFormFromItem,
  educationToIn,
  type AchievementEditorForm,
  type CertificationEditorForm,
  type EducationEditorForm,
} from "@/components/education/EducationEditor";

const LEVEL_ICONS: Record<string, LucideIcon> = {
  no_formal: School,
  middle_school: School,
  high_school: School,
  vocational: Wrench,
  bachelor: GraduationCap,
  master: GraduationCap,
  doctorate: GraduationCap,
};

const ACHIEVEMENT_KIND_ICONS: Record<string, LucideIcon> = {
  award: Award,
  honor: Medal,
  publication: BookOpen,
  extracurricular: Users,
};

type Entity = "education" | "certifications" | "achievements";

type Deleted =
  | { entity: "education"; item: EducationItemOut }
  | { entity: "certifications"; item: CertificationOut }
  | { entity: "achievements"; item: AchievementOut };

function levelRank(level: string): number {
  const idx = EDUCATION_LEVEL_ORDER.indexOf(level as EducationLevel);
  return idx === -1 ? -1 : idx;
}

function formatPeriod(start: string | null, end: string | null): string {
  const from = (start ?? "").slice(0, 7);
  const to = end ? end.slice(0, 7) : i18next.t("education.present");
  return `${from || "?"} → ${to}`;
}

function expiryState(expires: string | null): "expired" | "soon" | null {
  if (!expires) return null;
  const days = (new Date(expires).getTime() - Date.now()) / 86400000;
  if (days < 0) return "expired";
  if (days <= 90) return "soon";
  return null;
}

/** Education workspace: full-bleed master-detail over the
 * education/certification entities, nested under Profile — with
 * per-item + bulk selection (set status / delete), duplicates and
 * search/status/type filters. */
export function Education() {
  const { t } = useTranslation();
  const [entity, setEntity] = useState<Entity>("education");
  const [items, setItems] = useState<EducationItemOut[]>([]);
  const [certs, setCerts] = useState<CertificationOut[]>([]);
  const [achievements, setAchievements] = useState<AchievementOut[]>([]);
  const [universities, setUniversities] = useState<University[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [isNew, setIsNew] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [bulkConfirm, setBulkConfirm] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [filters, setFilters] = useState<{
    query: string;
    statuses: string[];
    aspects: string[];
  }>({ query: "", statuses: [], aspects: [] });
  const [eduForm, setEduForm] = useState<EducationEditorForm>({
    ...EMPTY_EDUCATION_FORM,
  });
  const [certForm, setCertForm] = useState<CertificationEditorForm>({
    ...EMPTY_CERTIFICATION_FORM,
  });
  const [achForm, setAchForm] = useState<AchievementEditorForm>({
    ...EMPTY_ACHIEVEMENT_FORM,
  });
  const [dirty, setDirty] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [deleted, setDeleted] = useState<Deleted[] | null>(null);
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
    const [education, certifications, achievements, catalog] = await Promise.all([
      fetchEducation(),
      fetchCertifications(),
      fetchAchievements(),
      fetchUniversities().catch(() => [] as University[]),
    ]);
    setItems(education);
    setCerts(certifications);
    setAchievements(achievements);
    setUniversities(catalog);
  }, []);

  useEffect(() => {
    void load().catch((err) => setError(apiDetail(err)));
  }, [load]);

  useEffect(() => {
    const uniId = eduForm.university_id;
    if (!uniId || !universities.some((u) => u.id === uniId)) {
      setDepartments([]);
      return;
    }
    let alive = true;
    void fetchUniversity(uniId)
      .then((detail) => alive && setDepartments(detail.departments))
      .catch(() => alive && setDepartments([]));
    return () => {
      alive = false;
    };
  }, [eduForm.university_id, universities]);

  const highestLevel = useMemo(() => {
    let best: EducationLevel | null = null;
    let rank = -1;
    for (const item of items) {
      if (item.status !== "active") continue;
      const r = levelRank(item.level);
      if (r > rank) {
        rank = r;
        best = item.level as EducationLevel;
      }
    }
    return best;
  }, [items]);

  const inProgressCount = items.filter(
    (i) => i.in_progress && i.status === "active"
  ).length;

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
    setDirty(false);
    setShowErrors(false);
  };

  const openCreate = () => {
    if (entity === "education") setEduForm({ ...EMPTY_EDUCATION_FORM });
    else if (entity === "certifications")
      setCertForm({ ...EMPTY_CERTIFICATION_FORM });
    else setAchForm({ ...EMPTY_ACHIEVEMENT_FORM });
    setSelectedId(null);
    setIsNew(true);
    setEditorOpen(true);
    setDirty(false);
    setShowErrors(false);
    setDepartments([]);
    setActivePane("editor");
  };

  const openEdit = (id: string) => {
    if (entity === "education") {
      const item = items.find((i) => i.id === id);
      if (item) setEduForm(educationFormFromItem(item));
    } else if (entity === "certifications") {
      const cert = certs.find((c) => c.id === id);
      if (cert) setCertForm(certificationFormFromItem(cert));
    } else {
      const achievement = achievements.find((a) => a.id === id);
      if (achievement) setAchForm(achievementFormFromItem(achievement));
    }
    setSelectedId(id);
    setIsNew(false);
    setEditorOpen(true);
    setDirty(false);
    setShowErrors(false);
    setActivePane("editor");
  };

  const patchForm = (
    partial: Partial<
      EducationEditorForm & CertificationEditorForm & AchievementEditorForm
    >
  ) => {
    if (entity === "education")
      setEduForm((prev) => ({ ...prev, ...partial }));
    else if (entity === "certifications")
      setCertForm((prev) => ({ ...prev, ...partial }));
    else setAchForm((prev) => ({ ...prev, ...partial }));
    setDirty(true);
    setShowErrors(false);
  };

  const switchEntity = (next: Entity) => {
    if (next === entity) return;
    guard(() => {
      closeEditor();
      setEntity(next);
      setSelectedIds([]);
      setFilters((prev) => ({ ...prev, aspects: [], statuses: [] }));
    });
  };

  const matchesFilters = useCallback(
    (title: string, status: string): boolean => {
      const q = filters.query.trim().toLowerCase();
      if (q && !title.toLowerCase().includes(q)) return false;
      if (filters.statuses.length && !filters.statuses.includes(status)) {
        return false;
      }
      return true;
    },
    [filters.query, filters.statuses]
  );

  const visEdu = useMemo(
    () =>
      items.filter(
        (item) =>
          matchesFilters(
            `${item.program} ${item.institution}`,
            item.status
          ) &&
          (filters.aspects.length === 0 || filters.aspects.includes(item.level))
      ),
    [items, filters, matchesFilters]
  );
  const visCerts = useMemo(
    () =>
      certs.filter((cert) =>
        matchesFilters(`${cert.name} ${cert.issuer}`, cert.status)
      ),
    [certs, matchesFilters]
  );
  const visAch = useMemo(
    () =>
      achievements.filter(
        (achievement) =>
          matchesFilters(
            `${achievement.title} ${achievement.issuer}`,
            achievement.status
          ) &&
          (filters.aspects.length === 0 ||
            filters.aspects.includes(achievement.kind))
      ),
    [achievements, filters, matchesFilters]
  );

  const save = async () => {
    setShowErrors(true);
    setError("");
    if (entity === "education") {
      const payload = educationToIn(eduForm);
      if (!payload.institution) return;
      setSaving(true);
      try {
        if (isNew) {
          const created = await createEducationItem(payload);
          setItems((prev) => [created, ...prev]);
          setSelectedId(created.id);
          setEduForm(educationFormFromItem(created));
          setIsNew(false);
        } else if (selectedId) {
          const updated = await updateEducationItem(selectedId, payload);
          setItems((prev) =>
            prev.map((i) => (i.id === selectedId ? updated : i))
          );
          setEduForm(educationFormFromItem(updated));
        }
        setDirty(false);
        setShowErrors(false);
      } catch (err) {
        setError(apiDetail(err));
      } finally {
        setSaving(false);
      }
    } else if (entity === "certifications") {
      const payload = certificationToIn(certForm);
      if (!payload.name) return;
      setSaving(true);
      try {
        if (isNew) {
          const created = await createCertification(payload);
          setCerts((prev) => [created, ...prev]);
          setSelectedId(created.id);
          setCertForm(certificationFormFromItem(created));
          setIsNew(false);
        } else if (selectedId) {
          const updated = await updateCertification(selectedId, payload);
          setCerts((prev) =>
            prev.map((c) => (c.id === selectedId ? updated : c))
          );
          setCertForm(certificationFormFromItem(updated));
        }
        setDirty(false);
        setShowErrors(false);
      } catch (err) {
        setError(apiDetail(err));
      } finally {
        setSaving(false);
      }
    } else {
      const payload = achievementToIn(achForm);
      if (!payload.title) return;
      setSaving(true);
      try {
        if (isNew) {
          const created = await createAchievement(payload);
          setAchievements((prev) => [created, ...prev]);
          setSelectedId(created.id);
          setAchForm(achievementFormFromItem(created));
          setIsNew(false);
        } else if (selectedId) {
          const updated = await updateAchievement(selectedId, payload);
          setAchievements((prev) =>
            prev.map((a) => (a.id === selectedId ? updated : a))
          );
          setAchForm(achievementFormFromItem(updated));
        }
        setDirty(false);
        setShowErrors(false);
      } catch (err) {
        setError(apiDetail(err));
      } finally {
        setSaving(false);
      }
    }
  };

  const remove = async (id: string) => {
    setError("");
    try {
      if (entity === "education") {
        const item = items.find((i) => i.id === id);
        if (!item) return;
        await deleteEducationItem(item.id);
        setItems((prev) => prev.filter((i) => i.id !== id));
        if (selectedId === id) closeEditor();
        setDeleted([{ entity: "education", item }]);
      } else if (entity === "certifications") {
        const cert = certs.find((c) => c.id === id);
        if (!cert) return;
        await deleteCertification(cert.id);
        setCerts((prev) => prev.filter((c) => c.id !== id));
        if (selectedId === id) closeEditor();
        setDeleted([{ entity: "certifications", item: cert }]);
      } else {
        const achievement = achievements.find((a) => a.id === id);
        if (!achievement) return;
        await deleteAchievement(achievement.id);
        setAchievements((prev) => prev.filter((a) => a.id !== id));
        if (selectedId === id) closeEditor();
        setDeleted([{ entity: "achievements", item: achievement }]);
      }
      setSelectedIds((prev) => prev.filter((value) => value !== id));
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const undoDelete = async () => {
    if (!deleted) return;
    setError("");
    try {
      for (const entry of deleted) {
        if (entry.entity === "education") {
          const restored = await createEducationItem(
            educationToIn(educationFormFromItem(entry.item))
          );
          setItems((prev) => [restored, ...prev]);
        } else if (entry.entity === "certifications") {
          const restored = await createCertification(
            certificationToIn(certificationFormFromItem(entry.item))
          );
          setCerts((prev) => [restored, ...prev]);
        } else {
          const restored = await createAchievement(
            achievementToIn(achievementFormFromItem(entry.item))
          );
          setAchievements((prev) => [restored, ...prev]);
        }
      }
      setDeleted(null);
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((value) => value !== id) : [...prev, id]
    );
  };

  const selectAllVisible = () =>
    setSelectedIds(
      (entity === "education" ? visEdu : entity === "certifications" ? visCerts : visAch).map(
        (item) => item.id
      )
    );

  const bulkSetStatus = async (status: "draft" | "active") => {
    setBulkBusy(true);
    setError("");
    try {
      for (const id of selectedIds) {
        if (entity === "education") {
          const updated = await updateEducationItem(id, { status });
          if (updated) {
            setItems((prev) =>
              prev.map((item) =>
                item.id === id ? { ...item, status } : item
              )
            );
          }
        } else if (entity === "certifications") {
          const updated = await updateCertification(id, { status });
          if (updated) {
            setCerts((prev) =>
              prev.map((item) => (item.id === id ? { ...item, status } : item))
            );
          }
        } else {
          const updated = await updateAchievement(id, { status });
          if (updated) {
            setAchievements((prev) =>
              prev.map((item) => (item.id === id ? { ...item, status } : item))
            );
          }
        }
      }
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
      const removed: Deleted[] = [];
      for (const id of selectedIds) {
        if (!selectedIds.includes(id)) continue;
        if (entity === "education") {
          const item = visEdu.find((i) => i.id === id);
          if (!item) continue;
          await deleteEducationItem(id);
          setItems((prev) => prev.filter((entry) => entry.id !== id));
          removed.push({ entity: "education", item });
        } else if (entity === "certifications") {
          const cert = visCerts.find((i) => i.id === id);
          if (!cert) continue;
          await deleteCertification(id);
          setCerts((prev) => prev.filter((entry) => entry.id !== id));
          removed.push({ entity: "certifications", item: cert });
        } else {
          const achievement = visAch.find((i) => i.id === id);
          if (!achievement) continue;
          await deleteAchievement(id);
          setAchievements((prev) => prev.filter((entry) => entry.id !== id));
          removed.push({ entity: "achievements", item: achievement });
        }
        if (selectedId === id) closeEditor();
      }
      setDeleted(removed);
      setSelectedIds([]);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBulkBusy(false);
    }
  };

  const duplicateEntry = async (id: string) => {
    setError("");
    try {
      if (entity === "education") {
        const item = items.find((i) => i.id === id);
        if (!item) return;
        const created = await createEducationItem({
          ...educationToIn(educationFormFromItem(item)),
          program: `${item.program} ${t("education.copySuffix")}`.trim(),
        });
        if (created) setItems((prev) => [created, ...prev]);
      } else if (entity === "certifications") {
        const cert = certs.find((c) => c.id === id);
        if (!cert) return;
        const created = await createCertification({
          ...certificationToIn(certificationFormFromItem(cert)),
          name: `${cert.name} ${t("education.copySuffix")}`.trim(),
        });
        if (created) setCerts((prev) => [created, ...prev]);
      } else {
        const achievement = achievements.find((a) => a.id === id);
        if (!achievement) return;
        const created = await createAchievement({
          ...achievementToIn(achievementFormFromItem(achievement)),
          title: `${achievement.title} ${t("education.copySuffix")}`.trim(),
        });
        if (created) setAchievements((prev) => [created, ...prev]);
      }
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  return (
    <div className="flex min-h-0 flex-col gap-3 lg:h-full" data-testid="education-page">
      <div
        className="flex shrink-0 flex-wrap items-center justify-between gap-3"
        data-testid="education-toolbar"
      >
        <div>
          <Link
            to="/profile"
            className="inline-flex items-center gap-1 text-xs text-[var(--as-muted-fg)] transition-colors hover:text-[var(--as-fg)]"
            data-testid="education-back"
          >
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> {t("nav.profile")}
          </Link>
          <h1 className="flex items-center gap-2 text-lg font-semibold text-[var(--as-fg)]">
            <GraduationCap className="h-5 w-5" aria-hidden /> {t("education.title")}
          </h1>
          <p className="mt-0.5 text-xs text-[var(--as-muted-fg)]">
            {t("education.subtitle")}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {entity === "education" && highestLevel && (
            <span
              className="text-sm text-[var(--as-muted-fg)]"
              data-testid="education-derived"
            >
              {t(`education.level.${highestLevel}`, {
                defaultValue: highestLevel,
              })}
              {inProgressCount > 0
                ? ` · ${t("education.inProgressCount", { count: inProgressCount })}`
                : ""}
            </span>
          )}
          <div
            className="flex gap-1 rounded-lg border border-[var(--as-border)] p-0.5"
            role="group"
            aria-label={t("education.entryTypeAria")}
            data-testid="education-entity-toggle"
          >
            {(
              [
                ["education", "education.entity.education"],
                ["certifications", "education.entity.certifications"],
                ["achievements", "education.entity.achievements"],
              ] as const
            ).map(([value, labelKey]) => (
              <button
                key={value}
                type="button"
                aria-pressed={entity === value}
                onClick={() => switchEntity(value)}
                data-testid={`education-entity-${value}`}
                className={`cursor-pointer rounded-md px-2.5 py-1 text-xs font-medium transition-colors duration-150 ${
                  entity === value
                    ? "bg-[var(--as-surface-raised)] text-[var(--as-fg)]"
                    : "text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
                }`}
              >
                {t(labelKey)}
              </button>
            ))}
          </div>
          <Button variant="default" onClick={openCreate} data-testid="add-education">
            <Plus className="mr-1 h-4 w-4" aria-hidden /> {t("education.addEntry")}
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
        aria-label={t("education.panesAria")}
        data-testid="pane-switcher"
      >
        {(
          [
            ["list", t("education.pane.list")],
            ["editor", t("education.pane.editor")],
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
          data-testid="education-rail"
        >
          {entity === "education" && items.length > 0 && (
            <section
              className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
              data-testid="education-overview"
            >
              <p className="text-xs font-semibold text-[var(--as-fg)]">
                {t("education.entriesCount", { count: items.length })}
              </p>
              <p className="mt-0.5 text-xs text-[var(--as-muted-fg)]">
                {highestLevel
                  ? t("education.highest", {
                      level: t(`education.level.${highestLevel}`, {
                        defaultValue: highestLevel,
                      }),
                    })
                  : t("education.nothingYet")}
                {inProgressCount > 0
                  ? ` · ${t("education.inProgressCount", { count: inProgressCount })}`
                  : ""}
              </p>
            </section>
          )}

          <section
            className="space-y-2 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
            data-testid="education-filters"
          >
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
                placeholder={t("common.searchPlaceholder")}
                className="w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] py-1.5 pl-7 pr-2 text-sm outline-none focus:border-[var(--as-accent)]"
                data-testid="education-search"
              />
            </div>
            <div className="flex gap-1.5" data-testid="education-filter-statuses">
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
                    data-testid={`education-filter-${mode}`}
                  >
                    {t(`experience.filter.${mode}`)}
                  </button>
                );
              })}
            </div>
            {entity === "education" && (
              <FilterChips
                testidPrefix="education"
                options={EDUCATION_LEVEL_ORDER.map((level) => ({
                  value: level,
                  label: t(`education.level.${level}`, {
                    defaultValue: level,
                  }),
                }))}
                selected={filters.aspects}
                onToggle={(level) =>
                  setFilters((prev) => ({
                    ...prev,
                    aspects: prev.aspects.includes(level)
                      ? prev.aspects.filter((value) => value !== level)
                      : [...prev.aspects, level],
                  }))
                }
              />
            )}
            {entity === "achievements" && (
              <FilterChips
                testidPrefix="education"
                options={Object.keys(ACHIEVEMENT_KIND_ICONS).map((kind) => ({
                  value: kind,
                  label: t(`education.kind.${kind}`, { defaultValue: kind }),
                }))}
                selected={filters.aspects}
                onToggle={(kind) =>
                  setFilters((prev) => ({
                    ...prev,
                    aspects: prev.aspects.includes(kind)
                      ? prev.aspects.filter((value) => value !== kind)
                      : [...prev.aspects, kind],
                  }))
                }
              />
            )}
          </section>

          <BulkBar
            count={selectedIds.length}
            total={
              (
                entity === "education"
                  ? visEdu
                  : entity === "certifications"
                    ? visCerts
                    : visAch
              ).length
            }
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

          <section className="space-y-2.5" data-testid="education-list">
            {entity === "education" ? (
              visEdu.length === 0 ? (
                <p className="px-2 py-6 text-center text-sm text-[var(--as-muted-fg)]">
                  {items.length > 0
                    ? t("common.noFilterMatches")
                    : t("education.emptyEducation")}
                </p>
              ) : (
                visEdu.map((item) => (
                  <RailCard
                    key={item.id}
                    id={item.id}
                    icon={
                      LEVEL_ICONS[item.level] ?? GraduationCap
                    }
                    title={item.program || item.institution}
                    subtitle={[
                      item.institution,
                      formatPeriod(item.start, item.in_progress ? null : item.end),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                    active={item.id === selectedId && editorOpen}
                    selected={selectedIds.includes(item.id)}
                    onOpen={() => guard(() => openEdit(item.id))}
                    onToggleSelect={() => toggleSelect(item.id)}
                    onDuplicate={() => void duplicateEntry(item.id)}
                    onDelete={() => void remove(item.id)}
                    badges={
                      <>
                        {item.in_progress && (
                          <Badge tone="accent">{t("education.inProgressBadge")}</Badge>
                        )}
                        {item.status === "draft" && (
                          <Badge tone="warn">{t("education.draftBadge")}</Badge>
                        )}
                        {item.source !== "self_report" && (
                          <Badge tone="muted">
                            {item.source === "cv_parse"
                              ? t("education.fromCv")
                              : item.source}
                          </Badge>
                        )}
                      </>
                    }
                  />
                ))
              )
            ) : entity === "certifications" ? (
              visCerts.length === 0 ? (
                <p className="px-2 py-6 text-center text-sm text-[var(--as-muted-fg)]">
                  {certs.length > 0
                    ? t("common.noFilterMatches")
                    : t("education.emptyCertifications")}
                </p>
              ) : (
                visCerts.map((cert) => {
                  const expiry = expiryState(cert.expires);
                  return (
                    <RailCard
                      key={cert.id}
                      id={cert.id}
                      icon={Award}
                      title={cert.name}
                      subtitle={[
                        cert.issuer,
                        cert.issued
                          ? t("education.issuedTag", {
                              date: cert.issued.slice(0, 7),
                            })
                          : "",
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                      active={cert.id === selectedId && editorOpen}
                      selected={selectedIds.includes(cert.id)}
                      onOpen={() => guard(() => openEdit(cert.id))}
                      onToggleSelect={() => toggleSelect(cert.id)}
                      onDuplicate={() => void duplicateEntry(cert.id)}
                      onDelete={() => void remove(cert.id)}
                      badges={
                        <>
                          {expiry === "expired" && (
                            <Badge tone="danger">{t("education.expired")}</Badge>
                          )}
                          {expiry === "soon" && (
                            <Badge tone="warn">{t("education.expiringSoon")}</Badge>
                          )}
                          {cert.status === "draft" && (
                            <Badge tone="warn">{t("education.draftBadge")}</Badge>
                          )}
                          {cert.source !== "self_report" && (
                            <Badge tone="muted">
                              {cert.source === "cv_parse"
                                ? t("education.fromCv")
                                : cert.source}
                            </Badge>
                          )}
                        </>
                      }
                     />
                   );
                 })
               )
            ) : visAch.length === 0 ? (
              <p className="px-2 py-6 text-center text-sm text-[var(--as-muted-fg)]">
                {achievements.length > 0
                  ? t("common.noFilterMatches")
                  : t("education.emptyAchievements")}
              </p>
            ) : (
              visAch.map((achievement) => (
                <RailCard
                  key={achievement.id}
                  id={achievement.id}
                  icon={ACHIEVEMENT_KIND_ICONS[achievement.kind] ?? Award}
                  title={achievement.title}
                  subtitle={[
                    achievement.issuer,
                    achievement.date
                      ? achievement.date.slice(0, 7)
                      : "",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                  active={achievement.id === selectedId && editorOpen}
                  selected={selectedIds.includes(achievement.id)}
                  onOpen={() => guard(() => openEdit(achievement.id))}
                  onToggleSelect={() => toggleSelect(achievement.id)}
                  onDuplicate={() => void duplicateEntry(achievement.id)}
                  onDelete={() => void remove(achievement.id)}
                  badges={
                    <>
                      {achievement.status === "draft" && (
                        <Badge tone="warn">{t("education.draftBadge")}</Badge>
                      )}
                      {achievement.source !== "self_report" && (
                        <Badge tone="muted">
                          {achievement.source === "cv_parse"
                            ? t("education.fromCv")
                            : achievement.source}
                        </Badge>
                      )}
                    </>
                  }
                />
              ))
            )}
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
            entity === "education" ? (
              <EducationEditor
                form={eduForm}
                onChange={patchForm}
                onSave={() => void save()}
                onCancel={() => guard(closeEditor)}
                onDismissErrors={() => setShowErrors(false)}
                showErrors={showErrors}
                saving={saving}
                isNew={isNew}
                universities={universities}
                departments={departments}
                onUniversityCreated={(university) =>
                  setUniversities((prev) =>
                    prev.some((u) => u.id === university.id)
                      ? prev
                      : [university, ...prev]
                  )
                }
                onDepartmentsChanged={(universityId) => {
                  void fetchUniversity(universityId)
                    .then((detail) => setDepartments(detail.departments))
                    .catch(() => undefined);
                }}
              />
            ) : entity === "certifications" ? (
              <CertificationEditor
                form={certForm}
                onChange={patchForm}
                onSave={() => void save()}
                onCancel={() => guard(closeEditor)}
                onDismissErrors={() => setShowErrors(false)}
                showErrors={showErrors}
                saving={saving}
                isNew={isNew}
              />
            ) : (
              <AchievementEditor
                form={achForm}
                onChange={patchForm}
                onSave={() => void save()}
                onCancel={() => guard(closeEditor)}
                onDismissErrors={() => setShowErrors(false)}
                showErrors={showErrors}
                saving={saving}
                isNew={isNew}
              />
            )
          ) : (
            <div
              className="flex min-h-0 flex-1 items-center justify-center p-6"
              data-testid="education-editor-empty"
            >
              <div className="text-center">
                <p className="text-sm font-medium text-[var(--as-fg)]">
                  {t("education.nothingSelected")}
                </p>
                <p className="mt-1 text-xs text-[var(--as-muted-fg)]">
                  {t("education.emptyBody")}
                </p>
                <Button
                  variant="default"
                  className="mt-3"
                  onClick={openCreate}
                >
                  {t("education.addEntry")}
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>

      {deleted && deleted.length > 0 && (
        <div
          className="fixed bottom-6 left-6 z-[var(--as-z-modal)]"
          data-testid="undo-education"
        >
          <UndoNotice
            message={
              deleted.length === 1
                ? t("education.deletedNotice", {
                    title:
                      deleted[0].entity === "education"
                        ? deleted[0].item.program ||
                          deleted[0].item.institution
                        : deleted[0].entity === "achievements"
                          ? deleted[0].item.title
                          : deleted[0].item.name,
                  })
                : t("education.bulkDeletedNotice", { count: deleted.length })
            }
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
        title={t("education.discardTitle")}
        description={t("education.discardBody")}
        confirmLabel={t("education.discard")}
        destructive
        onConfirm={() => confirmAction && discardAnd(confirmAction)}
      />

      <ConfirmationModal
        open={bulkConfirm}
        onOpenChange={setBulkConfirm}
        onConfirm={() => void bulkDelete()}
        title={t("education.bulkDeleteTitle", { count: selectedIds.length })}
        description={t("education.bulkDeleteBody")}
        confirmLabel={t("common.delete")}
        destructive
      />
    </div>
  );
}

function Badge({
  tone,
  children,
}: {
  tone: "accent" | "warn" | "muted" | "danger";
  children: React.ReactNode;
}) {
  const tones = {
    accent: "bg-[color-mix(in_srgb,var(--as-accent)_12%,transparent)] text-[var(--as-accent)]",
    warn: "bg-amber-100 text-amber-800",
    muted: "bg-[var(--as-muted)] text-[var(--as-muted-fg)]",
    danger: "bg-red-100 text-red-700",
  } as const;
  return (
    <span className={`rounded-full px-2 py-0.5 text-[11px] ${tones[tone]}`}>
      {children}
    </span>
  );
}

function RailCard({
  id,
  icon: Icon,
  title,
  subtitle,
  badges,
  active,
  selected,
  onOpen,
  onToggleSelect,
  onDuplicate,
  onDelete,
}: {
  id: string;
  icon: LucideIcon;
  title: string;
  subtitle: string;
  badges: React.ReactNode;
  active: boolean;
  selected: boolean;
  onOpen: () => void;
  onToggleSelect: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  return (
    <article
      className={`group relative cursor-pointer rounded-xl border p-3 transition-colors duration-150 ${
        selected
          ? "border-[var(--as-accent)] bg-[color-mix(in_srgb,var(--as-accent)_5%,transparent)]"
          : active
            ? "border-[var(--as-accent)] bg-[color-mix(in_srgb,var(--as-accent)_8%,transparent)]"
            : "border-[var(--as-border)] bg-[var(--as-surface)] hover:border-[var(--as-accent)]"
      }`}
      data-testid={`education-item-${id}`}
    >
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full cursor-pointer items-start justify-between gap-2 pr-8 text-left"
        data-testid="education-item"
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
              {title}
            </span>
            <span className="mt-0.5 block truncate text-xs text-[var(--as-muted-fg)]">
              {subtitle}
            </span>
            {(badges !== null) && (
              <span className="mt-1 flex flex-wrap gap-1">{badges}</span>
            )}
          </span>
        </span>
      </button>
      <button
        type="button"
        aria-label={t("education.duplicateAria", { title })}
        className="absolute right-8 top-2 hidden cursor-pointer rounded p-1 text-slate-300 transition-colors group-hover:text-slate-400 hover:text-[var(--as-accent)] group-hover:block"
        data-testid={`duplicate-education-${id}`}
        onClick={onDuplicate}
      >
        <Copy className="h-3.5 w-3.5" aria-hidden />
      </button>
      <button
        type="button"
        aria-label={t("education.deleteAria", { title })}
        className="absolute right-2 top-2 cursor-pointer rounded p-1 text-slate-300 transition-colors hover:text-[var(--as-danger)] group-hover:text-slate-400"
        data-testid={`delete-education-${id}`}
        onClick={onDelete}
      >
        <Trash2 className="h-3.5 w-3.5" aria-hidden />
      </button>
      <div className="absolute bottom-2 right-2">
        <SelectionToggle
          selected={selected}
          label={t("education.selectAria", { title })}
          onToggle={onToggleSelect}
        />
      </div>
    </article>
  );
}
