import { useTranslation } from "react-i18next";

import type { ChatMessage, ChatTemplatePreview } from "@/types";
import { useTemplatePreviewsStore } from "@/stores/templatePreviewsStore";

/**
 * Template preview thumbnails (plan 83): what the copilot compared.
 * During a turn the strip renders from the live store; afterwards the
 * persisted `metadata.template_previews` takes over, so history keeps
 * showing what the model saw.
 */
export function PreviewStrip({ previews }: { previews: ChatTemplatePreview[] }) {
  const { t } = useTranslation();
  if (previews.length === 0) {
    return null;
  }
  return (
    <div
      className="mt-1 flex w-full flex-wrap gap-2"
      data-testid="template-previews"
    >
      {previews.map((preview) => (
        <a
          key={preview.template_id}
          href={preview.url}
          target="_blank"
          rel="noreferrer"
          title={t("chat.previews.imageTitle", { title: preview.title })}
          className="group flex w-28 flex-col gap-1 rounded-[var(--as-radius)] border border-[var(--as-border)] bg-[var(--as-surface)] p-1 transition-colors hover:border-[var(--as-accent)]"
        >
          <img
            src={preview.url}
            alt={t("chat.previews.imageAlt", { title: preview.title })}
            className="aspect-[1/1.414] w-full rounded-sm object-cover object-top"
            loading="lazy"
          />
          <span className="truncate text-xs text-[var(--as-muted-fg)] group-hover:text-[var(--as-fg)]">
            {preview.title}
          </span>
        </a>
      ))}
    </div>
  );
}

export function MessageTemplatePreviews({ message }: { message: ChatMessage }) {
  const previews = message.metadata_json?.template_previews ?? [];
  return <PreviewStrip previews={previews} />;
}

export function LiveTemplatePreviews() {
  const live = useTemplatePreviewsStore((state) => state.live);
  return <PreviewStrip previews={live} />;
}
