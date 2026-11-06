import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { BookmarkPlus, MoreHorizontal } from "lucide-react";

import { deleteSearch, fetchSearches, recordSearch, updateSearch } from "@/api/engagement";
import {
  Button,
  ConfirmationModal,
  Menu,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuSeparator,
  MenuTrigger,
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalTitle,
} from "@/components/ui";
import {
  countActive,
  toParams,
  toSearchParams,
  type Filters,
} from "@/features/catalog/exploreParams";
import type { SearchRecord } from "@/types/wire";
import {
  describeFilters,
  presetFilters,
  suggestPresetName,
} from "@/features/postings/components/postings/presetSummary";

const CANONICAL_KEYS = (filters: Filters) => toSearchParams(filters).toString();

export function PresetBar({
  filters,
  total,
  onApply,
}: {
  filters: Filters;
  total: number;
  onApply: (next: Filters) => void;
}) {
  const { t } = useTranslation();
  const [presets, setPresets] = useState<SearchRecord[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [name, setName] = useState("");
  const [renaming, setRenaming] = useState<SearchRecord | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deleting, setDeleting] = useState<SearchRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(() => {
    void fetchSearches({ scope: "postings", saved: true })
      .then((rows) => setPresets(rows.filter((row) => Boolean(row.name))))
      .catch(() => setPresets([]))
      .finally(() => setLoaded(true));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const current = useMemo(
    () => ({ filters: toParams(filters) as unknown as Record<string, unknown>, canonical: CANONICAL_KEYS(filters) }),
    [filters]
  );
  const activeCount = countActive(filters);
  const matching = presets.find(
    (preset) => CANONICAL_KEYS(presetFilters(preset.filters)) === current.canonical
  );

  const flash = (message: string) => {
    setNote(message);
    setTimeout(() => setNote(""), 4000);
  };

  const run = (action: Promise<unknown>, done: () => void) => {
    setBusy(true);
    setError("");
    void action
      .then(() => {
        done();
        load();
      })
      .catch((err) => setError(String(err)))
      .finally(() => setBusy(false));
  };

  const openSave = () => {
    setName(matching?.name ?? suggestPresetName(filters, t));
    setSaveOpen(true);
  };

  const save = () => {
    const clean = name.trim();
    if (!clean) return;
    run(
      matching
        ? updateSearch(matching.id, {
            filters: current.filters,
            query: filters.q,
            result_count: total,
            name: matching.name ?? clean,
          })
        : recordSearch({
            scope: "postings",
            query: filters.q,
            filters: current.filters,
            result_count: total,
            saved: true,
            name: clean,
          }),
      () => {
        setSaveOpen(false);
        flash(matching ? t("presets.updated") : t("presets.saved"));
      }
    );
  };

  const updatePreset = (preset: SearchRecord) => {
    run(
      updateSearch(preset.id, {
        filters: current.filters,
        query: filters.q,
        result_count: total,
      }),
      () => flash(t("presets.updated"))
    );
  };

  const startRename = (preset: SearchRecord) => {
    setRenaming(preset);
    setRenameValue(preset.name ?? "");
  };

  const rename = () => {
    if (!renaming) return;
    const clean = renameValue.trim();
    if (!clean) return;
    run(updateSearch(renaming.id, { name: clean }), () => {
      setRenaming(null);
      flash(t("presets.renamed"));
    });
  };

  const remove = () => {
    if (!deleting) return;
    run(deleteSearch(deleting.id), () => {
      setDeleting(null);
      flash(t("presets.deleted"));
    });
  };

  return (
    <div className="space-y-2" data-testid="preset-bar">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs font-medium text-slate-500">{t("presets.title")}</span>
        {presets.map((preset) => {
          const presetFilterSet = presetFilters(preset.filters);
          const active = CANONICAL_KEYS(presetFilterSet) === current.canonical;
          const summary = describeFilters(presetFilterSet, t);
          return (
            <span
              key={preset.id}
              className={`inline-flex items-stretch overflow-hidden rounded-full border text-xs transition-colors ${
                active
                  ? "border-primary-300 bg-primary-50 text-primary-700"
                  : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
              }`}
            >
              <button
                type="button"
                onClick={() => onApply(presetFilterSet)}
                className={`py-1 pl-2.5 pr-1 ${active ? "font-medium" : ""}`}
                title={summary.join("\n")}
                data-testid={`preset-${preset.id}`}
                aria-pressed={active}
              >
                {preset.name}
                <span className="ml-1 opacity-60">{countActive(presetFilterSet)}</span>
              </button>
              <Menu>
                <MenuTrigger asChild>
                  <button
                    type="button"
                    className="py-1 pl-0.5 pr-1.5 opacity-70 hover:opacity-100"
                    aria-label={t("presets.options", { name: preset.name })}
                    data-testid={`preset-${preset.id}-menu`}
                  >
                    <MoreHorizontal aria-hidden className="h-3.5 w-3.5" />
                  </button>
                </MenuTrigger>
                <MenuContent align="end" className="w-72">
                  <MenuLabel>{preset.name}</MenuLabel>
                  <div
                    className="space-y-0.5 px-2 pb-2 text-xs text-slate-500"
                    data-testid={`preset-${preset.id}-summary`}
                  >
                    {summary.length ? (
                      summary.map((line) => <p key={line}>{line}</p>)
                    ) : (
                      <p>{t("presets.summary.empty")}</p>
                    )}
                  </div>
                  <MenuSeparator />
                  <MenuItem onSelect={() => updatePreset(preset)} disabled={busy}>
                    {t("presets.updateCurrent")}
                  </MenuItem>
                  <MenuItem onSelect={() => startRename(preset)}>{t("presets.rename")}</MenuItem>
                  <MenuItem danger onSelect={() => setDeleting(preset)}>
                    {t("presets.delete")}
                  </MenuItem>
                </MenuContent>
              </Menu>
            </span>
          );
        })}
        <button
          type="button"
          onClick={openSave}
          disabled={busy || (loaded && activeCount === 0)}
          className="inline-flex items-center gap-1 rounded-full border border-dashed border-slate-300 px-2.5 py-1 text-xs text-slate-500 transition-colors hover:border-primary-300 hover:text-primary-700 disabled:opacity-40"
          title={t("presets.saveHint")}
          data-testid="preset-save"
        >
          <BookmarkPlus aria-hidden className="h-3.5 w-3.5" />
          {matching ? t("presets.updateNamed", { name: matching.name }) : t("presets.saveCurrent")}
        </button>
        {note ? (
          <span className="text-xs text-emerald-600" data-testid="preset-note">
            {note}
          </span>
        ) : null}
        {error ? (
          <span className="text-xs text-rose-600" data-testid="preset-error">
            {error}
          </span>
        ) : null}
      </div>

      <Modal open={saveOpen} onOpenChange={setSaveOpen}>
        <ModalContent size="sm">
          <ModalHeader>
            <ModalTitle>{t("presets.saveTitle")}</ModalTitle>
          </ModalHeader>
          <ModalBody className="space-y-3">
            <label className="block text-xs font-medium text-slate-500">
              {t("presets.nameLabel")}
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={80}
                autoFocus
                className="mt-1 w-full rounded-lg border border-slate-200 px-2 py-1.5 text-sm"
                data-testid="preset-name-input"
              />
            </label>
            <div className="space-y-0.5 text-xs text-slate-500" data-testid="preset-save-summary">
              {describeFilters(filters, t).map((line) => (
                <p key={line}>{line}</p>
              ))}
            </div>
          </ModalBody>
          <ModalFooter>
            <Button variant="ghost" size="sm" onClick={() => setSaveOpen(false)}>
              {t("common.cancel")}
            </Button>
            <Button
              size="sm"
              onClick={save}
              disabled={busy || !name.trim()}
              data-testid="preset-save-confirm"
            >
              {matching ? t("presets.update") : t("presets.save")}
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>

      <Modal open={renaming !== null} onOpenChange={(open) => !open && setRenaming(null)}>
        <ModalContent size="sm">
          <ModalHeader>
            <ModalTitle>{t("presets.renameTitle")}</ModalTitle>
          </ModalHeader>
          <ModalBody>
            <input
              value={renameValue}
              onChange={(event) => setRenameValue(event.target.value)}
              maxLength={80}
              autoFocus
              className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-sm"
              data-testid="preset-rename-input"
            />
          </ModalBody>
          <ModalFooter>
            <Button variant="ghost" size="sm" onClick={() => setRenaming(null)}>
              {t("common.cancel")}
            </Button>
            <Button
              size="sm"
              onClick={rename}
              disabled={busy || !renameValue.trim()}
              data-testid="preset-rename-confirm"
            >
              {t("presets.rename")}
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>

      <ConfirmationModal
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        onConfirm={remove}
        title={t("presets.deleteTitle", { name: deleting?.name ?? "" })}
        description={t("presets.deleteBody")}
        confirmLabel={t("presets.delete")}
        destructive
      />
    </div>
  );
}
