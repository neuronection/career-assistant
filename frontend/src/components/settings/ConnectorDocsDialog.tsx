import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { useTranslation } from "react-i18next";

import {
  DocsDialog,
  type DocsDialogLabels,
  type IntegrationDocsNode,
} from "@/components/ui/integrations";
import { fetchConnectorDocs, type ConnectorDocs } from "@/api/sources";

/**
 * Connector documentation (plan 34 wave 8): the kit's DocsDialog owns the
 * tree chrome; the markdown fetch + render ride the app-owned content
 * slot (health's IntegrationDocsDialog is the family shape). The tree is
 * the extensionDocsTree form — the landing rule picks the opening page
 * and the audience tag (when present) renders as a badge.
 */

type Tree = NonNullable<ConnectorDocs["tree"]>;

function docsNodes(tree: Tree | null, locale?: string | null): IntegrationDocsNode[] {
  const i18n = tree?.i18n;
  const label = (key: string, inline: string | undefined, slug: string): string => {
    const localeMap = (code?: string | null) =>
      code ? i18n?.locales?.[code]?.[key] : undefined;
    return (
      localeMap(locale) ??
      localeMap(i18n?.defaultLocale) ??
      inline ??
      slug.replace(/(^|-)([a-z])/g, (_, sep: string, ch: string) =>
        sep ? ` ${ch.toUpperCase()}` : ch.toUpperCase(),
      )
    );
  };
  return (tree?.categories ?? []).map((category) => ({
    id: `category:${category.category}`,
    title: label(`category.${category.category}`, category.title, category.category),
    children: category.items.map((item) => ({
      id: item.file ?? item.id,
      title: label(`item.${item.id}`, item.title, item.id),
    })),
  }));
}

function landingDocFile(tree: Tree | null): string | null {
  const items = (tree?.categories ?? []).flatMap((category) => category.items);
  const flagged = items.find((item) => item.index);
  return (flagged ?? items[0])?.file ?? null;
}

function audienceOfFile(tree: Tree | null, file: string | null): "user" | "dev" | null {
  for (const category of tree?.categories ?? []) {
    for (const item of category.items) {
      if (item.file && item.file === file) {
        return item.audience === "dev" ? "dev" : item.audience === "user" ? "user" : null;
      }
    }
  }
  return null;
}

export function ConnectorDocsDialog({
  connectorKey,
  onClose,
}: {
  connectorKey: string;
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation();
  const [tree, setTree] = useState<Tree | null | undefined>(undefined);
  const [currentFile, setCurrentFile] = useState<string | null>(null);
  const [markdown, setMarkdown] = useState("");
  const [contentStatus, setContentStatus] = useState<"loading" | "error" | "ready">(
    "loading",
  );
  const [errorDetail, setErrorDetail] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchConnectorDocs(connectorKey)
      .then((data) => {
        if (cancelled) return;
        setTree(data.tree);
        setCurrentFile(landingDocFile(data.tree));
      })
      .catch((err) => {
        if (cancelled) return;
        setContentStatus("error");
        setErrorDetail(err?.response?.data?.detail ?? "Failed to load documentation.");
      });
    return () => {
      cancelled = true;
    };
  }, [connectorKey]);

  useEffect(() => {
    if (!currentFile || currentFile.startsWith("category:")) return;
    let cancelled = false;
    setContentStatus("loading");
    fetchConnectorDocs(connectorKey, currentFile)
      .then((data) => {
        if (cancelled) return;
        setMarkdown(data.markdown);
        setContentStatus("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        setContentStatus("error");
        setErrorDetail(err?.response?.data?.detail ?? "Failed to load documentation.");
      });
    return () => {
      cancelled = true;
    };
  }, [connectorKey, currentFile]);

  const nodes = docsNodes(tree ?? null, i18n.language);
  const audience = audienceOfFile(tree ?? null, currentFile);

  const labels: DocsDialogLabels = {
    title: t("toolsSettings.connectors.docs.title", "Documentation"),
    closeLabel: t("common.close", "Close"),
    treeLabel: t("toolsSettings.connectors.docs.tree", "Documentation"),
    emptyLabel: t("toolsSettings.connectors.docs.empty", "No documentation provided."),
    loadingLabel: t("toolsSettings.connectors.docs.loading", "Loading…"),
    errorLabel: t(
      "toolsSettings.connectors.docs.error",
      "Failed to load documentation.",
    ),
  };

  return (
    <DocsDialog
      open
      onOpenChange={(open) => !open && onClose()}
      docs={nodes}
      selectedId={currentFile}
      onSelect={(nodeId) => {
        if (!nodeId.startsWith("category:")) setCurrentFile(nodeId);
      }}
      status={contentStatus}
      errorDetail={errorDetail}
      labels={labels}
      renderContent={() => (
        <div className="max-w-none text-sm leading-relaxed">
          {audience ? (
            <span
              data-testid="connector-docs-audience"
              className="mb-3 inline-block rounded-full border border-slate-300 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-500"
            >
              {t(`toolsSettings.connectors.docs.audience.${audience}`, audience)}
            </span>
          ) : null}
          <ReactMarkdown>{markdown}</ReactMarkdown>
        </div>
      )}
    />
  );
}
