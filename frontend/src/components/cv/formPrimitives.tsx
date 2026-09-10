import { Minus, Plus } from "lucide-react";
import {
  Combobox,
  ComboboxMulti,
  DatePicker,
  Input,
  type ComboboxOption,
} from "@neuronection/assistant-ui";
import { Textarea } from "@neuronection/assistant-ui/textarea";

function slug(label: string): string {
  return label.toLowerCase().replace(/\s+/g, "-");
}

export type FieldRule<T> = (value: T) => string | null;

export function requiredRule(label: string): FieldRule<string> {
  return (value) => (value.trim() ? null : `${label} is required.`);
}

export function emailRule(value: string): string | null {
  if (!value.trim()) return null;
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim())
    ? null
    : "Enter a valid email address.";
}

export function rangeRule(
  label: string,
  min: number,
  max: number
): FieldRule<number | null> {
  return (value) => {
    if (value === null) return null;
    if (Number.isNaN(value) || value < min || value > max) {
      return `${label} must be between ${min} and ${max}.`;
    }
    return null;
  };
}

export function FormRow({
  label,
  hint,
  error,
  testId,
  children,
}: {
  label?: string;
  hint?: string;
  error?: string;
  testId?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="space-y-1 text-xs text-[var(--as-fg)]" data-testid={testId}>
      {label && <span className="text-[var(--as-muted-fg)]">{label}</span>}
      {children}
      {hint && !error && (
        <p className="text-[var(--as-muted-fg)]">{hint}</p>
      )}
      {error && (
        <p role="alert" className="font-medium text-[var(--as-danger)]">
          {error}
        </p>
      )}
    </div>
  );
}

export function TextField({
  label,
  value,
  onChange,
  type = "text",
  inputMode,
  autoComplete,
  placeholder,
  hint,
  error,
  required,
  maxLength,
  disabled,
  testId,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "email" | "tel" | "password" | "url";
  inputMode?: "text" | "email" | "tel" | "numeric" | "decimal" | "url";
  autoComplete?: string;
  placeholder?: string;
  hint?: string;
  error?: string;
  required?: boolean;
  maxLength?: number;
  disabled?: boolean;
  testId?: string;
}) {
  return (
    <Input
      type={type}
      inputMode={inputMode}
      autoComplete={autoComplete}
      label={label}
      value={value}
      maxLength={maxLength}
      required={required}
      disabled={disabled}
      placeholder={placeholder}
      hint={hint}
      error={error}
      onChange={(event) => onChange(event.target.value)}
      data-testid={testId}
    />
  );
}

export function EmailField(
  props: Omit<Parameters<typeof TextField>[0], "type" | "inputMode">
) {
  return (
    <TextField
      {...props}
      type="email"
      inputMode="email"
      autoComplete={props.autoComplete ?? "email"}
    />
  );
}

export function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  placeholder,
  hint,
  error,
  disabled,
  testId,
}: {
  label: string;
  value: number | null;
  onChange: (value: number | null) => void;
  min?: number;
  max?: number;
  placeholder?: string;
  hint?: string;
  error?: string;
  disabled?: boolean;
  testId?: string;
}) {
  return (
    <Input
      type="number"
      inputMode="numeric"
      label={label}
      min={min}
      max={max}
      value={value === null ? "" : String(value)}
      disabled={disabled}
      placeholder={placeholder}
      hint={hint}
      error={error}
      onChange={(event) =>
        onChange(event.target.value === "" ? null : Number(event.target.value))
      }
      data-testid={testId}
    />
  );
}

export function TextareaField({
  label,
  value,
  onChange,
  rows = 3,
  maxLength,
  placeholder,
  hint,
  error,
  counter = false,
  testId,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  maxLength?: number;
  placeholder?: string;
  hint?: string;
  error?: string;
  counter?: boolean;
  testId?: string;
}) {
  const resolvedHint =
    counter && maxLength
      ? `${value.length}/${maxLength}${hint ? ` · ${hint}` : ""}`
      : hint;
  return (
    <Textarea
      label={label}
      value={value}
      rows={rows}
      maxLength={maxLength}
      placeholder={placeholder}
      hint={resolvedHint}
      error={error}
      onChange={(event) => onChange(event.target.value)}
      data-testid={testId}
    />
  );
}

