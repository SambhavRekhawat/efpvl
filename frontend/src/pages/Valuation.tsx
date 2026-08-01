import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  api,
  ApiError,
  InputFieldSpec,
  ProductSchema,
  ProductSummary,
  SensitivityResponse,
  ValuationResult,
} from "../api/client";
import { SweepChart, TraceRail } from "../components/Charts";
import {
  DynamicForm,
  FormValues,
  defaultsFor,
  toPayload,
  validate,
} from "../components/DynamicForm";
import { ErrorNote, PageHead, Skeleton, fmt } from "../components/Layout";

/**
 * The heart of the laboratory. One page, any product: the form renders from
 * the API schema, Calculate returns the explainable result, and a sweep chart
 * previews how fair value moves along one chosen input.
 */
export default function Valuation() {
  const [params, setParams] = useSearchParams();
  const productId = params.get("product") ?? "";

  const [catalog, setCatalog] = useState<ProductSummary[] | null>(null);
  const [schema, setSchema] = useState<ProductSchema | null>(null);
  const [values, setValues] = useState<FormValues>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [modelId, setModelId] = useState("");

  const [result, setResult] = useState<ValuationResult | null>(null);
  const [pricing, setPricing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [sweepField, setSweepField] = useState("");
  const [sweep, setSweep] = useState<SensitivityResponse | null>(null);
  const [sweeping, setSweeping] = useState(false);

  /* -- Load catalog + schema ------------------------------------------- */

  useEffect(() => {
    api.products().then(setCatalog).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!productId) return;
    setSchema(null);
    setResult(null);
    setSweep(null);
    setError(null);
    api
      .schema(productId)
      .then((s) => {
        setSchema(s);
        setValues(defaultsFor(s.fields));
        setFieldErrors({});
        setModelId(s.supported_models[0] ?? "");
        setSweepField(defaultSweepField(s.fields));
      })
      .catch((e: Error) => setError(e.message));
  }, [productId]);

  const onChange = useCallback((name: string, value: string) => {
    setValues((v) => ({ ...v, [name]: value }));
    setFieldErrors((e) => {
      const { [name]: _gone, ...rest } = e;
      return rest;
    });
  }, []);

  /* -- Calculate --------------------------------------------------------- */

  const calculate = useCallback(async () => {
    if (!schema || pricing) return; // ignore repeat clicks while in flight
    const errors = validate(schema.fields, values);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setPricing(true);
    setError(null);
    try {
      const payload = toPayload(schema.fields, values);
      const res = await api.valuate(schema.product_id, modelId, payload);
      setResult(res);
      void runSweep(schema, modelId, payload, sweepField);
    } catch (e) {
      setResult(null);
      if (e instanceof ApiError && e.fieldErrors.length > 0) {
        const fe: Record<string, string> = {};
        for (const f of e.fieldErrors) fe[f.field] = f.message;
        setFieldErrors(fe);
        setError("Some inputs need attention — see the highlighted fields.");
      } else {
        setError(e instanceof Error ? e.message : "Pricing failed.");
      }
    } finally {
      setPricing(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schema, values, modelId, sweepField]);

  /* -- Sensitivity preview ----------------------------------------------- */

  const runSweep = useCallback(
    async (
      s: ProductSchema,
      model: string,
      payload: Record<string, unknown>,
      field: string
    ) => {
      const spec = s.fields.find((f) => f.name === field);
      if (!spec) return;
      const range = sweepRange(spec, Number(payload[field] ?? spec.default));
      if (!range) return;
      setSweeping(true);
      try {
        const res = await api.sensitivity(s.product_id, model, payload, {
          field,
          min_value: range[0],
          max_value: range[1],
          points: 60,
        });
        setSweep(res);
      } catch {
        setSweep(null); // chart is a bonus; never block results on it
      } finally {
        setSweeping(false);
      }
    },
    []
  );

  useEffect(() => {
    if (!schema || !result) return;
    void runSweep(schema, modelId, toPayload(schema.fields, values), sweepField);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sweepField]);

  const numericFields = useMemo(
    () =>
      schema?.fields.filter(
        (f) => (f.type === "number" || f.type === "percent") && f.required
      ) ?? [],
    [schema]
  );

  /* -- No product picked ------------------------------------------------- */

  if (!productId) {
    return (
      <div>
        <PageHead
          eyebrow="Valuation"
          title="Pick a product to price"
          blurb="Valuation starts from an instrument. Choose one and its input panel will build itself here."
        />
        {catalog ? (
          <div className="grid cols-3">
            {catalog.map((p) => (
              <button
                key={p.product_id}
                className="product-card"
                onClick={() => setParams({ product: p.product_id })}
              >
                <span className="name">{p.display_name}</span>
                <span className="desc">{p.summary}</span>
              </button>
            ))}
          </div>
        ) : error ? (
          <ErrorNote>{error}</ErrorNote>
        ) : (
          <Skeleton h={120} />
        )}
      </div>
    );
  }

  /* -- Main layout -------------------------------------------------------- */

  return (
    <div>
      <PageHead
        eyebrow="Valuation"
        title={schema?.display_name ?? "…"}
        blurb="Amber fields are yours. Blank optional fields fall back to the market snapshot. Everything violet below was derived by the engine — and shows its work."
      />

      <div className="grid split">
        {/* Left: contract terms */}
        <div className="card" style={{ margin: 0 }}>
          <div className="card-title">
            <h2>Contract terms</h2>
            <span className="tag user">user input</span>
          </div>

          {!schema && !error && <Skeleton h={220} />}
          {schema && (
            <>
              <DynamicForm
                fields={schema.fields}
                values={values}
                errors={fieldErrors}
                onChange={onChange}
              />
              <div
                style={{
                  display: "flex",
                  gap: 12,
                  alignItems: "center",
                  marginTop: 18,
                }}
              >
                <div className="field" style={{ flex: 1 }}>
                  <label htmlFor="model-select">Pricing model</label>
                  <select
                    id="model-select"
                    value={modelId}
                    onChange={(e) => setModelId(e.target.value)}
                  >
                    {schema.supported_models.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  className="primary"
                  onClick={calculate}
                  disabled={pricing}
                  style={{ alignSelf: "flex-end" }}
                >
                  {pricing ? "Calculating…" : "Calculate"}
                </button>
              </div>
              <p className="hint" style={{ marginTop: 10, color: "var(--faint)" }}>
                Model assumptions and limitations get their full page in Phase 4;
                for now, see them on <Link to="/">each model's card</Link>.
              </p>
            </>
          )}
          {error && !schema && <ErrorNote>{error}</ErrorNote>}
        </div>

        {/* Right: results */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {error && schema && <ErrorNote>{error}</ErrorNote>}

          {!result && !pricing && !error && (
            <div className="empty">
              Set the terms, then press Calculate. The fair value arrives with
              its entire derivation.
            </div>
          )}
          {pricing && <Skeleton h={150} />}

          {result && (
            <>
              <div className="card fade-in" style={{ margin: 0 }}>
                <div className="card-title">
                  <h2>Valuation</h2>
                  <span className="tag derived">derived</span>
                </div>
                <div className="hero-value">
                  <span className="eyebrow">Fair value ({result.currency})</span>
                  <span className="figure">{fmt(result.fair_value)}</span>
                  <span className="mono small" style={{ color: "var(--faint)" }}>
                    {result.model_id} · {fmt(result.runtime_ms, 2)} ms ·{" "}
                    {result.as_of.slice(0, 19).replace("T", " ")} UTC
                  </span>
                </div>
                {Object.keys(result.outputs).length > 0 && (
                  <div className="stat-grid" style={{ marginTop: 14 }}>
                    {Object.entries(result.outputs).map(([k, v]) => (
                      <div className="stat" key={k}>
                        <span className="k">{labelize(k)}</span>
                        <span className="v">{fmt(v)}</span>
                      </div>
                    ))}
                  </div>
                )}
                {result.warnings.length > 0 && (
                  <p className="small" style={{ color: "var(--user)", marginTop: 10 }}>
                    {result.warnings.join(" · ")}
                  </p>
                )}
              </div>

              <div className="card fade-in" style={{ margin: 0 }}>
                <details className="disclosure" open>
                  <summary>
                    <h2>Calculation trace</h2>
                    <span className="mono muted small">
                      {result.steps.length} steps
                    </span>
                  </summary>
                  <p className="small muted" style={{ margin: "10px 0 14px" }}>
                    The full derivation, in the order the engine computed it.
                    Nothing below is hidden from you.
                  </p>
                  <TraceRail steps={result.steps} />
                </details>
              </div>

              <div className="card fade-in" style={{ margin: 0 }}>
                <div className="card-title">
                  <h2>Sensitivity preview</h2>
                  <span className="tag derived">derived</span>
                </div>
                <div className="field" style={{ maxWidth: 260, marginBottom: 8 }}>
                  <label htmlFor="sweep-select">Fair value against</label>
                  <select
                    id="sweep-select"
                    value={sweepField}
                    onChange={(e) => setSweepField(e.target.value)}
                  >
                    {numericFields.map((f) => (
                      <option key={f.name} value={f.name}>
                        {f.label}
                      </option>
                    ))}
                  </select>
                </div>
                {sweeping && <Skeleton h={260} />}
                {!sweeping && sweep && (
                  <SweepChart
                    points={sweep.points}
                    xLabel={
                      schema?.fields.find((f) => f.name === sweepField)?.label ??
                      sweepField
                    }
                  />
                )}
                <p className="small muted">
                  Sixty repricings across the chosen input, everything else held
                  fixed. Full Greeks, duration, and convexity land in Phase 4.
                </p>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ---------- Helpers ------------------------------------------------------- */

function labelize(key: string): string {
  return key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

function defaultSweepField(fields: InputFieldSpec[]): string {
  const preferred = ["volatility", "coupon_rate", "spot", "face_value"];
  for (const p of preferred) {
    if (fields.some((f) => f.name === p)) return p;
  }
  return fields.find((f) => f.type === "number" || f.type === "percent")?.name ?? "";
}

/** Centered sweep window: current value ±60%, clamped to the schema range. */
function sweepRange(
  spec: InputFieldSpec,
  current: number
): [number, number] | null {
  if (Number.isNaN(current)) return null;
  const half = Math.max(Math.abs(current) * 0.6, spec.step ?? 1);
  let lo = current - half;
  let hi = current + half;
  if (spec.min != null) lo = Math.max(lo, spec.min);
  if (spec.max != null) hi = Math.min(hi, spec.max);
  if (hi <= lo) return null;
  return [lo, hi];
}
