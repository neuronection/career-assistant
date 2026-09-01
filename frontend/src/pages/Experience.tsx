import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CalendarRange, Plus, Sparkles, Trash2 } from "lucide-react";
import { Button } from "@/components/ui";
import {
  applyDerivation,
  createExperienceItem,
  deleteExperienceItem,
  fetchDerivation,
  fetchExperience,
  updateExperienceItem,
} from "@/api/experience";
import { fetchSkillOntology } from "@/api/skills";
import type { SkillSummary } from "@/api/skills";
import type {
  ExperienceItemOut,
  ExperienceItemIn,
  ExperienceSkillIn,
} from "@/types/experience";

const KINDS: ExperienceItemIn["kind"][] = [
  "job",
  "internship",
  "project",
  "freelance",
  "volunteer",
];
const ROLES: ExperienceSkillIn["role_in_item"][] = [
  "primary",
  "secondary",
  "exposure",
];

interface SkillOption {
  key: string;
  label: string;
}

const EMPTY_FORM = {
  title: "",
  kind: "project" as ExperienceItemIn["kind"],
  org_name: "",
  start: "",
  end: "",
  open_ended: false,
  hours_per_week: "" as string | number,
  onsite_policy: "onsite" as NonNullable<ExperienceItemIn["onsite_policy"]>,
  description: "",
  status: "active" as "draft" | "active",
  skills: [] as ExperienceSkillIn[],
};

/** Structured experience editor (plan 40): guided items + live
 * derivation preview with an explicit apply-to-skills step. */
