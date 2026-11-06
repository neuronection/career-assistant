import type { Company, CompanyFacets } from "@/types/wire";

export interface CompaniesListSnapshot {
  companies: Company[];
  facets: CompanyFacets | null;
}

const snapshots = new Map<string, CompaniesListSnapshot>();
const MAX_SNAPSHOTS = 8;

export function peekCompaniesList(key: string): CompaniesListSnapshot | null {
  return snapshots.get(key) ?? null;
}

export function rememberCompaniesList(
  key: string,
  snapshot: CompaniesListSnapshot
): void {
  snapshots.delete(key);
  snapshots.set(key, snapshot);
  if (snapshots.size > MAX_SNAPSHOTS) {
    const oldest = snapshots.keys().next().value;
    if (oldest !== undefined) snapshots.delete(oldest);
  }
}

export function resetCompaniesListCache(): void {
  snapshots.clear();
}
