import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import i18next from "i18next";
import {
  ComboboxField,
  ComboboxMultiField,
  DateField,
  SegmentedRow,
  SelectField,
  StepperRow,
  TextField,
  TextareaField,
  ToggleRow,
} from "@/components/cv/formPrimitives";
import {
  Button,
  Modal,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalTitle,
} from "@/components/ui";
import { apiDetail } from "@/api/client";
import {
  addDepartment,
  createUniversity,
} from "@/api/universities";
import type {
  AchievementIn,
  AchievementKind,
  AchievementOut,
  CertificationIn,
  CertificationOut,
  EducationItemIn,
  EducationItemOut,
  EducationLevel,
  GradeBand,
} from "@/types/education";
import {
  COMMON_SUBJECTS,
  EDUCATION_LEVEL_ORDER,
  GPA_BAND_OPTIONS,
  LANGUAGE_CODE_OPTIONS,
} from "@/components/profile/sections/options";
import type { Department, University } from "@/types";

const STATUS_OPTIONS = [
  { value: "active", labelKey: "education.statusOption.active" },
  { value: "draft", labelKey: "education.statusOption.draft" },
];

export interface EducationEditorForm {
  institution: string;
  program: string;
  level: EducationLevel;
  start: string;
  end: string;
  in_progress: boolean;
  grade_band: GradeBand | null;
  focus_subjects: string[];
  description: string;
  status: "draft" | "active";
  university_id: string | null;
  department_id: string | null;
}

export const EMPTY_EDUCATION_FORM: EducationEditorForm = {
  institution: "",
  program: "",
  level: "bachelor",
  start: "",
  end: "",
  in_progress: true,
  grade_band: null,
  focus_subjects: [],
  description: "",
  status: "active",
  university_id: null,
  department_id: null,
};

export function educationFormFromItem(
  item: EducationItemOut
): EducationEditorForm {
  return {
    institution: item.institution,
    program: item.program,
    level: (item.level as EducationLevel) || "high_school",
    start: item.start ?? "",
    end: item.end ?? "",
    in_progress: item.in_progress,
    grade_band: (item.grade_band as GradeBand | null) ?? null,
    focus_subjects: item.focus_subjects,
    description: item.description,
    status: item.status,
    university_id: item.university_id,
    department_id: item.department_id,
  };
}

export function educationToIn(form: EducationEditorForm): EducationItemIn {
  return {
    institution: form.institution,
    org_name: "",
    program: form.program,
    level: form.level,
    start: form.start || null,
    end: form.in_progress ? null : form.end || null,
    in_progress: form.in_progress,
    grade_band: form.grade_band,
    focus_subjects: form.focus_subjects,
    description: form.description,
    status: form.status,
    university_id: form.university_id,
    department_id: form.department_id,
  };
}

export function validateEducation(form: EducationEditorForm): {
  institution?: string;
  end?: string;
} {
  const errors: ReturnType<typeof validateEducation> = {};
  const institution = form.institution.trim()
    ? null
    : i18next.t("validation.required", {
        field: i18next.t("education.field.institution"),
      });
  if (institution) errors.institution = institution;
  if (!form.in_progress && form.start && !form.end) {
    errors.end = i18next.t("education.validation.endRequired");
  } else if (!form.in_progress && form.start && form.end && form.end < form.start) {
    errors.end = i18next.t("education.validation.endBeforeStart");
  }
  return errors;
}

export interface CertificationEditorForm {
  name: string;
  issuer: string;
  issued: string;
  expires: string;
  credential_id: string;
  link: string;
  status: "draft" | "active";
}

export const EMPTY_CERTIFICATION_FORM: CertificationEditorForm = {
  name: "",
  issuer: "",
  issued: "",
  expires: "",
  credential_id: "",
  link: "",
  status: "active",
};

export function certificationFormFromItem(
  item: CertificationOut
): CertificationEditorForm {
  return {
    name: item.name,
    issuer: item.issuer,
    issued: item.issued ?? "",
    expires: item.expires ?? "",
    credential_id: item.credential_id,
    link: item.link,
    status: item.status,
  };
}

export function certificationToIn(
  form: CertificationEditorForm
): CertificationIn {
  return {
    name: form.name,
    issuer: form.issuer,
    issued: form.issued || null,
    expires: form.expires || null,
    credential_id: form.credential_id,
    link: form.link,
    status: form.status,
  };
}

