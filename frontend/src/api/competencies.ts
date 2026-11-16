import { api } from "@/api/client";

type CompetencyKey =
  | "critical_thinking"
  | "communication"
  | "teamwork"
  | "digital_technology"
  | "leadership"
  | "professionalism"
  | "career_management"
  | "intercultural";

type CompetencyEvidenceKind =
  | "experience"
  | "achievement"
  | "skill"
  | "certification";

interface CompetencyEvidence {
  id: string;
  kind: CompetencyEvidenceKind;
  label: string;
  quote: string;
}

interface Competency {
  key: CompetencyKey;
  evidence: CompetencyEvidence[];
}

export interface Competencies {
  competencies: Competency[];
}

export async function fetchCompetencies(): Promise<Competencies> {
  const { data } = await api.get<Competencies>("/profile/competencies");
  return data;
}
