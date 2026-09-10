import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui";
import { FormRow, TextField, ToggleRow, TextareaField } from "@/components/cv/formPrimitives";

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
        label="Recipient name"
        value={letter.recipient_name ?? ""}
        onChange={(value) => onChange({ recipient_name: value })}
        maxLength={120}
        testId="letter-recipient-name"
      />
      <TextField
        label="Recipient organisation"
        value={letter.recipient_org ?? ""}
        onChange={(value) => onChange({ recipient_org: value })}
        maxLength={120}
        testId="letter-recipient-org"
      />
      <TextField
        label="Date line"
        value={letter.date_label ?? ""}
        onChange={(value) => onChange({ date_label: value })}
        maxLength={40}
        placeholder="e.g. September 2026"
        testId="letter-date"
      />
      <TextField
        label="Subject"
        value={letter.subject ?? ""}
        onChange={(value) => onChange({ subject: value })}
        maxLength={200}
        testId="letter-subject"
      />
      <TextField
        label="Salutation"
        value={letter.salutation ?? ""}
        onChange={(value) => onChange({ salutation: value })}
        maxLength={80}
        testId="letter-salutation"
      />

      <div className="space-y-2">
        {paragraphs.map((text, index) => (
          <FormRow key={index} testId={`letter-para-${index}`}>
            <TextareaField
              label={`Paragraph ${index + 1}`}
              value={text}
              onChange={(value) => setParagraph(index, value)}
              rows={4}
              maxLength={2000}
              counter
              testId={`letter-para-input-${index}`}
            />
            <div className="flex gap-1">
              <Button
                variant="ghost"
                size="sm"
                aria-label={`Move paragraph ${index + 1} up`}
                disabled={index === 0}
                onClick={() => moveParagraph(index, -1)}
                data-testid={`letter-para-up-${index}`}
              >
                <ArrowUp className="h-3.5 w-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                aria-label={`Move paragraph ${index + 1} down`}
                disabled={index === paragraphs.length - 1}
                onClick={() => moveParagraph(index, 1)}
                data-testid={`letter-para-down-${index}`}
              >
                <ArrowDown className="h-3.5 w-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                aria-label={`Remove paragraph ${index + 1}`}
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
          <Plus className="mr-1 h-3.5 w-3.5" /> Add paragraph
        </Button>
      </div>

      <TextField
        label="Closing"
        value={letter.closing ?? ""}
        onChange={(value) => onChange({ closing: value })}
        maxLength={80}
        testId="letter-closing"
      />
      <ToggleRow
        label="Sign with my name"
        checked={letter.show_signature !== false}
        onChange={(checked) => onChange({ show_signature: checked })}
      />
    </div>
  );
}