export function validateCertification(form: CertificationEditorForm): {
  name?: string;
} {
  const errors: ReturnType<typeof validateCertification> = {};
  const name = form.name.trim()
    ? null
    : i18next.t("validation.required", {
        field: i18next.t("education.field.name"),
      });
  if (name) errors.name = name;
  return errors;
}

export interface AchievementEditorForm {
  kind: AchievementKind;
  title: string;
  issuer: string;
  date: string;
  detail: string;
  link: string;
  status: "draft" | "active";
}

export const EMPTY_ACHIEVEMENT_FORM: AchievementEditorForm = {
  kind: "award",
  title: "",
  issuer: "",
  date: "",
  detail: "",
  link: "",
  status: "active",
};

export function achievementFormFromItem(item: AchievementOut): AchievementEditorForm {
  return {
    kind: (item.kind as AchievementKind) || "award",
    title: item.title,
    issuer: item.issuer,
    date: item.date ?? "",
    detail: item.detail,
    link: item.link,
    status: item.status,
  };
}

export function achievementToIn(form: AchievementEditorForm): AchievementIn {
  return {
    kind: form.kind,
    title: form.title,
    issuer: form.issuer,
    date: form.date || null,
    detail: form.detail,
    link: form.link,
    status: form.status,
  };
}

export function validateAchievement(form: AchievementEditorForm): {
  title?: string;
} {
  const errors: ReturnType<typeof validateAchievement> = {};
  const title = form.title.trim()
    ? null
    : i18next.t("validation.required", {
        field: i18next.t("education.field.title"),
      });
  if (title) errors.title = title;
  return errors;
}

interface EditorFrameProps {
  heading: string;
  hint: string;
  status: "draft" | "active";
  onStatus: (status: "draft" | "active") => void;
  children: React.ReactNode;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
  testIdPrefix: string;
}

function EditorFrame({
  heading,
  hint,
  status,
  onStatus,
  children,
  onSave,
  onCancel,
  saving,
  testIdPrefix,
}: EditorFrameProps) {
  const { t } = useTranslation();
  return (
    <div
      className="flex min-h-0 flex-1 flex-col overflow-y-auto"
      data-testid={`${testIdPrefix}-editor`}
    >
      <div className="sticky top-0 z-10 flex shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-[var(--as-border)] bg-[var(--as-surface)] px-5 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-[var(--as-fg)]">{heading}</h2>
          <p className="mt-0.5 truncate text-xs text-[var(--as-muted-fg)]">
            {hint}
          </p>
        </div>
        <SegmentedRow
          label={t("education.statusLabel")}
          value={status}
          options={STATUS_OPTIONS.map((o) => ({
            value: o.value,
            label: t(o.labelKey),
          }))}
          onChange={(v) => onStatus(v as "draft" | "active")}
        />
      </div>
      <div className="mx-auto w-full max-w-2xl space-y-4 px-5 py-4">{children}</div>
      <div className="sticky bottom-0 mt-auto flex shrink-0 items-center justify-end gap-2 border-t border-[var(--as-border)] bg-[var(--as-surface)] px-5 py-3">
        <Button variant="ghost" onClick={onCancel} data-testid={`cancel-${testIdPrefix}`}>
          {t("common.cancel")}
        </Button>
        <Button
          variant="default"
          onClick={onSave}
          disabled={saving}
          data-testid={`save-${testIdPrefix}`}
        >
          {saving ? t("common.saving") : t("common.save")}
        </Button>
      </div>
    </div>
  );
}

