import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Wand2 } from "lucide-react";
import {
  Button,
  Card,
  ConfirmationModal,
  EmptyState,
} from "@/components/ui";
import { apiDetail } from "@/api/client";
import {
  createSynthItem,
  bulkSynthItems,
  deleteSynthItem,
  fetchContextSources,
  fetchSynthItems,
  generateSynthItems,
  patchSynthItem,
  regenerateSynthItem,
} from "@/api/cv";
import type {
  CvContextRef,
  CvContextSourceOut,
  CvSynthAction,
  CvSynthItem,
} from "@/types/cv";
import { VariantEditor, type VariantEditorBody } from "@/components/cv/VariantEditor";

const ACTIONS: CvSynthAction[] = [
  "summarize",
  "detail",
  "restyle",
  "posting_fit",
  "translate",
];

const BULK_NOTICE: Record<string, string> = {
  archive: "archived",
  unarchive: "unarchived",
  delete: "deleted",
  draft: "setDraft",
  activate: "activated",
};

interface Group {
  key: string;
  sourceKey: string;
  refs: CvContextRef[];
  items: CvSynthItem[];
}

function refKey(ref: CvContextRef): string {
  return `${ref.source_key}:${ref.item_id}`;
}

function itemText(item: CvSynthItem): string {
  const payload = item.payload || {};
  if (payload.description) return payload.description;
  if (payload.summary) return payload.summary;
  if (payload.achievements?.length)
    return payload.achievements
      .map((entry) => entry.text)
      .filter(Boolean)
      .join(" · ");
  return "";
}

function refLabel(
  ref: CvContextRef,
  labels: Map<string, { label: string; source: string }>,
  t: (key: string) => string,
): { label: string; source: string; known: boolean } {
  const found = labels.get(refKey(ref));
  if (found) return { ...found, known: true };
  const sourceLabel = t(`cvSynth.sources.${ref.source_key}`);
  return {
    label: `${sourceLabel === `cvSynth.sources.${ref.source_key}` ? ref.source_key : sourceLabel} · ${ref.item_id.slice(0, 8)}`,
    source: ref.source_key,
    known: false,
  };
}

