import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Briefcase,
  ClipboardCheck,
  FileUp,
  Gauge,
  GraduationCap,
  Heart,
  ImagePlus,
  Languages,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Telescope,
  ThumbsUp,
  UserRound,
  Wrench,
} from "lucide-react";
import { SettingsShell, type SettingsNavItem } from "@neuronection/assistant-ui";
import { statusLabelKey } from "@/components/intake/CvStatus";
import { listCvDraftHistory } from "@/api/cvIntake";
import type { DraftHistoryRow } from "@/types/cvIntake";
import { useProfileStore } from "@/stores/profileStore";
import { useAuthStore } from "@/stores/authStore";
import {
  deleteAccount,
  downloadExport,
  requestExport,
  type BackgroundJob,
} from "@/api/backgroundJobs";
import { fetchExperience } from "@/api/experience";
import { fetchEducation } from "@/api/education";
import { fetchAssessments } from "@/api/assessments";
import { fetchMySkills } from "@/api/skills";
import type { ExperienceItemOut } from "@/types/experience";
import type { EducationItemOut } from "@/types/education";
import { EDUCATION_LEVEL_ORDER } from "@/components/profile/sections/options";
import { setStage } from "@/api/stages";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import { useBackgroundJob } from "@/hooks/useBackgroundJob";
import { apiDetail } from "@/api/client";
import { JobFlowStatus } from "@/components/JobFlowStatus";
import {
  deleteGalleryPhoto,
  fetchPhotoBlobUrl,
  fetchPhotoGallery,
  fetchPhotoState,
  setDefaultPhoto,
  uploadPhoto,
  type GalleryPhoto,
} from "@/api/mePhoto";
import { Button, SearchableDropdown } from "@/components/ui";
import {
  PROFILE_SCOPES,
  PROFILE_SCOPE_KEYS,
  SECTION_LABEL_KEYS,
  isProfileScopeKey,
  scopesFor,
  sectionsForScope,
  type ProfileScopeKey,
  type ProfileSectionId,
} from "@/config/profileScopes";
import { ScopeDots, ScopeFocusTabs } from "@/components/profile/ScopeChips";
import { AcademicsCard } from "@/components/profile/sections/AcademicsCard";
import { LanguagesCard } from "@/components/profile/sections/LanguagesCard";
import { AspirationsCard } from "@/components/profile/sections/AspirationsCard";
import { BasicsCard } from "@/components/profile/sections/BasicsCard";
import { ConstraintsCard } from "@/components/profile/sections/ConstraintsCard";
import { InterestsCard } from "@/components/profile/sections/InterestsCard";
import { SkillsCard } from "@/components/profile/sections/SkillsCard";
import { TastesCard } from "@/components/profile/sections/TastesCard";
import { WeightsCard } from "@/components/profile/sections/WeightsCard";
import { WorkStyleCard } from "@/components/profile/sections/WorkStyleCard";
import { ProfileSectionCard } from "@/components/profile/ProfileSectionCard";
import type { CareerStage, Profile } from "@/types";

const STAGE_OPTIONS = [
  { value: "student", labelKey: "profileEdit.stage.student" },
  { value: "early_career", labelKey: "profileEdit.stage.early_career" },
  { value: "experienced", labelKey: "profileEdit.stage.experienced" },
  { value: "switching", labelKey: "profileEdit.stage.switching" },
  { value: "returning", labelKey: "profileEdit.stage.returning" },
];

function CompleteDot({
  id,
  done,
  required,
}: {
  id: string;
  done: boolean;
  required: boolean;
}) {
  const { t } = useTranslation();
  const tone = done
    ? "bg-[var(--as-accent)]"
    : required
      ? "bg-amber-400"
      : "border border-[var(--as-border)] bg-transparent";
  return (
    <span
      aria-hidden
      title={
        done
          ? t("profileEdit.dot.completed")
          : required
            ? t("profileEdit.dot.required")
            : t("profileEdit.dot.optional")
      }
      className={`inline-block size-2 rounded-full ${tone}`}
      data-testid={`rail-dot-${id}`}
      data-complete={String(done)}
      data-required={String(required)}
    />
  );
}

const SCOPE_PINNED_IDS = new Set(["overview"]);

