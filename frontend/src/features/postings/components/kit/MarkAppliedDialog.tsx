import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { trackApplication } from "@/api/applications";
import { apiDetail } from "@/api/client";
import { Button, PanelModal, Spinner } from "@/components/ui";
import { SelectField } from "@/features/cv/components/cv/formPrimitives";
import type { PostingKit } from "@/types/wire";

/** "Mark as applied" (plan 212 S1.3): the one write the pre-application
 * kit offers. An explicit user action that creates/links the tracker
 * row — choosing documents here is the only place a kit click records
 * `applied_at`; nothing is submitted anywhere externally. */
export function MarkAppliedDialog({
  kit,
  open,
  onOpenChange,
}: {
  kit: PostingKit;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [cvId, setCvId] = useState("");
  const [letterId, setLetterId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setCvId(kit.cv?.variant?.id ?? kit.cv?.candidates?.[0]?.id ?? "");
    setLetterId(kit.cover_letter?.doc?.id ?? "");
  }, [open, kit]);

  async function submit() {
    setBusy(true);
    setError("");
    try {
      const application = await trackApplication({
        posting_id: kit.posting.id,
        applied_via: "url",
        applied_via_url: kit.posting.url ?? "",
        cv_id: cvId === "" ? null : cvId,
        cover_letter_id: letterId === "" ? null : letterId,
      });
      onOpenChange(false);
      navigate(`/applications/${application.id}`);
    } catch (exc) {
      setError(apiDetail(exc));
      setBusy(false);
    }
  }

  return (
    <PanelModal
      open={open}
      onOpenChange={onOpenChange}
      title={t("applications.kit.markApplied.title")}
      size="sm"
      data-testid="kit-mark-applied-dialog"
    >
      <div className="space-y-4">
        <p className="text-sm text-[var(--as-muted-fg)]">
          {t("applications.kit.markApplied.note")}
        </p>
        <SelectField
          label={t("applications.cv")}
          value={cvId}
          onChange={setCvId}
          options={[
            { value: "", label: t("applications.noDocument") },
            ...(kit.cv?.candidates ?? []).map((ref) => ({
              value: ref.id,
              label: ref.title || t("applications.kit.cv.untitled"),
            })),
          ]}
          testId="kit-mark-cv"
        />
        <SelectField
          label={t("applications.coverLetter")}
          value={letterId}
          onChange={setLetterId}
          options={[
            { value: "", label: t("applications.noDocument") },
            ...(kit.cover_letter?.candidates ?? []).map((ref) => ({
              value: ref.id,
              label: ref.title || t("applications.kit.letter.untitled"),
            })),
          ]}
          testId="kit-mark-letter"
        />
        <div className="flex items-center gap-2">
          <Button
            disabled={busy}
            onClick={() => void submit()}
            data-testid="kit-mark-submit"
          >
            {busy ? <Spinner /> : t("applications.kit.markApplied.submit")}
          </Button>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => onOpenChange(false)}
            data-testid="kit-mark-cancel"
          >
            {t("applications.kit.markApplied.cancel")}
          </Button>
        </div>
        {error !== "" && (
          <p className="text-xs text-rose-600" data-testid="kit-mark-error">
            {error}
          </p>
        )}
      </div>
    </PanelModal>
  );
}
