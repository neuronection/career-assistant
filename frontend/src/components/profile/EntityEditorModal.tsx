import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ConfirmationModal,
  Modal,
  ModalContent,
  ModalTitle,
} from "@/components/ui";
import { apiDetail } from "@/api/client";
import {
  createExperienceItem,
  fetchExperience,
  updateExperienceItem,
} from "@/api/experience";
import { fetchSkillOntology } from "@/api/skills";
import type { SkillSummary } from "@/api/skills";
import {
  createAchievement,
  createCertification,
  createEducationItem,
  fetchAchievements,
  fetchCertifications,
  fetchEducation,
  updateAchievement,
  updateCertification,
  updateEducationItem,
} from "@/api/education";
import { fetchUniversities, fetchUniversity } from "@/api/universities";
import type { Department, University } from "@/types";
import {
  EMPTY_FORM,
  ExperienceEditor,
  experienceToIn,
  formFromItem,
  validateExperience,
} from "@/components/experience/ExperienceEditor";
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
  validateEducation,
  type AchievementEditorForm,
  type CertificationEditorForm,
  type EducationEditorForm,
} from "@/components/education/EducationEditor";
import { SkillsCard } from "@/components/profile/sections/SkillsCard";
import { CONTEXT_SOURCE_LINKS } from "@/lib/entityLinks";

interface EntityEditorModalProps {
  sourceKey: string;
  /** `null` opens the editor in create mode (kind preset per source). */
  itemId: string | null;
  onSaved: () => void;
  onClose: () => void;
}

interface BodyBaseProps {
  itemId: string | null;
  onDirty: () => void;
  onSaved: () => void;
  onCancel: () => void;
}

function mergeSkillOptions(
  options: { value: string; label: string }[],
  item: { skills: { skill_key: string; skill_label: string }[] }
): { value: string; label: string }[] {
  const merged = [...options];
  const known = new Set(options.map((o) => o.value));
  for (const s of item.skills) {
    if (!known.has(s.skill_key)) {
      merged.push({ value: s.skill_key, label: s.skill_label });
      known.add(s.skill_key);
    }
  }
  return merged;
}

function ExperienceModalBody({
  sourceKey,
  itemId,
  onDirty,
  onSaved,
  onCancel,
}: BodyBaseProps & { sourceKey: string }) {
  const { t } = useTranslation();
  const [form, setForm] = useState(() => ({
    ...EMPTY_FORM,
    ...(sourceKey === "volunteer" ? { kind: "volunteer" as const } : {}),
    ...(sourceKey === "experience" ? { kind: "job" as const } : {}),
  }));
  const [skillOptions, setSkillOptions] = useState<
    { value: string; label: string }[]
  >([]);
  const [missing, setMissing] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const ontology = fetchSkillOntology()
      .then((rows: SkillSummary[]) =>
        rows.map((s) => ({ value: s.key, label: s.label }))
      )
      .catch(() => [] as { value: string; label: string }[]);
    if (itemId) {
      void Promise.all([fetchExperience(), ontology])
        .then(([list, options]) => {
          if (cancelled) return;
          const item = list.items.find((row) => row.id === itemId);
          if (!item) {
            setMissing(true);
            return;
          }
          setForm(formFromItem(item));
          setSkillOptions(mergeSkillOptions(options, item));
        })
        .catch((err) => !cancelled && setError(apiDetail(err)));
    } else {
      void ontology.then(
        (options) => !cancelled && setSkillOptions(options)
      );
    }
    return () => {
      cancelled = true;
    };
  }, [itemId]);

  const save = async () => {
    setShowErrors(true);
    const v = validateExperience(form);
    if (
      v.title ||
      v.start ||
      v.end ||
      v.hours ||
      v.links.some(Boolean) ||
      v.achievements.some(Boolean)
    ) {
      return;
    }
    setSaving(true);
    setError("");
    try {
      const payload = experienceToIn(form);
      if (itemId) await updateExperienceItem(itemId, payload);
      else await createExperienceItem(payload);
      onSaved();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setSaving(false);
    }
  };

  if (missing) {
    return (
      <p
        className="p-6 text-center text-sm text-[var(--as-muted-fg)]"
        data-testid="entity-editor-missing"
      >
        {t("entityEditor.notFound")}
      </p>
    );
  }

  return (
    <>
      <ExperienceEditor
        form={form}
        onChange={(patch) => {
          setForm((prev) => ({ ...prev, ...patch }));
          onDirty();
        }}
        onSave={() => void save()}
        onCancel={onCancel}
        onDismissErrors={() => setShowErrors(false)}
        showErrors={showErrors}
        skillOptions={skillOptions}
        saving={saving}
        isNew={!itemId}
      />
      {error && (
        <p role="alert" className="px-5 pb-2 text-sm text-[var(--as-danger)]">
          {error}
        </p>
      )}
    </>
  );
}

