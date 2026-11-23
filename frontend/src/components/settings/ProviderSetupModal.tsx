import { ProviderSetupWizard } from "@/components/settings/ProviderSetupWizard";

interface ProviderSetupModalProps {
  canUseSystemScope: boolean;
  /** Scope a scoped settings page pins for the setup flow. */
  initialScope?: "user" | "system";
  /** Hide the scope picker and submit only `initialScope`. */
  lockScope?: boolean;
  configuredKeys: string[];
  onClose: () => void;
  /** "Set up manually" hands off to the full create/edit modal. */
  onManual: () => void;
  onSaved: () => void;
  /** Finish: close and open this scope's task assignments. */
  onContinueToTasks?: () => void;
  /** Finish: open this scope's models surface. */
  onOpenModels?: () => void;
}

/** One-click §15 setup in a dialog — the AI settings entry into the shared
 * wizard flow (the first-run route hosts the same flow in page frame). */
export function ProviderSetupModal({
  canUseSystemScope,
  initialScope,
  lockScope = false,
  configuredKeys,
  onClose,
  onManual,
  onSaved,
  onContinueToTasks,
  onOpenModels,
}: ProviderSetupModalProps) {
  return (
    <ProviderSetupWizard
      frame="modal"
      canUseSystemScope={canUseSystemScope}
      initialScope={initialScope}
      lockScope={lockScope}
      configuredKeys={configuredKeys}
      onClose={onClose}
      onManual={onManual}
      onSaved={onSaved}
      onContinueToTasks={onContinueToTasks}
      onOpenModels={onOpenModels}
    />
  );
}
