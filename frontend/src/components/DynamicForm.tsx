import { InputFieldSpec } from "../api/client";

/**
 * The form that builds itself. Given a product's field specs from
 * GET /products/{id}/schema, renders inputs with units, tooltips, defaults,
 * and range validation — no per-product frontend code, ever.
 */

export type FormValues = Record<string, string>;

export function defaultsFor(fields: InputFieldSpec[]): FormValues {
  const v: FormValues = {};
  for (const f of fields) v[f.name] = f.default == null ? "" : String(f.default);
  return v;
}

/** Client-side mirror of the server's range/required checks (server re-checks). */
export function validate(
  fields: InputFieldSpec[],
  values: FormValues
): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const f of fields) {
    const raw = (values[f.name] ?? "").trim();
    if (raw === "") {
      if (f.required) errors[f.name] = `${f.label} is required.`;
      continue;
    }
    if (f.type === "number" || f.type === "percent") {
      const x = Number(raw);
      if (Number.isNaN(x)) {
        errors[f.name] = `${f.label} must be a number.`;
      } else if (f.min != null && x < f.min) {
        errors[f.name] = `${f.label} must be ≥ ${f.min}.`;
      } else if (f.max != null && x > f.max) {
        errors[f.name] = `${f.label} must be ≤ ${f.max}.`;
      }
    }
  }
  return errors;
}

/** Convert form strings into the JSON payload the API expects. */
export function toPayload(
  fields: InputFieldSpec[],
  values: FormValues
): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  for (const f of fields) {
    const raw = (values[f.name] ?? "").trim();
    if (raw === "") continue; // optional field left blank -> omit
    payload[f.name] =
      f.type === "number" || f.type === "percent" ? Number(raw) : raw;
  }
  return payload;
}

export function DynamicForm(props: {
  fields: InputFieldSpec[];
  values: FormValues;
  errors: Record<string, string>;
  onChange: (name: string, value: string) => void;
}) {
  return (
    <div className="form-grid">
      {props.fields.map((f) => (
        <Field
          key={f.name}
          spec={f}
          value={props.values[f.name] ?? ""}
          error={props.errors[f.name]}
          onChange={(v) => props.onChange(f.name, v)}
        />
      ))}
    </div>
  );
}

function Field(props: {
  spec: InputFieldSpec;
  value: string;
  error?: string;
  onChange: (v: string) => void;
}) {
  const { spec } = props;
  const id = `field-${spec.name}`;
  return (
    <div className={`field${props.error ? " invalid" : ""}`}>
      <label htmlFor={id} title={spec.tooltip ?? undefined}>
        {spec.label}
        {spec.unit && <span className="unit">{spec.unit}</span>}
        {!spec.required && <span className="hint">optional</span>}
      </label>

      {spec.type === "select" && spec.choices ? (
        <select
          id={id}
          value={props.value}
          aria-invalid={!!props.error}
          aria-describedby={props.error ? `${id}-err` : undefined}
          onChange={(e) => props.onChange(e.target.value)}
        >
          {spec.choices.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      ) : spec.type === "date" ? (
        <input
          id={id}
          type="date"
          value={props.value}
          aria-invalid={!!props.error}
          aria-describedby={props.error ? `${id}-err` : undefined}
          onChange={(e) => props.onChange(e.target.value)}
        />
      ) : (
        <input
          id={id}
          type="number"
          inputMode="decimal"
          value={props.value}
          min={spec.min ?? undefined}
          max={spec.max ?? undefined}
          step={spec.step ?? "any"}
          placeholder={spec.required ? undefined : "from market snapshot"}
          aria-invalid={!!props.error}
          aria-describedby={props.error ? `${id}-err` : undefined}
          onChange={(e) => props.onChange(e.target.value)}
        />
      )}

      {props.error ? (
        <span className="error" id={`${id}-err`} role="alert">
          {props.error}
        </span>
      ) : (
        spec.tooltip && <span className="hint">{spec.tooltip}</span>
      )}
    </div>
  );
}
