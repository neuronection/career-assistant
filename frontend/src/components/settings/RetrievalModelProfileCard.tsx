import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Download, ExternalLink, RotateCcw, Save } from "lucide-react";

import { apiDetail } from "@/api/client";
import {
  deleteRetrievalModelProfile,
  fetchRetrievalTokenizerFetch,
  saveRetrievalModelProfile,
  startRetrievalTokenizerFetch,
  type RetrievalModelProfile,
  type RetrievalModelProfilePayload,
  type RetrievalModelProfilesResponse,
  type RetrievalTokenizerFetchStatus,
} from "@/api/retrieval";
import { Badge, Button } from "@/components/ui";
import {
  NumberField,
  SelectField,
  TextField,
} from "@/features/cv/components/cv/formPrimitives";

interface Draft {
  providerClass: string;
  model: string;
  kind: string;
  identifier: string;
  revision: string;
  sha256: string;
  maxInput: number | null;
  batchItems: number | null;
  batchTokens: number | null;
  chunkTokens: number | null;
  chunkOverlap: number | null;
  chunkChars: number | null;
}

function draftFrom(profile: RetrievalModelProfile): Draft {
  return {
    providerClass: profile.provider_class,
    model: profile.model,
    kind: profile.tokenizer_kind,
    identifier: profile.tokenizer_identifier,
    revision: profile.tokenizer_revision ?? "",
    sha256: profile.tokenizer_artifact_sha256 ?? "",
    maxInput: profile.max_input_tokens,
    batchItems: profile.batch_max_items,
    batchTokens: profile.batch_max_tokens,
    chunkTokens: profile.chunk.max_chunk_tokens,
    chunkOverlap: profile.chunk.overlap_tokens,
    chunkChars: profile.chunk.max_chars,
  };
}

function sourceTone(source: RetrievalModelProfile["source"]) {
  if (source === "admin") return "success" as const;
  if (source === "curated") return "secondary" as const;
  return "warning" as const;
}

const TERMINAL_FETCH_STATUSES = new Set(["succeeded", "failed", "cancelled"]);