export function CvSynthLibrary() {
  const { t } = useTranslation();
  const [items, setItems] = useState<CvSynthItem[]>([]);
  const [sources, setSources] = useState<CvContextSourceOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<CvSynthItem | null>(null);
  const [editor, setEditor] = useState<{ open: boolean; initial: CvSynthItem | null }>({
    open: false,
    initial: null,
  });
  const [actions, setActions] = useState<Record<string, CvSynthAction>>({});
  const [selectMode, setSelectMode] = useState(false);
  const [bulkDelete, setBulkDelete] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const selectedIds = useMemo(() => Array.from(selected), [selected]);
  const archivedCount = items.filter((item) => item.status === "archived").length;

  const bulkRun = async (
    action: "archive" | "unarchive" | "delete" | "draft" | "activate"
  ) => {
    if (selectedIds.length === 0) return;
    await act(async () => {
      if (action === "draft" || action === "activate") {
        await Promise.all(
          selectedIds.map((id) =>
            patchSynthItem(id, { status: action === "draft" ? "draft" : "active" })
          )
        );
      } else {
        await bulkSynthItems(selectedIds, action);
      }
      setSelected(new Set());
    }, t(`cvSynth.bulk.${BULK_NOTICE[action]}`));
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setItems(await fetchSynthItems());
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    void fetchContextSources()
      .then((out) => setSources(out.sources))
      .catch(() => setSources([]));
  }, [load]);

  async function saveVariantEdit(body: VariantEditorBody) {
    const target = editor.initial;
    if (!target) {
      await act(() =>
        Promise.reject(new Error(t("cvSynth.noSelection"))),
      );
      return;
    }
    await act(
      () =>
        patchSynthItem(target.id, {
          payload: body.payload,
          variant_key: body.variant_key,
        }),
      t("cvSynth.saved"),
    );
    setEditor({ open: false, initial: null });
  }

  async function saveVariantNew(body: VariantEditorBody) {
    await act(
      () =>
        createSynthItem({
          refs: body.refs,
          scope: body.scope,
          payload: body.payload,
          variant_key: body.variant_key,
          target_posting_id: body.target_posting_id ?? undefined,
          voice: body.voice,
        }),
      t("cvSynth.created"),
    );
    setEditor({ open: false, initial: null });
  }

  const groups = useMemo<Group[]>(() => {
    const map = new Map<string, CvSynthItem[]>();
    for (const item of items) {
      if (!item.source_refs[0]) continue;
      const key = refKey(item.source_refs[0]);
      const list = map.get(key) ?? [];
      list.push(item);
      map.set(key, list);
    }
    return Array.from(map.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, list]) => ({
        key,
        sourceKey: list[0].source_refs[0].source_key,
        refs: list[0].source_refs,
        items: list.sort((a, b) =>
          (b.created_at ?? "").localeCompare(a.created_at ?? ""),
        ),
      }));
  }, [items]);

  const refLabels = useMemo(() => {
    const map = new Map<string, { label: string; source: string }>();
    for (const source of sources) {
      for (const entry of source.items) {
        map.set(`${source.key}:${entry.item_id}`, {
          label: entry.label,
          source: source.label,
        });
      }
    }
    return map;
  }, [sources]);

  async function act(fn: () => Promise<unknown>, message?: string) {
    setBusy(true);
    setError("");
    try {
      await fn();
      if (message) setNotice(message);
      await load();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  }

  const actWithNotice = act;
  async function generate(group: Group) {
    const action = actions[group.key] ?? "summarize";
    await act(
      () => generateSynthItems({ refs: group.refs, action }),
      t("cvSynth.generated"),
    );
  }

  return (
    <div className="space-y-6" data-testid="synth-library">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <Wand2 className="w-6 h-6" /> {t("cvSynth.title")}
          </h1>
          <p className="text-sm text-slate-500">{t("cvSynth.subtitle")}</p>
        </div>
        <Link to="/cv" className="text-sm text-primary-600 hover:underline">
          {t("cvSynth.backToStudio")}
        </Link>
      </div>

      <div className="flex justify-end gap-2">
        {selectMode && (
          <Button
            size="sm"
            variant="outline"
            disabled={busy || archivedCount === 0}
            data-testid="synth-select-archived"
            onClick={() =>
              setSelected(
                new Set(
                  items
                    .filter((item) => item.status === "archived")
                    .map((item) => item.id)
                )
              )
            }
          >
            {t("cvSynth.bulk.selectArchived", { defaultValue: "Select archived" })}
            {" ("}
            {archivedCount}
            {")"}
          </Button>
        )}
        {selectMode && selectedIds.length > 0 && (
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            data-testid="synth-bulk-archive"
            onClick={() => void bulkRun("archive")}
          >
            {t("cvSynth.bulk.archive", { defaultValue: "Archive" })}
          </Button>
        )}
        {selectMode && selectedIds.length > 0 && (
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            data-testid="synth-bulk-unarchive"
            onClick={() => void bulkRun("unarchive")}
          >
            {t("cvSynth.bulk.unarchive", { defaultValue: "Restore" })}
          </Button>
        )}
        {selectMode && selectedIds.length > 0 && (
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            data-testid="synth-bulk-draft"
            onClick={() => void bulkRun("draft")}
          >
            {t("cvSynth.bulk.draft", { defaultValue: "Set draft" })}
          </Button>
        )}
        {selectMode && selectedIds.length > 0 && (
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            data-testid="synth-bulk-activate"
            onClick={() => void bulkRun("activate")}
          >
            {t("cvSynth.bulk.activate", { defaultValue: "Activate" })}
          </Button>
        )}
        {selectMode && selectedIds.length > 0 && (
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            data-testid="synth-bulk-delete"
            onClick={() => setBulkDelete(true)}
          >
            <span className="text-red-600">
              {t("cvSynth.bulk.delete", { defaultValue: "Delete" })}
            </span>
          </Button>
        )}
        {selectMode && (
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            data-testid="synth-selection-clear"
            onClick={() => setSelected(new Set())}
          >
            {t("cvSynth.bulk.clear", { defaultValue: "Clear selection" })}
          </Button>
        )}
        <Button
          size="sm"
          variant={selectMode ? "outline" : undefined}
          data-testid="synth-select-mode"
          onClick={() => {
            setSelectMode((current) => !current);
            setSelected(new Set());
          }}
        >
          {selectMode
            ? t("cvSynth.bulk.done", { defaultValue: "Done" })
            : t("cvSynth.bulk.select", { defaultValue: "Select" })}
        </Button>
        <Button
          size="sm"
          data-testid="synth-add-variant"
          onClick={() => setEditor({ open: true, initial: null })}
        >
          <Wand2 className="w-3 h-3" /> {t("cvSynth.newVariant")}
        </Button>
      </div>

      {error && (
        <p className="text-sm text-red-600" data-testid="synth-error">
          {error}
        </p>
      )}
      {notice && (
        <p className="text-sm text-emerald-700" data-testid="synth-notice">
          {notice}
        </p>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">{t("common.loading")}</p>
      ) : groups.length === 0 ? (
        <EmptyState
          title={t("cvSynth.emptyTitle")}
          description={t("cvSynth.emptyBody")}
        />
      ) : (
        groups.map((group) => {
          const groupAction = actions[group.key] ?? "summarize";
          return (
            <Card
              key={group.key}
              className="p-4"
              data-testid={`synth-group-${group.key}`}
            >
              <div className="flex items-center justify-between gap-2 mb-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-1">
                    {group.refs.map((ref) => {
                      const resolved = refLabel(ref, refLabels, t);
                      return (
                        <span
                          key={`${ref.source_key}-${ref.item_id}`}
                          className={`rounded-full px-2 py-0.5 text-xs ${
                            resolved.known
                              ? "bg-[color-mix(in_srgb,var(--as-accent)_10%,transparent)] text-[var(--as-accent)]"
                              : "bg-slate-100 text-slate-700"
                          }`}
                          data-testid={`synth-group-ref-${refKey(ref)}`}
                        >
                          {resolved.label}
                        </span>
                      );
                    })}
                  </div>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {t("cvSynth.variantCount", { count: group.items.length })}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <select
                    aria-label={t("cvSynth.action")}
                    data-testid={`synth-action-${group.key}`}
                    className="text-sm border rounded-md px-2 py-1"
                    value={groupAction}
                    onChange={(event) =>
                      setActions({
                        ...actions,
                        [group.key]: event.target.value as CvSynthAction,
                      })
                    }
                  >
                    {ACTIONS.map((value) => (
                      <option key={value} value={value}>
                        {t(`cvSynth.actions.${value}`)}
                      </option>
                    ))}
                  </select>
                  <Button
                    size="sm"
                    disabled={busy}
                    data-testid={`synth-generate-${group.key}`}
                    onClick={() => void generate(group)}
                  >
                    <Wand2 className="w-3 h-3" /> {t("cvSynth.generate")}
                  </Button>
                </div>
              </div>
              {selectMode && (
                <div className="mb-1.5 flex items-center gap-2 text-xs text-[var(--as-muted-fg)]">
                  <input
                    type="checkbox"
                    className="accent-[var(--as-accent)]"
                    data-testid={`synth-group-select-${group.key}`}
                    checked={group.items.every((item) => selected.has(item.id))}
                    onChange={(event) => {
                      const next = new Set(selected);
                      for (const item of group.items) {
                        if (event.target.checked) next.add(item.id);
                        else next.delete(item.id);
                      }
                      setSelected(next);
                    }}
                  />
                  {t("cvSynth.bulk.selectGroup", { defaultValue: "Select all in group" })}
                </div>
              )}
              <ul className="divide-y rounded-lg border">
                {group.items.map((item) => (
                  <li
                    key={item.id}
                    className={`p-3 flex items-start justify-between gap-4 ${
                      item.status === "archived" ? "opacity-60 bg-slate-50" : ""
                    }`}
                    data-testid={`synth-variant-${item.id}`}
                    data-status={item.status}
                  >
                    {selectMode && (
                      <input
                        type="checkbox"
                        className="mt-1 accent-[var(--as-accent)]"
                        data-testid={`synth-select-${item.id}`}
                        checked={selected.has(item.id)}
                        aria-label={`Select variant ${item.id}`}
                        onChange={(event) => {
                          const next = new Set(selected);
                          if (event.target.checked) next.add(item.id);
                          else next.delete(item.id);
                          setSelected(next);
                        }}
                      />
                    )}
                    <div className="min-w-0">
                      <p
                        className={`line-clamp-2 text-sm break-words ${
                          item.status === "archived"
                            ? "text-slate-500"
                            : "text-slate-900"
                        }`}
                      >
                        {itemText(item) || t("cvSynth.emptyBody")}
                      </p>
                      {item.source_refs.length > 0 && (
                        <div
                          className="mt-1 flex flex-wrap items-center gap-1 text-[11px]"
                          data-testid={`synth-variant-refs-${item.id}`}
                        >
                          <span className="text-[var(--as-muted-fg)]">
                            {t("cvSynth.basedOn")}:
                          </span>
                          {item.source_refs.map((ref) => {
                            const resolved = refLabel(ref, refLabels, t);
                            return (
                              <span
                                key={`${ref.source_key}-${ref.item_id}`}
                                className={`max-w-52 truncate rounded-full px-1.5 py-0.5 ${
                                  resolved.known
                                    ? "bg-[color-mix(in_srgb,var(--as-accent)_8%,transparent)] text-[var(--as-accent)]"
                                    : "bg-slate-100 text-slate-700"
                                }`}
                                title={resolved.label}
                                data-testid={`synth-ref-${refKey(ref)}`}
                              >
                                {resolved.label}
                              </span>
                            );
                          })}
                        </div>
                      )}
                      <div className="mt-1 flex flex-wrap gap-1 text-[11px]">
                        <span
                          className={
                            item.status === "active"
                              ? "px-1.5 py-0.5 rounded bg-[color-mix(in_srgb,var(--as-accent)_10%,transparent)] text-[var(--as-accent)] font-medium"
                              : item.status === "draft"
                                ? "px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 font-medium"
                                : "px-1.5 py-0.5 rounded bg-[var(--as-muted)] text-[var(--as-muted-fg)] font-medium"
                          }
                          data-testid={`synth-status-${item.id}`}
                        >
                          {t(`cvSynth.status.${item.status}`)}
                        </span>
                        <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-700">
                          {item.voice.language}
                        </span>
                        <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-700">
                          {item.variant_key}
                        </span>
                        <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-700">
                          {t(`cvSynth.origin.${item.source}`)}
                        </span>
                        {item.stale && (
                          <span
                            className="px-1.5 py-0.5 rounded bg-amber-100 text-amber-800"
                            data-testid="synth-stale"
                          >
                            {t("cvSynth.stale")}
                          </span>
                        )}
                        {item.orphaned && (
                          <span className="px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">
                            {t("cvSynth.orphaned")}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex flex-col gap-1">
                      {item.status === "draft" && (
                        <Button
                          size="sm"
                          disabled={busy}
                          data-testid={`synth-activate-${item.id}`}
                          onClick={() =>
                            void act(
                              () => patchSynthItem(item.id, { status: "active" }),
                              t("cvSynth.activated"),
                            )
                          }
                        >
                          {t("cvSynth.activate")}
                        </Button>
                      )}
                      {item.status === "active" && (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={busy}
                          data-testid={`synth-archive-${item.id}`}
                          onClick={() =>
                            void act(
                              () => patchSynthItem(item.id, { status: "archived" }),
                              t("cvSynth.archived"),
                            )
                          }
                        >
                          {t("cvSynth.archive")}
                        </Button>
                      )}
                      {item.source === "ai" && (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={busy}
                          data-testid={`synth-regenerate-${item.id}`}
                          onClick={() =>
                            void act(
                              () => regenerateSynthItem(item.id),
                              t("cvSynth.regenerated"),
                            )
                          }
                        >
                          {t("cvSynth.regenerate")}
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy}
                        data-testid={`synth-edit-${item.id}`}
                        onClick={() => setEditor({ open: true, initial: item })}
                      >
                        {t("cvSynth.edit")}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy}
                        data-testid={`synth-delete-${item.id}`}
                        onClick={() => setDeleteTarget(item)}
                      >
                        {t("cvSynth.delete")}
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          );
        })
      )}

      {deleteTarget && (
        <ConfirmationModal
          open
          onOpenChange={(next) => !next && setDeleteTarget(null)}
          title={t("cvSynth.deleteConfirm")}
          description={t("cvSynth.deleteBody")}
          confirmLabel={t("cvSynth.delete")}
          destructive
          busy={busy}
          onConfirm={async () => {
            const target = deleteTarget;
            setDeleteTarget(null);
            await actWithNotice(
              () => deleteSynthItem(target.id),
              t("cvSynth.deleted"),
            );
          }}
        />
      )}

      {bulkDelete && (
        <ConfirmationModal
          open
          onOpenChange={(next) => !next && setBulkDelete(false)}
          title={t("cvSynth.deleteConfirm")}
          description={t("cvSynth.bulk.deleteBody", { defaultValue: "Delete the selected variants? The paired profile entries keep their text." })}
          confirmLabel={t("cvSynth.bulk.delete", { defaultValue: "Delete" })}
          destructive
          busy={busy}
          onConfirm={async () => {
            setBulkDelete(false);
            await bulkRun("delete");
          }}
        />
      )}

      {editor.open && (
        <VariantEditor
          open
          sources={sources}
          initial={editor.initial}
          defaultLanguage={items[0]?.voice.language ?? "en"}
          busy={busy}
          onActivate={async () => {
            const target = editor.initial;
            if (!target) return;
            await act(
              () => patchSynthItem(target.id, { status: "active" }),
              t("cvSynth.activated"),
            );
            setEditor({ open: false, initial: null });
          }}
          onDelete={async () => {
            const target = editor.initial;
            if (!target) return;
            setEditor({ open: false, initial: null });
            await actWithNotice(
              () => deleteSynthItem(target.id),
              t("cvSynth.deleted"),
            );
          }}
          onClose={() => setEditor({ open: false, initial: null })}
          onSubmit={(body) =>
            editor.initial ? saveVariantEdit(body) : saveVariantNew(body)
          }
        />
      )}
    </div>
  );
}
