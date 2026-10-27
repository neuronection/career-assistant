/**
 * The preset bar (plan 136): save/apply/delete named filter presets
 * with tag chips. Renders above the filter rail.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Save, Trash2 } from "lucide-react";

import {
  deleteFilterPreset,
  fetchFilterPresets,
  saveFilterPreset,
  type FilterPreset,
  type FilterSpec,
} from "@/api/postings";
import { countActiveFilters } from "@/features/postings/components/postings/filterState";

interface PresetBarProps {
  spec: FilterSpec;
  onApplyPreset: (filters: FilterSpec) => void;
}

export function PresetBar({ spec, onApplyPreset }: PresetBarProps) {
  const { t } = useTranslation();
  const [presets, setPresets] = useState<FilterPreset[]>([]);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [tagDraft, setTagDraft] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [showSave, setShowSave] = useState(false);
  const [error, setError] = useState("");
  const active = countActiveFilters(spec);

  const load = () => {
    fetchFilterPresets()
      .then(setPresets)
      .catch(() => setPresets([]));
  };

  useEffect(() => {
    load();
  }, []);

  const save = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    setSaving(true);
    setError("");
    try {
      await saveFilterPreset(trimmed, tags, spec);
      setName("");
      setTags([]);
      setTagDraft("");
      setShowSave(false);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (presetId: string) => {
    try {
      await deleteFilterPreset(presetId);
      load();
    } catch {
      // best-effort
    }
  };

  const addTag = () => {
    const tag = tagDraft.trim();
    if (tag && !tags.includes(tag) && tags.length < 20) {
      setTags([...tags, tag]);
    }
    setTagDraft("");
  };

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="preset-bar">
      {presets.map((preset) => (
        <span
          key={preset.id}
          className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100"
        >
          <button
            type="button"
            onClick={() => onApplyPreset(preset.filters)}
            className="font-medium"
            title={t("filters.applyPreset")}
          >
            {preset.name}
          </button>
          {preset.tags.map((tag) => (
            <span key={tag} className="text-[10px] px-1.5 py-0.5 rounded bg-primary-50 text-primary-600">
              {tag}
            </span>
          ))}
          <button
            type="button"
            onClick={() => void remove(preset.id)}
            className="text-slate-300 hover:text-rose-500"
            aria-label={t("filters.deletePreset")}
          >
            <Trash2 className="w-3 h-3" />
          </button>
        </span>
      ))}

      {active > 0 ? (
        <button
          type="button"
          className="text-xs inline-flex items-center gap-1 px-2.5 py-1 rounded-full border border-primary-200 bg-primary-50 text-primary-700 hover:bg-primary-100"
          onClick={() => setShowSave((v) => !v)}
          data-testid="save-preset-toggle"
        >
          <Save className="w-3 h-3" /> {t("filters.saveAs")}
        </button>
      ) : null}

      {showSave ? (
        <div className="w-full flex flex-wrap items-center gap-2 border border-slate-200 rounded-lg p-2 bg-slate-50" data-testid="preset-save-form">
          <input
            className="text-sm border border-slate-200 rounded px-2 py-1 flex-1 min-w-32"
            placeholder={t("filters.presetName")}
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void save();
              }
            }}
          />
          <div className="flex items-center gap-1">
            <input
              className="text-sm border border-slate-200 rounded px-2 py-1 w-24"
              placeholder={t("filters.tagPlaceholder")}
              value={tagDraft}
              onChange={(e) => setTagDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addTag();
                }
              }}
            />
          </div>
          {tags.map((tag) => (
            <span key={tag} className="text-xs px-2 py-0.5 rounded-full bg-primary-50 text-primary-700">
              {tag}
              <button type="button" onClick={() => setTags(tags.filter((t2) => t2 !== tag))} className="ml-1 text-slate-400">
                ×
              </button>
            </span>
          ))}
          <button
            type="button"
            className="text-sm px-3 py-1 rounded-lg bg-primary-600 text-white disabled:opacity-40"
            disabled={!name.trim() || saving}
            onClick={() => void save()}
          >
            {saving ? "…" : t("filters.save")}
          </button>
          {error ? <span className="text-xs text-rose-600">{error}</span> : null}
        </div>
      ) : null}
    </div>
  );
}