/** The admin profile selector: effective tokenizer/limits + a bounded editor. */
export function RetrievalModelProfileCard({
  profiles,
  onRefresh,
}: {
  profiles: RetrievalModelProfilesResponse;
  onRefresh: () => void;
}) {
  const { t } = useTranslation();
  const resolution = profiles.resolution;
  const bounds = profiles.bounds;
  const [draft, setDraft] = useState<Draft>(() => draftFrom(resolution));
  const [busy, setBusy] = useState<"save" | "reset" | "fetch" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [fetchStatus, setFetchStatus] = useState<RetrievalTokenizerFetchStatus | null>(
    null,
  );

  useEffect(() => {
    setDraft(draftFrom(resolution));
    setError("");
    setFetchStatus(null);
  }, [resolution]);

  const isHf = draft.kind === "hf_tokenizers";
  const canFetch =
    isHf &&
    draft.identifier.trim() !== "" &&
    draft.revision.trim() !== "" &&
    busy === null;
  const canSave =
    draft.providerClass.trim() !== "" &&
    draft.model.trim() !== "" &&
    draft.identifier.trim() !== "" &&
    draft.maxInput !== null &&
    draft.batchItems !== null &&
    draft.batchTokens !== null &&
    draft.chunkTokens !== null &&
    draft.chunkOverlap !== null &&
    draft.chunkChars !== null &&
    (!isHf || (draft.revision.trim() !== "" && draft.sha256.trim() !== "")) &&
    busy === null;

  const save = async () => {
    if (!canSave) return;
    const payload: RetrievalModelProfilePayload = {
      provider_class: draft.providerClass.trim(),
      model: draft.model.trim(),
      tokenizer_kind: draft.kind,
      tokenizer_identifier: draft.identifier.trim(),
      ...(draft.revision.trim() ? { tokenizer_revision: draft.revision.trim() } : {}),
      ...(draft.sha256.trim()
        ? { tokenizer_artifact_sha256: draft.sha256.trim() }
        : {}),
      max_input_tokens: draft.maxInput ?? 0,
      batch_max_items: draft.batchItems ?? 0,
      batch_max_tokens: draft.batchTokens ?? 0,
      chunk_max_tokens: draft.chunkTokens ?? 0,
      chunk_overlap_tokens: draft.chunkOverlap ?? 0,
      chunk_max_chars: draft.chunkChars ?? 0,
    };
    setBusy("save");
    setError("");
    setNotice("");
    try {
      await saveRetrievalModelProfile(payload);
      setNotice(t("retrieval.profile.saved"));
      onRefresh();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(null);
    }
  };

  const reset = async () => {
    setBusy("reset");
    setError("");
    setNotice("");
    try {
      await deleteRetrievalModelProfile(resolution.provider_class, resolution.model);
      setNotice(t("retrieval.profile.resetDone"));
      onRefresh();
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(null);
    }
  };

  const fetchTokenizer = async () => {
    if (!canFetch) return;
    setBusy("fetch");
    setError("");
    setNotice("");
    setFetchStatus(null);
    try {
      const started = await startRetrievalTokenizerFetch({
        repository: draft.identifier.trim(),
        revision: draft.revision.trim(),
        ...(draft.sha256.trim() ? { expected_sha256: draft.sha256.trim() } : {}),
      });
      let status = await fetchRetrievalTokenizerFetch(started.job_id);
      setFetchStatus(status);
      let attempts = 0;
      while (!TERMINAL_FETCH_STATUSES.has(status.status) && attempts < 60) {
        attempts += 1;
        await new Promise((resolve) => setTimeout(resolve, 1000));
        status = await fetchRetrievalTokenizerFetch(started.job_id);
        setFetchStatus(status);
      }
      if (status.status === "succeeded" && status.result) {
        setDraft((current) => ({ ...current, sha256: status.result?.sha256 ?? "" }));
        setNotice(
          t("retrieval.profile.fetchDone", {
            sha: status.result.sha256.slice(0, 12),
          }),
        );
      } else {
        setError(status.error || t("retrieval.profile.fetchFailed"));
      }
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(null);
    }
  };

  const selectedKindLabel = t(`retrieval.profile.kindName.${draft.kind}`, {
    defaultValue: draft.kind,
  });

  return (
    <div
      className="space-y-3 rounded-lg border border-[var(--as-border)] p-2"
      data-testid="retrieval-model-profile"
    >
      <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--as-muted-fg)]">
        <Badge variant={sourceTone(resolution.source)}>
          {t(`retrieval.profile.source.${resolution.source}`)}
        </Badge>
        <Badge variant={resolution.exact ? "success" : "warning"}>
          {resolution.exact
            ? t("retrieval.tokenizer.exact")
            : t("retrieval.tokenizer.approximate")}
        </Badge>
        {resolution.override && (
          <Badge variant="warning">{t("retrieval.profile.overridden")}</Badge>
        )}
        <span data-testid="retrieval-profile-identity">
          {t("retrieval.tokenizer.tokenizer")}:{" "}
          <strong className="text-[var(--as-fg)]">{resolution.identity}</strong>
        </span>
        <span data-testid="retrieval-profile-limit">
          {t("retrieval.tokenizer.maxInput")}:{" "}
          <strong className="text-[var(--as-fg)]">{resolution.max_input_tokens}</strong>
          {resolution.max_input_assumed ? ` (${t("retrieval.tokenizer.assumed")})` : ""}
        </span>
      </div>

      <div className="grid gap-1 text-xs text-[var(--as-muted-fg)] sm:grid-cols-2">
        <p data-testid="retrieval-profile-batch">
          {t("retrieval.profile.batch", {
            items: resolution.batch_max_items,
            tokens: resolution.batch_max_tokens,
          })}
        </p>
        <p data-testid="retrieval-profile-chunk">
          {t("retrieval.profile.chunk", {
            tokens: resolution.chunk.max_chunk_tokens,
            overlap: resolution.chunk.overlap_tokens,
            chars: resolution.chunk.max_chars,
          })}
        </p>
      </div>

      {(resolution.family || resolution.license || resolution.source_url) && (
        <p
          className="flex flex-wrap items-center gap-1.5 text-xs text-[var(--as-muted-fg)]"
          data-testid="retrieval-profile-provenance"
        >
          {resolution.family && <span>{t("retrieval.profile.family", { family: resolution.family })}</span>}
          {resolution.license && <span>· {t("retrieval.profile.license", { license: resolution.license })}</span>}
          {resolution.source_url && (
            <a
              className="inline-flex items-center gap-0.5 underline"
              href={resolution.source_url}
              target="_blank"
              rel="noreferrer"
            >
              {t("retrieval.profile.sourceLink")}
              <ExternalLink className="h-3 w-3" aria-hidden />
            </a>
          )}
        </p>
      )}

      {(!resolution.usable || !resolution.tokenizer_available) && (
        <p
          className="flex items-start gap-1.5 text-xs text-[var(--as-warning)]"
          data-testid="retrieval-profile-unavailable"
          role="status"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>
            {!resolution.usable
              ? t("retrieval.profile.unavailable", {
                  reason: resolution.usable_reason ?? "unsupported",
                })
              : t("retrieval.profile.assetMissing")}
          </span>
        </p>
      )}

      {(resolution.source === "fallback" ||
        resolution.degraded_reason ||
        resolution.max_input_assumed) && (
        <p
          className="flex items-start gap-1.5 text-xs text-[var(--as-warning)]"
          data-testid="retrieval-profile-warning"
          role="status"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>
            {resolution.degraded_reason
              ? t("retrieval.tokenizer.degraded", {
                  reason: resolution.degraded_reason,
                })
              : resolution.source === "fallback"
                ? t("retrieval.profile.fallbackWarning")
                : t("retrieval.tokenizer.assumedWarning")}
          </span>
        </p>
      )}

      <details className="rounded-md bg-[color-mix(in_srgb,var(--as-muted)_35%,transparent)] p-2">
        <summary className="cursor-pointer text-xs font-medium text-[var(--as-fg)]">
          {t("retrieval.profile.edit")}
        </summary>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <TextField
            label={t("retrieval.profile.providerClass")}
            value={draft.providerClass}
            onChange={(value) => setDraft({ ...draft, providerClass: value })}
            maxLength={bounds.max_provider_class_length}
            testId="retrieval-profile-provider-class"
          />
          <TextField
            label={t("retrieval.profile.model")}
            value={draft.model}
            onChange={(value) => setDraft({ ...draft, model: value })}
            maxLength={bounds.max_model_length}
            testId="retrieval-profile-model"
          />
          <SelectField
            label={t("retrieval.profile.kind")}
            value={draft.kind}
            onChange={(value) => setDraft({ ...draft, kind: value })}
            options={bounds.supported_kinds.map((kind) => ({
              value: kind,
              label: t(`retrieval.profile.kindName.${kind}`, { defaultValue: kind }),
            }))}
            testId="retrieval-profile-kind"
          />
          <TextField
            label={
              isHf
                ? t("retrieval.profile.repository")
                : t("retrieval.profile.identifier")
            }
            value={draft.identifier}
            onChange={(value) => setDraft({ ...draft, identifier: value })}
            maxLength={bounds.max_identifier_length}
            testId="retrieval-profile-identifier"
          />
          {(draft.kind === "tiktoken" || isHf) && (
            <>
              <TextField
                label={
                  isHf
                    ? t("retrieval.profile.pinnedRevision")
                    : t("retrieval.profile.revision")
                }
                value={draft.revision}
                onChange={(value) => setDraft({ ...draft, revision: value })}
                maxLength={bounds.max_revision_length}
                testId="retrieval-profile-revision"
              />
              <TextField
                label={t("retrieval.profile.checksum")}
                value={draft.sha256}
                onChange={(value) => setDraft({ ...draft, sha256: value })}
                maxLength={64}
                testId="retrieval-profile-sha256"
              />
            </>
          )}
          {isHf && (
            <div className="sm:col-span-2" data-testid="retrieval-profile-fetch-block">
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!canFetch}
                  loading={busy === "fetch"}
                  onClick={() => void fetchTokenizer()}
                  data-testid="retrieval-profile-fetch"
                >
                  <Download className="h-3.5 w-3.5" aria-hidden />
                  {t("retrieval.profile.fetch")}
                </Button>
                <span
                  className="text-[11px] text-[var(--as-muted-fg)]"
                  data-testid="retrieval-profile-fetch-status"
                  role="status"
                >
                  {fetchStatus
                    ? t("retrieval.profile.fetchStatus", {
                        status: fetchStatus.status,
                        progress: fetchStatus.progress,
                      })
                    : t("retrieval.profile.fetchHint", {
                        kind: selectedKindLabel,
                        file: bounds.hf_tokenizer_filename,
                      })}
                </span>
              </div>
            </div>
          )}
          <NumberField
            label={t("retrieval.profile.maxInput")}
            value={draft.maxInput}
            onChange={(value) => setDraft({ ...draft, maxInput: value })}
            min={1}
            max={bounds.max_input_tokens}
            testId="retrieval-profile-max-input"
          />
          <NumberField
            label={t("retrieval.profile.batchItems")}
            value={draft.batchItems}
            onChange={(value) => setDraft({ ...draft, batchItems: value })}
            min={1}
            max={bounds.max_batch_items}
            testId="retrieval-profile-batch-items"
          />
          <NumberField
            label={t("retrieval.profile.batchTokens")}
            value={draft.batchTokens}
            onChange={(value) => setDraft({ ...draft, batchTokens: value })}
            min={1}
            max={bounds.max_batch_tokens}
            testId="retrieval-profile-batch-tokens"
          />
          <NumberField
            label={t("retrieval.profile.chunkTokens")}
            value={draft.chunkTokens}
            onChange={(value) => setDraft({ ...draft, chunkTokens: value })}
            min={32}
            max={bounds.max_chunk_tokens}
            testId="retrieval-profile-chunk-tokens"
          />
          <NumberField
            label={t("retrieval.profile.chunkOverlap")}
            value={draft.chunkOverlap}
            onChange={(value) => setDraft({ ...draft, chunkOverlap: value })}
            min={0}
            max={bounds.max_chunk_tokens}
            testId="retrieval-profile-chunk-overlap"
          />
          <NumberField
            label={t("retrieval.profile.chunkChars")}
            value={draft.chunkChars}
            onChange={(value) => setDraft({ ...draft, chunkChars: value })}
            min={1}
            max={bounds.max_chunk_chars}
            testId="retrieval-profile-chunk-chars"
          />
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            disabled={!canSave}
            loading={busy === "save"}
            onClick={() => void save()}
            data-testid="retrieval-profile-save"
          >
            <Save className="h-3.5 w-3.5" aria-hidden />
            {t("retrieval.profile.save")}
          </Button>
          {resolution.override && (
            <Button
              size="sm"
              variant="outline"
              disabled={busy !== null}
              loading={busy === "reset"}
              onClick={() => void reset()}
              data-testid="retrieval-profile-reset"
            >
              <RotateCcw className="h-3.5 w-3.5" aria-hidden />
              {t("retrieval.profile.reset")}
            </Button>
          )}
        </div>
        {error && (
          <p className="mt-1 text-xs text-[var(--as-danger)]" role="alert">
            {error}
          </p>
        )}
        {notice && (
          <p className="mt-1 text-xs text-[var(--as-success)]" role="status">
            {notice}
          </p>
        )}
        <p className="mt-2 text-[11px] text-[var(--as-muted-fg)]">
          {t("retrieval.profile.note")}
        </p>
      </details>
    </div>
  );
}
