import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useProfileStore } from "@/stores/profileStore";
import { logout as clearToken, revokeSessions } from "@/api/auth";
import {
  deleteAccount,
  downloadExport,
  requestExport,
  type BackgroundJob,
} from "@/api/backgroundJobs";
import { fetchMySkills, saveMySkills } from "@/api/skills";
import { fetchSkillOntology } from "@/api/skills";
import { setStage } from "@/api/stages";
import { useBootstrapStore } from "@/stores/bootstrapStore";
import { useBackgroundJob } from "@/hooks/useBackgroundJob";
import { apiDetail } from "@/api/client";
import { ChipList, ScaleSlider, SearchableDropdown, Button } from "@/components/ui";
import { WeightsEditor } from "@/components/WeightsEditor";
import type { CareerStage, Profile, ScoringWeights, UserSkill } from "@/types";

const STAGE_DROPDOWN_OPTIONS = [
  { value: "student", label: "Student" },
  { value: "early_career", label: "Early career" },
  { value: "experienced", label: "Experienced" },
  { value: "switching", label: "Switching fields" },
  { value: "returning", label: "Returning after a break" },
];

export function ProfileEdit() {
  const { profile, load, saveSection, analyze } = useProfileStore();
  const reload = () => {
    useProfileStore.setState({ profile: null });
    void load();
  };
  const navigate = useNavigate();
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleting, setDeleting] = useState(false);

  const onExportDone = (finished: BackgroundJob) => {
    setExporting(false);
    if (finished.status === "failed") {
      setError(finished.error ?? "Export failed");
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
      clearToken();
      navigate("/login");
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

  useEffect(() => {
    void load();
  }, [load]);

  const signOutEverywhere = async () => {
    setRevoking(true);
    setError("");
    try {
      await revokeSessions();
      clearToken();
      navigate("/login");
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setRevoking(false);
    }
  };

  if (!profile) return <p className="text-slate-400">Loading…</p>;
  const p = profile;

  return (
    <div className="max-w-3xl mx-auto space-y-6" data-testid="profile-edit">
      <h1 className="text-2xl font-bold text-slate-900">Your profile</h1>
      <div className="bg-white border border-slate-200 rounded-xl p-4">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium">Completeness: {p.completeness.percent}%</p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => void signOutEverywhere()}
              disabled={revoking}
              title="Invalidates every issued session for your account"
              className="text-sm border border-slate-200 text-slate-600 hover:text-rose-600 hover:border-rose-300 rounded-lg px-3 py-1.5 disabled:opacity-50"
            >
              {revoking ? "Signing out…" : "Sign out everywhere"}
            </button>
            <button
              onClick={async () => {
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
              disabled={analyzing}
              className="text-sm bg-primary-600 text-white rounded-lg px-3 py-1.5 disabled:opacity-50"
            >
              {analyzing ? "Analyzing…" : "Re-run AI analysis"}
            </button>
          </div>
        </div>
        <div className="h-2 bg-slate-100 rounded-full mt-2">
          <div className="h-2 bg-primary-600 rounded-full" style={{ width: `${p.completeness.percent}%` }} />
        </div>
      </div>

      {error && <p className="text-sm text-rose-600">{error}</p>}

      {p.ai_summary && (
        <section className="bg-primary-50 border border-primary-100 rounded-xl p-4">
          <h2 className="font-medium text-primary-900">AI analysis</h2>
          <p className="text-sm mt-1 text-slate-700">{p.ai_summary.summary}</p>
          {p.ai_summary.strengths.length > 0 && (
            <p className="text-sm mt-2"><strong>Strengths:</strong> {p.ai_summary.strengths.join(", ")}</p>
          )}
          {p.ai_summary.watchouts.length > 0 && (
            <p className="text-sm"><strong>Watchouts:</strong> {p.ai_summary.watchouts.join(", ")}</p>
          )}
        </section>
      )}

      <Section title="Career stage">
        <p className="text-xs text-slate-500 mb-2">
          One switch adapts your suggested fit weights, assessment questions
          and which modules you see — never your data.
        </p>
        <div className="max-w-xs" data-testid="stage-switch">
          <SearchableDropdown
            options={STAGE_DROPDOWN_OPTIONS}
            value={p.career_stage ?? ""}
            onChange={(v) => void switchStage((v || null) as CareerStage | null)}
            placeholder="Auto-detected from your profile"
          />
        </div>
        {p.stage_source === "derived" && (
          <p className="text-xs text-slate-400 mt-1">
            Auto-detected — correct it above if it&apos;s off.
          </p>
        )}
      </Section>
      <Section title="Basics">
        <InlineEdit
          initial={JSON.stringify(p.basics, null, 0)}
          onSave={async (v) => {
            await saveSection({ basics: JSON.parse(v) });
            setSaved(true);
          }}
        />
      </Section>
      <Section title="Academics">
        <InlineEdit
          initial={JSON.stringify(p.academics, null, 0)}
          onSave={async (v) => {
            await saveSection({ academics: JSON.parse(v) });
            setSaved(true);
          }}
        />
      </Section>
      <Section title={`Interests (${p.interests.length})`}>
        <ChipList items={p.interests.map((i) => `${i.tag_key} · ${i.weight}`)} variant="primary" emptyText="No interests selected yet." />
      </Section>
      <SkillsSection />
      <WeightsSection initial={p.preferences?.scoring_weights} onChanged={reload} />
      <Section title="Experience">
        <InlineEdit
          initial={JSON.stringify(p.experience ?? [], null, 0)}
          onSave={async (v) => {
            await saveSection({ experience: JSON.parse(v) });
            setSaved(true);
          }}
        />
      </Section>
      <Section title={`Aspirations (${p.aspirations.length})`}>
        <ul className="text-sm text-slate-600 space-y-1">
          {p.aspirations.map((a, i) => (
            <li key={i}>· {a.label}</li>
          ))}
        </ul>
      </Section>
      <Section title="Constraints">
        <InlineEdit
          initial={JSON.stringify(p.constraints, null, 0)}
          onSave={async (v) => {
            await saveSection({ constraints: JSON.parse(v) });
            setSaved(true);
          }}
        />
      </Section>
      <section className="bg-white border border-slate-200 rounded-xl p-4" data-testid="data-privacy">
        <h2 className="font-medium mb-2">Data &amp; privacy</h2>
        <div className="flex items-center gap-3 flex-wrap">
          <button
            onClick={() => void startExport()}
            disabled={exporting}
            className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 hover:border-primary-400 disabled:opacity-50"
          >
            {exporting ? "Preparing export…" : "Export my data (zip)"}
          </button>
          <button
            onClick={() => setDeleteConfirm((v) => !v)}
            className="text-sm border border-slate-200 text-slate-600 hover:text-rose-600 hover:border-rose-300 rounded-lg px-3 py-1.5"
          >
            Delete account…
          </button>
        </div>
        {exporting && exportJob && (
          <p className="text-xs text-slate-400 mt-2">
            {exportJob.stage ?? "queued…"} ({exportJob.progress}%)
          </p>
        )}
        {deleteConfirm && (
          <div className="mt-3 border border-rose-200 bg-rose-50 rounded-lg p-3 space-y-2">
            <p className="text-sm text-rose-700">
              This permanently deletes your profile, matches, chats, documents
              and uploads. It cannot be undone.
            </p>
            <input
              type="password"
              value={deletePassword}
              onChange={(e) => setDeletePassword(e.target.value)}
              placeholder="Confirm your password"
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
            />
            <div className="flex gap-2">
              <button
                onClick={() => void confirmDelete()}
                disabled={deleting || !deletePassword}
                className="text-sm bg-rose-600 text-white rounded-lg px-3 py-1.5 disabled:opacity-50"
              >
                {deleting ? "Deleting…" : "Delete forever"}
              </button>
              <button
                onClick={() => setDeleteConfirm(false)}
                className="text-sm border border-slate-200 rounded-lg px-3 py-1.5"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </section>
      {saved && <p className="text-sm text-emerald-600">Saved ✓</p>}
    </div>
  );
}

function WeightsSection({
  initial,
  onChanged,
}: {
  initial?: ScoringWeights;
  onChanged: () => void;
}) {
  if (!initial) return null;
  return (
    <section className="bg-white border border-slate-200 rounded-xl p-4" data-testid="profile-weights">
      <h2 className="font-medium mb-1">What matters to you</h2>
      <p className="text-xs text-slate-400 mb-3">
        Slider weights per fit dimension (1–5). Saving recomputes your job fits instantly.
      </p>
      <WeightsEditor initial={initial} onSaved={() => onChanged()} />
    </section>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-white border border-slate-200 rounded-xl p-4">
      <h2 className="font-medium mb-2">{title}</h2>
      {children}
    </section>
  );
}

function SkillsSection() {
  const [skills, setSkills] = useState<UserSkill[]>([]);
  const [draft, setDraft] = useState<{ key: string; level: number } | null>(null);
  const [options, setOptions] = useState<{ label: string; value: string }[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void (async () => {
      try {
        setSkills(await fetchMySkills());
        const ontology = await fetchSkillOntology();
        setOptions(
          ontology.map((s) => ({ label: `${s.label} (${s.category})`, value: s.key })),
        );
      } catch (err) {
        setError(apiDetail(err));
      }
    })();
  }, []);

  const persist = async (next: { skill_key: string; level: number }[]) => {
    setSaving(true);
    setError("");
    try {
      setSkills(await saveMySkills(next));
      setDraft(null);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setSaving(false);
    }
  };

  const removeSkill = (key: string) => {
    const next = skills
      .filter((s) => s.key !== key && s.source === "self_report")
      .map((s) => ({ skill_key: s.key, level: s.level }));
    void persist(next);
  };

  const addSkill = () => {
    if (!draft?.key) return;
    const next = [
      ...skills
        .filter((s) => s.source === "self_report")
        .map((s) => ({ skill_key: s.key, level: s.level })),
      { skill_key: draft.key, level: draft.level },
    ];
    void persist(next);
  };

  const selfReported = skills.filter((s) => s.source === "self_report");
  const fromSystem = skills.filter((s) => s.source !== "self_report");

  return (
    <section className="bg-white border border-slate-200 rounded-xl p-4" data-testid="profile-skills">
      <h2 className="font-medium mb-2">Skills ({skills.length})</h2>
      <p className="text-xs text-slate-400 mb-3">Self-rated 1–10 with semantic anchors. Verified skills from assessments appear separately.</p>
      {error && <p className="text-sm text-rose-600 mb-2">{error}</p>}
      {skills.length === 0 ? (
        <p className="text-sm text-slate-400">No skills added yet.</p>
      ) : (
        <ul className="space-y-2">
          {[...selfReported, ...fromSystem].map((s) => (
            <li key={s.key} className="flex items-center gap-3">
              <span className="text-sm w-44 shrink-0">
                {s.label}
                {s.source !== "self_report" && (
                  <span className="text-xs text-slate-400"> · {s.source.replace(/_/g, " ")}</span>
                )}
              </span>
              {s.source === "self_report" ? (
                <div className="flex-1 min-w-0" data-testid={`skill-slider-${s.key}`}>
                  <ScaleSlider
                    value={s.level}
                    min={1}
                    max={10}
                    ariaLabel={`${s.label} level`}
                    onChange={(v) => {
                      const level = typeof v === "number" ? v : s.level;
                      setSkills((prev) => prev.map((p) => (p.key === s.key ? { ...p, level } : p)));
                    }}
                    onPointerUp={() => {
                      if (s.level !== undefined) {
                        void persist([{ skill_key: s.key, level: s.level }]);
                      }
                    }}
                  />
                </div>
              ) : (
                <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                  <div className="h-1.5 bg-primary-600 rounded-full" style={{ width: `${(s.level / 10) * 100}%` }} />
                </div>
              )}
              <span className="text-xs text-slate-500 w-8 text-right">{s.level}/10</span>
              {s.source === "self_report" && (
                <button
                  onClick={() => removeSkill(s.key)}
                  className="text-xs text-slate-400 hover:text-rose-600"
                  aria-label={`Remove ${s.label}`}
                >
                  remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="mt-4 flex items-end gap-3 flex-wrap">
        <div className="w-64">
          <SearchableDropdown
            options={options}
            value={draft?.key ?? ""}
            onChange={(value) => setDraft({ key: value, level: draft?.level ?? 5 })}
            placeholder="Add a skill…"
          />
        </div>
        {draft?.key && (
          <div className="w-56" data-testid="new-skill-slider">
            <ScaleSlider
              value={draft.level}
              min={1}
              max={10}
              ariaLabel="New skill level"
              onChange={(v) => setDraft({ ...draft, level: typeof v === "number" ? v : draft.level })}
            />
          </div>
        )}
        <Button variant="default" onClick={() => void addSkill()} disabled={!draft?.key || saving}>
          {saving ? "Saving…" : "Add skill"}
        </Button>
      </div>
    </section>
  );
}

function InlineEdit({ initial, onSave }: { initial: string; onSave: (value: string) => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);

  if (!editing) {
    return (
      <p
        onClick={() => setEditing(true)}
        className="text-sm text-slate-600 font-mono break-all cursor-text hover:text-slate-900"
      >
        {initial.length > 200 ? `${initial.slice(0, 200)}…` : initial} <span className="text-primary-700 text-xs">(click to edit)</span>
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        rows={5}
        className="w-full border border-slate-200 rounded-lg px-3 py-2 text-xs font-mono"
      />
      <div className="flex gap-2">
        <button
          onClick={async () => {
            setBusy(true);
            try {
              await onSave(value);
              setEditing(false);
            } finally {
              setBusy(false);
            }
          }}
          disabled={busy}
          className="text-sm bg-primary-600 text-white rounded-lg px-3 py-1.5 disabled:opacity-50"
        >
          Save
        </button>
        <button onClick={() => setEditing(false)} className="text-sm border border-slate-200 rounded-lg px-3 py-1.5">
          Cancel
        </button>
      </div>
    </div>
  );
}

export function useProfileGuard() {
  const navigate = useNavigate();
  return () => navigate("/onboarding");
}

export type ProfileDraft = Partial<Profile>;
