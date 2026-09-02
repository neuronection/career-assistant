import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BarChart3, Check, Lightbulb, Rocket, Sparkles, Users, Wrench } from "lucide-react";
import { Link } from "react-router-dom";
import { useProfileStore } from "@/stores/profileStore";
import { apiDetail } from "@/api/client";
import { ChipInput, ScaleSlider, SearchableDropdown } from "@/components/ui";
import type { Profile } from "@/types";

const STEPS = ["Basics", "Academics", "Interests", "Likes & dislikes", "Aspirations", "Work style", "Constraints"];

const MAX_BIRTH_YEAR = new Date().getFullYear() - 14;
const BIRTH_YEARS: string[] = Array.from(
  { length: MAX_BIRTH_YEAR - 1950 + 1 },
  (_, i) => String(MAX_BIRTH_YEAR - i)
);

type DraftSetter = (draft: Partial<Profile>) => void;

interface StepProps {
  profile: Profile | null;
  draft: Partial<Profile>;
  setDraft: DraftSetter;
}

const DEFAULT_BASICS: Profile["basics"] = {
  birth_year: null,
  education_level: "high_school",
  grade: null,
  career_stage: null,
  country: "",
  city: "",
};

const DEFAULT_ACADEMICS: Profile["academics"] = {
  favorite_subjects: [],
  gpa_band: "unknown",
  languages: [],
};

const DEFAULT_WORK: Profile["work_preferences"] = {
  teamwork: 3,
  environment: 3,
  structure: 3,
  pace: 3,
  leadership: 3,
  remote_ok: true,
  focus_areas: [],
  salary_priority: 3,
  stability_priority: 3,
  physical_activity: "light",
  creativity_priority: 3,
};

const DEFAULT_CONSTRAINTS: Profile["constraints"] = {
  physical_conditions: [],
  max_education_years: null,
  willing_to_relocate: true,
  hours_available_per_week: null,
};

