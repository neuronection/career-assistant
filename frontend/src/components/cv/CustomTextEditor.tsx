import { useRef, useState } from "react";
import { Bold, Italic, Link2, List, ChevronDown } from "lucide-react";

const MAX_TEXT = 2000;

interface CustomTextEditorProps {
  value: string;
  onChange: (text: string) => void;
}

function transform(
  value: string,
  start: number,
  end: number,
  mode: "bold" | "italic" | "link" | "bullet"
): { value: string; start: number; end: number } {
  const selected = value.slice(start, end);
  if (mode === "bold" || mode === "italic") {
    const marker = mode === "bold" ? "**" : "*";
    const already =
      value.slice(start - marker.length, start) === marker &&
      value.slice(end, end + marker.length) === marker;
    if (already) {
      return {
        value: value.slice(0, start - marker.length) + selected + value.slice(end + marker.length),
        start: start - marker.length,
        end: end - marker.length,
      };
    }
    return {
      value: value.slice(0, start) + marker + selected + marker + value.slice(end),
      start: start + marker.length,
      end: end + marker.length,
    };
  }
  if (mode === "link") {
    const label = selected || "text";
    const snippet = `[${label}](https://)`;
    return {
      value: value.slice(0, start) + snippet + value.slice(end),
      start: start + label.length + 3,
      end: start + snippet.length - 1,
    };
  }
  const lineStart = value.lastIndexOf("\n", start - 1) + 1;
  const lines = value.slice(lineStart, end).split("\n");
  const allBulleted = lines.every((line) => line.trim() === "" || line.startsWith("- "));
  const transformed = lines
    .map((line) => {
      if (line.trim() === "") return line;
      return allBulleted ? line.slice(2) : `- ${line}`;
    })
    .join("\n");
  return {
    value: value.slice(0, lineStart) + transformed + value.slice(end),
    start: lineStart,
    end: lineStart + transformed.length,
  };
}

const TOOLS: { id: "bold" | "italic" | "link" | "bullet"; label: string; icon: typeof Bold }[] = [
  { id: "bold", label: "Bold (**bold**)", icon: Bold },
  { id: "italic", label: "Italic (*italic*)", icon: Italic },
  { id: "link", label: "Link ([text](url))", icon: Link2 },
  { id: "bullet", label: "Bullet line (- )", icon: List },
];

export function CustomTextEditor({ value, onChange }: CustomTextEditorProps) {
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const [caret, setCaret] = useState<[number, number]>([0, 0]);

  const apply = (mode: "bold" | "italic" | "link" | "bullet") => {
    const area = areaRef.current;
    if (!area) return;
    const start = area.selectionStart;
    const end = area.selectionEnd;
    const result = transform(value, start, end, mode);
    if (result.value.length > MAX_TEXT) return;
    onChange(result.value);
    setCaret([result.start, result.end]);
    requestAnimationFrame(() => {
      area.focus();
      area.setSelectionRange(result.start, result.end);
    });
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (!(event.ctrlKey || event.metaKey)) return;
    const key = event.key.toLowerCase();
    if (key === "b") {
      event.preventDefault();
      apply("bold");
    } else if (key === "i") {
      event.preventDefault();
      apply("italic");
    }
  };

  return (
    <div className="space-y-1.5 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface-raised)] p-2">
      <div className="flex flex-wrap items-center gap-1" role="toolbar" aria-label="Text formatting">
        {TOOLS.map((tool) => (
          <button
            key={tool.id}
            type="button"
            title={tool.label}
            aria-label={tool.label}
            onClick={() => apply(tool.id)}
            data-testid={`md-tool-${tool.id}`}
            className="cursor-pointer rounded-md p-1.5 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)]"
          >
            <tool.icon className="h-3.5 w-3.5" aria-hidden />
          </button>
        ))}
        <span className="ml-auto text-[10px] tabular-nums text-[var(--as-muted-fg)]" data-testid="custom-text-counter">
          {value.length}/{MAX_TEXT}
        </span>
      </div>
      <textarea
        ref={areaRef}
        value={value}
        maxLength={MAX_TEXT}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        onSelect={(event) => {
          const target = event.currentTarget;
          setCaret([target.selectionStart, target.selectionEnd]);
        }}
        rows={5}
        aria-label="Section text"
        data-testid="custom-text-editor"
        className="w-full resize-y rounded-md border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-sm leading-relaxed outline-none transition-colors focus:border-[var(--as-accent)]"
      />
      <p className="text-[10px] leading-snug text-[var(--as-muted-fg)]">
        Markdown-lite: <code>**bold**</code>, <code>*italic*</code>, <code>[text](https://url)</code>,{" "}
        <code>- bullet</code> lines, blank line = new paragraph. Rendered safely in every export.
        {" "}
        {caret[0] !== caret[1] ? `${caret[1] - caret[0]} characters selected` : ""}
      </p>
    </div>
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
