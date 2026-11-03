import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowUpRight,
  Database,
  Download,
  Layers,
  Plus,
  RefreshCw,
  ShieldCheck,
  Target,
  Wrench,
} from "lucide-react";

import { apiDetail } from "@/api/client";
import {
  activateRetrievalSpace,
  buildRetrievalSpace,
  cancelRetrievalRun,
  compareRetrievalQuality,
  dropRetrievalSpace,
  fetchRetrievalCoverage,
  fetchRetrievalHealth,
  fetchRetrievalOverview,
  fetchRetrievalQuality,
  fetchRetrievalRuns,
  fetchRetrievalSpaces,
  reindexRetrievalSpace,
  retireRetrievalSpace,
  retryRetrievalRun,
  retrievalActionError,
  runRetrievalMaintenance,
  type BuildSpacePayload,
  type MaintenanceAction,
  type RetrievalActionResponse,
  type RetrievalCoverage,
  type RetrievalGate,
  type RetrievalHealth,
  type RetrievalOverview,
  type RetrievalQuality,
  type RetrievalRefusal,
  type RetrievalRun,
  type RetrievalRunsResponse,
  type RetrievalSpace,
  type RetrievalSpacesResponse,
} from "@/api/retrieval";
import {
  Badge,
  Button,
  EmptyState,
  Modal,
  ModalBody,
  ModalContent,
  ModalDescription,
  ModalFooter,
  ModalHeader,
  ModalTitle,
  Spinner,
} from "@/components/ui";
import { SettingsSectionCard } from "@/components/settings/SettingsSectionCard";
import { StatTiles, type StatTile } from "@/components/stats/StatTiles";
import {
  NumberField,
  SelectField,
  TextField,
  ToggleRow,
} from "@/features/cv/components/cv/formPrimitives";

const RETRIEVAL_KINDS = ["posting", "job", "profile", "skill"] as const;
const RETRIEVAL_VIEWS = [
  "summary",
  "requirements",
  "responsibilities",
  "skills",
  "body",
] as const;
const MAINTENANCE_ACTIONS: MaintenanceAction[] = [
  "index-rebuild",
  "vacuum",
  "orphan-sweep",
  "retry-failed",
];
const RUN_PAGE = 6;

type CardKey = "reindex" | "spaces" | "maintenance" | "quality" | "danger";
type NoticeTone = "ok" | "error";
interface Notice {
  card: CardKey;
  tone: NoticeTone;
  text: string;
  result?: RetrievalActionResponse;
  refusal?: RetrievalRefusal | null;
}
type TypedIntent =
  | { action: "retire"; space: RetrievalSpace }
  | { action: "drop"; space: RetrievalSpace }
  | null;

const rate = (value: number | null | undefined): string =>
  value == null ? "—" : `${(value * 100).toFixed(1)}%`;
const shortId = (value: string | null): string => (value ? value.slice(0, 8) : "—");
const when = (value: string | null): string =>
  value ? new Date(value).toLocaleString() : "—";

const gateVariant = (gate: RetrievalGate): "success" | "danger" | "secondary" =>
  gate === "pass" ? "success" : gate === "fail" ? "danger" : "secondary";

const statusVariant = (
  status: string,
): "success" | "danger" | "warning" | "secondary" => {
  if (status === "succeeded" || status === "active" || status === "ok") return "success";
  if (status === "failed" || status === "retired") return "danger";
  if (status === "queued" || status === "running" || status === "building") return "warning";
  return "secondary";
};

function actionResultText(
  t: (key: string, options?: Record<string, unknown>) => string,
  result: RetrievalActionResponse,
): string {
  if (result.action === "maintenance" && result.dry_run) {
    return t("retrieval.result.dryRun");
  }
  if (result.action === "quality_compare") {
    return result.quality?.passed
      ? t("retrieval.result.qualityPassed")
      : t("retrieval.result.qualityFailed");
  }
  return t(`retrieval.result.${result.action}`, { defaultValue: result.message });
}

function ActionNotice({ notice }: { notice: Notice | null }) {
  const { t } = useTranslation();
  if (!notice) return null;
  const result = notice.result;
  const queued = result && (result.status === "queued" || result.status === "running");
  const refusal = notice.refusal;
  return (
    <div
      className={`rounded-lg border p-2 text-xs ${
        notice.tone === "ok"
          ? "border-[color-mix(in_srgb,var(--as-success)_35%,var(--as-border))] text-[var(--as-fg)]"
          : "border-[color-mix(in_srgb,var(--as-danger)_35%,var(--as-border))] text-[var(--as-fg)]"
      }`}
      data-testid={`retrieval-notice-${notice.card}`}
      role={notice.tone === "error" ? "alert" : "status"}
    >
      <p>{notice.text}</p>
      {result?.message && result.message !== notice.text && (
        <p className="mt-0.5 text-[var(--as-muted-fg)]">{result.message}</p>
      )}
      {result?.run_id && (
        <p className="mt-1 text-[var(--as-muted-fg)]" data-testid="retrieval-queued-run">
          {t("retrieval.action.queuedRun", {
            id: shortId(result.run_id),
            status: t(`retrieval.status.${result.status ?? "queued"}`),
          })}
          {result.deduplicated ? ` · ${t("retrieval.action.deduplicated")}` : ""}
        </p>
      )}
      {queued && (
        <p className="mt-1 text-[var(--as-muted-fg)]">{t("retrieval.action.notFinished")}</p>
      )}
      {refusal?.activation_gate && (
        <div className="mt-1 space-y-0.5" data-testid="retrieval-gate-refusal">
          <p>
            {t("retrieval.gateLabel.coverage")}:{" "}
            {t(`retrieval.gate.${refusal.activation_gate.coverage}`)} ·{" "}
            {t("retrieval.gateLabel.quality")}:{" "}
            {t(`retrieval.gate.${refusal.activation_gate.quality}`)}
          </p>
          {refusal.activation_gate.reasons.length > 0 && (
            <p className="text-[var(--as-muted-fg)]">
              {refusal.activation_gate.reasons.join(", ")}
            </p>
          )}
        </div>
      )}
      {refusal?.quality && (
        <p className="mt-1 text-[var(--as-muted-fg)]">
          {t("retrieval.quality.recall")}: {rate(refusal.quality.new_recall_at_k)} ·{" "}
          {t("retrieval.quality.precision")}: {rate(refusal.quality.new_precision_at_k)}
        </p>
      )}
    </div>
  );
}

