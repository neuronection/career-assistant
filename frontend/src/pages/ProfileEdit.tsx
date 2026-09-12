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
  AcademicsCard,
} from "@/components/profile/sections/AcademicsCard";
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

function railNav(
  sections: Profile["completeness"]["sections"],
  required: Profile["completeness"]["required"],
  t: (key: string) => string
): (SettingsNavItem & { id: string })[] {
  const dot = (id: string, done: boolean, req: boolean) => (
    <CompleteDot id={id} done={done} required={req} />
  );
  return [
    { id: "overview", label: t("profileEdit.nav.overview"), icon: Gauge },
    { id: "photo", label: t("profileEdit.nav.photo"), icon: ImagePlus },
    {
      id: "basics",
      label: t("profileEdit.nav.basics"),
      icon: UserRound,
      trailing: dot("basics", !!sections.basics, !!required?.basics),
    },
    {
      id: "academics",
      label: t("profileEdit.nav.academics"),
      icon: GraduationCap,
      trailing: dot("academics", !!sections.academics, !!required?.academics),
    },
    {
      id: "interests",
      label: t("profileEdit.nav.interests"),
      icon: Heart,
      trailing: dot("interests", !!sections.interests, !!required?.interests),
    },
    {
      id: "tastes",
      label: t("profileEdit.nav.tastes"),
      icon: ThumbsUp,
      trailing: dot("tastes", !!sections.likes, !!required?.likes),
    },
    {
      id: "aspirations",
      label: t("profileEdit.nav.aspirations"),
      icon: Telescope,
      trailing: dot("aspirations", !!sections.aspirations, !!required?.aspirations),
    },
    {
      id: "work-style",
      label: t("profileEdit.nav.workStyle"),
      icon: SlidersHorizontal,
      trailing: dot(
        "work-style",
        !!sections.work_preferences,
        !!required?.work_preferences
      ),
    },
    {
      id: "constraints",
      label: t("profileEdit.nav.constraints"),
      icon: ShieldCheck,
      trailing: dot("constraints", !!sections.constraints, !!required?.constraints),
    },
    { id: "skills", label: t("profileEdit.nav.skills"), icon: Wrench },
    { id: "weights", label: t("profileEdit.nav.weights"), icon: SlidersHorizontal },
    { id: "experience", label: t("experience.title"), icon: Briefcase },
    { id: "education", label: t("education.title"), icon: GraduationCap },
    { id: "assessment", label: t("profileEdit.nav.assessment"), icon: ClipboardCheck },
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

  return (
    <div className="mx-auto max-w-6xl" data-testid="profile-edit">
      <SettingsShell
        nav={nav}
        active={active}
        onNavigate={navigateTo}
        header={{ icon: UserRound, title: t("profileEdit.title") }}
        navTestId="section-rail"
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
      <p className="mt-2 text-xs text-[var(--as-muted-fg)]" data-testid="import-cv-status">
        {t("profileImport.panel.empty")}
      </p>
    );
  }
  const latest = rows[0];
  return (
    <p className="mt-2 text-xs text-[var(--as-muted-fg)]" data-testid="import-cv-status">
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
  onAnalyze,
  analyzing,
}: {
  profile: Profile;
  onStage: (stage: CareerStage | null) => Promise<void>;
  onAnalyze: () => Promise<void>;
  analyzing: boolean;
}) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const p = profile;
  return (
    <>
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
        <div
          className="mt-3 rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
          data-testid="import-cv-panel"
        >
          <div className="flex items-start gap-3">
            <FileUp
              className="mt-0.5 h-5 w-5 shrink-0 text-[var(--as-accent)]"
              aria-hidden
            />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-[var(--as-fg)]">
                {t("profileImport.title")}
              </p>
              <p className="mt-0.5 text-xs text-[var(--as-muted-fg)]">
                {t("profileImport.subtitle")}
              </p>
              <CvImportStatus />
            </div>
            <Button
              size="sm"
              onClick={() => navigate("/profile/import")}
              data-testid="import-cv-entry"
            >
              {t("profileImport.open")}
            </Button>
          </div>
        </div>
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

  const top = useMemo(
    () =>
      [...items]
        .sort((a, b) => (b.start ?? "").localeCompare(a.start ?? ""))
        .slice(0, 3),
    [items]
  );

  return (
    <ProfileSectionCard
      name="experience"
      title={t("experience.title")}
      description={t("profileEdit.experienceBody")}
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
      {top.length > 0 && (
        <ul className="mt-2 space-y-1 text-sm text-[var(--as-fg)]">
          {top.map((item) => (
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
                {item.start.slice(0, 7)} →{" "}
                {item.open_ended ? t("experience.present") : (item.end ?? "").slice(0, 7)}
              </span>
            </li>
          ))}
        </ul>
      )}
      <Link
        to="/profile/experience"
        className="mt-3 inline-block text-sm text-[var(--as-accent)] hover:underline"
        data-testid="experience-link"
      >
        {t("profileEdit.experienceLink")}
      </Link>
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
      <Link
        to="/profile/education"
        className="mt-3 inline-block text-sm text-[var(--as-accent)] hover:underline"
        data-testid="education-link"
      >
        {t("profileEdit.educationLink")}
      </Link>
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

export function useProfileGuard() {
  const navigate = useNavigate();
  return () => navigate("/onboarding");
}

export type ProfileDraft = Partial<Profile>;
