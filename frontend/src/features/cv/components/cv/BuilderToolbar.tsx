import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Activity,
  ChevronDown,
  Command,
  Download,
  History,
  Redo2,
  Save,
  Sparkles,
  Undo2,
} from "lucide-react";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@neuronection/assistant-ui";
import { Button, Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
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

const EXPORT_LABEL_KEYS: Record<ExportFormat, string> = {
  pdf: "cvBuilder.toolbar.exportPdf",
  docx: "cvBuilder.toolbar.exportDocx",
  md: "cvBuilder.toolbar.exportMarkdown",
  json: "cvBuilder.toolbar.exportJson",
  ats_text: "cvBuilder.toolbar.exportAts",
};

function TitleField({ title, onRename }: { title: string; onRename: (title: string) => void }) {
  const { t } = useTranslation();
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
      aria-label={t("cvBuilder.toolbar.titleAria")}
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
  pagesSource?: "pdf" | "last_export" | null;
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
  onCreateLetter: (() => void) | null;
  letterBusy?: boolean;
  aiCluster?: React.ReactNode;
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
  pagesSource,
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
  onCreateLetter,
  letterBusy = false,
  aiCluster,
  onUndo,
  onRedo,
}: BuilderToolbarProps) {
  const { t } = useTranslation();
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
              ? t("cvBuilder.toolbar.versionsSummary", {
                  count: versions.length,
                  version: versions[0].version,
                })
              : t("cvBuilder.toolbar.noVersions")}
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
          <Popover>
            <PopoverTrigger asChild>
              <button
                type="button"
                className={`cursor-pointer rounded-full px-2 py-1 text-xs font-medium transition-colors duration-150 hover:brightness-95 ${
                  lint.passed
                    ? "bg-emerald-100 text-emerald-800"
                    : "bg-amber-100 text-amber-800"
                }`}
                title={t("cvBuilder.toolbar.atsLintTitle", { score: lint.score })}
                aria-label={t("cvBuilder.toolbar.atsLintAria", { score: lint.score })}
                data-testid="ats-chip"
              >
                ATS {lint.score}
              </button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-72" data-testid="lint-popover">
              <div className="flex items-baseline justify-between gap-2 border-b border-[var(--as-border)] pb-1.5">
                <p className="text-xs font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
                  {t("cvBuilder.toolbar.atsLint", { score: lint.score })}
                </p>
                <p className="text-[11px] tabular-nums text-[var(--as-muted-fg)]">
                  {t("cvBuilder.toolbar.lintCounts", {
                    fail: lint.checks.filter((check) => check.level === "fail").length,
                    warn: lint.checks.filter((check) => check.level === "warn").length,
                    pass: lint.checks.filter((check) => check.level === "pass").length,
                  })}
                </p>
              </div>
              <ul className="space-y-1 pt-1.5 text-xs" data-testid="lint-panel">
                {lint.checks.map((check) => (
                  <li
                    key={check.id}
                    className={
                      check.level === "fail"
                        ? "text-red-700"
                        : check.level === "warn"
                          ? "text-amber-700"
                          : "text-[var(--as-muted-fg)]"
                    }
                  >
                    {check.level === "pass" ? "✓" : "•"} {check.message}
                  </li>
                ))}
              </ul>
            </PopoverContent>
          </Popover>
        )}
        <span
          className={`rounded-full px-2 py-1 text-xs font-medium ${
            overflow ? "bg-red-100 text-red-800" : "bg-[var(--as-muted)]"
          }`}
          title={
            overflow
              ? t("cvBuilder.toolbar.overflowTitle")
              : pagesSource === "pdf"
                ? t("cvBuilder.toolbar.pagesFromPdf")
                : pagesSource === "last_export"
                  ? t("cvBuilder.toolbar.pagesFromExport")
                  : t("cvBuilder.toolbar.pagesEstimated")
          }
          data-testid="pages-chip"
        >
          {pagesSource ? "" : "~"}
          {t("cvBuilder.toolbar.pageCount", { count: pages, max: maxPages })}
          {pagesSource ? "" : ` ${t("cvBuilder.toolbar.unverified")}`}
          {overflow ? ` ${t("cvBuilder.toolbar.overBudget")}` : ""}
        </span>

        <Button variant="outline" size="sm" onClick={onOpenPalette} data-testid="open-palette" title={t("cvBuilder.toolbar.paletteTitle")}>
          <Command className="mr-1 h-4 w-4" /> {t("cvBuilder.toolbar.paletteShortcut")}
        </Button>
        {aiCluster}
        <Button size="sm" onClick={onOpenAssistant} data-testid="cv-ask-ai" title={t("cvBuilder.toolbar.assistantTitle")}>
          <Sparkles className="mr-1 h-4 w-4" /> {t("cvBuilder.toolbar.askAi")}
        </Button>
        <Button variant="outline" size="icon" onClick={onUndo} disabled={!canUndo} data-testid="undo" title={t("cvBuilder.toolbar.undoTitle")} aria-label={t("cvBuilder.toolbar.undo")}>
          <Undo2 className="h-4 w-4" />
        </Button>
        <Button variant="outline" size="icon" onClick={onRedo} disabled={!canRedo} data-testid="redo" title={t("cvBuilder.toolbar.redoTitle")} aria-label={t("cvBuilder.toolbar.redo")}>
          <Redo2 className="h-4 w-4" />
        </Button>
        <Button variant="outline" size="sm" onClick={onOpenVersions} data-testid="open-versions">
          <History className="mr-1 h-4 w-4" /> {t("cvBuilder.toolbar.versions")}
          {versions.length > 0 ? ` (${versions.length})` : ""}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={onOpenRuns}
          data-testid="open-runs"
          title={t("cvBuilder.toolbar.runsTitle")}
        >
          <Activity className="mr-1 h-4 w-4" /> {t("cvBuilder.toolbar.runs")}
          {onOpenPolish ? ` · ${t("cvBuilder.toolbar.notes")}` : ""}
        </Button>

        <Menu>
          <MenuTrigger asChild>
            <Button variant="outline" size="sm" data-testid="export-dropdown" title={t("cvBuilder.toolbar.exportTitle")}>
              <Download className="mr-1 h-4 w-4" /> {t("cvBuilder.toolbar.download")}
              <ChevronDown className="ml-1 h-3.5 w-3.5 text-[var(--as-muted-fg)]" />
            </Button>
          </MenuTrigger>
          <MenuContent align="end">
            {onCreateLetter && (
              <MenuItem
                data-testid="create-matching-letter"
                pending={letterBusy}
                disabled={letterBusy}
                onSelect={onCreateLetter}
              >
                {t("cvBuilder.toolbar.matchingLetter")}
              </MenuItem>
            )}
            {EXPORT_FORMATS.map((format) => (
              <MenuItem
                key={format}
                data-testid={`export-item-${format}`}
                pending={exportBusy === format}
                disabled={exportBusy === format}
                onSelect={() => onExport(format)}
              >
                {t(EXPORT_LABEL_KEYS[format])}
              </MenuItem>
            ))}
          </MenuContent>
        </Menu>

        <Button size="sm" onClick={onSaveVersion} disabled={saveBusy} data-testid="save-version">
          <Save className="mr-1 h-4 w-4" /> {t("cvBuilder.toolbar.saveVersion")}
        </Button>
      </div>
    </div>
  );
}