export function EducationEditor({
  form,
  onChange,
  onSave,
  onCancel,
  onDismissErrors,
  showErrors,
  saving,
  isNew,
  universities,
  departments,
  onUniversityCreated,
  onDepartmentsChanged,
}: {
  form: EducationEditorForm;
  onChange: (patch: Partial<EducationEditorForm>) => void;
  onSave: () => void;
  onCancel: () => void;
  onDismissErrors: () => void;
  showErrors: boolean;
  saving: boolean;
  isNew: boolean;
  universities: University[];
  departments: Department[];
  onUniversityCreated: (university: University) => void;
  onDepartmentsChanged: (universityId: string) => void;
}) {
  const { t } = useTranslation();
  const errors = validateEducation(form);
  const patch = (partial: Partial<EducationEditorForm>) => {
    onDismissErrors();
    onChange(partial);
  };
  const err = (message?: string) => (showErrors && message ? message : undefined);

  const [universityModalPrefill, setUniversityModalPrefill] = useState<
    string | null
  >(null);
  const [departmentModalPrefill, setDepartmentModalPrefill] = useState<
    string | null
  >(null);

  const institutionOptions = useMemo(() => {
    const opts = universities.map((u) => ({ value: u.name, label: u.name }));
    if (
      form.institution &&
      !universities.some((u) => u.name === form.institution)
    ) {
      opts.unshift({ value: form.institution, label: form.institution });
    }
    return opts;
  }, [universities, form.institution]);

  const pickUniversity = (name: string) => {
    const match = universities.find((u) => u.name === name);
    if (match) {
      patch({
        institution: name,
        university_id: match.id,
        department_id: null,
      });
      return;
    }
    patch({
      institution: name,
      university_id: null,
      department_id: null,
    });
    setUniversityModalPrefill(name);
  };

  const pickDepartment = (value: string) => {
    if (departments.some((d) => d.id === value)) {
      patch({ department_id: value });
      return;
    }
    setDepartmentModalPrefill(value);
  };

  const handleUniversityCreated = (university: University) => {
    onUniversityCreated(university);
    patch({
      institution: university.name,
      university_id: university.id,
      department_id: null,
    });
    setUniversityModalPrefill(null);
  };

  const handleDepartmentCreated = (department: Department) => {
    onDepartmentsChanged(department.university_id);
    patch({ department_id: department.id });
    setDepartmentModalPrefill(null);
  };

  return (
    <>
      <EditorFrame
        heading={isNew ? t("education.addTitle") : t("education.editTitle")}
        hint={t("education.editorHint")}
        status={form.status}
        onStatus={(status) => patch({ status })}
        onSave={onSave}
        onCancel={onCancel}
        saving={saving}
        testIdPrefix="education"
      >
      <SegmentedRow
        label={t("education.levelLabel")}
        value={form.level}
        options={EDUCATION_LEVEL_ORDER.map((level) => ({
          value: level,
          label: t(`education.level.${level}`, { defaultValue: level }),
        }))}
        onChange={(v) => patch({ level: v as EducationLevel })}
      />
      <div className="grid gap-3 sm:grid-cols-2">
        <ComboboxField
          label={t("education.institutionLabel")}
          value={form.institution}
          onChange={pickUniversity}
          options={institutionOptions}
          allowCreate
          createLabel={(term) => t("education.addNamed", { name: term })}
          hint={t("education.institutionHint")}
          error={err(errors.institution)}
          testId="education-institution"
        />
        <ComboboxField
          label={t("education.departmentLabel")}
          value={form.department_id ?? ""}
          onChange={pickDepartment}
          options={departments.map((d) => ({ value: d.id, label: d.name }))}
          hideLabel={false}
          disabled={!form.university_id}
          allowCreate
          createLabel={(term) => t("education.addNamed", { name: term })}
          hint={
            !form.university_id
              ? t("education.departmentHintNone")
              : departments.length === 0
                ? t("education.departmentHintEmpty")
                : undefined
          }
          testId="education-department"
        />
      </div>
      <TextField
        label={t("education.programLabel")}
        value={form.program}
        onChange={(v) => patch({ program: v })}
        maxLength={200}
        placeholder={t("education.programPlaceholder")}
        testId="education-program"
      />
      <div className="grid items-end gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
        <DateField
          label={t("education.startLabel")}
          value={form.start || null}
          onChange={(v) => patch({ start: v })}
          testId="education-start"
        />
        <DateField
          label={t("education.endLabel")}
          value={form.end || null}
          onChange={(v) => patch({ end: v })}
          disabled={form.in_progress}
          hint={form.in_progress ? t("education.endHint") : undefined}
          error={err(errors.end)}
          testId="education-end"
        />
        <div className="pb-2">
          <ToggleRow
            label={t("education.inProgressToggle")}
            checked={form.in_progress}
            onChange={(checked) =>
              patch({
                in_progress: checked,
                end: checked ? "" : form.end,
              })
            }
          />
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <SelectField
          label={t("education.gradeLabel")}
          value={form.grade_band ?? ""}
          onChange={(v) => patch({ grade_band: (v || null) as GradeBand | null })}
          options={[
            { value: "", label: t("education.gradeUnspecified") },
            ...GPA_BAND_OPTIONS.filter((o) => o.value !== "unknown").map((o) => ({
              value: o.value,
              label: t(`education.grade.${o.value}`, { defaultValue: o.label }),
            })),
          ]}
          testId="education-grade-band"
        />
        <div className="min-w-0" data-testid="education-focus">
          <ComboboxMultiField
            label={t("education.focusLabel")}
            values={form.focus_subjects}
            onChange={(values) => patch({ focus_subjects: values })}
            options={COMMON_SUBJECTS.map((s) => ({
              value: s,
              label: t(`education.subject.${s}`, {
                defaultValue: s.replace(/-/g, " "),
              }),
            }))}
            allowCreate
            createLabel={(term) => t("education.addNamed", { name: term })}
            testId="education-focus-picker"
          />
        </div>
      </div>
      <TextareaField
        label={t("education.descriptionLabel")}
        value={form.description}
        onChange={(v) => patch({ description: v })}
        rows={4}
        maxLength={4000}
        counter
        placeholder={t("education.descriptionPlaceholder")}
        testId="education-description"
      />
    </EditorFrame>
      {universityModalPrefill !== null && (
        <AddUniversityModal
          defaultName={universityModalPrefill}
          onClose={() => setUniversityModalPrefill(null)}
          onCreated={handleUniversityCreated}
        />
      )}
      {departmentModalPrefill !== null && form.university_id && (
        <AddDepartmentModal
          defaultName={departmentModalPrefill}
          universityId={form.university_id}
          onClose={() => setDepartmentModalPrefill(null)}
          onCreated={handleDepartmentCreated}
        />
      )}
    </>
  );
}

