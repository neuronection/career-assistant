import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui";
import { FormRow, TextField, ToggleRow } from "@/features/cv/components/cv/formPrimitives";
import { CvRichTextEditor } from "@/features/cv/components/cv/CvRichTextEditor";

export interface LetterProps {
  recipient_name?: string;
  recipient_org?: string;
  date_label?: string;
  subject?: string;
  salutation?: string;
  paragraphs?: string[];
  closing?: string;
  show_signature?: boolean;
  [key: string]: unknown;
}

export function letterPropsOf(blocks: { kind: string; props?: Record<string, unknown> }[]): {
  index: number;
  props: LetterProps;
} | null {
  const index = blocks.findIndex((block) => block.kind === "letter");
  if (index === -1) return null;
  return { index, props: (blocks[index].props ?? {}) as LetterProps };
}

export function LetterSectionsEditor({
  props: letter,
  onChange,
}: {
  props: LetterProps;
  onChange: (patch: Record<string, unknown>) => void;
}) {
  const { t } = useTranslation();
  const paragraphs = letter.paragraphs ?? [];

  const setParagraph = (index: number, text: string) =>
    onChange({
      paragraphs: paragraphs.map((value, position) => (position === index ? text : value)),
    });

  const moveParagraph = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= paragraphs.length) return;
    const next = [...paragraphs];
    [next[index], next[target]] = [next[target], next[index]];
    onChange({ paragraphs: next });
  };

  const removeParagraph = (index: number) =>
    onChange({ paragraphs: paragraphs.filter((_, position) => position !== index) });

  return (
    <div className="space-y-3" data-testid="letter-editor">
      <TextField
        label={t("cvBuilder.letter.recipientName")}
        value={letter.recipient_name ?? ""}
        onChange={(value) => onChange({ recipient_name: value })}
        maxLength={120}
        testId="letter-recipient-name"
      />
      <TextField
        label={t("cvBuilder.letter.recipientOrg")}
        value={letter.recipient_org ?? ""}
        onChange={(value) => onChange({ recipient_org: value })}
        maxLength={120}
        testId="letter-recipient-org"
      />
      <TextField
        label={t("cvBuilder.letter.dateLine")}
        value={letter.date_label ?? ""}
        onChange={(value) => onChange({ date_label: value })}
        maxLength={40}
        placeholder={t("cvBuilder.letter.datePlaceholder")}
        testId="letter-date"
      />
      <TextField
        label={t("cvBuilder.letter.subject")}
        value={letter.subject ?? ""}
        onChange={(value) => onChange({ subject: value })}
        maxLength={200}
        testId="letter-subject"
      />
      <TextField
        label={t("cvBuilder.letter.salutation")}
        value={letter.salutation ?? ""}
        onChange={(value) => onChange({ salutation: value })}
        maxLength={80}
        testId="letter-salutation"
      />

      <div className="space-y-2">
        {paragraphs.map((text, index) => (
          <FormRow key={index} testId={`letter-para-${index}`}>
            <CvRichTextEditor
              value={text}
              onChange={(value) => setParagraph(index, value)}
              ariaLabel={`Paragraph ${index + 1}`}
              testId={`letter-para-input-${index}`}
            />
            <div className="flex gap-1">
              <Button
                variant="ghost"
                size="sm"
                aria-label={t("cvBuilder.letter.moveUpAria", { n: index + 1 })}
                disabled={index === 0}
                onClick={() => moveParagraph(index, -1)}
                data-testid={`letter-para-up-${index}`}
              >
                <ArrowUp className="h-3.5 w-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                aria-label={t("cvBuilder.letter.moveDownAria", { n: index + 1 })}
                disabled={index === paragraphs.length - 1}
                onClick={() => moveParagraph(index, 1)}
                data-testid={`letter-para-down-${index}`}
              >
                <ArrowDown className="h-3.5 w-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                aria-label={t("cvBuilder.letter.removeAria", { n: index + 1 })}
                onClick={() => removeParagraph(index)}
                data-testid={`letter-para-remove-${index}`}
              >
                <Trash2 className="h-3.5 w-3.5 text-red-600" />
              </Button>
            </div>
          </FormRow>
        ))}
        <Button
          variant="outline"
          size="sm"
          className="w-full"
          onClick={() => onChange({ paragraphs: [...paragraphs, ""] })}
          data-testid="add-paragraph"
        >
          <Plus className="mr-1 h-3.5 w-3.5" /> {t("cvBuilder.letter.addParagraph")}
        </Button>
      </div>

      <TextField
        label={t("cvBuilder.letter.closing")}
        value={letter.closing ?? ""}
        onChange={(value) => onChange({ closing: value })}
        maxLength={80}
        testId="letter-closing"
      />
      <ToggleRow
        label={t("cvBuilder.letter.signWithName")}
        checked={letter.show_signature !== false}
        onChange={(checked) => onChange({ show_signature: checked })}
      />
    </div>
  );
}
