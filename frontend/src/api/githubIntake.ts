import { api } from "./client";

// Profile → Import → GitHub (plan 122 phase 3): preview a public GitHub
// profile's repositories, then create DRAFT projects/achievements. Nothing
// is written until apply, and apply only ever writes drafts.

export type GithubRepo = {
  index: number;
  name: string;
  full_name: string;
  description: string;
  html_url: string;
  homepage: string;
  language: string;
  topics: string[];
  stars: number;
  forks: number;
  created_at: string | null;
  pushed_at: string | null;
  fork: boolean;
};

export type GithubPreview = {
  login: string;
  repos: GithubRepo[];
};

export type GithubApplyResult = {
  created: number;
  skipped: number;
  draft_ids: string[];
};

export async function previewGithubRepos(login: string): Promise<GithubPreview> {
  const { data } = await api.get<GithubPreview>("/me/intake/github/preview", {
    params: { login },
  });
  return data;
}

export async function applyGithubRepos(
  login: string,
  selections: number[],
): Promise<GithubApplyResult> {
  const { data } = await api.post<GithubApplyResult>("/me/intake/github/apply", {
    login,
    selections,
  });
  return data;
}