export function CertificationEditor({
  form,
  onChange,
  onSave,
  onCancel,
  onDismissErrors,
  showErrors,
  saving,
  isNew,
}: {
  form: CertificationEditorForm;
  onChange: (patch: Partial<CertificationEditorForm>) => void;
  onSave: () => void;
  onCancel: () => void;
  onDismissErrors: () => void;
  showErrors: boolean;
  saving: boolean;
  isNew: boolean;
}) {
  const { t } = useTranslation();
  const errors = validateCertification(form);
  const patch = (partial: Partial<CertificationEditorForm>) => {
    onDismissErrors();
    onChange(partial);
  };
  const err = (message?: string) => (showErrors && message ? message : undefined);

  return (
    <EditorFrame
      heading={isNew ? t("education.certAddTitle") : t("education.certEditTitle")}
      hint={t("education.certHint")}
      status={form.status}
      onStatus={(status) => patch({ status })}
      onSave={onSave}
      onCancel={onCancel}
      saving={saving}
      testIdPrefix="certification"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField
          label={t("education.nameLabel")}
          value={form.name}
          onChange={(v) => patch({ name: v })}
          maxLength={200}
          placeholder={t("education.certNamePlaceholder")}
          error={err(errors.name)}
          testId="certification-name"
        />
        <TextField
          label={t("education.issuerLabel")}
          value={form.issuer}
          onChange={(v) => patch({ issuer: v })}
          maxLength={200}
          placeholder={t("education.certIssuerPlaceholder")}
          testId="certification-issuer"
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <DateField
          label={t("education.issuedLabel")}
          value={form.issued || null}
          onChange={(v) => patch({ issued: v })}
          testId="certification-issued"
        />
        <DateField
          label={t("education.expiresLabel")}
          value={form.expires || null}
          onChange={(v) => patch({ expires: v })}
          testId="certification-expires"
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField
          label={t("education.credentialLabel")}
          value={form.credential_id}
          onChange={(v) => patch({ credential_id: v })}
          maxLength={120}
          testId="certification-credential"
        />
        <TextField
          label={t("education.linkLabel")}
          type="url"
          value={form.link}
          onChange={(v) => patch({ link: v })}
          maxLength={500}
          placeholder="https://…"
          testId="certification-link"
        />
      </div>
    </EditorFrame>
  );
}

