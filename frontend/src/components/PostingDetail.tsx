import { useEffect, useState } from "react";
import { ExternalLink, Quote } from "lucide-react";

import { fetchPostingDetail } from "@/api/postings";
import {
  Modal,
  ModalContent,
  ModalHeader,
  ModalTitle,
} from "@/components/ui";
import type { JobPostingItem, PostingExtractSkill } from "@/types";
const PRIORITY_STYLES: Record<string, string> = {
  must_have: "bg-rose-50 text-rose-700",
  nice_to_have: "bg-amber-50 text-amber-700",
  bonus: "bg-slate-100 text-slate-500",
};

/**
 * Level dots (1–10, filled = required level) — the repo-wide 1–10 scale
 * from plan 21's anchors.
 */
function LevelDots({ level }: { level: number }) {
  return (
    <span className="inline-flex gap-0.5" data-testid="skill-level-dots" aria-label={`level ${level}`}>
      {Array.from({ length: 10 }, (_, i) => (
        <span
          key={i}
          className={`w-1.5 h-1.5 rounded-full ${i < level ? "bg-primary-600" : "bg-slate-200"}`}
        />
      ))}
    </span>
  );
}

function SkillChip({ skill }: { skill: PostingExtractSkill }) {
  const [showQuote, setShowQuote] = useState(false);
  const label = skill.unresolved
    ? `${skill.raw_label ?? "unknown"} (unmapped)`
    : skill.skill_key ?? "unknown";
  return (
    <span className="inline-flex items-center gap-1.5 border border-slate-200 rounded-lg px-2 py-1 text-xs">
      <span className="font-medium text-slate-700">{label}</span>
      <LevelDots level={skill.required_level} />
      <span className={`px-1.5 py-0.5 rounded text-[10px] ${PRIORITY_STYLES[skill.priority]}`}>
        {skill.priority.replace(/_/g, " ")}
      </span>
      <button
        type="button"
        aria-label="Show evidence"
        title={skill.evidence_quote}
        onClick={() => setShowQuote((v) => !v)}
        className="text-slate-300 hover:text-primary-600"
      >
        <Quote className="w-3 h-3" />
      </button>
      {showQuote && (
        <em
          className="text-slate-400 border-l border-slate-200 pl-1.5 max-w-56"
          data-testid="skill-evidence"
        >
          “{skill.evidence_quote}”
        </em>
      )}
    </span>
  );
}

/**
 * Posting detail (plan 31): renders the structured extract — skill chips
 * with level dots + priority badges, responsibility time-splits, salary,
 * benefits, evidence quotes on tap — plus the provenance indicator
 * (raw → fast-mapped → extracted).
 */