function TypedConfirmModal({
  open,
  onOpenChange,
  title,
  description,
  expectedName,
  confirmLabel,
  busy,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  expectedName: string;
  confirmLabel: string;
  busy: boolean;
  onConfirm: (typedName: string) => void;
}) {
  const { t } = useTranslation();
  const [typed, setTyped] = useState("");
  useEffect(() => {
    if (open) setTyped("");
  }, [open]);
  const matches = typed === expectedName;
  return (
    <Modal open={open} onOpenChange={onOpenChange}>
      <ModalContent size="sm">
        <ModalHeader>
          <ModalTitle>{title}</ModalTitle>
          <ModalDescription>{description}</ModalDescription>
        </ModalHeader>
        <ModalBody className="space-y-2">
          <TextField
            label={t("retrieval.confirm.typedLabel")}
            value={typed}
            onChange={setTyped}
            placeholder={expectedName}
            testId="retrieval-typed-confirm"
          />
          <p className="text-xs text-[var(--as-muted-fg)]">
            {matches ? expectedName : t("retrieval.confirm.wrongName")}
          </p>
        </ModalBody>
        <ModalFooter>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onOpenChange(false)}
            disabled={busy}
          >
            {t("retrieval.action.cancelAction")}
          </Button>
          <Button
            variant="destructive"
            size="sm"
            disabled={!matches || busy}
            loading={busy}
            onClick={() => onConfirm(typed)}
            data-testid="retrieval-typed-confirm-submit"
          >
            {confirmLabel}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

function RunRow({
  run,
  busy,
  onCancel,
  onRetry,
}: {
  run: RetrievalRun;
  busy: boolean;
  onCancel: (run: RetrievalRun) => void;
  onRetry: (run: RetrievalRun) => void;
}) {
  const { t } = useTranslation();
  const active = run.status === "queued" || run.status === "running";
  const retryable = run.status === "failed" || run.status === "cancelled";
  return (
    <div
      className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] px-3 py-2"
      data-testid={`retrieval-run-${run.run_id}`}
    >
      <div className="min-w-0 space-y-0.5">
        <p className="flex flex-wrap items-center gap-2 text-xs font-medium text-[var(--as-fg)]">
          <Badge variant={statusVariant(run.status)}>
            {t(`retrieval.status.${run.status}`)}
          </Badge>
          <span>{t(`retrieval.runType.${run.job_type}`)}</span>
          <span className="font-mono text-[11px] text-[var(--as-muted-fg)]">
            {shortId(run.run_id)}
          </span>
        </p>
        <p className="text-[11px] text-[var(--as-muted-fg)]">
          {t("retrieval.reindex.scope")}:{" "}
          {run.scope.kind ?? t("retrieval.kind.all")} · {run.scope.view ?? t("retrieval.view.all")}
          {run.progress > 0 ? ` · ${t("retrieval.reindex.showProgress", { progress: run.progress })}` : ""}
        </p>
      </div>
      <div className="flex items-center gap-2">
        {active && !run.cancel_requested && (
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => onCancel(run)}
            data-testid={`retrieval-cancel-${run.run_id}`}
          >
            {t("retrieval.action.cancel")}
          </Button>
        )}
        {run.cancel_requested && (
          <Badge variant="warning">{t("retrieval.status.cancelled")}</Badge>
        )}
        {retryable && (
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => onRetry(run)}
            data-testid={`retrieval-retry-${run.run_id}`}
          >
            {t("retrieval.action.retry")}
          </Button>
        )}
      </div>
    </div>
  );
}

