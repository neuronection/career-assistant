import { useTranslation } from "react-i18next";
import { ProfileSectionCard } from "@/components/profile/ProfileSectionCard";
import { WeightsEditor } from "@/components/WeightsEditor";
import type { ScoringWeights } from "@/types";

export interface WeightsCardProps {
  initial?: ScoringWeights;
  onChanged?: () => void;
}

/** Fit-weight sliders (1–5 per dimension); saving recomputes job fits. */
export function WeightsCard({ initial, onChanged }: WeightsCardProps) {
  const { t } = useTranslation();
  if (!initial) return null;
  return (
    <ProfileSectionCard
      name="weights"
      title={t("profileSection.weightsTitle")}
      description={t("profileSection.weightsBody")}
    >
      <WeightsEditor initial={initial} onSaved={() => onChanged?.()} />
    </ProfileSectionCard>
  );
}