export function Experience() {
  const navigate = useNavigate();
  const [items, setItems] = useState<ExperienceItemOut[]>([]);
  const [years, setYears] = useState(0);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [editingId, setEditingId] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [skillOptions, setSkillOptions] = useState<SkillOption[]>([]);
  const [derived, setDerived] = useState<
    { skill_label: string; months: number; level: number; confidence: number }[]
  >([]);
  const [applyState, setApplyState] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [list, derivation] = await Promise.all([
      fetchExperience(),
      fetchDerivation(),
    ]);
    setItems(list.items);
    setYears(list.years_of_experience);
    setDerived(derivation.skills);
  }, []);

  useEffect(() => {
    void load().catch(() => undefined);
    void fetchSkillOntology()
      .then((rows: SkillSummary[]) =>
        setSkillOptions(rows.map((s) => ({ key: s.key, label: s.label })))
      )
      .catch(() => setSkillOptions([]));
  }, [load]);

  const openCreate = () => {
    setForm({ ...EMPTY_FORM });
    setEditingId(null);
    setOpen(true);
  };

  const openEdit = (item: ExperienceItemOut) => {
    setForm({
      title: item.title,
      kind: item.kind,
      org_name: item.org_name,
      start: item.start,
      end: item.end ?? "",
      open_ended: item.open_ended,
      hours_per_week: item.hours_per_week ?? "",
      onsite_policy: (item.onsite_policy ?? "onsite") as NonNullable<
        ExperienceItemIn["onsite_policy"]
      >,
      description: item.description,
      status: item.status,
      skills: item.skills.map((s) => ({
        skill_key: s.skill_key,
        role_in_item: s.role_in_item,
        level_claim: s.level_claim,
        last_used: s.last_used,
      })),
    });
    setEditingId(item.id);
    setOpen(true);
  };

  const submit = async () => {
    const payload = {
      ...form,
      hours_per_week:
        form.hours_per_week === "" ? null : Number(form.hours_per_week),
      start: form.start || null,
      end: form.open_ended ? null : form.end || null,
    };
    if (editingId) {
      await updateExperienceItem(editingId, payload);
    } else {
      await createExperienceItem(payload as ExperienceItemIn);
    }
    setOpen(false);
    await load();
  };

  const remove = async (id: string) => {
    await deleteExperienceItem(id);
    await load();
  };

  const apply = async () => {
    const result = await applyDerivation();
    setApplyState(
      result.conflicts.length > 0
        ? `Applied ${result.applied} skill level(s); ${result.conflicts.length} conflict(s) need review.`
        : `Applied ${result.applied} skill level(s) from your experience.`
    );
    await load();
  };

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6" data-testid="experience-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 flex items-center gap-2">
            <CalendarRange className="w-5 h-5" /> Experience
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Structured history — skills, roles and metric-bearing outcomes.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span
            className="text-sm text-slate-600"
            data-testid="years-of-experience"
          >
            ≈ {years}y derived
          </span>
          <Button onClick={openCreate} data-testid="add-experience">
            <Plus className="w-4 h-4 mr-1" /> Add
          </Button>
        </div>
      </div>

      {derived.length > 0 && (
        <section
          className="rounded-xl border border-slate-200 bg-white p-5"
          data-testid="derivation-panel"
        >
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-900 flex items-center gap-1.5">
              <Sparkles className="w-4 h-4" /> Derived skill levels
            </h2>
            <Button
              variant="outline"
              onClick={() => void apply()}
              data-testid="apply-derivation"
            >
              Apply to my skills
            </Button>
          </div>
          {applyState && (
            <p className="mt-2 text-xs text-emerald-700" data-testid="apply-state">
              {applyState}
            </p>
          )}
          <div className="mt-3 space-y-2">
            {derived.map((d) => (
              <div key={d.skill_label} className="flex items-center gap-3 text-sm">
                <span className="w-40 truncate text-slate-700">{d.skill_label}</span>
                <div className="flex-1 h-2 rounded-full bg-slate-100 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-primary-500"
                    style={{ width: `${(d.level / 10) * 100}%` }}
                  />
                </div>
                <span className="w-32 text-xs text-slate-500">
                  ≈ level {d.level.toFixed(1)} · {Math.round(d.months)}mo
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="space-y-3" data-testid="experience-list">
        {items.length === 0 && (
          <p className="text-sm text-slate-400 py-8 text-center">
            No experience items yet — add your first project, internship or job.
          </p>
        )}
        {items.map((item) => (
          <article
            key={item.id}
            className="rounded-xl border border-slate-200 bg-white p-4"
            data-testid="experience-item"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-medium text-slate-900">
                  {item.title}
                  {item.status === "draft" && (
                    <span className="ml-2 text-xs rounded-full bg-amber-100 text-amber-800 px-2 py-0.5">
                      draft
                    </span>
                  )}
                </h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  {item.kind}
                  {item.org_name ? ` · ${item.org_name}` : ""} · {item.start} →{" "}
                  {item.open_ended ? "present" : item.end}
                </p>
              </div>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => openEdit(item)}
                  className="text-xs text-primary-700 hover:underline"
                  data-testid="edit-experience"
                >
                  Edit
                </button>
                <button
                  type="button"
                  aria-label="Delete item"
                  onClick={() => void remove(item.id)}
                  className="p-1.5 rounded text-slate-300 hover:text-rose-600"
                  data-testid="delete-experience"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
            {item.skills.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {item.skills.map((s) => (
                  <span
                    key={s.skill_id}
                    className="text-xs rounded-full bg-slate-100 text-slate-700 px-2 py-0.5"
                  >
                    {s.skill_label} · {s.role_in_item}
                  </span>
                ))}
              </div>
            )}
            {item.achievements.length > 0 && (
              <ul className="mt-2 text-xs text-slate-600 list-disc pl-4">
                {item.achievements.map((a) => (
                  <li key={a.id}>{a.text}</li>
                ))}
              </ul>
            )}
          </article>
        ))}
      </section>

      {open && (
        <div
          className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center overflow-y-auto p-6"
          data-testid="experience-modal"
        >
          <div className="bg-white rounded-xl w-full max-w-lg p-6 space-y-4">
            <h2 className="text-base font-semibold text-slate-900">
              {editingId ? "Edit experience" : "Add experience"}
            </h2>
            <input
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
              placeholder="Role or project title"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              data-testid="experience-title"
            />
            <div className="grid grid-cols-2 gap-3">
              <select
                className="border border-slate-200 rounded-lg px-3 py-2 text-sm"
                value={form.kind}
                onChange={(e) =>
                  setForm({ ...form, kind: e.target.value as ExperienceItemIn["kind"] })
                }
                data-testid="experience-kind"
              >
                {KINDS.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
              <input
                className="border border-slate-200 rounded-lg px-3 py-2 text-sm"
                placeholder="Organization (optional)"
                value={form.org_name}
                onChange={(e) => setForm({ ...form, org_name: e.target.value })}
                data-testid="experience-org"
              />
            </div>
            <div className="grid grid-cols-3 gap-3 items-end">
              <label className="text-xs text-slate-600">
                Start
                <input
                  type="date"
                  className="w-full border border-slate-200 rounded-lg px-2 py-1.5 text-sm"
                  value={form.start}
                  onChange={(e) => setForm({ ...form, start: e.target.value })}
                  data-testid="experience-start"
                />
              </label>
              <label className="text-xs text-slate-600">
                End
                <input
                  type="date"
                  className="w-full border border-slate-200 rounded-lg px-2 py-1.5 text-sm disabled:opacity-40"
                  value={form.end}
                  disabled={form.open_ended}
                  onChange={(e) => setForm({ ...form, end: e.target.value })}
                  data-testid="experience-end"
                />
              </label>
              <label className="flex items-center gap-1.5 text-xs text-slate-600 pb-2">
                <input
                  type="checkbox"
                  checked={form.open_ended}
                  onChange={(e) =>
                    setForm({ ...form, open_ended: e.target.checked })
                  }
                />
                ongoing
              </label>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <input
                type="number"
                min={1}
                max={80}
                className="border border-slate-200 rounded-lg px-3 py-2 text-sm"
                placeholder="Hours / week (optional)"
                value={form.hours_per_week}
                onChange={(e) =>
                  setForm({ ...form, hours_per_week: e.target.value })
                }
              />
              <select
                className="border border-slate-200 rounded-lg px-3 py-2 text-sm"
                value={form.status}
                onChange={(e) =>
                  setForm({
                    ...form,
                    status: e.target.value as "draft" | "active",
                  })
                }
              >
                <option value="active">active</option>
                <option value="draft">draft</option>
              </select>
            </div>
            <div>
              <p className="text-xs text-slate-600 mb-1.5">Skills used</p>
              <div className="flex flex-wrap gap-1.5 mb-2" data-testid="skill-chips">
                {form.skills.map((s, i) => (
                  <span
                    key={`${s.skill_key}-${i}`}
                    className="text-xs rounded-full bg-primary-50 text-primary-800 px-2 py-0.5"
                  >
                    {skillOptions.find((o) => o.key === s.skill_key)?.label ??
                      s.skill_key}
                    · {s.role_in_item}
                    <button
                      type="button"
                      className="ml-1 text-primary-400 hover:text-primary-700"
                      onClick={() =>
                        setForm({
                          ...form,
                          skills: form.skills.filter((_, j) => j !== i),
                        })
                      }
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
              <div className="flex gap-2">
                <select
                  className="flex-1 border border-slate-200 rounded-lg px-2 py-1.5 text-sm"
                  value=""
                  onChange={(e) => {
                    if (!e.target.value) return;
                    setForm({
                      ...form,
                      skills: [
                        ...form.skills,
                        {
                          skill_key: e.target.value,
                          role_in_item: "primary",
                          level_claim: null,
                          last_used: null,
                        },
                      ],
                    });
                  }}
                  data-testid="skill-select"
                >
                  <option value="">Add a skill…</option>
                  {skillOptions
                    .filter(
                      (o) => !form.skills.some((s) => s.skill_key === o.key)
                    )
                    .map((o) => (
                      <option key={o.key} value={o.key}>
                        {o.label}
                      </option>
                    ))}
                </select>
              </div>
              {form.skills.length > 0 && (
                <div className="mt-2 space-y-1.5">
                  {form.skills.map((s, i) => (
                    <div key={`${s.skill_key}-role-${i}`} className="flex items-center gap-2">
                      <span className="text-xs text-slate-500 w-32 truncate">
                        {skillOptions.find((o) => o.key === s.skill_key)?.label}
                      </span>
                      <select
                        className="text-xs border border-slate-200 rounded px-1.5 py-1"
                        value={s.role_in_item}
                        onChange={(e) => {
                          const next = [...form.skills];
                          next[i] = {
                            ...s,
                            role_in_item: e.target
                              .value as ExperienceSkillIn["role_in_item"],
                          };
                          setForm({ ...form, skills: next });
                        }}
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>
                            {r}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button
                onClick={() => void submit()}
                disabled={!form.title || !form.start || (!form.end && !form.open_ended)}
                data-testid="experience-save"
              >
                Save
              </Button>
            </div>
          </div>
        </div>
      )}

      <button
        type="button"
        className="text-xs text-slate-400 hover:text-slate-600"
        onClick={() => navigate("/profile")}
      >
        ← Back to profile
      </button>
    </div>
  );
}
