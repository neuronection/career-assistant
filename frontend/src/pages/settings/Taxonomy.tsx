import { useCallback, useEffect, useState } from "react";
import {
  createTag,
  deleteTag,
  fetchInterests,
  fetchSkillRows,
  mergeSkill,
  promoteSkill,
  updateTag,
  type SkillRow,
  type Tag,
} from "@/api/taxonomy";
import { api } from "@/api/client";
import { apiDetail } from "@/api/client";
import { EmptyState, Spinner } from "@/components/ui";

interface PathRow {
  id: string;
  title: string;
  description: string;
  source: string;
  status: string;
  job_code: string | null;
  job_title: string | null;
  steps: { position: number; label: string; kind: string }[];
}

/** Admin taxonomy management: create, edit, promote/deprecate, merge, delete. */
export function Taxonomy() {
  const [kind, setKind] = useState<"interests" | "skills" | "paths">("interests");
  const [tags, setTags] = useState<Tag[]>([]);
  const [skills, setSkills] = useState<SkillRow[]>([]);
  const [paths, setPaths] = useState<PathRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({ key: "", label: "", category: "", description: "" });
  const [merging, setMerging] = useState<string | null>(null);
  const [mergeTarget, setMergeTarget] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      if (kind === "interests") {
        setTags(await fetchInterests());
      } else if (kind === "skills") {
        setSkills(await fetchSkillRows());
      } else {
        const { data } = await api.get<PathRow[]>("/admin/paths", {
          params: { status: "draft" },
        });
        setPaths(data);
      }
      setError("");
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setLoading(false);
    }
  }, [kind]);

  useEffect(() => {
    void load();
  }, [load]);

  const onCreate = async () => {
    setError("");
    try {
      await createTag(kind === "paths" ? "skills" : kind, draft);
      setDraft({ key: "", label: "", category: "", description: "" });
      setCreating(false);
      await load();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const promote = async (skill: SkillRow) => {
    setError("");
    try {
      await promoteSkill(skill.id);
      await load();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const setStatus = async (tag: Tag | SkillRow, status: string) => {
    setError("");
    try {
      await updateTag(kind === "paths" ? "skills" : kind, tag.id, { status } as never);
      await load();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const doMerge = async (skill: SkillRow) => {
    setError("");
    try {
      await mergeSkill(skill.id, mergeTarget);
      setMerging(null);
      setMergeTarget("");
      await load();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const remove = async (tag: Tag | SkillRow) => {
    setError("");
    setNote("");
    try {
      await deleteTag(kind === "paths" ? "skills" : kind, tag.id);
      await load();
    } catch (err) {
      setError(apiDetail(err));
      setNote("Referenced tags cannot be deleted — deprecate instead.");
    }
  };

  const moderatePath = async (id: string, action: "publish" | "reject") => {
    setError("");
    try {
      await api.post(`/admin/paths/${id}/${action}`);
      await load();
    } catch (err) {
      setError(apiDetail(err));
    }
  };

  const activeSkills = skills.filter((s) => s.status === "active");
  const proposed = skills.filter((s) => s.status === "proposed");

  return (
    <div className="space-y-4" data-testid="settings-taxonomy">
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          {(["interests", "skills", "paths"] as const).map((k) => (
            <button
              key={k}
              onClick={() => setKind(k)}
              className={`text-sm px-4 py-2 rounded-lg border capitalize ${
                kind === k
                  ? "bg-primary-600 text-white border-primary-600"
                  : "border-slate-200 bg-white"
              }`}
            >
              {k}
            </button>
          ))}
        </div>
        {kind !== "paths" && (
          <button
            onClick={() => setCreating((v) => !v)}
            className="text-sm bg-primary-600 text-white rounded-lg px-3 py-1.5"
          >
            {creating ? "Cancel" : "New tag"}
          </button>
        )}
      </div>

      {creating && kind !== "paths" && (
        <div className="bg-white border border-slate-200 rounded-xl p-4 grid md:grid-cols-2 gap-2">
          <input
            placeholder="key (stable slug, e.g. renewable-energy)"
            value={draft.key}
            onChange={(e) => setDraft({ ...draft, key: e.target.value })}
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm"
          />
          <input
            placeholder="label"
            value={draft.label}
            onChange={(e) => setDraft({ ...draft, label: e.target.value })}
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm"
          />
          <input
            placeholder="category"
            value={draft.category}
            onChange={(e) => setDraft({ ...draft, category: e.target.value })}
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm"
          />
          <input
            placeholder="description (optional)"
            value={draft.description}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm"
          />
          <button
            onClick={() => void onCreate()}
            disabled={!draft.key || !draft.label || !draft.category}
            className="md:col-span-2 bg-emerald-600 text-white rounded-lg px-3 py-2 text-sm disabled:opacity-50"
          >
            Create tag
          </button>
        </div>
      )}

      {error && <p className="text-sm text-rose-600">{error}</p>}
      {note && <p className="text-xs text-amber-600">{note}</p>}

      {loading ? (
        <div className="flex w-full flex-col items-center justify-center py-24">
          <Spinner size="lg" />
          <p className="mt-3 text-sm text-slate-400">Loading…</p>
        </div>
      ) : kind === "paths" ? (
        paths.length === 0 ? (
          <EmptyState title="No draft paths" description="AI-drafted career paths will queue here for review." />
        ) : (
          <div className="space-y-3">
            {paths.map((path) => (
              <div key={path.id} className="bg-white border border-slate-200 rounded-xl p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="font-medium text-sm">
                      {path.title}{" "}
                      <span className="text-slate-400">→ {path.job_title ?? path.job_code}</span>
                    </p>
                    <p className="text-xs text-slate-500">
                      {path.steps.length} steps · source {path.source}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => void moderatePath(path.id, "publish")}
                      className="text-xs bg-emerald-600 text-white rounded-lg px-3 py-1.5"
                    >
                      Publish
                    </button>
                    <button
                      onClick={() => void moderatePath(path.id, "reject")}
                      className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 hover:text-rose-600"
                    >
                      Reject
                    </button>
                  </div>
                </div>
                <ol className="mt-2 space-y-0.5">
                  {path.steps.map((step) => (
                    <li key={step.position} className="text-xs text-slate-500">
                      {step.position + 1}. {step.label || step.kind}
                    </li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
        )
      ) : kind === "skills" ? (
        skills.length === 0 ? (
          <EmptyState title="No skills" />
        ) : (
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-slate-500">
                <tr>
                  <th className="px-4 py-2">Key</th>
                  <th className="px-4 py-2">Label</th>
                  <th className="px-4 py-2">Category</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {[...proposed, ...skills.filter((s) => s.status !== "proposed")].map((skill) => (
                  <tr key={skill.id} className="border-t border-slate-100">
                    <td className="px-4 py-2 font-mono text-xs">{skill.key}</td>
                    <td className="px-4 py-2">
                      {skill.label}
                      {skill.aliases.length > 0 && (
                        <span className="text-xs text-slate-400"> · {skill.aliases.join(", ")}</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-slate-500">{skill.category}</td>
                    <td className="px-4 py-2">
                      {skill.status === "proposed" ? (
                        <span className="text-sky-600">proposed</span>
                      ) : skill.status === "deprecated" ? (
                        <span className="text-amber-600">deprecated</span>
                      ) : (
                        <span className="text-emerald-600">active</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right space-x-2 whitespace-nowrap">
                      {skill.status === "proposed" && (
                        <button
                          onClick={() => void promote(skill)}
                          className="text-xs text-emerald-700 hover:text-emerald-600"
                        >
                          Promote
                        </button>
                      )}
                      {skill.status === "active" ? (
                        <button
                          onClick={() => void setStatus(skill, "deprecated")}
                          className="text-xs text-slate-500 hover:text-primary-700"
                        >
                          Deprecate
                        </button>
                      ) : (
                        <button
                          onClick={() => void setStatus(skill, "active")}
                          className="text-xs text-slate-500 hover:text-primary-700"
                        >
                          Restore
                        </button>
                      )}
                      {skill.status !== "active" && activeSkills.length > 0 && (
                        <button
                          onClick={() => setMerging(merging === skill.id ? null : skill.id)}
                          className="text-xs text-slate-500 hover:text-primary-700"
                        >
                          Merge…
                        </button>
                      )}
                      <button
                        onClick={() => void remove(skill)}
                        className="text-xs text-slate-400 hover:text-rose-600"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {merging && (
              <div className="border-t border-slate-100 bg-slate-50 p-3 flex items-center gap-2">
                <span className="text-xs text-slate-500">
                  Merge {skills.find((s) => s.id === merging)?.key} into:
                </span>
                <select
                  value={mergeTarget}
                  onChange={(e) => setMergeTarget(e.target.value)}
                  className="text-xs border border-slate-200 rounded-lg px-2 py-1"
                >
                  <option value="">Choose active skill…</option>
                  {activeSkills.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.key}
                    </option>
                  ))}
                </select>
                <button
                  onClick={() => {
                    const skill = skills.find((s) => s.id === merging);
                    if (skill && mergeTarget) void doMerge(skill);
                  }}
                  disabled={!mergeTarget}
                  className="text-xs bg-primary-600 text-white rounded-lg px-3 py-1 disabled:opacity-50"
                >
                  Merge
                </button>
                <button
                  onClick={() => setMerging(null)}
                  className="text-xs text-slate-400"
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        )
      ) : tags.length === 0 ? (
        <EmptyState title="No tags" />
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-slate-500">
              <tr>
                <th className="px-4 py-2">Key</th>
                <th className="px-4 py-2">Label</th>
                <th className="px-4 py-2">Category</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {tags.map((tag) => (
                <tr key={tag.id} className="border-t border-slate-100">
                  <td className="px-4 py-2 font-mono text-xs">{tag.key}</td>
                  <td className="px-4 py-2">{tag.label}</td>
                  <td className="px-4 py-2 text-slate-500">{tag.category}</td>
                  <td className="px-4 py-2">
                    {tag.deprecated ? (
                      <span className="text-amber-600">deprecated</span>
                    ) : (
                      <span className="text-emerald-600">active</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right space-x-2 whitespace-nowrap">
                    <button
                      onClick={() => {
                        void updateTag("interests", tag.id, {
                          deprecated: !tag.deprecated,
                        }).then(load);
                      }}
                      className="text-xs text-slate-500 hover:text-primary-700"
                    >
                      {tag.deprecated ? "Restore" : "Deprecate"}
                    </button>
                    <button
                      onClick={() => void remove(tag)}
                      className="text-xs text-slate-400 hover:text-rose-600"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