export function DateField({
  label,
  value,
  onChange,
  onClear,
  hint,
  error,
  disabled,
  clearable = true,
  testId,
}: {
  label: string;
  value: string | null;
  onChange: (value: string) => void;
  onClear?: () => void;
  hint?: string;
  error?: string;
  disabled?: boolean;
  clearable?: boolean;
  testId?: string;
}) {
  return (
    <FormRow label={label} hint={hint} error={error} testId={testId}>
      <DatePicker
        value={value || null}
        onChange={onChange}
        onClear={onClear}
        allowClear={clearable}
        clearLabel={`Clear ${label.toLowerCase()}`}
        label={label}
        placeholder={label}
        disabled={disabled}
        required
      />
    </FormRow>
  );
}

export function ComboboxField({
  label,
  value,
  onChange,
  options,
  placeholder,
  hint,
  error,
  clearable = false,
  disabled,
  hideLabel = false,
  allowCreate = false,
  createLabel,
  testId,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: ComboboxOption[];
  placeholder?: string;
  hint?: string;
  error?: string;
  clearable?: boolean;
  disabled?: boolean;
  hideLabel?: boolean;
  allowCreate?: boolean;
  createLabel?: (term: string) => string;
  testId?: string;
}) {
  return (
    <FormRow hint={hint} testId={testId}>
      <Combobox
        options={options}
        value={value || undefined}
        onChange={onChange}
        label={label}
        hideLabel={hideLabel}
        placeholder={placeholder ?? `Select ${label.toLowerCase()}…`}
        clearable={clearable}
        clearLabel={`Clear ${label.toLowerCase()}`}
        disabled={disabled}
        allowCreate={allowCreate}
        createLabel={createLabel}
        error={error}
      />
    </FormRow>
  );
}

export function ComboboxMultiField({
  label,
  values,
  onChange,
  options,
  placeholder,
  hint,
  error,
  disabled,
  maxTriggerLabels,
  allowCreate = false,
  createLabel,
  testId,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  options: ComboboxOption[];
  placeholder?: string;
  hint?: string;
  error?: string;
  disabled?: boolean;
  maxTriggerLabels?: number;
  allowCreate?: boolean;
  createLabel?: (term: string) => string;
  testId?: string;
}) {
  return (
    <FormRow hint={hint} testId={testId}>
      <ComboboxMulti
        options={options}
        value={values}
        onChange={onChange}
        label={label}
        placeholder={placeholder ?? `Select ${label.toLowerCase()}…`}
        maxTriggerLabels={maxTriggerLabels}
        disabled={disabled}
        allowCreate={allowCreate}
        createLabel={createLabel}
        error={error}
      />
    </FormRow>
  );
}