const ACHIEVEMENT_KIND_OPTIONS = [
  { value: "award", labelKey: "education.achKind.award" },
  { value: "honor", labelKey: "education.achKind.honor" },
  { value: "publication", labelKey: "education.achKind.publication" },
  { value: "extracurricular", labelKey: "education.achKind.extracurricular" },
];

export function AchievementEditor({
  form,
  onChange,
  onSave,
  onCancel,
  onDismissErrors,
  showErrors,
  saving,
  isNew,
}: {
  form: AchievementEditorForm;
  onChange: (patch: Partial<AchievementEditorForm>) => void;
  onSave: () => void;
  onCancel: () => void;
  onDismissErrors: () => void;
  showErrors: boolean;
  saving: boolean;
  isNew: boolean;
}) {
  const { t } = useTranslation();
  const errors = validateAchievement(form);
  const patch = (partial: Partial<AchievementEditorForm>) => {
    onDismissErrors();
    onChange(partial);
  };
  const err = (message?: string) => (showErrors && message ? message : undefined);

  return (
    <EditorFrame
      heading={isNew ? t("education.achAddTitle") : t("education.achEditTitle")}
      hint={t("education.achHint")}
      status={form.status}
      onStatus={(status) => patch({ status })}
      onSave={onSave}
      onCancel={onCancel}
      saving={saving}
      testIdPrefix="achievement"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <SelectField
          label={t("education.kindLabel")}
          value={form.kind}
          onChange={(v) => patch({ kind: v as AchievementKind })}
          options={ACHIEVEMENT_KIND_OPTIONS.map((o) => ({
            value: o.value,
            label: t(o.labelKey),
          }))}
          testId="achievement-kind"
        />
        <TextField
          label={t("education.achTitleLabel")}
          value={form.title}
          onChange={(v) => patch({ title: v })}
          maxLength={200}
          placeholder={t("education.achTitlePlaceholder")}
          error={err(errors.title)}
          testId="achievement-title"
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField
          label={t("education.issuerLabel")}
          value={form.issuer}
          onChange={(v) => patch({ issuer: v })}
          maxLength={200}
          placeholder={t("education.achIssuerPlaceholder")}
          testId="achievement-issuer"
        />
        <DateField
          label={t("education.dateLabel")}
          value={form.date || null}
          onChange={(v) => patch({ date: v })}
          testId="achievement-date"
        />
      </div>
      <TextField
        label={t("education.linkLabel")}
        type="url"
        value={form.link}
        onChange={(v) => patch({ link: v })}
        maxLength={500}
        placeholder="https://…"
        testId="achievement-link"
      />
      <TextareaField
        label={t("education.detailLabel")}
        value={form.detail}
        onChange={(v) => patch({ detail: v })}
        rows={4}
        maxLength={4000}
        counter
        placeholder={t("education.detailPlaceholder")}
        testId="achievement-detail"
      />
    </EditorFrame>
  );
}

const UNIVERSITY_TYPE_OPTIONS = [
  { value: "public", labelKey: "education.uniType.public" },
  { value: "private", labelKey: "education.uniType.private" },
  { value: "other", labelKey: "education.uniType.other" },
];

const DEGREE_LEVEL_OPTIONS = [
  { value: "vocational", labelKey: "education.degree.vocational" },
  { value: "bachelor", labelKey: "education.degree.bachelor" },
  { value: "master", labelKey: "education.degree.master" },
  { value: "phd", labelKey: "education.degree.phd" },
];

