import { useState } from "react";
import { AlertTriangle, Briefcase, Check, MapPin, Sparkles } from "lucide-react";
import type { CoverLetterBriefOut } from "@/types/cv";

function LevelDots({ level }: { level: number }) {
  return (
    <span className="inline-flex gap-0.5" aria-label={`required level ${level}`}>
      {Array.from({ length: 10 }, (_, i) => (
        <span
          key={i}
          className={`h-1.5 w-1.5 rounded-full ${
            i < level ? "bg-[var(--as-accent)]" : "bg-[var(--as-border)]"
          }`}
        />
      ))}
    </span>
  );
}

function BriefSkillRow({
  skill,
  testId,
}: {
  skill: CoverLetterBriefOut["must_have"][number];
  testId: string;
}) {
  const [showQuote, setShowQuote] = useState(false);
  const covered = skill.user_level != null;
  return (
    <li
      className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] p-2"
      data-testid={testId}
    >
      <div className="flex items-center gap-1.5">
        {covered ? (
          <Check className="h-3 w-3 shrink-0 text-emerald-600" aria-label="covered" />
        ) : (
          <AlertTriangle className="h-3 w-3 shrink-0 text-amber-500" aria-label="missing" />
        )}
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-[var(--as-fg)]">
          {skill.label || skill.skill_key}
        </span>
        <LevelDots level={skill.required_level} />
      </div>
      {skill.evidence_quote && (
        <>
          <button
            type="button"
            onClick={() => setShowQuote((value) => !value)}
            aria-expanded={showQuote}
            className="mt-1 text-[10px] font-medium text-[var(--as-muted-fg)] underline-offset-2 hover:underline"
            data-testid={`${testId}-quote-toggle`}
          >
            {showQuote ? "Hide quote" : "Why? (quote)"}
          </button>
          {showQuote && (
            <em
              className="mt-1 block border-l-2 border-[var(--as-border)] pl-1.5 text-[11px] text-[var(--as-muted-fg)]"
              data-testid={`${testId}-quote`}
            >
              “{skill.evidence_quote}”
            </em>
          )}
        </>
      )}
    </li>
  );
}

export function LetterBriefPanel({
  brief,
  loading,
}: {
  brief: CoverLetterBriefOut | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="space-y-2 p-1" data-testid="letter-brief-loading">
        <div className="cv-shimmer h-5 w-3/4 rounded" />
        <div className="cv-shimmer h-16 rounded-lg" />
        <div className="cv-shimmer h-24 rounded-lg" />
      </div>
    );
  }
  if (!brief) {
    return (
      <p className="p-2 text-xs text-[var(--as-muted-fg)]" data-testid="letter-brief-empty">
        No target posting on this cover letter.
      </p>
    );
  }
  const covered = brief.coverage.covered.length;
  const missing = brief.coverage.missing.length;
  const fitPct = brief.fit.score != null ? Math.round(brief.fit.score * 10) : null;
  return (
    <div className="space-y-3 overflow-y-auto p-1" data-testid="letter-brief">
      <section>
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-[var(--as-fg)]">
          <Briefcase className="h-3.5 w-3.5 text-[var(--as-muted-fg)]" />
          {brief.posting_title}
        </h3>
        <p className="mt-0.5 text-xs text-[var(--as-muted-fg)]">
          {[brief.org, brief.location].filter(Boolean).join(" · ") || "Target posting"}
        </p>
      </section>

      {fitPct != null && (
        <section data-testid="brief-fit">
          <div className="flex items-center justify-between text-xs">
            <span className="text-[var(--as-muted-fg)]">Profile fit</span>
            <span className="font-semibold text-[var(--as-fg)]">
              {brief.fit.score?.toFixed(1)}/10
              {brief.fit.estimate && (
                <span className="ml-1 font-normal text-[var(--as-muted-fg)]">(est.)</span>
              )}
            </span>
          </div>
          <div className="mt-1 h-1.5 rounded-full bg-[var(--as-muted)]">
            <div
              className="h-1.5 rounded-full bg-[var(--as-accent)] transition-all duration-300"
              style={{ width: `${fitPct}%` }}
            />
          </div>
        </section>
      )}

      {brief.goal && (
        <section
          className="rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] p-2"
          data-testid="brief-goal"
        >
          <p className="flex items-start gap-1.5 text-xs text-[var(--as-fg)]">
            <Sparkles className="mt-0.5 h-3 w-3 shrink-0 text-[var(--as-accent)]" />
            {brief.goal}
          </p>
        </section>
      )}

      {brief.extract_ready ? (
        <section>
          <p className="mb-1.5 flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
            Must-haves
            <span className="font-normal normal-case">
              {covered} covered · {missing} missing
            </span>
          </p>
          <ul className="space-y-1.5">
            {brief.must_have.map((skill) => (
              <BriefSkillRow
                key={skill.skill_key}
                skill={skill}
                testId={`brief-skill-${skill.skill_key}`}
              />
            ))}
          </ul>
          {brief.must_have.length === 0 && (
            <p className="text-xs text-[var(--as-muted-fg)]">
              No must-have skills extracted for this posting.
            </p>
          )}
        </section>
      ) : (
        <section
          className="rounded-lg border border-[var(--as-border)] p-2 text-xs text-[var(--as-muted-fg)]"
          data-testid="brief-no-extract"
        >
          This posting has no deep extraction yet — the draft grounds on your
          profile evidence alone.
        </section>
      )}

      <p className="flex items-center gap-1.5 text-[11px] text-[var(--as-muted-fg)]">
        <MapPin className="h-3 w-3" />
        {brief.evidence_items} profile item{brief.evidence_items === 1 ? "" : "s"} feed the draft.
      </p>
    </div>
  );
}
