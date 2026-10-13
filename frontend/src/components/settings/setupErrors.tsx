import { useTranslation } from "react-i18next";
import { AlertTriangle } from "lucide-react";

import type { ProviderSetupErrorDetail } from "@/api/ai";
import { SETUP_ERROR_CODES } from "@/components/ui";

/** The shared §15 enum (library-owned order — i18n copy keyed off it). */
export const ERROR_CODES = SETUP_ERROR_CODES;

export function errorLabel(code: string): string {
  return (ERROR_CODES as readonly string[]).includes(code) ? code : "unknown";
}

export function SetupErrorPanel({
  error,
  plainError,
}: {
  error: ProviderSetupErrorDetail | null;
  plainError: string | null;
}) {
  const { t } = useTranslation();
  if (!error && !plainError) return null;
  return (
    <div
      role="alert"
      className="space-y-1 rounded-md border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700"
    >
      <p className="flex items-center gap-1.5 font-medium">
        <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
        {t(`aiSettings.setup.errors.${errorLabel(error?.code ?? "unknown")}`)}
      </p>
      {error?.suspected_vendor && (
        <p>{t("aiSettings.setup.errors.suspectedVendor", { vendor: error.suspected_vendor })}</p>
      )}
      {(error?.detail || plainError) && (
        <p className="break-words font-mono text-[11px] text-rose-600 opacity-80">
          {error?.detail || plainError}
        </p>
      )}
    </div>
  );
}