function EducationModalBody({
  kind,
  itemId,
  onDirty,
  onSaved,
  onCancel,
}: BodyBaseProps & { kind: "education" | "certification" | "achievement" }) {
  const { t } = useTranslation();
  const [eduForm, setEduForm] = useState<EducationEditorForm>({
    ...EMPTY_EDUCATION_FORM,
  });
  const [certForm, setCertForm] = useState<CertificationEditorForm>({
    ...EMPTY_CERTIFICATION_FORM,
  });
  const [achForm, setAchForm] = useState<AchievementEditorForm>({
    ...EMPTY_ACHIEVEMENT_FORM,
  });
  const [universities, setUniversities] = useState<University[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [missing, setMissing] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const loadItem = async () => {
      try {
        if (kind === "education") {
          const [rows, catalog] = await Promise.all([
            fetchEducation(),
            fetchUniversities().catch(() => [] as University[]),
          ]);
          if (cancelled) return;
          setUniversities(catalog);
          const item = itemId
            ? rows.find((row) => row.id === itemId)
            : null;
          if (itemId && !item) {
            setMissing(true);
            return;
          }
          if (item) setEduForm(educationFormFromItem(item));
        } else if (kind === "certification") {
          const rows = await fetchCertifications();
          if (cancelled) return;
          const item = itemId
            ? rows.find((row) => row.id === itemId)
            : null;
          if (itemId && !item) {
            setMissing(true);
            return;
          }
          if (item) setCertForm(certificationFormFromItem(item));
        } else {
          const rows = await fetchAchievements();
          if (cancelled) return;
          const item = itemId
            ? rows.find((row) => row.id === itemId)
            : null;
          if (itemId && !item) {
            setMissing(true);
            return;
          }
          if (item) setAchForm(achievementFormFromItem(item));
        }
      } catch (err) {
        if (!cancelled) setError(apiDetail(err));
      }
    };
    void loadItem();
    return () => {
      cancelled = true;
    };
  }, [kind, itemId]);

  useEffect(() => {
    if (kind !== "education") return;
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
  }, [kind, eduForm.university_id, universities]);

  const patchForm = (
    partial: Partial<
      EducationEditorForm & CertificationEditorForm & AchievementEditorForm
    >
  ) => {
    if (kind === "education") setEduForm((prev) => ({ ...prev, ...partial }));
    else if (kind === "certification")
      setCertForm((prev) => ({ ...prev, ...partial }));
    else setAchForm((prev) => ({ ...prev, ...partial }));
    onDirty();
    setShowErrors(false);
  };

  const save = async () => {
    setShowErrors(true);
    setError("");
    try {
      if (kind === "education") {
        const payload = educationToIn(eduForm);
        if (!payload.institution || validateEducation(eduForm).end) return;
        setSaving(true);
        if (itemId) await updateEducationItem(itemId, payload);
        else await createEducationItem(payload);
      } else if (kind === "certification") {
        const payload = certificationToIn(certForm);
        if (!payload.name) return;
        setSaving(true);
        if (itemId) await updateCertification(itemId, payload);
        else await createCertification(payload);
      } else {
        const payload = achievementToIn(achForm);
        if (!payload.title) return;
        setSaving(true);
        if (itemId) await updateAchievement(itemId, payload);
        else await createAchievement(payload);
      }
      onSaved();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setSaving(false);
    }
  };

  if (missing) {
    return (
      <p
        className="p-6 text-center text-sm text-[var(--as-muted-fg)]"
        data-testid="entity-editor-missing"
      >
        {t("entityEditor.notFound")}
      </p>
    );
  }

  const shared = {
    onChange: patchForm,
    onSave: () => void save(),
    onCancel,
    onDismissErrors: () => setShowErrors(false),
    showErrors,
    saving,
    isNew: !itemId,
  };

  if (kind === "education") {
    return (
      <>
        <EducationEditor
          form={eduForm}
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
          {...shared}
        />
        {error && (
          <p role="alert" className="px-5 pb-2 text-sm text-[var(--as-danger)]">
            {error}
          </p>
        )}
      </>
    );
  }
  if (kind === "certification") {
    return (
      <>
        <CertificationEditor form={certForm} {...shared} />
        {error && (
          <p role="alert" className="px-5 pb-2 text-sm text-[var(--as-danger)]">
            {error}
          </p>
        )}
      </>
    );
  }
  return (
    <>
      <AchievementEditor form={achForm} {...shared} />
      {error && (
        <p role="alert" className="px-5 pb-2 text-sm text-[var(--as-danger)]">
          {error}
        </p>
      )}
    </>
  );
}