function AddUniversityModal({
  defaultName,
  onClose,
  onCreated,
}: {
  defaultName: string;
  onClose: () => void;
  onCreated: (university: University) => void;
}) {
  const [name, setName] = useState(defaultName);
  const [country, setCountry] = useState("");
  const [city, setCity] = useState("");
  const [type, setType] = useState("public");
  const [website, setWebsite] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { t } = useTranslation();

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const created = await createUniversity({
        name,
        country,
        city,
        university_type: type,
        website,
      });
      onCreated(created);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <ModalContent size="md" aria-describedby={undefined}>
        <ModalHeader>
          <ModalTitle>{t("education.uniModalTitle")}</ModalTitle>
        </ModalHeader>
        <div className="space-y-4 px-6 pb-6">
          <div className="grid gap-3 sm:grid-cols-2">
            <TextField
              label={t("education.nameLabel")}
              value={name}
              onChange={setName}
              maxLength={200}
              placeholder={t("education.uniNamePlaceholder")}
              testId="university-name"
            />
            <SelectField
              label={t("education.typeLabel")}
              value={type}
              onChange={setType}
              options={UNIVERSITY_TYPE_OPTIONS.map((o) => ({
                value: o.value,
                label: t(o.labelKey),
              }))}
              testId="university-type"
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <TextField
              label={t("education.countryLabel")}
              value={country}
              onChange={setCountry}
              maxLength={80}
              placeholder={t("education.countryPlaceholder")}
              testId="university-country"
            />
            <TextField
              label={t("education.cityLabel")}
              value={city}
              onChange={setCity}
              maxLength={80}
              placeholder={t("education.cityPlaceholder")}
              testId="university-city"
            />
          </div>
          <TextField
            label={t("education.websiteLabel")}
            type="url"
            value={website}
            onChange={setWebsite}
            maxLength={300}
            placeholder="https://…"
            testId="university-website"
          />
          {error && (
            <p role="alert" className="text-sm text-[var(--as-danger)]">
              {error}
            </p>
          )}
        </div>
        <ModalFooter>
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            size="sm"
            onClick={() => void save()}
            disabled={busy || name.trim().length < 2}
            data-testid="save-university"
          >
            {busy ? t("common.saving") : t("education.saveUniversity")}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

function AddDepartmentModal({
  defaultName,
  universityId,
  onClose,
  onCreated,
}: {
  defaultName: string;
  universityId: string;
  onClose: () => void;
  onCreated: (department: Department) => void;
}) {
  const [name, setName] = useState(defaultName);
  const [fieldKey, setFieldKey] = useState("");
  const [degree, setDegree] = useState("bachelor");
  const [durationYears, setDurationYears] = useState(4);
  const [language, setLanguage] = useState("");
  const [deadline, setDeadline] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { t } = useTranslation();

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const created = await addDepartment(universityId, {
        name,
        field_key: fieldKey,
        degree,
        duration_years: durationYears,
        language,
        application_deadline: deadline || null,
        description,
      });
      onCreated(created);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <ModalContent size="md" aria-describedby={undefined}>
        <ModalHeader>
          <ModalTitle>{t("education.deptModalTitle")}</ModalTitle>
        </ModalHeader>
        <div className="space-y-4 px-6 pb-6">
          <div className="grid gap-3 sm:grid-cols-2">
            <TextField
              label={t("education.nameLabel")}
              value={name}
              onChange={setName}
              maxLength={200}
              placeholder={t("education.deptNamePlaceholder")}
              testId="department-name"
            />
            <TextField
              label={t("education.fieldKeyLabel")}
              value={fieldKey}
              onChange={setFieldKey}
              maxLength={80}
              placeholder={t("education.fieldKeyPlaceholder")}
              testId="department-field-key"
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <SelectField
              label={t("education.degreeLabel")}
              value={degree}
              onChange={setDegree}
              options={DEGREE_LEVEL_OPTIONS.map((o) => ({
                value: o.value,
                label: t(o.labelKey),
              }))}
              testId="department-degree"
            />
            <div className="pt-4">
              <StepperRow
                label={t("education.durationLabel")}
                value={durationYears}
                min={1}
                max={10}
                onChange={setDurationYears}
              />
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <SelectField
              label={t("education.languageLabel")}
              value={language}
              onChange={setLanguage}
              options={[
                { value: "", label: t("education.languageUnspecified") },
                ...LANGUAGE_CODE_OPTIONS,
              ]}
              testId="department-language"
            />
            <DateField
              label={t("education.deadlineLabel")}
              value={deadline || null}
              onChange={setDeadline}
              testId="department-deadline"
            />
          </div>
          <TextareaField
            label={t("education.descriptionLabel")}
            value={description}
            onChange={setDescription}
            rows={2}
            maxLength={2000}
            placeholder={t("education.deptDescriptionPlaceholder")}
            testId="department-description"
          />
          {error && (
            <p role="alert" className="text-sm text-[var(--as-danger)]">
              {error}
            </p>
          )}
        </div>
        <ModalFooter>
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            size="sm"
            onClick={() => void save()}
            disabled={busy || name.trim().length < 2}
            data-testid="save-department"
          >
            {busy ? t("common.saving") : t("education.saveDepartment")}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
