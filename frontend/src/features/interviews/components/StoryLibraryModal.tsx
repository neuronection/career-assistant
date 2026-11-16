import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Sparkles, Trash2 } from "lucide-react";

import {
  Button,
  ConfirmationModal,
  Modal,
  ModalContent,
  ModalHeader,
  ModalTitle,
} from "@/components/ui";
import { apiDetail } from "@/api/client";
import {
  createStory,
  deleteStory,
  fetchStories,
  fetchStorySuggestions,
  updateStory,
  type InterviewStory,
  type StorySuggestion,
} from "@/api/interviewStories";

const EMPTY = {
  id: null as string | null,
  title: "",
  competencies: "",
  situation: "",
  task: "",
  action: "",
  result: "",
  experience_item_id: null as string | null,
};

type Draft = typeof EMPTY;

export function StoryLibraryModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [stories, setStories] = useState<InterviewStory[]>([]);
  const [suggestions, setSuggestions] = useState<StorySuggestion[]>([]);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [pendingDelete, setPendingDelete] = useState<InterviewStory | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setError("");
    void Promise.all([fetchStories(), fetchStorySuggestions()])
      .then(([rows, hints]) => {
        setStories(rows);
        setSuggestions(hints);
      })
      .catch((err) => setError(apiDetail(err)));
  }, [open]);

  const reload = async () => {
    const [rows, hints] = await Promise.all([fetchStories(), fetchStorySuggestions()]);
    setStories(rows);
    setSuggestions(hints);
  };

  const edit = (story: InterviewStory) => {
    setDraft({
      id: story.id,
      title: story.title,
      competencies: story.competency_keys.join(", "),
      situation: story.situation,
      task: story.task,
      action: story.action,
      result: story.result,
      experience_item_id: story.experience_item_id,
    });
  };

  const save = async () => {
    if (draft.title.trim() === "") return;
    setBusy(true);
    setError("");
    const body = {
      title: draft.title.trim(),
      competency_keys: draft.competencies
        .split(",")
        .map((key) => key.trim())
        .filter(Boolean)
        .slice(0, 8),
      situation: draft.situation,
      task: draft.task,
      action: draft.action,
      result: draft.result,
      experience_item_id: draft.experience_item_id,
    };
    try {
      if (draft.id === null) await createStory(body);
      else await updateStory(draft.id, body);
      setDraft(EMPTY);
      await reload();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (story: InterviewStory) => {
    setBusy(true);
    try {
      await deleteStory(story.id);
      if (draft.id === story.id) setDraft(EMPTY);
      await reload();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  const applySuggestion = (hint: StorySuggestion) => {
    setDraft({
      ...EMPTY,
      title: hint.title,
      experience_item_id: hint.experience_item_id,
      situation: hint.hint,
    });
  };

  return (
    <Modal open={open} onOpenChange={(next) => !next && onClose()}>
      <ModalContent size="xl" aria-describedby={undefined} data-testid="story-library">
        <ModalHeader>
          <ModalTitle>{t("interviews.stories.title")}</ModalTitle>
        </ModalHeader>
        <div className="space-y-4">
          <p className="text-xs text-[var(--as-muted-fg)]">{t("interviews.stories.note")}</p>
          {error !== "" && (
            <p role="alert" className="text-sm text-[var(--as-danger)]" data-testid="story-error">
              {error}
            </p>
          )}

          <div className="space-y-2" data-testid="story-list">
            {stories.map((story) => (
              <div
                key={story.id}
                className="flex flex-wrap items-start gap-2 rounded-[var(--as-radius)] border border-[var(--as-border)] p-2"
                data-testid={`story-row-${story.id}`}
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-[var(--as-fg)]">{story.title}</p>
                  <p className="text-xs text-[var(--as-muted-fg)]">
                    {story.result || story.situation || "—"}
                  </p>
                </div>
                <Button size="sm" variant="ghost" onClick={() => edit(story)} data-testid={`story-edit-${story.id}`}>
                  {t("common.edit")}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setPendingDelete(story)}
                  data-testid={`story-delete-${story.id}`}
                  aria-label={t("interviews.stories.delete", { title: story.title })}
                >
                  <Trash2 className="size-3.5" aria-hidden />
                </Button>
              </div>
            ))}
            {stories.length === 0 && (
              <p className="text-xs text-[var(--as-muted-fg)]">{t("interviews.stories.empty")}</p>
            )}
          </div>

          {suggestions.length > 0 && (
            <div className="space-y-1" data-testid="story-suggestions">
              <p className="text-[10px] uppercase tracking-wide text-[var(--as-muted-fg)]">
                {t("interviews.stories.suggestions")}
              </p>
              {suggestions.slice(0, 5).map((hint) => (
                <button
                  key={hint.experience_item_id}
                  type="button"
                  className="flex w-full items-center gap-2 rounded border border-dashed border-[var(--as-border)] p-2 text-left text-xs hover:bg-[var(--as-muted)]"
                  onClick={() => applySuggestion(hint)}
                  data-testid={`story-suggestion-${hint.experience_item_id}`}
                >
                  <Sparkles className="size-3.5 shrink-0 text-[var(--as-accent)]" aria-hidden />
                  <span className="min-w-0 truncate">
                    {hint.title}
                    {hint.org ? ` · ${hint.org}` : ""}
                  </span>
                </button>
              ))}
            </div>
          )}

          <div className="space-y-2 rounded-[var(--as-radius)] border border-[var(--as-border)] p-3">
            <p className="text-sm font-medium text-[var(--as-fg)]">
              {draft.id === null ? t("interviews.stories.new") : t("interviews.stories.edit")}
            </p>
            <input
              value={draft.title}
              onChange={(event) => setDraft({ ...draft, title: event.target.value })}
              placeholder={t("interviews.stories.titlePlaceholder")}
              maxLength={200}
              className="w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-sm"
              data-testid="story-title"
              aria-label={t("interviews.stories.titlePlaceholder")}
            />
            <input
              value={draft.competencies}
              onChange={(event) => setDraft({ ...draft, competencies: event.target.value })}
              placeholder={t("interviews.stories.competenciesPlaceholder")}
              className="w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-sm"
              data-testid="story-competencies"
              aria-label={t("interviews.stories.competenciesPlaceholder")}
            />
            {(["situation", "task", "action", "result"] as const).map((field) => (
              <textarea
                key={field}
                value={draft[field]}
                onChange={(event) => setDraft({ ...draft, [field]: event.target.value })}
                placeholder={t(`interviews.stories.${field}`)}
                maxLength={2000}
                className="min-h-16 w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-sm"
                data-testid={`story-${field}`}
                aria-label={t(`interviews.stories.${field}`)}
              />
            ))}
            <div className="flex justify-end gap-2">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setDraft(EMPTY)}
                disabled={busy}
              >
                {t("common.cancel")}
              </Button>
              <Button
                size="sm"
                onClick={() => void save()}
                disabled={busy || draft.title.trim() === ""}
                data-testid="story-save"
              >
                <Plus className="mr-1 size-3.5" aria-hidden />
                {t("common.save")}
              </Button>
            </div>
          </div>
        </div>
      </ModalContent>

      <ConfirmationModal
        open={pendingDelete !== null}
        onOpenChange={(open) => !open && setPendingDelete(null)}
        title={t("interviews.stories.deleteTitle")}
        description={t("interviews.stories.deleteConfirm", {
          title: pendingDelete?.title ?? "",
        })}
        confirmLabel={t("common.delete")}
        destructive
        busy={busy}
        onConfirm={() => {
          const story = pendingDelete;
          setPendingDelete(null);
          if (story) void remove(story);
        }}
      />
    </Modal>
  );
}
