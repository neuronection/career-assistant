import { useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { RichTextEditor } from "@neuronection/assistant-ui/rich-text-editor";

/**
 * CV-prose rich-text editor over the library `RichTextEditor`.
 *
 * Storage format is markdown — the bounded subset the CV pipeline
 * renders everywhere (**bold**, *italic*, [text](url), line breaks;
 * backend `normalize_rich_text` strips everything else on write). The
 * toolbar therefore offers exactly that subset: history + format, no
 * headings/lists/quotes. What you see formatted is what the CV prints.
 */
export function CvRichTextEditor({
  value,
  onChange,
  ariaLabel,
  disabled = false,
  minHeight = "min-h-32",
  testId,
}: {
  value: string;
  onChange: (markdown: string) => void;
  ariaLabel: string;
  disabled?: boolean;
  minHeight?: string;
  testId?: string;
}) {
  const { t } = useTranslation();
  const labels = useMemo(
    () => ({
      toolbar: t("cvBuilder.richText.toolbar"),
      bold: t("cvBuilder.richText.bold"),
      italic: t("cvBuilder.richText.italic"),
      strike: t("cvBuilder.richText.strike"),
      code: t("cvBuilder.richText.code"),
      undo: t("cvBuilder.toolbar.undo"),
      redo: t("cvBuilder.toolbar.redo"),
    }),
    [t]
  );
  const holderRef = useRef<HTMLDivElement>(null);
  return (
    <div
      ref={holderRef}
      data-testid={testId}
      data-rich-editor-holder=""
      className="[&_[data-as=rich-text-editor]]:w-full"
    >
      <RichTextEditor
        value={value}
        onValueChange={onChange}
        ariaLabel={ariaLabel}
        disabled={disabled}
        toolbar={["history", "format"]}
        labels={labels}
        contentClassName={`${minHeight} text-sm`}
        onReady={(editor) => {
          if (holderRef.current) {
            (holderRef.current as unknown as { __editor?: unknown }).__editor = editor;
          }
        }}
      />
      <p className="mt-1 text-[11px] text-[var(--as-muted-fg)]">
        {t("cvBuilder.richTextHint")}
      </p>
    </div>
  );
}
