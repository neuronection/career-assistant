import { HardDrive } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";

import { SettingsPage } from "@/components/settings/SettingsPage";
import { StorageStatusCard } from "@/components/settings/StorageStatusCard";
import { isDesktop } from "@/lib/desktop";
import { useAuthStore } from "@/stores/authStore";

/** Admin-only read-only deployment storage surface (plan 55 P4b2). */
export function Storage() {
  const { t } = useTranslation();
  const user = useAuthStore((state) => state.user);

  // Desktop is always local storage, and the operator surface is
  // instance-admin only: neither the nav nor a hand-written deep link may
  // mount it.
  if (isDesktop() || !user?.is_admin) {
    return <Navigate to="/settings/account" replace />;
  }

  return (
    <SettingsPage
      icon={HardDrive}
      title={t("settingsNav.storage.label")}
      description={t("settingsNav.storage.description")}
    >
      <StorageStatusCard />
    </SettingsPage>
  );
}
