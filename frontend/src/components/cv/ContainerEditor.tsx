import { useTranslation } from "react-i18next";
import { ColorField, SelectField, StepperRow } from "@/components/cv/formPrimitives";

const CONTAINER_STYLES = [
  { value: "inherit", label: "Inherit" },
  { value: "flat", label: "Flat" },
  { value: "tinted", label: "Tinted" },
  { value: "card", label: "Card" },
  { value: "outline", label: "Outline" },
  { value: "accent-bar", label: "Accent bar" },
];

export function containerActive(box: Record<string, unknown> | undefined): boolean {
  return Boolean(box?.container) && box?.container !== "inherit";
}

export function ContainerEditor({
  box,
  fallbackBackground,
  fallbackBorder,
  onChange,
  testId,
}: {
  box: Record<string, unknown>;
  fallbackBackground: string;
  fallbackBorder: string;
  onChange: (patch: Record<string, unknown>) => void;
  testId?: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-2" data-testid={testId}>
      <SelectField
        label={t("templateEditor.container")}
        value={String(box.container ?? "inherit")}
        onChange={(value) => onChange({ container: { ...box, container: value } })}
        options={CONTAINER_STYLES}
      />
      {containerActive(box) && (
        <div className="grid grid-cols-2 gap-2">
          <StepperRow
            label={t("templateEditor.radius")}
            value={Number(box.radius ?? 0)}
            min={0}
            max={8}
            onChange={(radius) => onChange({ container: { ...box, radius } })}
            suffix="mm"
          />
          <StepperRow
            label={t("templateEditor.padding")}
            value={Number(box.padding_mm ?? 4)}
            min={1}
            max={10}
            onChange={(padding_mm) => onChange({ container: { ...box, padding_mm } })}
            suffix="mm"
          />
          <ColorField
            label={t("templateEditor.color.bg")}
            value={String(box.background ?? fallbackBackground)}
            onChange={(background) => onChange({ container: { ...box, background } })}
          />
          <ColorField
            label={t("templateEditor.color.border")}
            value={String(box.border_color ?? fallbackBorder)}
            onChange={(border_color) => onChange({ container: { ...box, border_color } })}
          />
        </div>
      )}
    </div>
  );
}
