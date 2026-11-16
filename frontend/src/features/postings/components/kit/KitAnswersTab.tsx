import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge, Button } from "@/components/ui";
import { apiDetail } from "@/api/client";
import { deleteAnswer, saveAnswer } from "@/api/profileAnswers";
import type { KitAnswerPrompt, PostingKit } from "@/types/wire";

/** The kit's answers tab (plan 212 S1.5): deterministic screening
 * prompts backed by the user's own saved answers. Saving is explicit —
 * no generated text, no auto-fill. */
export function KitAnswersTab({
  kit,
  onChanged,
}: {
  kit: PostingKit;
  onChanged?: () => void;
}) {
  const { t } = useTranslation();
  const [drafts, setDrafts] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      (kit.answers ?? []).map((row) => [row.key, row.saved_answer ?? ""]),
    ),
  );
  const [savedIds, setSavedIds] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      (kit.answers ?? [])
        .filter((row) => row.saved_answer_id != null)
        .map((row) => [row.key, row.saved_answer_id as string]),
    ),
  );
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setSavedIds(
      Object.fromEntries(
        (kit.answers ?? [])
          .filter((row) => row.saved_answer_id != null)
          .map((row) => [row.key, row.saved_answer_id as string]),
      ),
    );
    setDrafts((prev) => {
      const next = { ...prev };
      for (const row of kit.answers ?? []) {
        if ((next[row.key] ?? "") === "" && (row.saved_answer ?? "") !== "") {
          next[row.key] = row.saved_answer as string;
        }
      }
      return next;
    });
  }, [kit.answers]);

  async function save(prompt: KitAnswerPrompt) {
    const text = (drafts[prompt.key] ?? "").trim();
    if (text === "") return;
    setBusy(prompt.key);
    setError("");
    try {
      const row = await saveAnswer({
        question_key: prompt.key,
        question_text: prompt.prompt,
        answer_text: text,
      });
      setSavedIds((prev) => ({ ...prev, [prompt.key]: row.id }));
      setDrafts((prev) => ({ ...prev, [prompt.key]: row.answer_text }));
      onChanged?.();
    } catch (exc) {
      setError(apiDetail(exc));
    } finally {
      setBusy(null);
    }
  }

  async function clear(prompt: KitAnswerPrompt) {
    const id = savedIds[prompt.key];
    if (id === undefined) return;
    setBusy(prompt.key);
    setError("");
    try {
      await deleteAnswer(id);
      setSavedIds((prev) => {
        const next = { ...prev };
        delete next[prompt.key];
        return next;
      });
      setDrafts((prev) => ({ ...prev, [prompt.key]: "" }));
      onChanged?.();
    } catch (exc) {
      setError(apiDetail(exc));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-3 py-3" data-testid="kit-answers-tab">
      <p className="text-xs text-[var(--as-muted-fg)]">{t("applications.kit.answers.note")}</p>
      {error !== "" && (
        <p className="text-xs text-[var(--as-danger)]" role="alert" data-testid="kit-answers-error">
          {error}
        </p>
      )}
      <ul className="space-y-2">
        {(kit.answers ?? []).map((prompt) => {
          const saved = savedIds[prompt.key] != null;
          return (
            <li
              key={prompt.key}
              className="rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] p-3"
              data-testid={`kit-answer-${prompt.key}`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-[var(--as-fg)]">
                  {t(`applications.kit.answers.key.${prompt.key}`, {
                    defaultValue: prompt.prompt,
                  })}
                </span>
                <Badge
                  variant={saved ? "default" : "secondary"}
                  className="ml-auto"
                  data-testid={`kit-answer-state-${prompt.key}`}
                >
                  {saved
                    ? t("applications.kit.answers.saved")
                    : t("applications.kit.answers.notSaved")}
                </Badge>
              </div>
              <label className="mt-2 block">
                <span className="sr-only">{prompt.prompt}</span>
                <textarea
                  className="min-h-20 w-full rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-sm text-[var(--as-fg)]"
                  value={drafts[prompt.key] ?? ""}
                  placeholder={t("applications.kit.answers.placeholder")}
                  onChange={(event) =>
                    setDrafts((prev) => ({ ...prev, [prompt.key]: event.target.value }))
                  }
                  data-testid={`kit-answer-input-${prompt.key}`}
                />
              </label>
              <div className="mt-2 flex items-center gap-2">
                <Button
                  size="sm"
                  disabled={busy === prompt.key || (drafts[prompt.key] ?? "").trim() === ""}
                  onClick={() => void save(prompt)}
                  data-testid={`kit-answer-save-${prompt.key}`}
                >
                  {t("applications.kit.answers.save")}
                </Button>
                {saved && (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy === prompt.key}
                    onClick={() => void clear(prompt)}
                    data-testid={`kit-answer-clear-${prompt.key}`}
                  >
                    {t("applications.kit.answers.clear")}
                  </Button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