export function OptionalStepper({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
  addValue,
  addLabel = "Set value",
  suffix,
}: {
  label: string;
  value: number | null;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number | null) => void;
  addValue: number;
  addLabel?: string;
  suffix?: string;
}) {
  const clamp = (next: number) => Math.min(Math.max(next, min), max);
  if (value === null) {
    return (
      <div
        className="flex items-center justify-between gap-2 text-xs text-[var(--as-fg)]"
        data-testid={`stepper-${slug(label)}`}
      >
        <span>
          {label}
          {suffix ? ` (${suffix})` : ""}
        </span>
        <button
          type="button"
          onClick={() => onChange(clamp(addValue))}
          className="cursor-pointer rounded-md border border-[var(--as-border)] px-2 py-0.5 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)]"
          aria-label={`${addLabel} — ${label}`}
          data-testid={`stepper-${slug(label)}-add`}
        >
          {addLabel}
        </button>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-1.5">
      <div className="min-w-0 flex-1">
        <StepperRow
          label={label}
          value={value}
          min={min}
          max={max}
          step={step}
          suffix={suffix}
          onChange={onChange}
        />
      </div>
      <button
        type="button"
        onClick={() => onChange(null)}
        className="shrink-0 cursor-pointer rounded-md px-1 py-0.5 text-[var(--as-muted-fg)] transition-colors hover:text-[var(--as-fg)]"
        aria-label={`Unset ${label.toLowerCase()}`}
        title="Not set"
        data-testid={`stepper-${slug(label)}-clear`}
      >
        <Plus className="h-3 w-3 rotate-45" aria-hidden />
      </button>
    </div>
  );
}

export function ToggleRow({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-2 text-xs text-[var(--as-fg)]">
      <span>{label}</span>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="as-switch"
        data-testid={`toggle-${slug(label)}`}
      />
    </label>
  );
}

export function StepperRow({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
  suffix,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
  suffix?: string;
}) {
  const clamp = (next: number) => Math.min(Math.max(next, min), max);
  return (
    <div className="flex items-center justify-between gap-2 text-xs text-[var(--as-fg)]">
      <span>
        {label}
        {suffix ? ` (${suffix})` : ""}
      </span>
      <span
        className="inline-flex items-center gap-1"
        data-testid={`stepper-${slug(label)}`}
      >
        <button
          type="button"
          aria-label={`${label} decrease`}
          disabled={value <= min}
          onClick={() => onChange(clamp(value - step))}
          className="cursor-pointer rounded-md border border-[var(--as-border)] p-0.5 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)] disabled:pointer-events-none disabled:opacity-40"
        >
          <Minus className="h-3 w-3" aria-hidden />
        </button>
        <span className="min-w-8 text-center font-medium tabular-nums">{value}</span>
        <button
          type="button"
          aria-label={`${label} increase`}
          disabled={value >= max}
          onClick={() => onChange(clamp(value + step))}
          className="cursor-pointer rounded-md border border-[var(--as-border)] p-0.5 text-[var(--as-muted-fg)] transition-colors hover:bg-[var(--as-muted)] hover:text-[var(--as-fg)] disabled:pointer-events-none disabled:opacity-40"
        >
          <Plus className="h-3 w-3" aria-hidden />
        </button>
      </span>
    </div>
  );
}

export function SegmentedRow({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-1 text-xs text-[var(--as-fg)]">
      <p className="text-[var(--as-muted-fg)]">{label}</p>
      <div className="flex flex-wrap gap-1" role="group" aria-label={label}>
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={value === option.value}
            onClick={() => onChange(option.value)}
            className={`cursor-pointer rounded-full border px-2 py-0.5 text-xs transition-colors duration-150 ${
              value === option.value
                ? "border-[var(--as-accent)] bg-[var(--as-accent)] text-white"
                : "border-[var(--as-border)] text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function ChipTogglesRow({
  label,
  values,
  options,
  onChange,
}: {
  label: string;
  values: string[];
  options: { value: string; label: string }[];
  onChange: (values: string[]) => void;
}) {
  const toggle = (value: string) => {
    if (values.includes(value)) onChange(values.filter((entry) => entry !== value));
    else onChange([...values, value]);
  };
  return (
    <div className="space-y-1 text-xs text-[var(--as-fg)]">
      <p className="text-[var(--as-muted-fg)]">{label}</p>
      <div className="flex flex-wrap gap-1" role="group" aria-label={label}>
        {options.map((option) => {
          const active = values.includes(option.value);
          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={active}
              onClick={() => toggle(option.value)}
              className={`cursor-pointer rounded-full border px-2 py-0.5 text-xs transition-colors duration-150 ${
                active
                  ? "border-[var(--as-accent)] bg-[color-mix(in_srgb,var(--as-accent)_12%,transparent)] text-[var(--as-accent)]"
                  : "border-[var(--as-border)] text-[var(--as-muted-fg)] hover:text-[var(--as-fg)]"
              }`}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function FieldLabel({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-1 text-xs text-[var(--as-fg)]">
      <span className="text-[var(--as-muted-fg)]">{label}</span>
      {children}
    </label>
  );
}

export function SelectField({
  label,
  value,
  onChange,
  options,
  testId,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  testId?: string;
}) {
  return (
    <FieldLabel label={label}>
      <select
        aria-label={label}
        className="w-full cursor-pointer rounded-lg border border-[var(--as-border)] bg-[var(--as-surface)] p-1.5 text-sm outline-none transition-colors focus:border-[var(--as-accent)]"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        data-testid={testId}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </FieldLabel>
  );
}

export function RangeField({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
  suffix,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
  suffix?: string;
}) {
  return (
    <FieldLabel label={`${label}: ${value}${suffix ?? ""}`}>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full accent-[var(--as-accent)]"
        aria-label={label}
      />
    </FieldLabel>
  );
}
