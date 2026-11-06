import { ProviderSetupWizard } from "@/components/settings/ProviderSetupWizard";

interface ProviderSetupModalProps {
  canUseSystemScope: boolean;
  configuredKeys: string[];
  onClose: () => void;
  /** "Set up manually" hands off to the full create/edit modal. */
  onManual: () => void;
  onSaved: () => void;
}

/** One-click §15 setup in a dialog — the AI settings entry into the shared
 * wizard flow (the first-run route hosts the same flow in page frame). */
export function ProviderSetupModal({
  canUseSystemScope,
  configuredKeys,
  onClose,
  onManual,
  onSaved,
}: ProviderSetupModalProps) {
  return (
    <ProviderSetupWizard
      frame="modal"
      canUseSystemScope={canUseSystemScope}
      configuredKeys={configuredKeys}
      onClose={onClose}
      onManual={onManual}
      onSaved={onSaved}
    />
  );
}
