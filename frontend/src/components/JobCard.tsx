import { Bookmark, Compass } from "lucide-react";
import { DemandBadge } from "./DemandBadge";
import type { Job } from "@/types";

export const EDUCATION_CHIP: Record<string, string> = {
  no_formal: "No formal",
  middle_school: "Middle school",
  high_school: "High school",
  vocational: "Vocational",
  bachelor: "Bachelor's",
  master: "Master's",
  doctorate: "Doctorate",
};

export function JobCard({
  job,
  onSelect,
  seen = false,
  saved = false,
  notes,
  exploration = false,
}: {
  job: Job;
  onSelect?: (job: Job) => void;
  seen?: boolean;
  saved?: boolean;
  notes?: string;
  exploration?: boolean;
}) {
  const education = job.attributes?.education?.level;
  return (
    <button
      type="button"
      data-testid="job-card"
      onClick={() => onSelect?.(job)}
      className={`text-left w-full bg-white border rounded-xl p-4 hover:border-primary-500 hover:shadow-sm transition ${
        seen ? "border-slate-100 opacity-75" : "border-slate-200"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-medium text-slate-900">
          {job.title}
          {seen && (
            <span className="ml-2 text-[10px] uppercase tracking-wide text-slate-400 font-normal">
              seen
            </span>
          )}
        </h3>
        <div className="flex items-center gap-1.5 shrink-0">
          {saved && <Bookmark className="w-3.5 h-3.5 text-primary-600 fill-primary-600" />}
          <DemandBadge outlook={job.attributes?.demand?.outlook} />
        </div>
      </div>
      <p className="mt-1 text-sm text-slate-500 line-clamp-2">{job.short_description}</p>
      {notes && (
        <p className="mt-1 text-xs text-slate-400 italic line-clamp-1" data-testid="job-card-notes">
          {notes}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-1">
        {education && (
          <span
            className="text-xs bg-primary-50 text-primary-700 px-2 py-0.5 rounded"
            data-testid="education-chip"
          >
            {EDUCATION_CHIP[education] ?? education}
          </span>
        )}
        {(job.interests ?? []).slice(0, 4).map((interest) => (
          <span key={interest.key} className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded">
            {interest.label}
          </span>
        ))}
        {exploration && (
          <span className="text-xs bg-amber-50 text-amber-700 px-2 py-0.5 rounded flex items-center gap-1">
            <Compass className="w-3 h-3" /> explore
          </span>
        )}
      </div>
    </button>
  );
}
