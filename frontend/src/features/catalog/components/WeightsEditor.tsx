import { useState } from "react";
import { useTranslation } from "react-i18next";
import { saveScoringWeights } from "@/api/matching";
import { ScaleSlider, Button } from "@/components/ui";
import { apiDetail } from "@/api/client";
import type { ScoringWeights } from "@/types";

const DIMENSIONS: { key: keyof ScoringWeights; labelKey: string }[] = [
  { key: "skills", labelKey: "weightsEditor.dim.skills" },
  { key: "interests", labelKey: "weightsEditor.dim.interests" },
  { key: "values", labelKey: "weightsEditor.dim.values" },
  { key: "education", labelKey: "weightsEditor.dim.education" },
  { key: "experience", labelKey: "weightsEditor.dim.experience" },
  { key: "location", labelKey: "weightsEditor.dim.location" },
];

/** Inline fit-weight sliders (1–5); saving triggers a deterministic refit. */
export function WeightsEditor({
  initial,
  onSaved,
}: {
  initial: ScoringWeights;
  onSaved?: (weights: ScoringWeights) => void;
}) {
  const { t } = useTranslation();
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
      {DIMENSIONS.map(({ key, labelKey }) => {
        const label = t(labelKey);
        return (
          <div key={key} className="flex items-center gap-3">
            <span className="text-xs text-slate-500 w-36 shrink-0">{label}</span>
            <div className="flex-1 min-w-0">
              <ScaleSlider
                value={weights[key]}
                min={1}
                max={5}
                ariaLabel={t("shared.weightAria", { label })}
                onChange={(v) => {
                  setSaved(false);
                  setWeights((w) => ({ ...w, [key]: typeof v === "number" ? v : w[key] }));
                }}
              />
            </div>
            <span className="text-xs text-slate-400 w-4 text-right">{weights[key]}</span>
          </div>
        );
      })}
      <div className="flex items-center gap-2 pt-1">
        <Button variant="secondary" onClick={() => void save()} disabled={saving}>
          {saving ? t("weightsEditor.recomputing") : t("weightsEditor.saveRefit")}
        </Button>
        {saved && <span className="text-xs text-emerald-600">{t("weightsEditor.fitUpdated")}</span>}
        {error && <span className="text-xs text-rose-600">{error}</span>}
      </div>
    </div>
  );
}
