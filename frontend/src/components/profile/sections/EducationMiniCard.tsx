import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { SelectField, TextField } from "@/components/cv/formPrimitives";
import {
  ProfileSectionCard,
  type SectionSaveState,
} from "@/components/profile/ProfileSectionCard";
import type { SectionCardHandle } from "./shared";
import { EDUCATION_OPTIONS } from "./options";
import {
  createEducationItem,
  fetchEducation,
  updateEducationItem,
} from "@/api/education";
import type { EducationItemOut, EducationLevel } from "@/types/education";
import { apiDetail } from "@/api/client";

/** Onboarding education mini-step: level + school only —
 * writes the education row so the workspace, CV context and the
 * derived fit level see it; skipped when the school field stays empty. */
export const EducationMiniCard = forwardRef<SectionCardHandle>(
  function EducationMiniCard(_props, ref) {
    const { t } = useTranslation();
    const [level, setLevel] = useState<EducationLevel>("high_school");
    const [institution, setInstitution] = useState("");
    const [saveState, setSaveState] = useState<SectionSaveState>("idle");
    const [error, setError] = useState("");
    const loaded = useRef(false);

    useEffect(() => {
      if (loaded.current) return;
      loaded.current = true;
      void fetchEducation()
        .then((items: EducationItemOut[]) => {
          const latest = items[0];
          if (latest) {
            setInstitution(latest.institution);
            setLevel((latest.level as EducationLevel) || "high_school");
          }
        })
        .catch(() => undefined);
    }, []);

    const save = async () => {
      const school = institution.trim();
      if (!school) return true;
      setSaveState("saving");
      setError("");
      try {
        const items = await fetchEducation();
        const existing = items.find(
          (i) => i.institution.trim().toLowerCase() === school.toLowerCase()
        );
        if (existing) {
          await updateEducationItem(existing.id, {
            institution: school,
            level,
            in_progress: true,
            status: "active",
          });
        } else {
          await createEducationItem({
            institution: school,
            org_name: "",
            program: "",
            level,
            start: null,
            end: null,
            in_progress: true,
            grade_band: null,
            focus_subjects: [],
            description: "",
            status: "active",
            university_id: null,
            department_id: null,
          });
        }
        setSaveState("saved");
        return true;
      } catch (err) {
        setError(apiDetail(err));
        setSaveState("error");
        return false;
      }
    };

    useImperativeHandle(ref, () => ({ save, isDirty: () => false }));

    return (
      <ProfileSectionCard
        name="education"
        title={t("education.title")}
        description={t("profileSection.educationMiniBody")}
        saveState={saveState}
        error={error}
        variant="onboarding"
      >
        <div className="space-y-5">
          <SelectField
            label={t("education.levelLabel")}
            value={level}
            options={EDUCATION_OPTIONS.map((o) => ({
              value: o.value,
              label: t(o.labelKey, { defaultValue: o.label }),
            }))}
            onChange={(v) => setLevel(v as EducationLevel)}
            testId="education-mini-level"
          />
          <TextField
            label={t("profileSection.school")}
            value={institution}
            onChange={setInstitution}
            maxLength={200}
            placeholder={t("profileSection.schoolPlaceholder")}
            hint={t("profileSection.schoolHint")}
            testId="education-mini-school"
          />
        </div>
      </ProfileSectionCard>
    );
  }
);
