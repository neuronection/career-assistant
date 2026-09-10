import { useTranslation } from "react-i18next";
import { Modal, ModalContent, ModalHeader, ModalTitle } from "@/components/ui";
import { GenerateCvFlow } from "@/components/cv/GenerateCvFlow";

/** The one-shot generate modal: preferences gate + progress.
 * Mounts the flow fresh per open so every entry starts from defaults. */
export function GenerateCvModal({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  return (
    <Modal open={open} onOpenChange={(next) => !next && onOpenChange(false)}>
      <ModalContent size="xl" className="max-w-2xl" aria-describedby={undefined}>
        <ModalHeader>
          <ModalTitle>{t("cvGenerate.title")}</ModalTitle>
        </ModalHeader>
        {open && <GenerateCvFlow onClose={() => onOpenChange(false)} />}
      </ModalContent>
    </Modal>
  );
}
