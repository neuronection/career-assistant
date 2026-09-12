import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal, ModalContent, ModalHeader, ModalTitle } from "@/components/ui";
import { GenerateCvFlow } from "@/components/cv/GenerateCvFlow";

const COMPACT_WIDTH = "w-[min(680px,96vw)]";
const WIDE_WIDTH = "w-[min(1500px,96vw)]";
const SMALL_FULLSCREEN =
  "max-sm:w-screen max-sm:max-w-none max-sm:h-[100dvh] max-sm:max-h-none max-sm:rounded-none";

/** The one-shot generate modal: preferences gate + progress.
 * Mounts the flow fresh per open so every entry starts from defaults.
 * Stays compact until the first preview HTML renders, then widens;
 * small screens always fill the viewport. */
export function GenerateCvModal({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const [previewActive, setPreviewActive] = useState(false);
  useEffect(() => {
    if (!open) setPreviewActive(false);
  }, [open]);
  return (
    <Modal open={open} onOpenChange={(next) => !next && onOpenChange(false)}>
      <ModalContent
        size="xl"
        className={`max-w-none ${SMALL_FULLSCREEN} ${
          previewActive ? WIDE_WIDTH : COMPACT_WIDTH
        }`}
        aria-describedby={undefined}
      >
        <ModalHeader>
          <ModalTitle>{t("cvGenerate.title")}</ModalTitle>
        </ModalHeader>
        {open && (
          <GenerateCvFlow
            onClose={() => onOpenChange(false)}
            onPreviewActiveChange={setPreviewActive}
          />
        )}
      </ModalContent>
    </Modal>
  );
}
