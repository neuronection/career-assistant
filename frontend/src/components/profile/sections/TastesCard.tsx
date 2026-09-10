import { forwardRef } from "react";
import { useTranslation } from "react-i18next";
import { ChipInput } from "@/components/ui";
import { ProfileSectionCard } from "@/components/profile/ProfileSectionCard";
import { useProfileStore } from "@/stores/profileStore";
import type { Profile } from "@/types";
import {
  useSectionCard,
  type SectionCardBaseProps,
  type SectionCardHandle,
} from "./shared";

export interface TastesCardProps
  extends SectionCardBaseProps<Pick<Profile, "likes" | "dislikes" | "hobbies">> {}

type Hobby = { key: string | null; label: string; weight: number };
export const TastesCard = forwardRef<SectionCardHandle, TastesCardProps>(
  function TastesCard(
    { initial, onSave, mode = "autosave", variant = "page", complete = null },
    ref
  ) {
    const taxonomy = useProfileStore((s) => s.interests);
    const { t } = useTranslation();
    const { draft, setDraft, state, error } = useSectionCard(ref, {
      initial,
      onSave,
      mode,
      buildPayload: (d) => ({ likes: d.likes, dislikes: d.dislikes, hobbies: d.hobbies }),
    });

    function withTagKey<T extends { label: string; weight: number }>(
      items: T[],
      labels: string[],
      keyField: "tag_key" | "key"
    ): T[] {
      return labels.map((label) => {
        const existing = items.find(
          (i) => i.label.toLowerCase() === label.toLowerCase()
        );
        if (existing) return { ...existing, label };
        const tag = taxonomy.find(
          (t) =>
            t.label.toLowerCase() === label.toLowerCase() || t.key === label
        );
        return keyField === "key"
          ? ({ key: tag?.key ?? null, label, weight: 3 } as unknown as T)
          : ({ tag_key: tag?.key ?? null, label, weight: 3 } as unknown as T);
      });
    }

    return (
      <ProfileSectionCard
        name="tastes"
        title={t("profileSection.tastes")}
        description={
          variant === "page"
            ? t("profileSection.tastesBody")
            : undefined
        }
        complete={complete}
        saveState={state}
        error={error}
        variant={variant}
      >
        <div className="space-y-5">
          <div>
            <h3 className="mb-2 text-xs font-semibold text-[var(--as-fg)]">
              {t("profileSection.likesHeading")}
            </h3>
            <ChipInput
              value={draft.likes.map((i) => i.label)}
              onChange={(labels) =>
                setDraft({ ...draft, likes: withTagKey(draft.likes, labels, "tag_key") })
              }
              inputLabel={t("profileSection.newLike")}
              addLabel="Add"
              placeholder={t("profileSection.likesPlaceholder")}
            />
          </div>
          <div>
            <h3 className="mb-2 text-xs font-semibold text-[var(--as-fg)]">
              {t("profileSection.dislikesHeading")}
            </h3>
            <ChipInput
              value={draft.dislikes.map((i) => i.label)}
              onChange={(labels) =>
                setDraft({
                  ...draft,
                  dislikes: withTagKey(draft.dislikes, labels, "tag_key"),
                })
              }
              inputLabel={t("profileSection.newDislike")}
              addLabel="Add"
              placeholder={t("profileSection.dislikesPlaceholder")}
            />
          </div>
          <div>
            <h3 className="mb-2 text-xs font-semibold text-[var(--as-fg)]">
              {t("profileSection.hobbiesHeading")}
            </h3>
            <ChipInput
              value={draft.hobbies.map((i) => i.label)}
              onChange={(labels) =>
                setDraft({
                  ...draft,
                  hobbies: withTagKey<Hobby>(draft.hobbies, labels, "key"),
                })
              }
              inputLabel={t("profileSection.newHobby")}
              addLabel="Add"
              placeholder={t("profileSection.hobbiesPlaceholder")}
            />
          </div>
          <p className="text-xs text-[var(--as-muted-fg)]">
            {t("profileSection.tastesFreeText")}
          </p>
        </div>
      </ProfileSectionCard>
    );
  }
);