function QualitySummary({
  quality,
  compare,
}: {
  quality: RetrievalQuality | null;
  compare?: RetrievalActionResponse["quality"];
}) {
  const { t } = useTranslation();
  if (compare) {
    return (
      <div className="space-y-1" data-testid="retrieval-quality-compare">
        <p className="flex flex-wrap items-center gap-2 text-xs">
          <Badge variant={compare.passed ? "success" : "danger"}>
            {compare.passed ? t("retrieval.gate.pass") : t("retrieval.gate.fail")}
          </Badge>
          <span>v{compare.set_version}</span>
        </p>
        <p className="text-xs text-[var(--as-muted-fg)]">
          {t("retrieval.quality.recall")}: {rate(compare.new_recall_at_k)}{" "}
          {t("retrieval.quality.floor", { value: rate(compare.floor_recall) })} ·{" "}
          {t("retrieval.quality.precision")}: {rate(compare.new_precision_at_k)}{" "}
          {t("retrieval.quality.floor", { value: rate(compare.floor_precision) })}
        </p>
        <p className="text-xs text-[var(--as-muted-fg)]">
          {t("retrieval.quality.candidateVsBaseline", {
            candidate: shortId(compare.new_space_id),
            baseline: shortId(compare.old_space_id),
          })}
        </p>
      </div>
    );
  }
  const block = quality?.quality ?? null;
  if (!quality) {
    return <p className="text-xs text-[var(--as-muted-fg)]">{t("retrieval.state.loading")}</p>;
  }
  if (quality.state === "no_golden_set") {
    return (
      <p className="text-xs text-[var(--as-muted-fg)]" data-testid="retrieval-quality-state">
        {t("retrieval.state.no_golden_set")}
      </p>
    );
  }
  if (quality.state === "not_sampled" || !block) {
    return (
      <p className="text-xs text-[var(--as-muted-fg)]" data-testid="retrieval-quality-state">
        {t("retrieval.state.not_sampled")}
      </p>
    );
  }
  return (
    <div className="space-y-1" data-testid="retrieval-quality-state">
      <p className="flex flex-wrap items-center gap-2 text-xs">
        <Badge variant={block.passed ? "success" : "danger"}>
          {block.passed ? t("retrieval.gate.pass") : t("retrieval.gate.fail")}
        </Badge>
        {quality.set && (
          <span className="text-[var(--as-muted-fg)]">
            {t("retrieval.quality.setVersion", {
              version: quality.set.set_version,
              count: quality.set.query_count,
            })}
          </span>
        )}
        {quality.state === "stale_compare" && (
          <Badge variant="warning">{t("retrieval.state.stale_compare")}</Badge>
        )}
      </p>
      <p className="text-xs text-[var(--as-muted-fg)]">
        {t("retrieval.quality.recall")}: {rate(block.recall_at_k)} ·{" "}
        {t("retrieval.quality.precision")}: {rate(block.precision_at_k)}
      </p>
    </div>
  );
}

