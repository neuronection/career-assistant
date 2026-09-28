import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ConfirmationModal, ProfileSwitcher } from "@neuronection/assistant-ui";

import type { ProfileSummary } from "@/api/profiles";
import { useProfilesStore } from "@/stores/profilesStore";

/**
 * App-chrome profile switcher (identity-auth §6/§12/§15): the shared
 * `ProfileSwitcher` bound to the profiles store — create, rename,
 * set-Default and delete (behind a confirm) against `/api/v1/profiles`,
 * and every selection re-binds the `X-Profile-Id` header (§15).
 */
export function ProfileSwitcherMenu() {
  const { t } = useTranslation();
  const profiles = useProfilesStore((state) => state.profiles);
  const currentId = useProfilesStore((state) => state.currentId);
  const loading = useProfilesStore((state) => state.loading);
  const error = useProfilesStore((state) => state.error);
  const hydrate = useProfilesStore((state) => state.hydrate);
  const select = useProfilesStore((state) => state.select);
  const create = useProfilesStore((state) => state.create);
  const rename = useProfilesStore((state) => state.rename);
  const setDefault = useProfilesStore((state) => state.setDefault);
  const remove = useProfilesStore((state) => state.remove);
  const [pendingDelete, setPendingDelete] = useState<ProfileSummary | null>(null);

  useEffect(() => {
    void hydrate();
  }, [hydrate]);

  // The switcher passes its own `ProfileItem` shape (color optional) —
  // resolve to the store's `ProfileSummary` before mutating.
  const pick = (item: { id: string }): ProfileSummary | null =>
    profiles.find((profile) => profile.id === item.id) ?? null;

  return (
    <>
      <ProfileSwitcher
        profiles={profiles}
        currentId={currentId}
        loading={loading && profiles.length === 0}
        error={error ? t("profiles.saveFailed") : null}
        labels={{
          trigger: t("profiles.trigger"),
          panelTitle: t("profiles.panelTitle"),
          currentBadge: t("profiles.currentBadge"),
          defaultBadge: t("profiles.defaultBadge"),
          newProfile: t("profiles.newProfile"),
          newProfilePlaceholder: t("profiles.namePlaceholder"),
          create: t("profiles.create"),
          rename: (name) => t("profiles.rename", { name }),
          renamePlaceholder: t("profiles.namePlaceholder"),
          renameSubmit: t("profiles.renameSubmit"),
          setDefault: (name) => t("profiles.setDefault", { name }),
          delete: (name) => t("profiles.delete", { name }),
          cancel: t("profiles.cancel"),
          loading: t("profiles.loading"),
          empty: t("profiles.empty"),
        }}
        onSelect={(item) => {
          const profile = pick(item);
          if (profile) void select(profile);
        }}
        onCreate={(name) => void create(name)}
        onRename={(item, name) => {
          const profile = pick(item);
          if (profile) void rename(profile, name);
        }}
        onDelete={(item) => {
          const profile = pick(item);
          if (profile) setPendingDelete(profile);
        }}
        onSetDefault={(item) => {
          const profile = pick(item);
          if (profile) void setDefault(profile);
        }}
      />
      {pendingDelete && (
        <ConfirmationModal
          open
          title={t("profiles.confirmDeleteTitle")}
          description={t("profiles.confirmDeleteBody")}
          confirmLabel={t("profiles.delete", { name: pendingDelete.name })}
          cancelLabel={t("profiles.cancel")}
          destructive
          onConfirm={() => {
            const target = pendingDelete;
            setPendingDelete(null);
            void remove(target);
          }}
          onOpenChange={(open) => (open ? undefined : setPendingDelete(null))}
        />
      )}
    </>
  );
}
