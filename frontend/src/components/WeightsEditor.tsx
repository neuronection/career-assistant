import { useState } from "react";
import { saveScoringWeights } from "@/api/matching";
import { ScaleSlider, Button } from "@/components/ui";
import { apiDetail } from "@/api/client";
import type { ScoringWeights } from "@/types";

const DIMENSIONS: { key: keyof ScoringWeights; label: string }[] = [
  { key: "skills", label: "Skills" },
  { key: "interests", label: "Interests & work style" },
  { key: "education", label: "Education" },
  { key: "experience", label: "Experience" },
  { key: "location", label: "Location" },
];

/** Inline fit-weight sliders (1–5); saving triggers a deterministic refit. */
export function WeightsEditor({
  initial,
  onSaved,
}: {
  initial: ScoringWeights;
  onSaved?: (weights: ScoringWeights) => void;
}) {
  const [weights, setWeights] = useState<ScoringWeights>(initial);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      await saveScoringWeights(weights);
      setSaved(true);
      onSaved?.(weights);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-2" data-testid="weights-editor">
      {DIMENSIONS.map(({ key, label }) => (
        <div key={key} className="flex items-center gap-3">
          <span className="text-xs text-slate-500 w-36 shrink-0">{label}</span>
          <div className="flex-1 min-w-0">
            <ScaleSlider
              value={weights[key]}
              min={1}
              max={5}
              ariaLabel={`${label} weight`}
              onChange={(v) => {
                setSaved(false);
                setWeights((w) => ({ ...w, [key]: typeof v === "number" ? v : w[key] }));
              }}
            />
          </div>
          <span className="text-xs text-slate-400 w-4 text-right">{weights[key]}</span>
        </div>
      ))}
      <div className="flex items-center gap-2 pt-1">
        <Button variant="secondary" onClick={() => void save()} disabled={saving}>
          {saving ? "Recomputing…" : "Save & refit"}
        </Button>
        {saved && <span className="text-xs text-emerald-600">Fit updated ✓</span>}
        {error && <span className="text-xs text-rose-600">{error}</span>}
      </div>
    </div>
  );
}