export function PostingDetail({
  postingId,
  onClose,
}: {
  postingId: string;
  onClose: () => void;
}) {
  const [posting, setPosting] = useState<JobPostingItem | null>(null);
  const [activeId, setActiveId] = useState(postingId);

  useEffect(() => {
    setPosting(null);
    void fetchPostingDetail(activeId)
      .then(setPosting)
      .catch(() => setPosting(null));
  }, [activeId]);

  const setDetail = (ref: string) => setActiveId(ref);

  const extract = posting?.extract ?? null;
  const provenance =
    posting?.extract_version != null
      ? "extracted"
      : posting?.mapping_method
        ? "fast-mapped"
        : "raw";
  const match = posting?.match ?? null;

  return (
    <Modal open onOpenChange={(o) => !o && onClose()}>
      <ModalContent size="lg" aria-describedby={undefined}>
        <ModalHeader>
          <ModalTitle>
            {posting?.title ?? "Loading…"}
            {posting?.ref && (
              <span
                className="ml-2 text-xs font-mono text-slate-400 align-middle"
                title="Short reference — paste it into chat"
                data-testid="posting-ref"
              >
                {posting.ref}
              </span>
            )}
          </ModalTitle>
        </ModalHeader>
        {!posting ? (
          <p className="text-sm text-slate-400 p-4">Loading posting…</p>
        ) : (
          <div className="space-y-4 p-4 text-sm" data-testid="posting-detail">
          <div className="flex items-center gap-2 flex-wrap text-xs">
            <span
              className={`px-2 py-0.5 rounded ${
                provenance === "extracted"
                  ? "bg-emerald-50 text-emerald-700"
                  : "bg-slate-100 text-slate-500"
              }`}
              data-testid="provenance"
            >
              {provenance}
            </span>
            {posting.needs_review && (
              <span className="px-2 py-0.5 rounded bg-amber-50 text-amber-700" data-testid="needs-review">
                needs review
              </span>
            )}
            {posting.coverage != null && (
              <span className="px-2 py-0.5 rounded bg-primary-50 text-primary-700" data-testid="coverage">
                profile coverage {posting.coverage.toFixed(1)}/10
              </span>
            )}
            {posting.url && (
              <a
                href={posting.url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-primary-700 hover:underline"
              >
                <ExternalLink className="w-3 h-3" /> original posting
              </a>
            )}
          </div>

          <p className="text-slate-500">
            {posting.org}
            {posting.location?.city ? ` · ${posting.location.city}` : ""}
            {posting.onsite_policy ? ` · ${posting.onsite_policy}` : ""}
            {posting.salary_min != null
              ? ` · ${posting.salary_currency ?? ""} ${Number(posting.salary_min).toLocaleString()}${
                  posting.salary_max != null ? `–${Number(posting.salary_max).toLocaleString()}` : ""
                } / ${posting.salary_period ?? "year"}`
              : ""}
          </p>

          <div
            className="text-xs text-slate-400 border border-slate-100 bg-slate-50 rounded-lg px-3 py-2 flex flex-wrap gap-x-4 gap-y-1"
            data-testid="source-attribution"
          >
            <span>
              Source:{" "}
              <span className="text-slate-600">
                {posting.source_title || posting.source_key || posting.source_connector || "unknown"}
              </span>
            </span>
            {posting.source_synced_at && (
              <span>synced {new Date(posting.source_synced_at).toLocaleDateString()}</span>
            )}
            {posting.url && (
              <a
                href={posting.url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-primary-700 hover:underline"
              >
                <ExternalLink className="w-3 h-3" /> original listing
              </a>
            )}
          </div>

          {match && (
            <section className="border border-slate-100 rounded-xl p-3" data-testid="match-card">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-semibold text-slate-400 uppercase">Match score</h3>
                <span className="text-lg font-bold text-primary-700" data-testid="match-score">
                  {match.score.toFixed(1)}
                  <span className="text-xs text-slate-400 font-normal">/10</span>
                </span>
              </div>
              {match.estimate && (
                <p className="text-[11px] text-amber-600 mt-1" data-testid="match-estimate-note">
                  archetype estimate — deep extraction has not run for this posting yet
                </p>
              )}
              <div className="mt-2 space-y-1.5">
                {Object.entries(match.breakdown).map(([dim, entry]) => (
                  <div key={dim} className="flex items-center gap-2 text-xs">
                    <span className="w-28 shrink-0 text-slate-500">
                      {dim.replace(/_/g, " ")}
                    </span>
                    <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${entry.neutral ? "bg-slate-300" : "bg-primary-500"}`}
                        style={{ width: `${Math.min(100, entry.score * 10)}%` }}
                      />
                    </div>
                    <span className="w-8 text-right text-slate-600">{entry.score.toFixed(1)}</span>
                    <span className="w-10 text-right text-slate-300">×{entry.weight}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {extract?.skills && extract.skills.length > 0 && (
            <section>
              <h3 className="text-xs font-semibold text-slate-400 uppercase mb-1.5">Skills</h3>
              <div className="flex flex-wrap gap-2" data-testid="extract-skills">
                {extract.skills.map((skill, i) => (
                  <SkillChip key={`${skill.skill_key ?? skill.raw_label}-${i}`} skill={skill} />
                ))}
              </div>
            </section>
          )}

          {extract?.responsibilities && extract.responsibilities.length > 0 && (
            <section>
              <h3 className="text-xs font-semibold text-slate-400 uppercase mb-1.5">
                Responsibilities
              </h3>
              <ul className="space-y-1" data-testid="extract-responsibilities">
                {extract.responsibilities.map((r, i) => (
                  <li key={i} className="flex items-center gap-2 text-slate-600">
                    <span>{r.text}</span>
                    {r.time_pct != null && (
                      <span className="text-[10px] bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded">
                        {r.time_pct}% of time
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {(extract?.benefits?.length ?? 0) > 0 && (
            <section>
              <h3 className="text-xs font-semibold text-slate-400 uppercase mb-1.5">Benefits</h3>
              <div className="flex flex-wrap gap-1.5" data-testid="extract-benefits">
                {extract?.benefits?.map((benefit) => (
                  <span key={benefit} className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded">
                    {benefit}
                  </span>
                ))}
              </div>
            </section>
          )}

          {provenance !== "extracted" && (
            <p className="text-xs text-slate-400">
              Structured extraction has not run for this posting yet — filters by skill level
              ignore it until then.
            </p>
          )}

          {(posting.similar?.length ?? 0) > 0 && (
            <section>
              <h3 className="text-xs font-semibold text-slate-400 uppercase mb-1.5">
                Similar postings
              </h3>
              <div className="flex flex-col gap-1" data-testid="similar-rail">
                {posting?.similar?.map((s) => (
                  <button
                    key={s.ref}
                    onClick={() => setDetail(s.ref)}
                    className="text-left text-xs text-slate-600 hover:text-primary-700 flex items-center justify-between border border-slate-100 rounded-lg px-2 py-1.5"
                  >
                    <span>
                      <span className="font-mono text-slate-400 mr-1.5">{s.ref}</span>
                      {s.title} · {s.org}
                    </span>
                    <span className="text-slate-400">{Math.round(s.score * 100)}%</span>
                  </button>
                ))}
              </div>
            </section>
          )}
        </div>
      )}
      </ModalContent>
    </Modal>
  );
}