function railNav(
  sections: Profile["completeness"]["sections"],
  required: Profile["completeness"]["required"],
  t: (key: string) => string
): (SettingsNavItem & { id: string })[] {
  const dot = (id: string, done: boolean, req: boolean) => (
    <CompleteDot id={id} done={done} required={req} />
  );
  const dots = (id: string) => <ScopeDots sectionId={id} />;
  const dotAndDots = (
    id: string,
    done: boolean,
    req: boolean
  ) => (
    <span className="flex items-center gap-1.5">
      {dot(id, done, req)}
      {dots(id)}
    </span>
  );
  return [
    { id: "overview", label: t("profileEdit.nav.overview"), icon: Gauge },
    {
      id: "photo",
      label: t("profileEdit.nav.photo"),
      icon: ImagePlus,
      trailing: dots("photo"),
    },
    {
      id: "basics",
      label: t("profileEdit.nav.basics"),
      icon: UserRound,
      trailing: dotAndDots("basics", !!sections.basics, !!required?.basics),
    },
    {
      id: "academics",
      label: t("profileEdit.nav.academics"),
      icon: GraduationCap,
      trailing: dotAndDots("academics", !!sections.academics, !!required?.academics),
    },
    {
      id: "languages",
      label: t("profileEdit.nav.languages"),
      icon: Languages,
      trailing: dots("languages"),
    },
    {
      id: "interests",
      label: t("profileEdit.nav.interests"),
      icon: Heart,
      trailing: dotAndDots("interests", !!sections.interests, !!required?.interests),
    },
    {
      id: "tastes",
      label: t("profileEdit.nav.tastes"),
      icon: ThumbsUp,
      trailing: dotAndDots("tastes", !!sections.likes, !!required?.likes),
    },
    {
      id: "aspirations",
      label: t("profileEdit.nav.aspirations"),
      icon: Telescope,
      trailing: dotAndDots("aspirations", !!sections.aspirations, !!required?.aspirations),
    },
    {
      id: "work-style",
      label: t("profileEdit.nav.workStyle"),
      icon: SlidersHorizontal,
      trailing: dotAndDots(
        "work-style",
        !!sections.work_preferences,
        !!required?.work_preferences
      ),
    },
    {
      id: "constraints",
      label: t("profileEdit.nav.constraints"),
      icon: ShieldCheck,
      trailing: dotAndDots("constraints", !!sections.constraints, !!required?.constraints),
    },
    {
      id: "skills",
      label: t("profileEdit.nav.skills"),
      icon: Wrench,
      trailing: dots("skills"),
    },
    { id: "weights", label: t("profileEdit.nav.weights"), icon: SlidersHorizontal, trailing: dots("weights") },
    { id: "experience", label: t("experience.title"), icon: Briefcase, trailing: dots("experience") },
    { id: "education", label: t("education.title"), icon: GraduationCap, trailing: dots("education") },
    {
      id: "assessment",
      label: t("profileEdit.nav.assessment"),
      icon: ClipboardCheck,
      trailing: dots("assessment"),
    },
    { id: "account", label: t("profileEdit.nav.account"), icon: UserRound },
  ];
}

