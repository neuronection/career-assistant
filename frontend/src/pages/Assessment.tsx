import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { FileDown, FileUp, Library } from "lucide-react";
import { ScaleSlider } from "@/components/ui";
import { apiDetail } from "@/api/client";
import {
  advanceAssessment,
  assistQuestion,
  cancelAssessment,
  createAssessment,
  exportTemplate,
  fetchAssessment,
  fetchAssessmentResults,
  fetchTemplates,
  importTemplate,
  runTemplate,
  submitAnswers,
  type AssessmentQuestion,
  type AssessmentState,
  type AssessmentTemplate,
} from "@/api/assessments";
import type { AssessmentResults } from "@/api/assessments";

type Draft = Record<string, Record<string, unknown> | null>;

export function Assessment() {
  const [state, setState] = useState<AssessmentState | null>(null);
  const [results, setResults] = useState<AssessmentResults | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [effects, setEffects] = useState<Record<string, unknown> | null>(null);
  const [templates, setTemplates] = useState<AssessmentTemplate[]>([]);
  const [templateNote, setTemplateNote] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  const start = useCallback(async (kind: string, context: Record<string, unknown> = {}) => {
    setBusy(true);
    setError("");
    try {
      const fresh = await createAssessment(kind, context);
      setState(fresh);
      setResults(null);
      setEffects(null);
      setDraft({});
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void (async () => {
      setBusy(true);
      try {
        const fresh = await createAssessment("full");
        setState(fresh);
      } catch (err) {
        setError(apiDetail(err));
      } finally {
        setBusy(false);
      }
    })();
    void fetchTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([]));
  }, []);

  const startTemplate = async (template: AssessmentTemplate) => {
    setBusy(true);
    setError("");
    try {
      const fresh = await runTemplate(template.id);
      setState(fresh);
      setResults(null);
      setEffects(null);
      setDraft({});
      setTemplateNote(`Running template: ${template.title}`);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const importFromFile = async (file: File) => {
    setError("");
    try {
      const pkg = JSON.parse(await file.text());
      const imported = await importTemplate(pkg);
      const proposed = imported.import_report?.proposed ?? [];
      setTemplateNote(
        proposed.length > 0
          ? `Imported "${imported.title}" — ${proposed.length} new skill(s) proposed for moderation.`
          : `Imported "${imported.title}".`
      );
      const fresh = await runTemplate(imported.id);
      setState(fresh);
      setResults(null);
      setEffects(null);
      setDraft({});
    } catch (err) {
      setError(err instanceof Error ? err.message : apiDetail(err));
    }
  };

  const setAnswer = (questionId: string, answer: Record<string, unknown> | null) => {
    setDraft((d) => ({ ...d, [questionId]: answer }));
  };

  const saveAndAdvance = async () => {
    if (!state) return;
    setBusy(true);
    setError("");
    try {
      const answers = Object.entries(draft)
        .filter(([, v]) => v !== undefined)
        .map(([question_id, answer]) => ({ question_id, answer: answer ?? {} }));
      if (answers.length > 0) {
        await submitAnswers(state.id, answers);
      }
      const advanced = await advanceAssessment(state.id);
      if (advanced.status === "completed") {
        setEffects(advanced.effects ?? null);
        setResults(await fetchAssessmentResults(state.id));
        setState(null);
      } else {
        const fresh = await fetchAssessment(state.id);
        setState(fresh);
        setDraft({});
      }
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const ask = async (questionId: string) => {
    setError("");
    try {
      const reply = await assistQuestion(state!.id, questionId);
      setDraft((d) => ({ ...d, [questionId]: d[questionId] ?? null }));
      setAssistText((t) => ({ ...t, [questionId]: reply.answer }));
    } catch (err) {
      setError(apiDetail(err));
    }
  };
  const [assistText, setAssistText] = useState<Record<string, string>>({});

  if (error && !state && !results) return <p className="text-rose-600">{error}</p>;
  if (busy && !state && !results) return <p className="text-slate-400">Loading…</p>;

  if (results) {
    return (
      <div className="space-y-6 max-w-3xl mx-auto" data-testid="assessment-results">
        <h1 className="text-2xl font-bold text-slate-900">Your results</h1>
        {effects && (effects.skill_conflicts as unknown[])?.length > 0 && (
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm">
            <p className="font-medium text-amber-800 mb-1">We spotted conflicts</p>
            <ul className="space-y-1">
              {(effects.skill_conflicts as { key: string; self_level: number; assessed_level: number }[]).map((c) => (
                <li key={c.key}>
                  You rated yourself <strong>{c.self_level}</strong> on {c.key}, but
                  your scenario answers suggest <strong>{c.assessed_level}</strong> —
                  we kept your rating. Adjust it on your profile if you disagree.
                </li>
              ))}
            </ul>
          </div>
        )}
        <section className="bg-white border border-slate-200 rounded-xl p-4">
          <h2 className="font-medium mb-2">Skills the scenarios revealed</h2>
          {results.skill_levels.length === 0 ? (
            <p className="text-sm text-slate-400">No skill signal from this run.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {results.skill_levels.map((s) => (
                <li key={s.key} className="flex items-center gap-2">
                  <span className="w-40">{s.key}</span>
                  <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                    <div className="h-1.5 bg-primary-600 rounded-full" style={{ width: `${(s.level / 10) * 100}%` }} />
                  </div>
                  <span className="text-xs text-slate-400 w-8">{s.level}/10</span>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="bg-white border border-slate-200 rounded-xl p-4">
          <h2 className="font-medium mb-2">Interests touched</h2>
          <div className="flex flex-wrap gap-1">
            {results.interest_keys.map((k) => (
              <span key={k} className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded">{k}</span>
            ))}
          </div>
        </section>
        <section className="bg-white border border-slate-200 rounded-xl p-4">
          <h2 className="font-medium mb-2">Your shortlist (refreshed fit)</h2>
          <ol className="text-sm space-y-1">
            {results.shortlist.slice(0, 5).map((s, i) => (
              <li key={s.job_id} className="flex items-center gap-2">
                <span className="text-slate-400">{i + 1}.</span>
                fit <strong>{Number(s.fit_score).toFixed(1)}</strong>
                <Link to="/rankings" className="text-primary-700 text-xs">see rankings →</Link>
              </li>
            ))}
          </ol>
        </section>
        <button
          onClick={() => void start("custom", { phase_order: [2, 3, 4] })}
          disabled={busy}
          className="text-sm bg-primary-600 text-white rounded-lg px-4 py-2 disabled:opacity-50"
        >
          Re-run with focus (phases 2–4)
        </button>
      </div>
    );
  }

  if (!state) return null;
  const answeredTotal = Object.values(state.progress).reduce(
    (acc, p) => acc + p.answered,
    0,
  );

  return (
    <div className="space-y-6 max-w-3xl mx-auto" data-testid="assessment">
      <section
        className="rounded-xl border border-slate-200 bg-white p-4"
        data-testid="templates-panel"
      >
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-900 flex items-center gap-1.5">
            <Library className="w-4 h-4" /> Test library
          </h2>
          <div className="flex items-center gap-2">
            {templateNote && (
              <span className="text-xs text-emerald-700" data-testid="template-note">
                {templateNote}
              </span>
            )}
            <input
              ref={fileInput}
              type="file"
              accept="application/json"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void importFromFile(file);
                e.target.value = "";
              }}
            />
            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              className="inline-flex items-center gap-1 text-xs text-slate-600 hover:text-slate-900"
              data-testid="import-template"
            >
              <FileUp className="w-3.5 h-3.5" /> Import
            </button>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {templates.length === 0 && (
            <p className="text-xs text-slate-400">
              No templates yet — bank templates and imports appear here.
            </p>
          )}
          {templates.map((t) => (
            <div
              key={t.id}
              className="inline-flex items-center gap-2 rounded-full border border-slate-200 px-3 py-1.5"
              data-testid="template-chip"
            >
              <button
                type="button"
                onClick={() => void startTemplate(t)}
                className="text-xs text-slate-800 hover:text-primary-700"
                title={t.description || t.title}
              >
                {t.title}
                <span className="ml-1 text-slate-400">
                  v{t.version}
                  {t.is_bank ? " · bank" : ""}
                </span>
              </button>
              <button
                type="button"
                aria-label={`Export ${t.title}`}
                onClick={() => void exportTemplate(t.id)}
                className="text-slate-300 hover:text-slate-600"
              >
                <FileDown className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      </section>

      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900 capitalize">{state.kind} assessment</h1>
        <button
          onClick={async () => {
            if (!state) return;
            await cancelAssessment(state.id);
            setState(null);
            setResults(null);
          }}
          className="text-sm text-slate-400 hover:text-rose-600"
        >
          cancel run
        </button>
      </div>

      {/* progress rail */}
      <div className="flex gap-2" data-testid="progress-rail">
        {state.phase_order.map((phase) => {
          const p = state.progress[String(phase)] ?? { answered: 0, total: 0, title: "" };
          const current = phase === state.current_phase;
          return (
            <div
              key={phase}
              className={`flex-1 rounded-lg border px-3 py-2 text-xs ${
                current ? "border-primary-500 bg-primary-50" : "border-slate-200 bg-white"
              }`}
            >
              <span className="font-medium">Phase {phase}</span>
              <span className="block text-slate-400 truncate">{p.title}</span>
              {p.total > 0 && (
                <span className="text-slate-400">{p.answered}/{p.total}</span>
              )}
            </div>
          );
        })}
      </div>

      {state.phase_one_form && (
        <div className="bg-white border border-slate-200 rounded-xl p-4 text-sm text-slate-600">
          Phase 1 reuses your profile — basics, interests and school details you
          already entered. Update them any time from your{" "}
          <Link to="/profile" className="text-primary-700">profile</Link>.
        </div>
      )}

      <div className="space-y-4">
        {state.questions.map((q) => (
          <QuestionCard
            key={q.id}
            question={q}
            value={draft[q.id]}
            assist={assistText[q.id]}
            onChange={(answer) => setAnswer(q.id, answer)}
            onAsk={() => void ask(q.id)}
          />
        ))}
      </div>

      {error && <p className="text-sm text-rose-600">{error}</p>}

      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-400">
          {answeredTotal} answered · progress saves as you go
        </p>
        <button
          onClick={() => void saveAndAdvance()}
          disabled={busy}
          className="bg-primary-600 text-white rounded-lg px-5 py-2 text-sm disabled:opacity-50"
          data-testid="advance-phase"
        >
          {busy ? "Working…" : state.phase_one_form ? "Start scenarios →" : "Save & continue →"}
        </button>
      </div>
    </div>
  );
}

function QuestionCard({
  question,
  value,
  assist,
  onChange,
  onAsk,
}: {
  question: AssessmentQuestion;
  value: Record<string, unknown> | null | undefined;
  assist?: string;
  onChange: (answer: Record<string, unknown> | null) => void;
  onAsk: () => void;
}) {
  const answered = value != null && Object.keys(value).length > 0;
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4" data-testid="question-card">
      <div className="flex items-start justify-between gap-2">
        <p className="font-medium text-sm">{question.prompt}</p>
        <button onClick={onAsk} className="text-xs text-primary-700 shrink-0 hover:underline">
          Ask
        </button>
      </div>
      {question.help && <p className="text-xs text-slate-400 mt-0.5">{question.help}</p>}
      {assist && <p className="text-xs bg-primary-50 border border-primary-100 rounded-lg p-2 mt-2 text-slate-600">{assist}</p>}

      {question.kind === "scenario_mcq" && (
        <div className="mt-3 space-y-2">
          {question.options.map((option) => {
            const selected = (value as { option_id?: string } | null)?.option_id === option.id;
            return (
              <button
                key={option.id}
                onClick={() => onChange({ option_id: option.id })}
                className={`w-full text-left border rounded-lg px-3 py-2 text-sm transition ${
                  selected ? "border-primary-500 bg-primary-50" : "border-slate-200 hover:border-primary-300"
                }`}
              >
                <span className="font-medium">{option.label}</span>
                {option.detail && <span className="text-slate-500"> — {option.detail}</span>}
              </button>
            );
          })}
        </div>
      )}

      {question.kind === "time_allocation" && (
        <AllocationSliders
          options={question.options}
          value={value as { weights?: Record<string, number> } | null}
          onChange={onChange}
        />
      )}

      {question.kind === "ranking" && (
        <RankList
          options={question.options}
          value={value as { order?: string[] } | null}
          onChange={onChange}
        />
      )}

      {question.kind === "slider" && (
        <div className="mt-3 flex items-center gap-3">
          <ScaleSlider
            value={((value as { value?: number } | null)?.value ?? 5) as number}
            min={1}
            max={10}
            ariaLabel={question.prompt}
            onChange={(v) => onChange({ value: typeof v === "number" ? v : 5 })}
          />
          <span className="text-sm text-slate-500 w-8">
            {((value as { value?: number } | null)?.value ?? 5)}
          </span>
        </div>
      )}

      <p className="text-xs mt-2">
        {answered ? (
          <span className="text-emerald-600">saved ✓</span>
        ) : (
          <button onClick={() => onChange({})} className="text-slate-400 hover:text-slate-600">
            skip this one
          </button>
        )}
      </p>
    </div>
  );
}

function AllocationSliders({
  options,
  value,
  onChange,
}: {
  options: AssessmentQuestion["options"];
  value: { weights?: Record<string, number> } | null;
  onChange: (answer: Record<string, unknown> | null) => void;
}) {
  const weights = value?.weights ?? {};
  const total = options.reduce((acc, o) => acc + (weights[o.id] ?? 0), 0);
  const setWeight = (id: string, v: number) => {
    onChange({ weights: { ...weights, [id]: v } });
  };
  return (
    <div className="mt-3 space-y-2">
      {options.map((option) => (
        <div key={option.id} className="flex items-center gap-2">
          <span className="text-xs text-slate-500 w-40 shrink-0">{option.label}</span>
          <input
            type="number"
            min={0}
            max={100}
            value={weights[option.id] ?? 0}
            onChange={(e) => setWeight(option.id, Math.max(0, Math.min(100, Number(e.target.value))))}
            className="w-16 border border-slate-200 rounded-lg px-2 py-1 text-sm"
          />
          <span className="text-xs text-slate-400">%</span>
        </div>
      ))}
      <p className={`text-xs ${total === 100 ? "text-emerald-600" : "text-slate-400"}`}>
        total: {total}% (must be 100)
      </p>
    </div>
  );
}

function RankList({
  options,
  value,
  onChange,
}: {
  options: AssessmentQuestion["options"];
  value: { order?: string[] } | null;
  onChange: (answer: Record<string, unknown> | null) => void;
}) {
  const [order, setOrder] = useState<string[]>(
    value?.order ?? options.map((o) => o.id),
  );
  const label = (id: string) => options.find((o) => o.id === id)?.label ?? id;
  const move = (index: number, delta: number) => {
    const next = [...order];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setOrder(next);
    onChange({ order: next });
  };
  return (
    <ul className="mt-3 space-y-1.5">
      {order.map((id, index) => (
        <li key={id} className="flex items-center gap-2 border border-slate-200 rounded-lg px-3 py-1.5 text-sm">
          <span className="text-slate-400">{index + 1}.</span>
          <span className="flex-1">{label(id)}</span>
          <button onClick={() => move(index, -1)} aria-label="move up" className="text-slate-400 hover:text-primary-700">↑</button>
          <button onClick={() => move(index, 1)} aria-label="move down" className="text-slate-400 hover:text-primary-700">↓</button>
        </li>
      ))}
    </ul>
  );
}
