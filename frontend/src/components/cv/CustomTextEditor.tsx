import { ChevronDown } from "lucide-react";
import { CvRichTextEditor } from "@/components/cv/CvRichTextEditor";

export function CustomTextEditor({ value, onChange }: { value: string; onChange: (text: string) => void }) {
  return (
    <CvRichTextEditor
      value={value}
      onChange={onChange}
      ariaLabel="Section text"
      testId="custom-text-editor"
    />
  );
}

export function CustomTextToggle({
  open,
  onToggle,
}: {
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      aria-expanded={open}
      onClick={onToggle}
      data-testid="edit-custom-text"
      className="flex shrink-0 cursor-pointer items-center gap-1 rounded p-1 text-xs text-[var(--as-accent)] hover:bg-[var(--as-muted)]"
      title="Edit section text"
    >
      Edit
      <ChevronDown
        className={`h-3 w-3 transition-transform duration-200 ${open ? "" : "-rotate-90"}`}
        aria-hidden
      />
    </button>
  );
}
