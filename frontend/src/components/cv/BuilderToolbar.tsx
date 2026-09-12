import { useEffect, useState } from "react";
import {
  Activity,
  ChevronDown,
  Command,
  Download,
  History,
  NotebookPen,
  Redo2,
  Save,
  Sparkles,
  Undo2,
} from "lucide-react";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@neuronection/assistant-ui";
import { Button } from "@/components/ui";
import type { CvLintReport, CvVersionOut } from "@/types/cv";

export type AutosaveState = "idle" | "saving" | "saved" | "error";

const AUTOSAVE_LABELS: Record<AutosaveState, string> = {
  idle: "",
  saving: "Saving…",
  saved: "Saved",
  error: "Not saved",
};

export const EXPORT_FORMATS = ["pdf", "docx", "md", "json", "ats_text"] as const;
export type ExportFormat = (typeof EXPORT_FORMATS)[number];

const EXPORT_LABELS: Record<ExportFormat, string> = {
  pdf: "PDF",
  docx: "DOCX",
  md: "Markdown",
  json: "JSON",
  ats_text: "ATS text",
};

function TitleField({ title, onRename }: { title: string; onRename: (title: string) => void }) {
  const [draft, setDraft] = useState(title);

  useEffect(() => setDraft(title), [title]);

  const commit = () => {
    const next = draft.trim();
    if (!next || next === title) {
      setDraft(title);
      return;
    }
    onRename(next);
  };

  return (
    <input
      data-testid="cv-title-input"
      aria-label="CV title"
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") (event.target as HTMLInputElement).blur();
        if (event.key === "Escape") setDraft(title);
      }}
      className="-mx-1.5 w-full min-w-0 rounded-md border border-transparent px-1.5 py-0.5 text-xl font-semibold outline-none transition-colors duration-150 hover:border-[var(--as-border)] focus:border-[var(--as-accent)] focus:bg-[var(--as-surface)]"
    />
  );
}

interface BuilderToolbarProps {
  title: string;
  onRename: (title: string) => void;
  versions: CvVersionOut[];
  lint: CvLintReport | null;
  pages: number;
  maxPages: number;
  overflow: boolean;
  saveState: AutosaveState;
  saveBusy: boolean;
  exportBusy: string;
  canUndo: boolean;
  canRedo: boolean;
  onSaveVersion: () => void;
  onExport: (format: ExportFormat) => void;
  onOpenVersions: () => void;
  onOpenRuns: () => void;
  onOpenPolish: (() => void) | null;
  onOpenPalette: () => void;
  onOpenAssistant: () => void;
  onUndo: () => void;
  onRedo: () => void;
}

export function BuilderToolbar({
  title,
  onRename,
  versions,
  lint,
  pages,
  maxPages,
  overflow,
  saveState,
  saveBusy,
  exportBusy,
  canUndo,
  canRedo,
  onSaveVersion,
  onExport,
  onOpenVersions,
  onOpenRuns,
  onOpenPolish,
  onOpenPalette,
  onOpenAssistant,
  onUndo,
  onRedo,
}: BuilderToolbarProps) {
  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-2"
      data-testid="builder-toolbar"
    >
      <div className="min-w-40 max-w-xs flex-1 basis-52">
        <TitleField title={title} onRename={onRename} />
        <p className="flex items-center gap-1.5 px-1.5 text-xs text-[var(--as-muted-fg)]">
          <span>
            {versions.length > 0
              ? `${versions.length} version(s) · latest v${versions[0].version}`
              : "no versions yet"}
          </span>
          {saveState !== "idle" && (
            <span
              data-testid="autosave-indicator"
              className={`inline-flex items-center gap-1 ${
                saveState === "error" ? "text-[var(--as-danger)]" : ""
              }`}
            >
              <span
                aria-hidden
                className={`inline-block h-1.5 w-1.5 rounded-full ${
                  saveState === "saving"
                    ? "animate-pulse bg-[var(--as-accent)]"
                    : saveState === "saved"
                      ? "bg-[var(--as-success)]"
                      : "bg-[var(--as-danger)]"
                }`}
              />
              {AUTOSAVE_LABELS[saveState]}
            </span>
          )}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {lint && (
          <span
            className={`rounded-full px-2 py-1 text-xs font-medium ${
              lint.passed
                ? "bg-emerald-100 text-emerald-800"
                : "bg-amber-100 text-amber-800"
            }`}
            title={`ATS lint score ${lint.score}`}
            data-testid="ats-chip"
          >
            ATS {lint.score}
          </span>
        )}
        <span
          className={`rounded-full px-2 py-1 text-xs font-medium ${
            overflow ? "bg-red-100 text-red-800" : "bg-[var(--as-muted)]"
          }`}
          title={overflow ? "Content exceeds the page budget" : "Estimated page usage"}
        >
          ~{pages}/{maxPages} page{maxPages > 1 ? "s" : ""}
          {overflow ? " — over budget" : ""}
        </span>

        <Button variant="outline" size="sm" onClick={onOpenPalette} data-testid="open-palette" title="Command palette (Ctrl+K)">
          <Command className="mr-1 h-4 w-4" /> Ctrl+K
        </Button>
        <Button size="sm" onClick={onOpenAssistant} data-testid="cv-ask-ai" title="Ask the CV assistant">
          <Sparkles className="mr-1 h-4 w-4" /> Ask AI
        </Button>
        <Button variant="outline" size="icon" onClick={onUndo} disabled={!canUndo} data-testid="undo" title="Undo (Ctrl+Z)" aria-label="Undo">
          <Undo2 className="h-4 w-4" />
        </Button>
        <Button variant="outline" size="icon" onClick={onRedo} disabled={!canRedo} data-testid="redo" title="Redo (Ctrl+Shift+Z)" aria-label="Redo">
          <Redo2 className="h-4 w-4" />
        </Button>
        <Button variant="outline" size="sm" onClick={onOpenVersions} data-testid="open-versions">
          <History className="mr-1 h-4 w-4" /> Versions
          {versions.length > 0 ? ` (${versions.length})` : ""}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={onOpenRuns}
          data-testid="open-runs"
          title="Runs & metrics"
        >
          <Activity className="mr-1 h-4 w-4" /> AI runs
        </Button>
        {onOpenPolish && (
          <Button
            variant="outline"
            size="sm"
            onClick={onOpenPolish}
            data-testid="open-polish"
            title="AI polish review log"
          >
            <NotebookPen className="mr-1 h-4 w-4" /> Notes
          </Button>
        )}

        <Menu>
          <MenuTrigger asChild>
            <Button variant="outline" size="sm" data-testid="export-dropdown" title="Export this CV">
              <Download className="mr-1 h-4 w-4" /> Download
              <ChevronDown className="ml-1 h-3.5 w-3.5 text-[var(--as-muted-fg)]" />
            </Button>
          </MenuTrigger>
          <MenuContent align="end">
            {EXPORT_FORMATS.map((format) => (
              <MenuItem
                key={format}
                data-testid={`export-item-${format}`}
                pending={exportBusy === format}
                disabled={exportBusy === format}
                onSelect={() => onExport(format)}
              >
                {EXPORT_LABELS[format]}
              </MenuItem>
            ))}
          </MenuContent>
        </Menu>

        <Button size="sm" onClick={onSaveVersion} disabled={saveBusy} data-testid="save-version">
          <Save className="mr-1 h-4 w-4" /> Save version
        </Button>
      </div>
    </div>
  );
}