export function RetrievalManagementSection() {
  const { t } = useTranslation();
  const [spaces, setSpaces] = useState<RetrievalSpacesResponse | null>(null);
  const [health, setHealth] = useState<RetrievalHealth | null>(null);
  const [overview, setOverview] = useState<RetrievalOverview | null>(null);
  const [coverage, setCoverage] = useState<RetrievalCoverage | null>(null);
  const [quality, setQuality] = useState<RetrievalQuality | null>(null);
  const [activeQuality, setActiveQuality] = useState<RetrievalQuality | null>(null);
  const [runs, setRuns] = useState<RetrievalRunsResponse | null>(null);
  const [selectedSpace, setSelectedSpace] = useState("");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const [reindexKind, setReindexKind] = useState("");
  const [reindexView, setReindexView] = useState("");
  const [reindexSince, setReindexSince] = useState("");
  const [reindexBudget, setReindexBudget] = useState<number | null>(2000);
  const [reindexLimit, setReindexLimit] = useState<number | null>(200);
  const [reindexForce, setReindexForce] = useState(false);

  const [buildOpen, setBuildOpen] = useState(false);
  const [buildDraft, setBuildDraft] = useState({
    name: "",
    provider: "",
    model: "",
    dim: 1536,
    queryPrefix: "",
    documentPrefix: "",
  });

  const [maintenanceAction, setMaintenanceAction] =
    useState<MaintenanceAction>("index-rebuild");
  const [maintenanceDryRun, setMaintenanceDryRun] = useState(false);
  const [maintenanceLimit, setMaintenanceLimit] = useState<number | null>(null);

  const [candidateSpace, setCandidateSpace] = useState("");
  const [baselineSpace, setBaselineSpace] = useState("");
  const [lastCompare, setLastCompare] = useState<
    RetrievalActionResponse["quality"] | undefined
  >();

  const [typedIntent, setTypedIntent] = useState<TypedIntent>(null);
  const [typedBusy, setTypedBusy] = useState(false);

  const refresh = useCallback(() => setReloadKey((value) => value + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      fetchRetrievalSpaces(),
      fetchRetrievalHealth(),
      fetchRetrievalOverview("24h"),
    ])
      .then(([loadedSpaces, loadedHealth, loadedOverview]) => {
        if (cancelled) return;
        setSpaces(loadedSpaces);
        setHealth(loadedHealth);
        setOverview(loadedOverview);
        setSelectedSpace((current) => {
          if (current && loadedSpaces.spaces.some((space) => space.space_id === current)) {
            return current;
          }
          return (
            loadedSpaces.spaces.find((space) => space.status === "active")?.space_id ??
            loadedSpaces.spaces[0]?.space_id ??
            ""
          );
        });
        setBaselineSpace((current) => {
          if (current) return current;
          return loadedSpaces.spaces.find((space) => space.status === "active")?.space_id ?? "";
        });
        setCandidateSpace((current) => {
          if (current) return current;
          return (
            loadedSpaces.spaces.find((space) => space.status === "building")?.space_id ??
            loadedSpaces.spaces.find((space) => space.status === "active")?.space_id ??
            ""
          );
        });
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(retrievalActionError(err).detail);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const activeSpace = useMemo(
    () => spaces?.spaces.find((space) => space.status === "active") ?? null,
    [spaces],
  );
  const activeHealth = useMemo(
    () => health?.spaces.find((space) => space.space_id === activeSpace?.space_id) ?? null,
    [health, activeSpace],
  );
  const activeSpaceId = activeSpace?.space_id ?? "";

  useEffect(() => {
    if (!activeSpaceId) {
      setActiveQuality(null);
      return;
    }
    let cancelled = false;
    fetchRetrievalQuality(activeSpaceId)
      .then((loaded) => {
        if (!cancelled) setActiveQuality(loaded);
      })
      .catch(() => {
        if (!cancelled) setActiveQuality(null);
      });
    return () => {
      cancelled = true;
    };
  }, [activeSpaceId, reloadKey]);

  useEffect(() => {
    if (!selectedSpace) {
      setCoverage(null);
      setQuality(null);
      setRuns(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    Promise.all([
      fetchRetrievalCoverage(selectedSpace),
      fetchRetrievalQuality(selectedSpace),
      fetchRetrievalRuns({ space: selectedSpace, limit: RUN_PAGE, window: "7d" }),
    ])
      .then(([loadedCoverage, loadedQuality, loadedRuns]) => {
        if (cancelled) return;
        setCoverage(loadedCoverage);
        setQuality(loadedQuality);
        setRuns(loadedRuns);
      })
      .catch((err) => {
        if (!cancelled) setError(retrievalActionError(err).detail);
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedSpace, reloadKey]);

  const spaceOptions = useMemo(
    () =>
      (spaces?.spaces ?? []).map((space) => ({
        value: space.space_id,
        label: `${space.name} · ${t(`retrieval.spaceStatus.${space.status}`)}`,
      })),
    [spaces, t],
  );

  const busyWith = async <T,>(
    card: CardKey,
    action: () => Promise<T>,
  ): Promise<T | null> => {
    setBusy(card);
    setNotice(null);
    try {
      return await action();
    } finally {
      setBusy("");
    }
  };

  const recordError = (card: CardKey, err: unknown) => {
    const info = retrievalActionError(err);
    setNotice({
      card,
      tone: "error",
      text: info.detail,
      refusal: info.payload,
    });
  };

  const submitReindex = async () => {
    if (!selectedSpace) return;
    const result = await busyWith("reindex", () =>
      reindexRetrievalSpace({
        space: selectedSpace,
        ...(reindexKind ? { kind: reindexKind } : {}),
        ...(reindexView ? { view: reindexView } : {}),
        ...(reindexSince.trim() ? { since: reindexSince.trim() } : {}),
        budget: reindexBudget ?? 2000,
        limit: reindexLimit ?? 200,
        force: reindexForce,
      }),
    );
    if (result) {
      setNotice({ card: "reindex", tone: "ok", text: actionResultText(t, result), result });
      refresh();
    }
  };

  const submitBuild = async () => {
    if (!buildDraft.name.trim() || !buildDraft.provider.trim() || !buildDraft.model.trim()) {
      return;
    }
    const payload: BuildSpacePayload = {
      name: buildDraft.name.trim(),
      provider: buildDraft.provider.trim(),
      model: buildDraft.model.trim(),
      dim: buildDraft.dim,
      query_prefix: buildDraft.queryPrefix.trim() || undefined,
      document_prefix: buildDraft.documentPrefix.trim() || undefined,
    };
    try {
      const result = await busyWith("spaces", () => buildRetrievalSpace(payload));
      if (result) {
        setNotice({ card: "spaces", tone: "ok", text: actionResultText(t, result), result });
        setBuildOpen(false);
        setBuildDraft({
          name: "",
          provider: "",
          model: "",
          dim: 1536,
          queryPrefix: "",
          documentPrefix: "",
        });
        refresh();
      }
    } catch (err) {
      recordError("spaces", err);
    }
  };

  const activate = async (space: RetrievalSpace) => {
    try {
      const result = await busyWith("spaces", () => activateRetrievalSpace(space.space_id));
      if (result) {
        setNotice({ card: "spaces", tone: "ok", text: actionResultText(t, result), result });
        refresh();
      }
    } catch (err) {
      recordError("spaces", err);
    }
  };

  const submitMaintenance = async () => {
    if (!selectedSpace) return;
    try {
      const result = await busyWith("maintenance", () =>
        runRetrievalMaintenance({
          space: selectedSpace,
          action: maintenanceAction,
          dry_run: maintenanceDryRun,
          ...(maintenanceLimit ? { limit: maintenanceLimit } : {}),
        }),
      );
      if (result) {
        setNotice({ card: "maintenance", tone: "ok", text: actionResultText(t, result), result });
        refresh();
      }
    } catch (err) {
      recordError("maintenance", err);
    }
  };

  const submitCompare = async () => {
    if (!candidateSpace || !baselineSpace || candidateSpace === baselineSpace) return;
    try {
      const result = await busyWith("quality", () =>
        compareRetrievalQuality({
          space: candidateSpace,
          compare_space: baselineSpace,
        }),
      );
      if (result) {
        setLastCompare(result.quality);
        setNotice({
          card: "quality",
          tone: result.quality?.passed ? "ok" : "error",
          text: actionResultText(t, result),
          result,
        });
        refresh();
      }
    } catch (err) {
      recordError("quality", err);
    }
  };

  const submitTyped = async (typedName: string) => {
    if (!typedIntent) return;
    const { action, space } = typedIntent;
    setTypedBusy(true);
    setNotice(null);
    try {
      const result =
        action === "retire"
          ? await retireRetrievalSpace(space.space_id, typedName)
          : await dropRetrievalSpace(space.space_id, typedName);
      setNotice({
        card: action === "retire" ? "spaces" : "danger",
        tone: "ok",
        text: actionResultText(t, result),
        result,
      });
      setTypedIntent(null);
      refresh();
    } catch (err) {
      const info = retrievalActionError(err);
      setNotice({
        card: action === "retire" ? "spaces" : "danger",
        tone: "error",
        text: info.detail,
        refusal: info.payload,
      });
    } finally {
      setTypedBusy(false);
    }
  };

  const cancelRun = async (run: RetrievalRun) => {
    try {
      const result = await busyWith("reindex", () => cancelRetrievalRun(run.run_id));
      if (result) {
        setNotice({ card: "reindex", tone: "ok", text: actionResultText(t, result), result });
        refresh();
      }
    } catch (err) {
      recordError("reindex", err);
    }
  };

  const retryRun = async (run: RetrievalRun) => {
    try {
      const result = await busyWith("reindex", () => retryRetrievalRun(run.run_id));
      if (result) {
        setNotice({ card: "reindex", tone: "ok", text: actionResultText(t, result), result });
        refresh();
      }
    } catch (err) {
      recordError("reindex", err);
    }
  };

  const exportStatus = async () => {
    setBusy("danger");
    setNotice(null);
    try {
      const [freshHealth, freshSpaces, freshOverview] = await Promise.all([
        fetchRetrievalHealth(),
        fetchRetrievalSpaces(),
        fetchRetrievalOverview("24h"),
      ]);
      const payload = {
        exported_at: new Date().toISOString(),
        health: freshHealth,
        spaces: freshSpaces.spaces,
        overview: freshOverview,
      };
      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `retrieval-status-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setNotice({ card: "danger", tone: "ok", text: t("retrieval.action.exported") });
    } catch (err) {
      setNotice({ card: "danger", tone: "error", text: apiDetail(err) });
    } finally {
      setBusy("");
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20" data-testid="retrieval-management-loading">
        <Spinner size="lg" />
        <p className="mt-3 text-sm text-[var(--as-muted-fg)]">{t("retrieval.loading")}</p>
      </div>
    );
  }

  if (error && !spaces) {
    return (
      <div className="rounded-xl border border-[var(--as-border)] bg-[var(--as-surface)] p-4" data-testid="retrieval-management-error">
        <p className="text-sm text-rose-600">{error}</p>
        <Button size="sm" variant="outline" className="mt-3" onClick={refresh}>
          {t("retrieval.refresh")}
        </Button>
      </div>
    );
  }

  const activeStats: StatTile[] = activeSpace
    ? [
        {
          label: t("retrieval.active.coverage"),
          value: rate(activeSpace.coverage),
          hint: activeSpace.as_of
            ? `${t("retrieval.active.asOf")} ${when(activeSpace.as_of)}`
            : t("retrieval.state.never_reconciled"),
          title: activeSpace.coverage == null ? undefined : String(activeSpace.coverage),
        },
        {
          label: t("retrieval.active.gate"),
          value: (
            <Badge variant={gateVariant(activeSpace.gate)}>
              {t(`retrieval.gate.${activeSpace.gate}`)}
            </Badge>
          ),
        },
        {
          label: t("retrieval.quality.heading"),
          value: activeQuality?.quality ? (
            <Badge variant={activeQuality.quality.passed ? "success" : "danger"}>
              {activeQuality.quality.passed
                ? t("retrieval.gate.pass")
                : t("retrieval.gate.fail")}
            </Badge>
          ) : (
            <span className="text-sm font-medium">
              {activeQuality?.state
                ? t(`retrieval.state.${activeQuality.state}`)
                : t("retrieval.state.not_sampled")}
            </span>
          ),
        },
        { label: t("retrieval.active.documents"), value: activeSpace.documents },
        { label: t("retrieval.active.records"), value: activeSpace.records },
        {
          label: t("retrieval.active.lastReindex"),
          value: when(activeSpace.last_reindex_at),
        },
      ]
    : [];

  const retiredSpaces = (spaces?.spaces ?? []).filter(
    (space) => space.status === "retired",
  );

  return (
    <div className="space-y-5" data-testid="retrieval-management">
      {error && (
        <p className="text-sm text-rose-600" role="alert">
          {error}
        </p>
      )}

      <SettingsSectionCard
        name="retrieval-active"
        icon={Database}
        title={t("retrieval.card.active.title")}
        description={t("retrieval.card.active.description")}
        adminOnly
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="ghost" onClick={refresh} data-testid="retrieval-refresh">
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
              {t("retrieval.refresh")}
            </Button>
            <Button size="sm" variant="outline" asChild>
              <Link to="/settings/audit?tab=retrieval&section=overview" data-testid="retrieval-audit-link">
                {t("retrieval.auditLink")}
                <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
              </Link>
            </Button>
          </div>
        }
      >
        {!activeSpace ? (
          <EmptyState
            icon={Database}
            title={t("retrieval.active.empty")}
            description={t("retrieval.active.emptyBody")}
          />
        ) : (
          <div className="space-y-3" data-testid="retrieval-active-space">
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-[var(--as-muted-fg)]">
              <span>
                {t("retrieval.active.spaceName")}:{" "}
                <strong className="text-[var(--as-fg)]">{activeSpace.name}</strong>
              </span>
              <span data-testid="retrieval-active-backend">
                {t("retrieval.active.backend")}:{" "}
                <strong className="text-[var(--as-fg)]">
                  {overview?.backend.label ?? spaces?.backend.label ?? activeSpace.backend}
                </strong>
              </span>
              <span data-testid="retrieval-active-model">
                {t("retrieval.active.model")}:{" "}
                <strong className="text-[var(--as-fg)]">
                  {activeSpace.provider}/{activeSpace.model} · {activeSpace.dim}
                </strong>
              </span>
              <span>
                {t("retrieval.active.health")}:{" "}
                <Badge variant={activeHealth?.ok ? "success" : "danger"}>
                  {activeHealth?.ok
                    ? t("retrieval.active.healthOk")
                    : t("retrieval.active.healthFailed")}
                </Badge>
              </span>
            </div>
            <StatTiles tiles={activeStats} layout="auto" testId="retrieval-active-stats" />
            {activeSpace.last_error && (
              <p className="text-xs text-rose-600" data-testid="retrieval-active-last-error">
                {activeSpace.last_error}
              </p>
            )}
          </div>
        )}
      </SettingsSectionCard>

      <SettingsSectionCard
        name="retrieval-reindex"
        icon={RefreshCw}
        title={t("retrieval.reindex.heading")}
        description={t("retrieval.card.reindex.description")}
        adminOnly
      >
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <SelectField
              label={t("retrieval.field.space")}
              value={selectedSpace}
              onChange={setSelectedSpace}
              options={spaceOptions}
              testId="retrieval-reindex-space"
            />
            <SelectField
              label={t("retrieval.field.kind")}
              value={reindexKind}
              onChange={setReindexKind}
              options={[
                { value: "", label: t("retrieval.kind.all") },
                ...RETRIEVAL_KINDS.map((kind) => ({
                  value: kind,
                  label: t(`retrieval.kind.${kind}`),
                })),
              ]}
              testId="retrieval-reindex-kind"
            />
            <SelectField
              label={t("retrieval.field.view")}
              value={reindexView}
              onChange={setReindexView}
              options={[
                { value: "", label: t("retrieval.view.all") },
                ...RETRIEVAL_VIEWS.map((view) => ({
                  value: view,
                  label: t(`retrieval.view.${view}`),
                })),
              ]}
              testId="retrieval-reindex-view"
            />
            <TextField
              label={t("retrieval.field.since")}
              value={reindexSince}
              onChange={setReindexSince}
              placeholder={t("retrieval.field.sincePlaceholder")}
              testId="retrieval-reindex-since"
            />
            <NumberField
              label={t("retrieval.field.budget")}
              value={reindexBudget}
              onChange={setReindexBudget}
              min={0}
              max={100000}
              testId="retrieval-reindex-budget"
            />
            <NumberField
              label={t("retrieval.field.limit")}
              value={reindexLimit}
              onChange={setReindexLimit}
              min={1}
              max={5000}
              testId="retrieval-reindex-limit"
            />
          </div>
          <ToggleRow
            label={t("retrieval.field.force")}
            checked={reindexForce}
            onChange={setReindexForce}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              disabled={!selectedSpace || busy === "reindex"}
              loading={busy === "reindex"}
              onClick={() => void submitReindex()}
              data-testid="retrieval-reindex-submit"
            >
              {t("retrieval.action.reindex")}
            </Button>
            {coverage && (
              <span className="text-xs text-[var(--as-muted-fg)]" data-testid="retrieval-coverage-state">
                {coverage.state === "never_reconciled"
                  ? t("retrieval.state.never_reconciled")
                  : `${t("retrieval.active.coverage")}: ${rate(coverage.coverage.coverage)}`}
              </span>
            )}
          </div>
          <ActionNotice notice={notice?.card === "reindex" ? notice : null} />
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
              {t("retrieval.reindex.recent")}
            </p>
            {detailLoading ? (
              <div className="flex justify-center py-4">
                <Spinner />
              </div>
            ) : !runs || runs.runs.length === 0 ? (
              <p className="text-xs text-[var(--as-muted-fg)]">{t("retrieval.reindex.emptyRuns")}</p>
            ) : (
              <div className="space-y-2">
                {runs.runs.map((run) => (
                  <RunRow
                    key={run.run_id}
                    run={run}
                    busy={busy === "reindex"}
                    onCancel={(entry) => void cancelRun(entry)}
                    onRetry={(entry) => void retryRun(entry)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      </SettingsSectionCard>

      <SettingsSectionCard
        name="retrieval-spaces"
        icon={Layers}
        title={t("retrieval.spaces.heading")}
        description={t("retrieval.card.spaces.description")}
        adminOnly
        actions={
          <Button
            size="sm"
            variant="outline"
            onClick={() => setBuildOpen((open) => !open)}
            data-testid="retrieval-build-toggle"
          >
            <Plus className="h-3.5 w-3.5" aria-hidden />
            {buildOpen ? t("retrieval.action.hideBuild") : t("retrieval.action.buildNew")}
          </Button>
        }
      >
        <div className="space-y-3">
          {buildOpen && (
            <div
              className="space-y-3 rounded-lg border border-[var(--as-border)] bg-[color-mix(in_srgb,var(--as-muted)_35%,transparent)] p-3"
              data-testid="retrieval-build-form"
            >
              <p className="text-xs text-[var(--as-muted-fg)]">{t("retrieval.spaces.buildHint")}</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <TextField
                  label={t("retrieval.field.name")}
                  value={buildDraft.name}
                  onChange={(value) => setBuildDraft({ ...buildDraft, name: value })}
                  maxLength={40}
                  testId="retrieval-build-name"
                />
                <TextField
                  label={t("retrieval.field.provider")}
                  value={buildDraft.provider}
                  onChange={(value) => setBuildDraft({ ...buildDraft, provider: value })}
                  maxLength={60}
                  testId="retrieval-build-provider"
                />
                <TextField
                  label={t("retrieval.field.model")}
                  value={buildDraft.model}
                  onChange={(value) => setBuildDraft({ ...buildDraft, model: value })}
                  maxLength={120}
                  testId="retrieval-build-model"
                />
                <NumberField
                  label={t("retrieval.field.dim")}
                  value={buildDraft.dim}
                  onChange={(value) => setBuildDraft({ ...buildDraft, dim: value ?? 1 })}
                  min={1}
                  max={3072}
                  testId="retrieval-build-dim"
                />
                <TextField
                  label={t("retrieval.field.queryPrefix")}
                  value={buildDraft.queryPrefix}
                  onChange={(value) => setBuildDraft({ ...buildDraft, queryPrefix: value })}
                  maxLength={80}
                  testId="retrieval-build-query-prefix"
                />
                <TextField
                  label={t("retrieval.field.documentPrefix")}
                  value={buildDraft.documentPrefix}
                  onChange={(value) => setBuildDraft({ ...buildDraft, documentPrefix: value })}
                  maxLength={80}
                  testId="retrieval-build-document-prefix"
                />
              </div>
              <Button
                size="sm"
                disabled={
                  busy === "spaces" ||
                  !buildDraft.name.trim() ||
                  !buildDraft.provider.trim() ||
                  !buildDraft.model.trim()
                }
                loading={busy === "spaces"}
                onClick={() => void submitBuild()}
                data-testid="retrieval-build-submit"
              >
                {t("retrieval.action.build")}
              </Button>
            </div>
          )}

          {!spaces || spaces.spaces.length === 0 ? (
            <EmptyState
              icon={Layers}
              title={t("retrieval.spaces.empty")}
              description={t("retrieval.active.emptyBody")}
            />
          ) : (
            <div className="overflow-x-auto rounded-lg border border-[var(--as-border)]">
              <table className="w-full text-sm" data-testid="retrieval-spaces-table">
                <thead>
                  <tr className="border-b border-[var(--as-border)] text-left text-[11px] uppercase tracking-wide text-[var(--as-muted-fg)]">
                    <th className="px-3 py-2">{t("retrieval.field.space")}</th>
                    <th className="px-3 py-2">{t("retrieval.active.model")}</th>
                    <th className="px-3 py-2">{t("retrieval.active.coverage")}</th>
                    <th className="px-3 py-2">{t("retrieval.active.gate")}</th>
                    <th className="px-3 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {spaces.spaces.map((space) => (
                    <tr
                      key={space.space_id}
                      className="border-b border-[var(--as-border)] last:border-0"
                      data-testid={`retrieval-space-${space.name}`}
                    >
                      <td className="px-3 py-2">
                        <p className="flex flex-wrap items-center gap-2 font-medium text-[var(--as-fg)]">
                          {space.name}
                          <Badge variant={statusVariant(space.status)}>
                            {t(`retrieval.spaceStatus.${space.status}`)}
                          </Badge>
                        </p>
                        <p className="text-[11px] text-[var(--as-muted-fg)]">
                          {t("retrieval.spaces.documents", {
                            count: space.documents,
                            records: space.records,
                          })}
                        </p>
                      </td>
                      <td className="px-3 py-2 text-xs text-[var(--as-muted-fg)]">
                        {space.provider}/{space.model} · {space.dim}
                        <br />
                        {space.backend}
                      </td>
                      <td className="px-3 py-2 text-xs tabular-nums text-[var(--as-muted-fg)]">
                        {rate(space.coverage)}
                        <br />
                        {space.stale != null
                          ? `${t("retrieval.active.stale")}: ${space.stale}`
                          : t("retrieval.state.never_reconciled")}
                      </td>
                      <td className="px-3 py-2 text-xs">
                        <Badge variant={gateVariant(space.gate)}>
                          {t(`retrieval.gate.${space.gate}`)}
                        </Badge>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap justify-end gap-2">
                          {space.status === "building" && (
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={busy === "spaces"}
                              onClick={() => void activate(space)}
                              data-testid={`retrieval-activate-${space.name}`}
                            >
                              {t("retrieval.action.activate")}
                            </Button>
                          )}
                          {space.status !== "active" && space.status !== "retired" && (
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={busy === "spaces"}
                              onClick={() => setTypedIntent({ action: "retire", space })}
                              data-testid={`retrieval-retire-${space.name}`}
                            >
                              {t("retrieval.action.retire")}
                            </Button>
                          )}
                          {space.status === "retired" && (
                            <Button
                              size="sm"
                              variant="destructive"
                              disabled={busy === "danger"}
                              onClick={() => setTypedIntent({ action: "drop", space })}
                              data-testid={`retrieval-drop-${space.name}`}
                            >
                              {t("retrieval.action.drop")}
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {activeSpace && (
            <p className="text-xs text-[var(--as-muted-fg)]">{t("retrieval.spaces.activeHint")}</p>
          )}
          <ActionNotice notice={notice?.card === "spaces" ? notice : null} />
        </div>
      </SettingsSectionCard>

      <SettingsSectionCard
        name="retrieval-maintenance"
        icon={Wrench}
        title={t("retrieval.maintenance.heading")}
        description={t("retrieval.card.maintenance.description")}
        adminOnly
      >
        <div className="space-y-3">
          <p className="text-xs text-[var(--as-muted-fg)]">{t("retrieval.maintenance.hint")}</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <SelectField
              label={t("retrieval.field.space")}
              value={selectedSpace}
              onChange={setSelectedSpace}
              options={spaceOptions}
              testId="retrieval-maintenance-space"
            />
            <SelectField
              label={t("retrieval.field.maintenanceAction")}
              value={maintenanceAction}
              onChange={(value) => setMaintenanceAction(value as MaintenanceAction)}
              options={MAINTENANCE_ACTIONS.map((action) => ({
                value: action,
                label: t(`retrieval.maintenanceAction.${action}`),
              }))}
              testId="retrieval-maintenance-action"
            />
            <NumberField
              label={t("retrieval.field.maintenanceLimit")}
              value={maintenanceLimit}
              onChange={setMaintenanceLimit}
              min={1}
              max={5000}
              testId="retrieval-maintenance-limit"
            />
          </div>
          <ToggleRow
            label={t("retrieval.field.dryRun")}
            checked={maintenanceDryRun}
            onChange={setMaintenanceDryRun}
          />
          {maintenanceAction === "retry-failed" && (
            <p className="text-xs text-[var(--as-muted-fg)]">{t("retrieval.maintenance.retryHint")}</p>
          )}
          <Button
            size="sm"
            disabled={!selectedSpace || busy === "maintenance"}
            loading={busy === "maintenance"}
            onClick={() => void submitMaintenance()}
            data-testid="retrieval-maintenance-submit"
          >
            {t("retrieval.action.maintenance")}
          </Button>
          <ActionNotice notice={notice?.card === "maintenance" ? notice : null} />
        </div>
      </SettingsSectionCard>

      <SettingsSectionCard
        name="retrieval-quality"
        icon={Target}
        title={t("retrieval.quality.heading")}
        description={t("retrieval.card.quality.description")}
        adminOnly
      >
        <div className="space-y-3">
          <p className="text-xs text-[var(--as-muted-fg)]">{t("retrieval.quality.hint")}</p>
          <QualitySummary quality={quality} compare={lastCompare} />
          <div className="grid gap-3 sm:grid-cols-2">
            <SelectField
              label={t("retrieval.field.candidate")}
              value={candidateSpace}
              onChange={setCandidateSpace}
              options={spaceOptions}
              testId="retrieval-quality-candidate"
            />
            <SelectField
              label={t("retrieval.field.baseline")}
              value={baselineSpace}
              onChange={setBaselineSpace}
              options={spaceOptions}
              testId="retrieval-quality-baseline"
            />
          </div>
          <Button
            size="sm"
            disabled={
              busy === "quality" ||
              !candidateSpace ||
              !baselineSpace ||
              candidateSpace === baselineSpace
            }
            loading={busy === "quality"}
            onClick={() => void submitCompare()}
            data-testid="retrieval-quality-submit"
          >
            <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
            {t("retrieval.action.compare")}
          </Button>
          <ActionNotice notice={notice?.card === "quality" ? notice : null} />
        </div>
      </SettingsSectionCard>

      <SettingsSectionCard
        name="retrieval-danger"
        icon={AlertTriangle}
        variant="danger"
        title={t("retrieval.danger.heading")}
        description={t("retrieval.danger.description")}
        adminOnly
      >
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={busy === "danger"}
              loading={busy === "danger"}
              onClick={() => void exportStatus()}
              data-testid="retrieval-export"
            >
              <Download className="h-3.5 w-3.5" aria-hidden />
              {t("retrieval.action.export")}
            </Button>
            <span className="text-xs text-[var(--as-muted-fg)]">{t("retrieval.danger.exportHint")}</span>
          </div>
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--as-muted-fg)]">
              {t("retrieval.danger.retired")}
            </p>
            {retiredSpaces.length === 0 ? (
              <p className="text-xs text-[var(--as-muted-fg)]">{t("retrieval.danger.noRetired")}</p>
            ) : (
              retiredSpaces.map((space) => (
                <div
                  key={space.space_id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[var(--as-border)] px-3 py-2"
                  data-testid={`retrieval-danger-${space.name}`}
                >
                  <span className="text-xs text-[var(--as-fg)]">{space.name}</span>
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={busy === "danger"}
                    onClick={() => setTypedIntent({ action: "drop", space })}
                    data-testid={`retrieval-danger-drop-${space.name}`}
                  >
                    {t("retrieval.danger.dropButton")}
                  </Button>
                </div>
              ))
            )}
          </div>
          <ActionNotice notice={notice?.card === "danger" ? notice : null} />
        </div>
      </SettingsSectionCard>

      <TypedConfirmModal
        open={typedIntent !== null}
        onOpenChange={(open) => {
          if (!open) setTypedIntent(null);
        }}
        title={
          typedIntent
            ? t(
                typedIntent.action === "retire"
                  ? "retrieval.spaces.retireTitle"
                  : "retrieval.spaces.dropTitle",
                { name: typedIntent.space.name },
              )
            : ""
        }
        description={
          typedIntent
            ? t(
                typedIntent.action === "retire"
                  ? "retrieval.spaces.retireBody"
                  : "retrieval.spaces.dropBody",
              )
            : ""
        }
        expectedName={typedIntent?.space.name ?? ""}
        confirmLabel={
          typedIntent
            ? t(
                typedIntent.action === "retire"
                  ? "retrieval.action.retire"
                  : "retrieval.action.drop",
              )
            : t("retrieval.action.confirm")
        }
        busy={typedBusy}
        onConfirm={(typedName) => void submitTyped(typedName)}
      />
    </div>
  );
}
