import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Plus } from "lucide-react";
import { addAdmission, addDepartment, fetchUniversity } from "@/api/universities";
import { DeadlineCalendar, type Deadline } from "@/components/DeadlineCalendar";
import { Button, DatePicker, EmptyState, Modal, ModalContent, ModalHeader, ModalTitle, ModalFooter, Table } from "@/components/ui";
import { apiDetail } from "@/api/client";
import type { UniversityDetail } from "@/types";

export function UniversityDetail() {
  const { id = "" } = useParams();
  const [university, setUniversity] = useState<UniversityDetail | null>(null);
  const [error, setError] = useState("");
  const [addOpen, setAddOpen] = useState(false);

  useEffect(() => {
    void fetchUniversity(id)
      .then(setUniversity)
      .catch((err) => setError(apiDetail(err)));
  }, [id]);

  const deadlines: Deadline[] = useMemo(() => {
    if (!university) return [];
    return university.departments
      .filter((d) => d.application_deadline)
      .map((d) => ({ date: d.application_deadline as string, label: `Apply: ${d.name}` }));
  }, [university]);

  if (error) return <p className="text-rose-600">{error}</p>;
  if (!university) return <p className="text-slate-400">Loading…</p>;

  return (
    <div className="max-w-5xl mx-auto space-y-6" data-testid="university-detail">
      <div>
        <Link to="/universities" className="text-sm text-slate-400 hover:text-slate-600 inline-flex items-center gap-1">
          <ArrowLeft className="w-3.5 h-3.5" /> All universities
        </Link>
        <div className="flex items-start justify-between mt-2">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">{university.name}</h1>
            <p className="text-slate-500">
              {[university.city, university.country].filter(Boolean).join(", ")} · {university.university_type}
            </p>
          </div>
          <Button size="sm" onClick={() => setAddOpen(true)}>
            <Plus className="w-4 h-4" /> Add department
          </Button>
        </div>
      </div>

      <div className="grid lg:grid-cols-[1fr_320px] gap-6">
        <section className="space-y-4">
          {university.departments.length === 0 ? (
            <EmptyState
              title="No departments yet"
              description="Add a department manually, or upload an admissions PDF on the Universities page — the AI extracts departments and baselines for you."
            />
          ) : (
            university.departments.map((d) => (
              <div key={d.id} className="bg-white border border-slate-200 rounded-xl overflow-hidden">
                <div className="px-4 py-3 flex items-center justify-between border-b border-slate-100">
                  <div>
                    <p className="font-medium">{d.name}</p>
                    <p className="text-sm text-slate-500">
                      {d.degree} · {d.duration_years} years
                      {d.language ? ` · ${d.language}` : ""}
                      {d.application_deadline && (
                        <span className="text-amber-700"> · deadline {d.application_deadline}</span>
                      )}
                    </p>
                  </div>
                  {d.field_key && (
                    <span className="text-xs bg-slate-100 text-slate-600 px-2 py-1 rounded">{d.field_key}</span>
                  )}
                </div>
                <Table
                  headers={["Year", "Baseline", "Top", "Quota", "Source"]}
                  emptyText="No admission baselines recorded"
                  rows={d.admissions
                    .slice()
                    .sort((a, b) => b.year - a.year)
                    .map((a) => [
                      String(a.year),
                      a.baseline_score != null ? String(a.baseline_score) : "–",
                      a.top_score != null ? String(a.top_score) : "–",
                      a.quota != null ? String(a.quota) : "–",
                      a.source,
                    ])}
                />
              </div>
            ))
          )}
        </section>

        <aside>
          <DeadlineCalendar deadlines={deadlines} />
          <p className="text-xs text-slate-400 mt-2">
            Amber days are application deadlines extracted from your documents (or added manually).
          </p>
        </aside>
      </div>

      <AddDepartmentModal
        isOpen={addOpen}
        universityId={university.id}
        onClose={() => setAddOpen(false)}
        onSaved={(u) => {
          setUniversity(u);
          setAddOpen(false);
        }}
      />
    </div>
  );
}

function AddDepartmentModal({
  isOpen,
  universityId,
  onClose,
  onSaved,
}: {
  isOpen: boolean;
  universityId: string;
  onClose: () => void;
  onSaved: (u: UniversityDetail) => void;
}) {
  const [name, setName] = useState("");
  const [fieldKey, setFieldKey] = useState("");
  const [deadline, setDeadline] = useState("");
  const [baseline, setBaseline] = useState("");
  const [year, setYear] = useState(String(new Date().getFullYear()));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const dept = await addDepartment(universityId, {
        name,
        field_key: fieldKey,
        application_deadline: deadline || null,
      } as never);
      if (baseline && year) {
        await addAdmission(dept.id, {
          year: Number(year),
          baseline_score: Number(baseline),
          units: "points",
        });
      }
      onSaved(await fetchUniversity(universityId));
      setName("");
      setFieldKey("");
      setDeadline("");
      setBaseline("");
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={isOpen} onOpenChange={(o) => !o && onClose()}>
      <ModalContent size="md" aria-describedby={undefined}>
        <ModalHeader>
          <ModalTitle>Add department</ModalTitle>
        </ModalHeader>
        <div className="space-y-4 px-6 pb-6">
          <label className="block text-sm">
            Name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="School of Computing"
              className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
            />
          </label>
          <label className="block text-sm">
            Field key
            <input
              value={fieldKey}
              onChange={(e) => setFieldKey(e.target.value)}
              placeholder="computer-science"
              className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
            />
          </label>
          <div className="text-sm">
            Application deadline
            <div className="mt-1">
              <DatePicker value={deadline} onChange={setDeadline} allowClear placeholder="Pick a date…" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm">
              Baseline score
              <input
                value={baseline}
                onChange={(e) => setBaseline(e.target.value)}
                placeholder="82.5"
                className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-sm">
              Year
              <input
                value={year}
                onChange={(e) => setYear(e.target.value)}
                className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm"
              />
            </label>
          </div>
          {error && <p className="text-sm text-rose-600">{error}</p>}
        </div>
        <ModalFooter>
          <Button variant="secondary" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button size="sm" onClick={() => void save()} disabled={busy || name.trim().length < 2}>
            {busy ? "Saving…" : "Save department"}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
