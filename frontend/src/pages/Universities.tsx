import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Building2, CheckCircle2, Circle, FileText, Upload } from "lucide-react";
import { applyDocument, fetchDocuments, fetchUniversities, uploadDocument, fetchUniversity } from "@/api/universities";
import type { BackgroundJob } from "@/api/backgroundJobs";
import { useBackgroundJob } from "@/hooks/useBackgroundJob";
import { apiDetail } from "@/api/client";
import { EmptyState } from "@/components/ui";
import type { DocumentRecord, University } from "@/types";

export function Universities() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [universities, setUniversities] = useState<University[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  const refresh = () => {
    void fetchDocuments().then(setDocuments);
    void fetchUniversities().then(setUniversities);
  };

  useEffect(() => {
    refresh();
  }, []);

  const onParseDone = (finished: BackgroundJob) => {
    setUploading(false);
    if (finished.status === "failed") {
      setError(finished.error ?? "Parsing failed");
    }
    refresh();
  };
  const { job: parseJob, track: trackParse } = useBackgroundJob(onParseDone);

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      const { job_id } = await uploadDocument(file);
      refresh();
      trackParse(job_id);
    } catch (err) {
      setError(apiDetail(err));
      setUploading(false);
    }
  };

  const apply = async (id: string) => {
    setError("");
    try {
      await applyDocument(id);
      refresh();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6" data-testid="universities">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Universities & admissions</h1>
        <p className="text-slate-500 mt-1">
          Upload your country&rsquo;s admissions/prospectus PDF. The AI extracts departments and yearly entry baselines,
          which then connect to jobs on each job page.
        </p>
      </div>

      <label className="block border-2 border-dashed border-slate-300 rounded-xl p-8 text-center cursor-pointer hover:border-primary-500 bg-white">
        <input type="file" accept=".pdf,.txt" className="hidden" onChange={(e) => void onFile(e.target.files?.[0])} />
        <Upload className="w-8 h-8 mx-auto text-slate-400" />
        <p className="mt-2 text-sm font-medium">
          {uploading ? "Uploading & parsing…" : "Drop a university catalog PDF or click to upload"}
        </p>
        <p className="text-xs text-slate-400">PDF or text, up to 25MB</p>
        {uploading && parseJob && (
          <div className="mt-3 max-w-xs mx-auto space-y-1" data-testid="parse-progress">
            <div className="h-2 w-full bg-slate-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-primary-500 transition-all duration-500"
                style={{ width: `${parseJob.progress}%` }}
              />
            </div>
            <p className="text-xs text-slate-400">{parseJob.stage ?? "queued…"}</p>
          </div>
        )}
      </label>
      {error && <p className="text-sm text-rose-600">{error}</p>}

      <section className="space-y-3">
        <h2 className="font-semibold">Your universities</h2>
        {universities.length === 0 ? (
          <EmptyState
            icon={Building2}
            compact
            title="No universities yet"
            description="Add them here by uploading an admissions PDF — departments and baselines are extracted automatically."
          />
        ) : (
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
            {universities.map((u) => (
              <Link
                key={u.id}
                to={`/universities/${u.id}`}
                className="bg-white border border-slate-200 rounded-xl p-4 hover:border-primary-400"
              >
                <p className="font-medium">{u.name}</p>
                <p className="text-sm text-slate-500">{[u.city, u.country].filter(Boolean).join(", ")}</p>
                <p className="text-xs text-slate-400 mt-1">{u.department_count} departments</p>
              </Link>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="font-semibold">Your documents</h2>
        {documents.length === 0 && <p className="text-sm text-slate-400">No documents uploaded yet.</p>}
        {documents.map((doc) => (
          <DocumentRow key={doc.id} doc={doc} onApply={() => void apply(doc.id)} />
        ))}
      </section>
    </div>
  );
}

function DocumentRow({ doc, onApply }: { doc: DocumentRecord; onApply: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const uniCount = doc.extraction?.universities.length ?? 0;

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4">
      <div className="flex items-center gap-3">
        <FileText className="w-5 h-5 text-slate-400" />
        <div className="flex-1">
          <p className="font-medium text-sm">{doc.filename}</p>
          <p className="text-xs text-slate-400">
            {doc.page_count} pages · {(doc.size_bytes / 1024).toFixed(0)} KB
          </p>
        </div>
        <StatusBadge status={doc.status} />
        {doc.status === "parsed" && (
          <button onClick={onApply} className="text-sm bg-emerald-600 text-white rounded-lg px-3 py-1.5">
            Apply to catalog
          </button>
        )}
        {uniCount > 0 && (
          <button onClick={() => setExpanded(!expanded)} className="text-sm text-primary-700">
            {expanded ? "Hide" : "Review"} extraction
          </button>
        )}
      </div>
      {doc.error && <p className="text-sm text-rose-600 mt-2">{doc.error}</p>}
      {expanded && doc.extraction && (
        <div className="mt-3 border-t border-slate-100 pt-3 space-y-3">
          {doc.extraction.universities.map((uni, i) => (
            <div key={i}>
              <p className="text-sm font-medium flex items-center gap-1">
                <CheckCircle2 className="w-4 h-4 text-emerald-500" /> {uni.name}
              </p>
              <ul className="ml-6 mt-1 space-y-1">
                {uni.departments.map((d, j) => (
                  <li key={j} className="text-sm text-slate-600 flex items-center gap-1">
                    <Circle className="w-3 h-3 text-slate-300" />
                    {d.name}
                    <span className="text-slate-400 text-xs">
                      {d.admissions.map((a) => `${a.year}: ${a.baseline_score ?? "?"}`).join(", ")}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: DocumentRecord["status"] }) {
  const styles: Record<string, string> = {
    uploaded: "bg-slate-100 text-slate-600",
    parsing: "bg-amber-100 text-amber-700 animate-pulse",
    parsed: "bg-sky-100 text-sky-700",
    applied: "bg-emerald-100 text-emerald-700",
    error: "bg-rose-100 text-rose-700",
  };
  return <span className={`text-xs px-2 py-1 rounded-full font-medium ${styles[status]}`}>{status}</span>;
}

export function UniversityDepartments({ universityId }: { universityId: string }) {
  const [detail, setDetail] = useState<Awaited<ReturnType<typeof fetchUniversity>> | null>(null);
  useEffect(() => {
    void fetchUniversity(universityId).then(setDetail);
  }, [universityId]);
  if (!detail) return null;
  return (
    <ul>
      {detail.departments.map((d: { id: string; name: string }) => (
        <li key={d.id}>{d.name}</li>
      ))}
    </ul>
  );
}
