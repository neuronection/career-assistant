import { api } from "./client";
import type {
  AchievementIn,
  AchievementOut,
  AchievementUpdate,
  CertificationIn,
  CertificationOut,
  CertificationUpdate,
  EducationItemIn,
  EducationItemOut,
  EducationItemUpdate,
} from "@/types/education";

export async function fetchEducation(): Promise<EducationItemOut[]> {
  const { data } = await api.get<EducationItemOut[]>("/me/education");
  return data;
}

export async function createEducationItem(
  body: EducationItemIn
): Promise<EducationItemOut> {
  const { data } = await api.post<EducationItemOut>("/me/education", body);
  return data;
}

export async function updateEducationItem(
  id: string,
  body: EducationItemUpdate
): Promise<EducationItemOut> {
  const { data } = await api.patch<EducationItemOut>(`/me/education/${id}`, body);
  return data;
}

export async function deleteEducationItem(id: string): Promise<void> {
  await api.delete(`/me/education/${id}`);
}

export async function fetchCertifications(): Promise<CertificationOut[]> {
  const { data } = await api.get<CertificationOut[]>("/me/certifications");
  return data;
}

export async function createCertification(
  body: CertificationIn
): Promise<CertificationOut> {
  const { data } = await api.post<CertificationOut>("/me/certifications", body);
  return data;
}

export async function updateCertification(
  id: string,
  body: CertificationUpdate
): Promise<CertificationOut> {
  const { data } = await api.patch<CertificationOut>(
    `/me/certifications/${id}`,
    body
  );
  return data;
}

export async function deleteCertification(id: string): Promise<void> {
  await api.delete(`/me/certifications/${id}`);
}

export async function fetchAchievements(): Promise<AchievementOut[]> {
  const { data } = await api.get<AchievementOut[]>("/me/achievements");
  return data;
}

export async function createAchievement(
  body: AchievementIn
): Promise<AchievementOut> {
  const { data } = await api.post<AchievementOut>("/me/achievements", body);
  return data;
}

export async function updateAchievement(
  id: string,
  body: AchievementUpdate
): Promise<AchievementOut> {
  const { data } = await api.patch<AchievementOut>(
    `/me/achievements/${id}`,
    body
  );
  return data;
}

export async function deleteAchievement(id: string): Promise<void> {
  await api.delete(`/me/achievements/${id}`);
}