export function ProfileEdit() {
  const { t } = useTranslation();
  const { profile, load, saveSection, analyze } = useProfileStore();
  const reload = () => {
    useProfileStore.setState({ profile: null });
    void load();
  };
  const navigate = useNavigate();
  const [active, setActive] = useState<string>(
    () => window.location.hash.replace("#", "") || "overview"
  );
  const [scopeFocus, setScopeFocus] = useState<ProfileScopeKey | null>(() => {
    const param = new URLSearchParams(window.location.search).get("focus");
    return isProfileScopeKey(param) ? param : null;
  });
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onHash = () =>
      setActive(window.location.hash.replace("#", "") || "overview");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const navigateTo = (id: string) => {
    setActive(id);
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${window.location.search}#${id}`
    );
    document
      .getElementById("main")
      ?.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  };

  const applyScopeFocus = (scope: ProfileScopeKey | null) => {
    setScopeFocus(scope);
    const params = new URLSearchParams(window.location.search);
    if (scope === null) {
      params.delete("focus");
    } else {
      params.set("focus", scope);
    }
    const query = Array.from(params.keys()).length > 0 ? `?${params.toString()}` : "";
    window.history.replaceState(null, "", `${window.location.pathname}${query}${window.location.hash}`);
    if (scope !== null && !SCOPE_PINNED_IDS.has(active) && !scopesFor(active).includes(scope)) {
      navigateTo("overview");
    }
  };

  const onExportDone = (finished: BackgroundJob) => {
    setExporting(false);
    if (finished.status === "failed") {
      setError(finished.error ?? t("profileEdit.exportFailed"));
      return;
    }
    if (finished.status === "succeeded") {
      void downloadExport(finished.id);
    }
  };
  const { job: exportJob, track: trackExport } = useBackgroundJob(onExportDone);

  const startExport = async () => {
    setExporting(true);
    setError("");
    try {
      const jobId = await requestExport();
      trackExport(jobId);
    } catch (err) {
      setError(apiDetail(err));
      setExporting(false);
    }
  };

  const confirmDelete = async () => {
    setDeleting(true);
    setError("");
    try {
      await deleteAccount(deletePassword);
      useAuthStore.getState().reset();
      navigate("/");
    } catch (err) {
      setError(apiDetail(err));
      setDeleting(false);
    }
  };

  const switchStage = async (stage: CareerStage | null) => {
    setError("");
    try {
      const bootstrap = await setStage(stage);
      useBootstrapStore.getState().apply(bootstrap);
      reload();
      setSaved(true);
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  if (!profile) return <p className="text-slate-400">{t("common.loading")}</p>;
  const p = profile;
  const nav = railNav(p.completeness.sections, p.completeness.required, t);
  const visibleNav = scopeFocus === null
    ? nav
    : nav.filter(
        (item) =>
          SCOPE_PINNED_IDS.has(item.id) || scopesFor(item.id).includes(scopeFocus)
      );
  const hiddenCount = nav.length - visibleNav.length;

  return (
    <div className="mx-auto max-w-6xl" data-testid="profile-edit">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <ScopeFocusTabs focus={scopeFocus} onFocus={applyScopeFocus} />
        {scopeFocus !== null && (
          <p
            className="text-xs text-[var(--as-muted-fg)]"
            data-testid="scope-focus-strip"
          >
            {t("profileScopes.hiddenCount", { count: hiddenCount })} ·{" "}
            <button
              type="button"
              onClick={() => applyScopeFocus(null)}
              className="font-medium text-[var(--as-accent)] hover:underline"
              data-testid="scope-focus-show-all"
            >
              {t("profileScopes.showAll")}
            </button>
          </p>
        )}
      </div>
      <SettingsShell
        nav={visibleNav}
        active={active}
        onNavigate={navigateTo}
        header={{ icon: UserRound, title: t("profileEdit.title") }}
        navTestId="section-rail"
        navClassName="lg:top-0 lg:max-h-[calc(100vh-3.5rem)] lg:overflow-y-auto"
      >
        <div className="space-y-4">
          {error && (
            <p role="alert" className="text-sm text-rose-600">
              {error}
            </p>
          )}
          {active === "overview" && (
            <OverviewSection
              profile={p}
              onStage={switchStage}
              onNavigate={navigateTo}
              onAnalyze={async () => {
                setAnalyzing(true);
                setError("");
                try {
                  await analyze();
                } catch (err) {
                  setError(apiDetail(err));
                } finally {
                  setAnalyzing(false);
                }
              }}
              analyzing={analyzing}
            />
          )}
          {active === "photo" && <PhotoSection />}
          {active === "basics" && (
            <BasicsCard
              initial={p.basics}
              onSave={saveSection}
              complete={p.completeness.sections.basics}
            />
          )}
          {active === "academics" && (
            <AcademicsCard
              initial={p.academics}
              onSave={saveSection}
              complete={p.completeness.sections.academics}
            />
          )}
          {active === "languages" && (
            <LanguagesCard
              initial={p.academics}
              onSave={saveSection}
              complete={p.academics.languages.length > 0}
            />
          )}
          {active === "interests" && (
            <InterestsCard
              initial={p.interests}
              onSave={saveSection}
              complete={p.completeness.sections.interests}
            />
          )}
          {active === "tastes" && (
            <TastesCard
              initial={{ likes: p.likes, dislikes: p.dislikes, hobbies: p.hobbies }}
              onSave={saveSection}
              complete={p.completeness.sections.likes}
            />
          )}
          {active === "aspirations" && (
            <AspirationsCard
              initial={p.aspirations}
              onSave={saveSection}
              complete={p.completeness.sections.aspirations}
            />
          )}
          {active === "work-style" && (
            <WorkStyleCard
              initial={p.work_preferences}
              onSave={saveSection}
              complete={p.completeness.sections.work_preferences}
            />
          )}
          {active === "constraints" && (
            <ConstraintsCard
              initial={p.constraints}
              onSave={saveSection}
              complete={p.completeness.sections.constraints}
            />
          )}
          {active === "skills" && (
            <SkillsCard onChanged={reload} />
          )}
          {active === "weights" && (
            <WeightsCard
              initial={p.preferences?.scoring_weights}
              onChanged={reload}
            />
          )}
          {active === "experience" && <ExperienceSummaryCard />}
          {active === "education" && <EducationSummaryCard />}
          {active === "assessment" && <AssessmentSummaryCard />}
          {active === "account" && (
            <AccountSection
              exporting={exporting}
              exportJob={exportJob}
              onExport={() => void startExport()}
              onDeleteConfirm={() => void confirmDelete()}
              deleteConfirm={deleteConfirm}
              onDeleteToggle={() => setDeleteConfirm((v) => !v)}
              deletePassword={deletePassword}
              onDeletePassword={setDeletePassword}
              deleting={deleting}
            />
          )}
          {saved && <p className="text-sm text-emerald-600">{t("profileEdit.saved")}</p>}
        </div>
      </SettingsShell>
    </div>
  );
}

function CvImportStatus() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<DraftHistoryRow[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    listCvDraftHistory()
      .then((history) => {
        if (!cancelled) setRows(history);
      })
      .catch(() => {
        if (!cancelled) setRows([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  if (rows === null) return null;
  if (rows.length === 0) {
    return (
      <p className="text-xs text-[var(--as-muted-fg)]" data-testid="import-cv-status">
        {t("profileImport.panel.empty")}
      </p>
    );
  }
  const latest = rows[0];
  return (
    <p className="text-xs text-[var(--as-muted-fg)]" data-testid="import-cv-status">
      {t("profileImport.panel.summary", {
        count: rows.length,
        filename: latest.document.filename,
      })}{" "}
      · {t(statusLabelKey(latest))}
    </p>
  );
}

function OverviewSection({
  profile,
  onStage,
  onNavigate,
  onAnalyze,
  analyzing,
}: {
  profile: Profile;
  onStage: (stage: CareerStage | null) => Promise<void>;
  onNavigate: (id: string) => void;
  onAnalyze: () => Promise<void>;
  analyzing: boolean;
}) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const p = profile;
  return (
    <>
      <GoalReadinessCard profile={p} onNavigate={onNavigate} />
      <ProfileSectionCard
        name="overview"
        title={t("profileEdit.completenessTitle")}
        description={t("profileEdit.completenessBody")}
      >
        <div className="flex items-center justify-between">
          <p className="text-sm text-[var(--as-muted-fg)]">
            {t("profileEdit.completeness", { percent: p.completeness.percent })}
          </p>
          <Button
            variant="default"
            size="sm"
            onClick={() => void onAnalyze()}
            disabled={analyzing}
          >
            <Sparkles className="mr-1 h-3.5 w-3.5" aria-hidden />
            {analyzing ? t("onboarding.analyzing") : t("profileEdit.rerunAnalysis")}
          </Button>
        </div>
        <div
          className="mt-2 h-2 rounded-full bg-[var(--as-muted)]"
          data-testid="completeness-bar"
        >
          <div
            className="h-2 rounded-full bg-[var(--as-accent)]"
            style={{ width: `${p.completeness.percent}%` }}
          />
        </div>
        {p.completeness.required_percent != null &&
          p.completeness.required_percent < 100 && (
            <p
              className="mt-2 text-xs text-amber-600"
              data-testid="required-hint"
            >
              {t("profileEdit.requiredHint", {
                percent: p.completeness.required_percent,
              })}
            </p>
          )}
        {p.ai_summary && (
          <div
            className="mt-3 rounded-lg border border-[color-mix(in_srgb,var(--as-accent)_25%,transparent)] bg-[color-mix(in_srgb,var(--as-accent)_8%,transparent)] p-3"
            data-testid="ai-summary"
          >
            <p className="text-sm text-[var(--as-fg)]">{p.ai_summary.summary}</p>
            {p.ai_summary.strengths.length > 0 && (
              <p className="mt-1 text-xs text-[var(--as-muted-fg)]">
                <strong>{t("profileEdit.strengthsLabel")}</strong>{" "}
                {p.ai_summary.strengths.join(", ")}
              </p>
            )}
            {p.ai_summary.watchouts.length > 0 && (
              <p className="text-xs text-[var(--as-muted-fg)]">
                <strong>{t("profileEdit.watchoutsLabel")}</strong>{" "}
                {p.ai_summary.watchouts.join(", ")}
              </p>
            )}
          </div>
        )}
      </ProfileSectionCard>
      <ProfileSectionCard
        name="import_cv"
        title={t("profileEdit.importCvTitle")}
        description={t("profileEdit.importCvBody")}
      >
        <div
          className="flex items-center gap-3 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
          data-testid="import-cv-panel"
        >
          <span
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[color-mix(in_srgb,var(--as-accent)_12%,transparent)]"
            aria-hidden
          >
            <FileUp className="h-5 w-5 text-[var(--as-accent)]" />
          </span>
          <div className="min-w-0 flex-1">
            <CvImportStatus />
          </div>
          <Button
            size="sm"
            onClick={() => navigate("/profile/import")}
            data-testid="import-cv-entry"
          >
            {t("profileEdit.importCvAction")}
          </Button>
        </div>
      </ProfileSectionCard>
      <ProfileSectionCard
        name="stage"
        title={t("profileEdit.stageTitle")}
        description={t("profileEdit.stageBody")}
      >
        <div className="max-w-xs" data-testid="stage-switch">
          <SearchableDropdown
            options={STAGE_OPTIONS.map((o) => ({
              value: o.value,
              label: t(o.labelKey),
            }))}
            value={p.career_stage ?? ""}
            onChange={(v) => void onStage((v || null) as CareerStage | null)}
            placeholder={t("profileEdit.stagePlaceholder")}
          />
        </div>
        {p.stage_source === "derived" && (
          <p className="mt-1 text-xs text-[var(--as-muted-fg)]">
            {t("profileEdit.stageDerived")}
          </p>
        )}
      </ProfileSectionCard>
    </>
  );
}

function PhotoSection() {
  const { t } = useTranslation();
  const [gallery, setGallery] = useState<GalleryPhoto[]>([]);
  const [photoUrls, setPhotoUrls] = useState<Record<string, string>>({});
  const [photoBusy, setPhotoBusy] = useState(false);
  const [error, setError] = useState("");

  const loadPhoto = async () => {
    setPhotoBusy(true);
    try {
      const [photos, state] = await Promise.all([
        fetchPhotoGallery(),
        fetchPhotoState(),
      ]);
      setGallery(photos);
      const urls: Record<string, string> = {};
      for (const photo of photos) {
        urls[photo.document_id] = await fetchPhotoBlobUrl(photo.document_id);
      }
      setPhotoUrls(urls);
      if (state.photo_document_id && !urls[state.photo_document_id]) {
        urls[state.photo_document_id] = await fetchPhotoBlobUrl(
          state.photo_document_id
        );
        setPhotoUrls({ ...urls });
      }
    } catch {
      setGallery([]);
    } finally {
      setPhotoBusy(false);
    }
  };

  useEffect(() => {
    void loadPhoto();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onPhotoSelected = async (file: File) => {
    setPhotoBusy(true);
    setError("");
    try {
      await uploadPhoto(file);
      await loadPhoto();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setPhotoBusy(false);
    }
  };

  const onPhotoRemoved = async (documentId: string) => {
    setPhotoBusy(true);
    setError("");
    try {
      await deleteGalleryPhoto(documentId);
      await loadPhoto();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setPhotoBusy(false);
    }
  };

  const onPhotoDefault = async (documentId: string) => {
    setError("");
    try {
      await setDefaultPhoto(documentId);
      setGallery((rows) =>
        [...rows]
          .map((row) => ({ ...row, is_default: row.document_id === documentId }))
          .sort((a) => (a.is_default ? -1 : 1))
      );
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  return (
    <ProfileSectionCard
      name="photo"
      title={t("profileEdit.photosTitle")}
      description={t("profileEdit.photosBody")}
      error={error || undefined}
    >
      <div data-testid="photo-card">
        <label className="inline-block cursor-pointer rounded-lg border border-[var(--as-border)] px-3 py-1.5 text-sm text-[var(--as-fg)] transition-colors hover:border-[var(--as-accent)]">
          {photoBusy ? t("common.saving") : t("profileEdit.upload")}
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            data-testid="photo-input"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void onPhotoSelected(file);
              event.target.value = "";
            }}
          />
        </label>
        {gallery.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-3">
            {gallery.map((photo) => (
              <div key={photo.document_id} className="w-28" data-testid="gallery-photo">
                <img
                  src={photoUrls[photo.document_id]}
                  alt={photo.filename}
                  className={`h-24 w-24 rounded-lg object-cover border ${
                    photo.is_default ? "ring-2 ring-[var(--as-accent)]" : ""
                  }`}
                />
                <div className="mt-1 flex items-center justify-between text-xs">
                  {photo.is_default ? (
                    <span className="font-medium text-[var(--as-accent)]">{t("profileEdit.defaultPhoto")}</span>
                  ) : (
                    <button
                      className="text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
                      onClick={() => void onPhotoDefault(photo.document_id)}
                      data-testid={`photo-default-${photo.document_id}`}
                    >
                      {t("profileEdit.setDefault")}
                    </button>
                  )}
                  <button
                    className="text-[var(--as-muted-fg)] hover:text-[var(--as-danger)]"
                    onClick={() => void onPhotoRemoved(photo.document_id)}
                    aria-label={t("profileEdit.deletePhoto")}
                    data-testid={`photo-delete-${photo.document_id}`}
                  >
                    ✕
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </ProfileSectionCard>
  );
}

function ExperienceSummaryCard() {
  const { t } = useTranslation();
  const [items, setItems] = useState<ExperienceItemOut[]>([]);
  const [years, setYears] = useState(0);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    void fetchExperience()
      .then((data) => {
        setItems(data.items);
        setYears(data.years_of_experience);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, []);

  const groups = useMemo(() => {
    const KIND_ORDER: ExperienceItemOut["kind"][] = [
      "job",
      "internship",
      "freelance",
      "project",
      "volunteer",
    ];
    return KIND_ORDER.map((kind) => ({
      kind,
      list: [...items]
        .filter((item) => item.kind === kind)
        .sort((a, b) => (b.start ?? "").localeCompare(a.start ?? "")),
    })).filter((group) => group.list.length > 0);
  }, [items]);

  return (
    <ProfileSectionCard
      name="experience"
      title={t("experience.title")}
      description={t("profileEdit.experienceBody")}
      actions={
        <Button asChild variant="outline" size="sm" data-testid="experience-link">
          <Link to="/profile/experience">
            <Briefcase className="mr-1 h-3.5 w-3.5" aria-hidden />
            {t("profileEdit.experienceLink")}
          </Link>
        </Button>
      }
    >
      {loaded && items.length === 0 ? (
        <p className="text-sm text-[var(--as-muted-fg)]">
          {t("experience.empty")}
        </p>
      ) : (
        <p className="text-sm text-[var(--as-muted-fg)]" data-testid="experience-years">
          {t("profileEdit.yearsSummary", {
            years,
            count: items.length,
          })}
        </p>
      )}
      {groups.map(({ kind, list }) => (
        <div key={kind} className="mt-3" data-testid={`experience-group-summary-${kind}`}>
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
              {t(`experience.kind.${kind}`, { defaultValue: kind })}
            </span>
            <span className="rounded-full bg-[var(--as-muted)] px-1.5 text-[10px] font-medium tabular-nums text-[var(--as-muted-fg)]">
              {list.length}
            </span>
            <span className="h-px flex-1 bg-[var(--as-border)]" aria-hidden />
          </div>
          <ul className="mt-1.5 space-y-1 text-sm text-[var(--as-fg)]">
            {list.map((item) => (
              <li
                key={item.id}
                className="flex items-center gap-2"
                data-testid={`experience-summary-${item.id}`}
              >
                <Briefcase className="h-3.5 w-3.5 shrink-0 text-[var(--as-muted-fg)]" aria-hidden />
                <span className="truncate">
                  {item.title}
                  {item.org_name ? ` · ${item.org_name}` : ""}
                </span>
                <span className="ml-auto shrink-0 text-xs text-[var(--as-muted-fg)]">
                  {item.start
                    ? `${item.start.slice(0, 7)} → ${
                        item.open_ended
                          ? t("experience.present")
                          : (item.end ?? "").slice(0, 7)
                      }`
                    : t("experience.noDates")}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </ProfileSectionCard>
  );
}

function EducationSummaryCard() {
  const { t } = useTranslation();
  const [items, setItems] = useState<EducationItemOut[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    fetchEducation()
      .then(setItems)
      .catch(() => undefined)
      .finally(() => setLoaded(true));
  }, []);

  const highest = useMemo(() => {
    let best: string | null = null;
    let rank = -1;
    for (const item of items) {
      if (item.status !== "active") continue;
      const r = EDUCATION_LEVEL_ORDER.indexOf(
        item.level as (typeof EDUCATION_LEVEL_ORDER)[number]
      );
      if (r > rank) {
        rank = r;
        best = item.level;
      }
    }
    return best;
  }, [items]);

  const inProgress = items.filter((i) => i.in_progress && i.status === "active");
  const top = useMemo(() => items.slice(0, 3), [items]);

  return (
    <ProfileSectionCard
      name="education"
      title={t("education.title")}
      description={t("profileEdit.educationBody")}
      actions={
        <Button asChild variant="outline" size="sm" data-testid="education-link">
          <Link to="/profile/education">
            <GraduationCap className="mr-1 h-3.5 w-3.5" aria-hidden />
            {t("profileEdit.educationLink")}
          </Link>
        </Button>
      }
    >
      {loaded && items.length === 0 ? (
        <p className="text-sm text-[var(--as-muted-fg)]">
          {t("education.emptyEducation")}
        </p>
      ) : (
        <p className="text-sm text-[var(--as-muted-fg)]" data-testid="education-highest">
          {t("education.entriesCount", { count: items.length })}
          {highest
            ? ` · ${t("profileEdit.highestShort", {
                level: t(`education.level.${highest}`, { defaultValue: highest }),
              })}`
            : ""}
          {inProgress.length > 0
            ? ` · ${t("education.inProgressCount", { count: inProgress.length })}`
            : ""}
          .
        </p>
      )}
      {top.length > 0 && (
        <ul className="mt-2 space-y-1 text-sm text-[var(--as-fg)]">
          {top.map((item) => (
            <li
              key={item.id}
              className="flex items-center gap-2"
              data-testid={`education-summary-${item.id}`}
            >
              <GraduationCap
                className="h-3.5 w-3.5 shrink-0 text-[var(--as-muted-fg)]"
                aria-hidden
              />
              <span className="truncate">
                {item.program || item.institution}
                {item.program ? ` · ${item.institution}` : ""}
              </span>
              <span className="ml-auto shrink-0 text-xs text-[var(--as-muted-fg)]">
                {t(`education.level.${item.level}`, { defaultValue: item.level })}
                {item.in_progress ? ` · ${t("profileEdit.ongoing")}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </ProfileSectionCard>
  );
}

function AssessmentSummaryCard() {
  const { t } = useTranslation();
  return (
    <ProfileSectionCard
      name="assessment"
      title={t("profileEdit.nav.assessment")}
      description={t("profileEdit.assessmentBody")}
    >
      <p className="text-sm text-[var(--as-muted-fg)]">
        {t("profileEdit.assessmentHint")}
      </p>
      <Link
        to="/profile/assessment"
        className="mt-3 inline-block text-sm text-[var(--as-accent)] hover:underline"
        data-testid="assessment-link"
      >
        {t("profileEdit.assessmentLink")}
      </Link>
    </ProfileSectionCard>
  );
}

function AccountSection({
  exporting,
  exportJob,
  onExport,
  deleteConfirm,
  onDeleteToggle,
  onDeleteConfirm,
  deletePassword,
  onDeletePassword,
  deleting,
}: {
  exporting: boolean;
  exportJob: BackgroundJob | null;
  onExport: () => void;
  deleteConfirm: boolean;
  onDeleteToggle: () => void;
  onDeleteConfirm: () => void;
  deletePassword: string;
  onDeletePassword: (value: string) => void;
  deleting: boolean;
}) {
  const { t } = useTranslation();
  return (
    <ProfileSectionCard
      name="account"
      title={t("profileEdit.accountTitle")}
      description={t("profileEdit.accountBody")}
    >
      <div data-testid="data-privacy">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" size="sm" onClick={onExport} disabled={exporting}>
            {exporting ? t("profileEdit.preparingExport") : t("profileEdit.exportData")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="text-[var(--as-danger)]"
            onClick={onDeleteToggle}
          >
            {t("profileEdit.deleteAccount")}
          </Button>
        </div>
        {exporting && exportJob && (
          <div className="mt-2" data-testid="export-progress">
            <JobFlowStatus job={exportJob} title={t("profileEdit.preparingExport")} />
          </div>
        )}
        {deleteConfirm && (
          <div className="mt-3 space-y-2 rounded-lg border border-[var(--as-danger)] bg-[color-mix(in_srgb,var(--as-danger)_8%,transparent)] p-3">
            <p className="text-sm text-[var(--as-danger)]">
              {t("profileEdit.deleteWarning")}
            </p>
            <input
              type="password"
              value={deletePassword}
              onChange={(e) => onDeletePassword(e.target.value)}
              placeholder={t("profileEdit.confirmPassword")}
              className="w-full rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2 text-sm text-[var(--as-fg)]"
            />
            <div className="flex gap-2">
              <Button
                variant="destructive"
                size="sm"
                onClick={onDeleteConfirm}
                disabled={deleting || !deletePassword}
              >
                {deleting ? t("profileEdit.deleting") : t("profileEdit.deleteForever")}
              </Button>
              <Button variant="outline" size="sm" onClick={onDeleteToggle}>
                {t("common.cancel")}
              </Button>
            </div>
          </div>
        )}
      </div>
    </ProfileSectionCard>
  );
}

const READINESS_COMPLETENESS_KEYS: Partial<
  Record<ProfileSectionId, keyof Profile["completeness"]["sections"]>
> = {
  basics: "basics",
  academics: "academics",
  interests: "interests",
  tastes: "likes",
  aspirations: "aspirations",
  "work-style": "work_preferences",
  constraints: "constraints",
};

function GoalReadinessCard({
  profile,
  onNavigate,
}: {
  profile: Profile;
  onNavigate: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [signals, setSignals] = useState<Record<string, boolean> | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchExperience().then((result) => result.items.length > 0).catch(() => false),
      fetchEducation().then((rows) => rows.length > 0).catch(() => false),
      fetchMySkills().then((rows) => rows.length > 0).catch(() => false),
      fetchAssessments()
        .then((runs) => runs.some((run) => run.status === "completed"))
        .catch(() => false),
      fetchPhotoState()
        .then((state) => state.photo_document_id !== null)
        .catch(() => false),
    ]).then(([experience, education, skills, assessment, photo]) => {
      if (!cancelled) {
        setSignals({ experience, education, skills, assessment, photo });
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const filledFor = (id: ProfileSectionId): boolean | null => {
    if (id === "weights") {
      return profile.preferences?.scoring_weights !== undefined;
    }
    if (id === "languages") {
      return profile.academics.languages.length > 0;
    }
    const completenessKey = READINESS_COMPLETENESS_KEYS[id];
    if (completenessKey !== undefined) {
      return !!profile.completeness.sections[completenessKey];
    }
    return signals === null ? null : !!signals[id];
  };

  const scopeRows = PROFILE_SCOPE_KEYS.map((key) => {
    const sections = sectionsForScope(key);
    const states = sections.map((id) => ({ id, filled: filledFor(id) }));
    const known = states.filter((state) => state.filled !== null);
    const filledCount = known.filter((state) => state.filled === true).length;
    const percent =
      known.length === 0 ? 0 : Math.round((filledCount / known.length) * 100);
    const next = states.find((state) => state.filled === false);
    return { key, sections, states, filledCount, percent, next };
  });

  return (
    <ProfileSectionCard
      name="readiness"
      title={t("profileScopes.readinessTitle")}
      description={t("profileScopes.readinessBody")}
    >
      <div className="flex flex-col gap-3" data-testid="scope-readiness">
        {scopeRows.map(({ key, filledCount, sections, percent, next }) => {
          const scope = PROFILE_SCOPES[key];
          const Icon = scope.icon;
          return (
            <div
              key={key}
              className="flex flex-col gap-2 sm:flex-row sm:items-center"
              data-testid={`scope-readiness-${key}`}
            >
              <span
                className={`inline-flex w-fit shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${scope.chipClass}`}
              >
                <Icon className="size-3.5" aria-hidden />
                {t(scope.labelKey)}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between text-xs text-[var(--as-muted-fg)]">
                  <span data-testid={`scope-readiness-${key}-count`}>
                    {t("profileScopes.progressCount", {
                      filled: filledCount,
                      total: sections.length,
                    })}
                  </span>
                  <span className="tabular-nums" data-testid={`scope-readiness-${key}-percent`}>
                    {signals === null ? "…" : `${percent}%`}
                  </span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[var(--as-muted)]">
                  <div
                    className={`h-full rounded-full transition-[width] ${
                      percent === 100 ? "bg-[var(--as-accent)]" : scope.dotClass
                    }`}
                    style={{ width: `${signals === null ? 0 : percent}%` }}
                    data-testid={`scope-readiness-${key}-bar`}
                  />
                </div>
              </div>
              {next ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="shrink-0"
                  data-testid={`scope-readiness-${key}-continue`}
                  onClick={() => onNavigate(next.id)}
                >
                  {t("profileScopes.continue", {
                    section: t(SECTION_LABEL_KEYS[next.id]),
                  })}
                </Button>
              ) : (
                signals !== null && (
                  <span
                    className="shrink-0 text-xs font-medium text-[var(--as-accent)]"
                    data-testid={`scope-readiness-${key}-done`}
                  >
                    {t("profileScopes.ready")}
                  </span>
                )
              )}
            </div>
          );
        })}
      </div>
    </ProfileSectionCard>
  );
}

export function useProfileGuard() {
  const navigate = useNavigate();
  return () => navigate("/onboarding");
}

export type ProfileDraft = Partial<Profile>;
