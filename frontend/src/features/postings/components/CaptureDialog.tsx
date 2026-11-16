import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import {
  Button,
  Modal,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalTitle,
} from "@/components/ui";
import { apiDetail } from "@/api/client";
import { capturePosting } from "@/api/postings";

export function CaptureDialog({
  open,
  initialUrl,
  onClose,
  onCaptured,
}: {
  open: boolean;
  initialUrl: string;
  onClose: () => void;
  onCaptured: (ref: string) => void;
}) {
  const { t } = useTranslation();
  const [url, setUrl] = useState(initialUrl);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (open) {
      setUrl(initialUrl);
      setError("");
    }
  }, [open, initialUrl]);

  const run = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await capturePosting(url.trim());
      onCaptured(result.ref);
    } catch (err) {
      setError(apiDetail(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onOpenChange={(next) => !next && onClose()}>
      <ModalContent data-testid="capture-dialog" aria-describedby={undefined}>
        <ModalHeader>
          <ModalTitle>{t("capture.title")}</ModalTitle>
        </ModalHeader>
        <div className="space-y-3">
          <p className="text-sm text-[var(--as-muted-fg)]">{t("capture.intro")}</p>
          <label className="block space-y-1 text-xs text-[var(--as-muted-fg)]">
            <span>{t("capture.urlLabel")}</span>
            <input
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              maxLength={1000}
              className="w-full rounded border border-[var(--as-border)] bg-[var(--as-surface)] p-2 text-sm text-[var(--as-fg)]"
              data-testid="capture-url"
            />
          </label>
          {error !== "" && (
            <p role="alert" className="text-sm text-[var(--as-danger)]" data-testid="capture-error">
              {error}
            </p>
          )}
          <Link
            to="/postings/capture-help"
            className="inline-block text-xs text-[var(--as-accent)] underline"
            data-testid="capture-help-link"
          >
            {t("capture.helpLink")}
          </Link>
        </div>
        <ModalFooter>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button
            onClick={() => void run()}
            disabled={busy || url.trim() === ""}
            data-testid="capture-confirm"
          >
            {busy ? t("capture.saving") : t("capture.confirm")}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