function SkillsModalBody({ onSaved }: { onSaved: () => void }) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4">
      <SkillsCard onChanged={onSaved} />
    </div>
  );
}

/** Plan 105: edit or create the profile entity behind a CV context
 * item, in place — hosts the real workspace editors (one source, no
 * re-rolled forms). The host mounts it conditionally; onSaved fires
 * once per successful create/update (per save for skills autosaves). */
export function EntityEditorModal({
  sourceKey,
  itemId,
  onSaved,
  onClose,
}: EntityEditorModalProps) {
  const { t } = useTranslation();
  const [dirty, setDirty] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);

  const kind = CONTEXT_SOURCE_LINKS[sourceKey]?.editor ?? null;
  if (!kind) {
    return null;
  }

  const requestClose = () => {
    if (dirty) setConfirmDiscard(true);
    else onClose();
  };

  const bodyProps: BodyBaseProps = {
    itemId,
    onDirty: () => setDirty(true),
    onSaved: () => {
      setDirty(false);
      onSaved();
    },
    onCancel: requestClose,
  };

  const title =
    kind === "skills"
      ? t("profileEdit.nav.skills")
      : kind === "experience"
        ? t(itemId ? "experience.editTitle" : "experience.addTitle")
        : kind === "education"
          ? t(itemId ? "education.editTitle" : "education.addTitle")
          : kind === "certification"
            ? t(itemId ? "education.certEditTitle" : "education.certAddTitle")
            : t(itemId ? "education.achEditTitle" : "education.achAddTitle");

  return (
    <Modal open onOpenChange={(open) => !open && requestClose()}>
      <ModalContent
        size="xl"
        aria-describedby={undefined}
        aria-label={title}
        data-testid="entity-editor-modal"
        className={`max-w-none ${kind === "experience" ? "max-w-4xl" : "max-w-3xl"}`}
      >
        <ModalTitle className="sr-only">{title}</ModalTitle>
        {kind === "skills" ? (
          <div className="flex h-[70vh] flex-col">
            <SkillsModalBody onSaved={onSaved} />
          </div>
        ) : (
          <div className="flex h-[80vh] flex-col">
            {kind === "experience" ? (
              <ExperienceModalBody sourceKey={sourceKey} {...bodyProps} />
            ) : (
              <EducationModalBody
                kind={
                  kind === "certification"
                    ? "certification"
                    : kind === "achievement"
                      ? "achievement"
                      : "education"
                }
                {...bodyProps}
              />
            )}
          </div>
        )}
      </ModalContent>
      <ConfirmationModal
        open={confirmDiscard}
        onOpenChange={(open) => !open && setConfirmDiscard(false)}
        title={t("experience.discardTitle")}
        description={t("experience.discardBody")}
        confirmLabel={t("experience.discard")}
        destructive
        onConfirm={() => {
          setConfirmDiscard(false);
          setDirty(false);
          onClose();
        }}
      />
    </Modal>
  );
}
