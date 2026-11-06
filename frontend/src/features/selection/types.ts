/** Per-item bulk outcome, shared by every selection surface (plan 200). */
export interface BulkFailure {
  id: string;
  reason: string;
  /** Stable human key when the surface has one (a skill key, a job code). */
  key?: string;
}

export interface BulkOutcome {
  affected: string[];
  failed: BulkFailure[];
}