export function Onboarding() {
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<Partial<Profile>>({});
  const [saved, setSaved] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState("");
  const { profile, interests, load, loadTaxonomy, saveSection, analyze } = useProfileStore();
  const navigate = useNavigate();
  const stepRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    stepRef.current?.scrollTo({ top: 0 });
  }, [step]);

  useEffect(() => {
    void load();
    void loadTaxonomy();
  }, [load, loadTaxonomy]);

  const saveStep = async () => {
    if (step === 0 && draft.basics) await saveSection({ basics: draft.basics });
    if (step === 1 && draft.academics) await saveSection({ academics: draft.academics });
    if (step === 2 && draft.interests) await saveSection({ interests: draft.interests });
    if (step === 3 && (draft.likes || draft.dislikes || draft.hobbies))
      await saveSection({ likes: draft.likes, dislikes: draft.dislikes, hobbies: draft.hobbies });
    if (step === 4 && draft.aspirations) await saveSection({ aspirations: draft.aspirations });
    if (step === 5 && draft.work_preferences) await saveSection({ work_preferences: draft.work_preferences });
    if (step === 6 && draft.constraints) await saveSection({ constraints: draft.constraints });
  };

  const next = async () => {
    setSaved(false);
    setError("");
    try {
      await saveStep();
      setSaved(true);
      if (step < STEPS.length - 1) {
        setStep(step + 1);
      } else {
        setAnalyzing(true);
        try {
          await analyze();
          navigate("/");
        } finally {
          setAnalyzing(false);
        }
      }
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  return (
    <div className="max-w-3xl flex flex-col h-[calc(100dvh-6.5rem)] min-h-0 -mx-4 -mt-6 -mb-6 sm:mx-auto sm:mt-0 sm:mb-0" data-testid="onboarding">
      <Link
        to="/onboarding/express"
        className="mb-2 sm:mb-4 flex items-center gap-2 text-xs sm:text-sm bg-primary-50 border border-primary-100 text-primary-800 rounded-xl px-3 py-2 sm:px-4 sm:py-2.5 hover:border-primary-300"
        data-testid="express-entry"
      >
        <Rocket className="w-4 h-4 shrink-0" />
        Already know your target job? Express start — 2 minutes, no profiling.
      </Link>
      <div className="flex items-start gap-1.5 sm:gap-2 mb-3 sm:mb-6">
        {STEPS.map((label, i) => {
          const done = i < step;
          const active = i === step;
          return (
            <button
              key={label}
              type="button"
              disabled={!done}
              aria-current={active ? "step" : undefined}
              aria-label={label}
              onClick={() => {
                setSaved(false);
                setError("");
                setStep(i);
              }}
              className={`flex-1 text-left ${done ? "cursor-pointer" : "cursor-default"}`}
            >
              <div className={`h-1.5 rounded-full transition-colors ${i <= step ? "bg-primary-600" : "bg-slate-200"}`} />
              <p className={`text-xs mt-1 items-center gap-1 ${active ? "flex text-primary-700 font-medium" : done ? "hidden sm:flex text-slate-500 hover:text-primary-700" : "hidden sm:flex text-slate-400"}`}>
                {done && <Check className="w-3 h-3 shrink-0" aria-hidden />}
                {label}
              </p>
            </button>
          );
        })}
      </div>

      <div className="bg-white border-0 sm:border sm:border-slate-200 sm:rounded-2xl p-4 sm:p-6 md:p-8 flex flex-1 flex-col min-h-0">
        <div ref={stepRef} className="flex-1 min-h-0 overflow-y-auto flex flex-col pr-1" data-testid="step-content">
          {step === 0 && <BasicsStep profile={profile} draft={draft} setDraft={setDraft} />}
          {step === 1 && <AcademicsStep profile={profile} draft={draft} setDraft={setDraft} />}
          {step === 2 && <InterestsStep profile={profile} draft={draft} setDraft={setDraft} interests={interests} />}
          {step === 3 && <LikesStep profile={profile} draft={draft} setDraft={setDraft} />}
          {step === 4 && <AspirationsStep profile={profile} draft={draft} setDraft={setDraft} />}
          {step === 5 && <WorkStyleStep profile={profile} draft={draft} setDraft={setDraft} />}
          {step === 6 && <ConstraintsStep profile={profile} draft={draft} setDraft={setDraft} />}
        </div>

        <div className="sticky bottom-0 -mx-4 -mb-4 mt-3 border-t border-slate-100 bg-white/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:-mb-6 sm:rounded-b-2xl sm:px-6 sm:py-4 md:-mx-8 md:-mb-8 md:px-8">
          {error && <p className="text-sm text-rose-600">{error}</p>}
          {saved && step < STEPS.length - 1 && <p className="text-sm text-emerald-600">Saved ✓</p>}
          <div className="flex justify-between">
            <button
              type="button"
              onClick={() => setStep(Math.max(0, step - 1))}
              disabled={step === 0}
              className="text-sm px-4 py-2 rounded-lg border border-slate-200 disabled:opacity-40"
            >
              Back
            </button>
            <button
              type="button"
              onClick={() => void next()}
              disabled={analyzing}
              className="text-sm px-5 py-2 rounded-lg bg-primary-600 text-white font-medium disabled:opacity-50 flex items-center gap-1"
            >
              {step === STEPS.length - 1 ? (
                <>
                  <Sparkles className="w-4 h-4" /> {analyzing ? "Analyzing…" : "Finish & analyze"}
                </>
              ) : (
                "Save & continue"
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

const EDUCATION_OPTIONS = [
  { value: "middle_school", label: "Middle school", group: "Current" },
  { value: "high_school", label: "High school", group: "Current" },
  { value: "vocational", label: "Vocational school", group: "Current" },
  { value: "bachelor", label: "Bachelor student", group: "Current" },
  { value: "master", label: "Master student", group: "Current" },
  { value: "no_formal", label: "No formal education", group: "Other" },
];

const STAGE_OPTIONS = [
  { value: "student", label: "I'm a student" },
  { value: "early_career", label: "Early in my career" },
  { value: "experienced", label: "Experienced professional" },
  { value: "switching", label: "Switching fields" },
  { value: "returning", label: "Returning after a break" },
];

const STAGE_SUBTITLE: Record<string, string> = {
  student: "Tell us about you",
  early_career: "Tell us about you — your experience counts from day one",
  experienced: "Tell us about you — your experience leads the way",
  switching: "Tell us about you — we'll focus on what transfers",
  returning: "Welcome back — let's rebuild from what you bring",
};

function BasicsStep({ profile, draft, setDraft }: StepProps) {
  const current = { ...DEFAULT_BASICS, ...profile?.basics, ...draft.basics };
  const stage = current.career_stage ?? "";
  return (
    <div className="space-y-4">
      <h2 className="font-semibold">{STAGE_SUBTITLE[stage] ?? STAGE_SUBTITLE.student}</h2>
      <div className="text-sm" data-testid="stage-question">
        Where are you in your career right now?
        <div className="mt-1">
          <SearchableDropdown
            options={STAGE_OPTIONS}
            value={stage}
            onChange={(v) =>
              setDraft({ ...draft, basics: { ...current, career_stage: (v || null) as Profile["basics"]["career_stage"] } })
            }
            placeholder="Pick one — you can change it anytime…"
          />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div className="text-sm">
          Birth year
          <div className="mt-1">
            <SearchableDropdown
              options={BIRTH_YEARS.map((y) => ({ value: y, label: y }))}
              value={current.birth_year ? String(current.birth_year) : ""}
              onChange={(v) => setDraft({ ...draft, basics: { ...current, birth_year: v ? Number(v) : null } })}
              placeholder="Select year…"
            />
          </div>
        </div>
        <div className="text-sm">
          Education level
          <div className="mt-1">
            <SearchableDropdown
              options={EDUCATION_OPTIONS}
              value={current.education_level}
              onChange={(v) => setDraft({ ...draft, basics: { ...current, education_level: v as Profile["basics"]["education_level"] } })}
              placeholder="Select level…"
            />
          </div>
        </div>
        <label className="text-sm">
          Country
          <input
            value={current.country}
            onChange={(e) => setDraft({ ...draft, basics: { ...current, country: e.target.value } })}
            className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
          />
        </label>
        <label className="text-sm">
          City
          <input
            value={current.city}
            onChange={(e) => setDraft({ ...draft, basics: { ...current, city: e.target.value } })}
            className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
          />
        </label>
      </div>
    </div>
  );
}

const COMMON_SUBJECTS = [
  "mathematics", "physics", "chemistry", "biology", "history",
  "literature", "art", "computer-science", "economics", "geography",
];

function AcademicsStep({ profile, draft, setDraft }: StepProps) {
  const current = { ...DEFAULT_ACADEMICS, ...profile?.academics, ...draft.academics };
  const subjects = current.favorite_subjects;
  return (
    <div className="space-y-4">
      <h2 className="font-semibold">Which subjects do you enjoy?</h2>
      <div className="flex flex-wrap gap-2">
        {COMMON_SUBJECTS.map((subject) => {
          const found = subjects.find((s) => s.key === subject);
          return (
            <button
              key={subject}
              type="button"
              onClick={() => {
                const next = found
                  ? subjects.filter((s) => s.key !== subject)
                  : [...subjects, { key: subject, weight: 3 }];
                setDraft({ ...draft, academics: { ...current, favorite_subjects: next } });
              }}
              className={`text-sm px-3 py-1.5 rounded-full border ${
                found ? "bg-primary-600 text-white border-primary-600" : "border-slate-200 hover:border-primary-500"
              }`}
            >
              {subject} {found ? `·${found.weight}` : ""}
            </button>
          );
        })}
      </div>
      {subjects.map((s) => (
        <div key={s.key} className="text-sm">
          <p className="font-medium mb-1">{s.key}</p>
          <ScaleSlider
            min={1}
            max={5}
            value={s.weight}
            lowLabel="meh"
            highLabel="love it"
            onChange={(v) =>
              setDraft({
                ...draft,
                academics: {
                  ...current,
                  favorite_subjects: subjects.map((x) => (x.key === s.key ? { ...x, weight: Number(v) || x.weight } : x)),
                },
              })
            }
          />
        </div>
      ))}
    </div>
  );
}

function InterestsStep({
  profile,
  draft,
  setDraft,
  interests,
}: StepProps & { interests: { key: string; label: string; category: string }[] }) {
  const current = draft.interests ?? profile?.interests ?? [];
  const [query, setQuery] = useState("");
  const filtered = interests.filter(
    (t) => !query || t.label.toLowerCase().includes(query.toLowerCase()) || t.key.includes(query.toLowerCase())
  );
  return (
    <div className="flex flex-1 min-h-0 flex-col space-y-4">
      <h2 className="font-semibold">Pick your interests — this powers your matches</h2>
      <input
        placeholder="Search interests…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        className="w-full h-8 border border-slate-200 rounded-lg px-2.5 text-xs sm:h-9 sm:px-3 sm:text-sm"
      />
      <div className="grid grid-cols-2 md:grid-cols-3 gap-1.5 sm:gap-2 content-start flex-1 min-h-0 overflow-y-auto pr-1">
        {filtered.map((tag) => {
          const found = current.find((i) => i.tag_key === tag.key);
          return (
            <button
              key={tag.key}
              type="button"
              onClick={() => {
                const next = found
                  ? current.filter((i) => i.tag_key !== tag.key)
                  : [...current, { tag_key: tag.key, weight: 3, source: "self" }];
                setDraft({ ...draft, interests: next });
              }}
              className={`text-left px-2 py-1.5 rounded-lg border text-xs sm:px-3 sm:py-2 sm:text-sm ${
                found ? "bg-primary-600 text-white border-primary-600" : "border-slate-200 hover:border-primary-500"
              }`}
            >
              {tag.label}
              <span className="hidden sm:block text-xs opacity-60">{tag.category}</span>
            </button>
          );
        })}
      </div>
      <p className="text-xs text-slate-400">{current.length} selected</p>
    </div>
  );
}

interface TextItem {
  tag_key: string | null;
  label: string;
  weight: number;
}

function LikesStep({ profile, draft, setDraft }: StepProps) {
  const likes = draft.likes ?? profile?.likes ?? [];
  const dislikes = draft.dislikes ?? profile?.dislikes ?? [];
  const hobbies = draft.hobbies ?? profile?.hobbies ?? [];

  const toLabels = (items: { label: string }[]) => items.map((i) => i.label);

  return (
    <div className="space-y-5">
      <p className="text-sm text-slate-500">
        Each list takes as many entries as you like — type one, press <b>Add</b> (or Enter), repeat.
      </p>
      <div>
        <h2 className="font-semibold mb-2">Things you like</h2>
        <ChipInput
          value={toLabels(likes)}
          onChange={(labels) =>
            setDraft({
              ...draft,
              likes: labels.map<TextItem>((label) => ({
                tag_key: likes.find((l) => l.label === label)?.tag_key ?? null,
                label,
                weight: likes.find((l) => l.label === label)?.weight ?? 3,
              })),
            })
          }
          inputLabel="New like"
          addLabel="Add"
          placeholder="e.g. building PCs"
        />
      </div>
      <div>
        <h2 className="font-semibold mb-2">Things you dislike</h2>
        <ChipInput
          value={toLabels(dislikes)}
          onChange={(labels) =>
            setDraft({
              ...draft,
              dislikes: labels.map<TextItem>((label) => ({
                tag_key: dislikes.find((l) => l.label === label)?.tag_key ?? null,
                label,
                weight: dislikes.find((l) => l.label === label)?.weight ?? 3,
              })),
            })
          }
          inputLabel="New dislike"
          addLabel="Add"
          placeholder="e.g. cold calling"
        />
      </div>
      <div>
        <h2 className="font-semibold mb-2">Hobbies</h2>
        <ChipInput
          value={toLabels(hobbies)}
          onChange={(labels) =>
            setDraft({
              ...draft,
              hobbies: labels.map<Profile["hobbies"][number]>((label) => ({
                key: hobbies.find((l) => l.label === label)?.key ?? null,
                label,
                weight: hobbies.find((l) => l.label === label)?.weight ?? 3,
              })),
            })
          }
          inputLabel="New hobby"
          addLabel="Add"
          placeholder="e.g. chess, sketching"
        />
      </div>
    </div>
  );
}

function AspirationsStep({ profile, draft, setDraft }: StepProps) {
  const aspirations = draft.aspirations ?? profile?.aspirations ?? [];
  return (
    <div className="space-y-4">
      <div>
        <h2 className="font-semibold">Things you imagine yourself doing</h2>
        <p className="text-sm text-slate-500 mt-1">
          Dream scenarios count — &ldquo;working outdoors&rdquo;, &ldquo;building a robot&rdquo;, &ldquo;helping my town&rdquo;. Add as many as you like.
        </p>
      </div>
      <ChipInput
        value={aspirations.map((a) => a.label)}
        onChange={(labels) =>
          setDraft({
            ...draft,
            aspirations: labels.map((label) => ({
              label,
              tag_keys: aspirations.find((a) => a.label === label)?.tag_keys ?? [],
              notes: aspirations.find((a) => a.label === label)?.notes ?? "",
            })),
          })
        }
        inputLabel="New aspiration"
        addLabel="Add"
        placeholder="e.g. designing my own game"
      />
    </div>
  );
}

const SCALES: [keyof Profile["work_preferences"], string, string, string][] = [
  ["teamwork", "Teamwork", "solo", "team"],
  ["environment", "Environment", "indoors", "outdoors"],
  ["structure", "Structure", "routine", "variety"],
  ["pace", "Pace", "calm", "fast"],
  ["leadership", "Leadership", "follow", "lead"],
  ["salary_priority", "Salary priority", "low", "high"],
  ["stability_priority", "Stability priority", "risky", "secure"],
  ["creativity_priority", "Creativity priority", "conventional", "creative"],
];

const FOCUS_AREAS: {
  key: string;
  label: string;
  hint: string;
  icon: typeof Users;
}[] = [
  { key: "people", label: "People", hint: "teaching, selling, caring, leading teams", icon: Users },
  { key: "things", label: "Things", hint: "tools, machines, building and fixing", icon: Wrench },
  { key: "data", label: "Data", hint: "numbers, code, patterns, analysis", icon: BarChart3 },
  { key: "ideas", label: "Ideas", hint: "design, writing, inventing, storytelling", icon: Lightbulb },
];

function WorkStyleStep({ profile, draft, setDraft }: StepProps) {
  const current = { ...DEFAULT_WORK, ...profile?.work_preferences, ...draft.work_preferences };
  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-semibold">How do you like to work?</h2>
        <p className="text-sm text-slate-500 mt-1">
          Slide each one — the ends name the two extremes, there is no wrong answer.
        </p>
      </div>
      <div className="grid sm:grid-cols-2 gap-x-8 gap-y-5">
        {SCALES.map(([key, label, low, high]) => (
          <div key={key} className="text-sm">
            <p className="font-medium mb-1">{label}</p>
            <ScaleSlider
              min={1}
              max={5}
              value={current[key] as number}
              lowLabel={low}
              highLabel={high}
              showInput={false}
              onChange={(v) =>
                setDraft({ ...draft, work_preferences: { ...current, [key]: Number(v) || (current[key] as number) } })
              }
            />
          </div>
        ))}
      </div>
      <div>
        <h3 className="text-sm font-semibold">What do you want to work with?</h3>
        <p className="text-sm text-slate-500 mt-0.5 mb-2">
          Pick any — they steer which jobs and skills we surface for you.
        </p>
        <div className="grid sm:grid-cols-2 gap-2" data-testid="focus-areas">
          {FOCUS_AREAS.map(({ key, label, hint, icon: Icon }) => {
            const active = current.focus_areas.includes(key);
            return (
              <button
                key={key}
                type="button"
                aria-pressed={active}
                onClick={() => {
                  const next = active
                    ? current.focus_areas.filter((a) => a !== key)
                    : [...current.focus_areas, key];
                  setDraft({ ...draft, work_preferences: { ...current, focus_areas: next } });
                }}
                className={`flex items-start gap-3 rounded-xl border p-3 text-left transition-colors ${
                  active
                    ? "bg-primary-600 text-white border-primary-600"
                    : "border-slate-200 hover:border-primary-500"
                }`}
              >
                <Icon className={`w-5 h-5 mt-0.5 shrink-0 ${active ? "" : "text-primary-600"}`} aria-hidden />
                <span className="block">
                  <span className="block text-sm font-medium">{label}</span>
                  <span className={`block text-xs mt-0.5 ${active ? "text-white/80" : "text-slate-500"}`}>{hint}</span>
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

const CONDITION_OPTIONS = ["none", "mobility_limited", "hearing_impaired", "vision_impaired", "chronic_fatigue", "other"];

function ConstraintsStep({ profile, draft, setDraft }: StepProps) {
  const current = { ...DEFAULT_CONSTRAINTS, ...profile?.constraints, ...draft.constraints };
  return (
    <div className="space-y-4">
      <h2 className="font-semibold">Constraints & reality checks</h2>
      <p className="text-sm text-slate-500">These help the AI filter jobs that are genuinely open to you.</p>
      <div className="flex flex-wrap gap-2">
        {CONDITION_OPTIONS.map((c) => {
          const active = current.physical_conditions.includes(c);
          return (
            <button
              key={c}
              type="button"
              onClick={() => {
                const next = active
                  ? current.physical_conditions.filter((x) => x !== c)
                  : [...current.physical_conditions, c];
                setDraft({ ...draft, constraints: { ...current, physical_conditions: next } });
              }}
              className={`text-sm px-3 py-1.5 rounded-full border ${
                active ? "bg-primary-600 text-white border-primary-600" : "border-slate-200"
              }`}
            >
              {c.replace(/_/g, " ")}
            </button>
          );
        })}
      </div>
      <label className="text-sm block">
        Max years of education you&rsquo;re willing to study
        <input
          type="number"
          min={0}
          max={12}
          value={current.max_education_years ?? ""}
          onChange={(e) =>
            setDraft({ ...draft, constraints: { ...current, max_education_years: Number(e.target.value) || null } })
          }
          className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
        />
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={current.willing_to_relocate}
          onChange={(e) => setDraft({ ...draft, constraints: { ...current, willing_to_relocate: e.target.checked } })}
        />
        Willing to relocate for the right job
      </label>
    </div>
  );
}
