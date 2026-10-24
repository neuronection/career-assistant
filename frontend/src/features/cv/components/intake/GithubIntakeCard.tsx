import { useState } from "react";
import { Github, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import * as intakeApi from "@/api/githubIntake";
import type { GithubPreview } from "@/api/githubIntake";
import { apiDetail } from "@/api/client";
import { Button } from "@/components/ui";

// Profile → Import → GitHub (plan 122 phase 3): preview repositories, tick
// the ones worth keeping, create drafts. The review-first guarantee lives
// on the server — this card only ever asks for drafts.

export function GithubIntakeCard() {
  const { t } = useTranslation();
  const [login, setLogin] = useState("");
  const [preview, setPreview] = useState<GithubPreview | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [result, setResult] = useState("");

  const runPreview = async () => {
    setBusy(true);
    setNotice("");
    setResult("");
    try {
      const data = await intakeApi.previewGithubRepos(login.trim());
      setPreview(data);
      setSelected(new Set(data.repos.map((repo) => repo.index)));
    } catch (error) {
      setNotice(apiDetail(error));
      setPreview(null);
    } finally {
      setBusy(false);
    }
  };

  const toggle = (index: number) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const apply = async () => {
    if (!preview) return;
    setBusy(true);
    setNotice("");
    try {
      const applied = await intakeApi.applyGithubRepos(preview.login, [...selected]);
      setResult(
        t("profileImport.github.created", {
          created: applied.created,
          skipped: applied.skipped,
        }),
      );
      setPreview(null);
      setSelected(new Set());
    } catch (error) {
      setNotice(apiDetail(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4"
      data-testid="github-intake"
      aria-label={t("profileImport.github.title")}
    >
      <h2 className="flex items-center gap-2 text-sm font-semibold text-[var(--as-fg)]">
        <Github className="h-4 w-4" aria-hidden />
        {t("profileImport.github.title")}
      </h2>
      <p className="mt-1 text-sm text-[var(--as-muted-fg)]">{t("profileImport.github.hint")}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input
          className="w-full flex-1 rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] px-2 py-1.5 text-sm sm:w-auto"
          placeholder={t("profileImport.github.loginPlaceholder")}
          value={login}
          onChange={(event) => setLogin(event.target.value)}
          aria-label={t("profileImport.github.loginPlaceholder")}
        />
        <Button
          size="sm"
          variant="outline"
          disabled={busy || login.trim() === ""}
          onClick={() => void runPreview()}
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {t("profileImport.github.preview")}
        </Button>
      </div>
      {notice ? (
        <p className="mt-2 text-sm text-rose-600" data-testid="github-intake-error">
          {notice}
        </p>
      ) : null}
      {result ? (
        <p className="mt-2 text-sm text-emerald-600" data-testid="github-intake-result">
          {result}
        </p>
      ) : null}
      {preview ? (
        <div className="mt-3 space-y-2">
          {preview.repos.length === 0 ? (
            <p className="text-sm text-[var(--as-muted-fg)]">
              {t("profileImport.github.empty")}
            </p>
          ) : (
            <ul className="space-y-1">
              {preview.repos.map((repo) => (
                <li key={repo.index} className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={selected.has(repo.index)}
                    aria-label={repo.name}
                    onChange={() => toggle(repo.index)}
                  />
                  <span>
                    <span className="font-medium text-[var(--as-fg)]">{repo.name}</span>
                    {repo.language ? (
                      <span className="text-[var(--as-muted-fg)]"> · {repo.language}</span>
                    ) : null}
                    {repo.stars > 0 ? (
                      <span className="text-[var(--as-muted-fg)]">
                        {" · "}
                        {t("profileImport.github.stars", { count: repo.stars })}
                      </span>
                    ) : null}
                    {repo.description ? (
                      <span className="block text-xs text-[var(--as-muted-fg)]">
                        {repo.description}
                      </span>
                    ) : null}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" disabled={busy || selected.size === 0} onClick={() => void apply()}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {t("profileImport.github.createDrafts")}
            </Button>
            <span className="text-xs text-[var(--as-muted-fg)]">
              {t("profileImport.github.selected", { count: selected.size })}
            </span>
          </div>
        </div>
      ) : null}
    </section>
  );
}
