import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  api,
  InputFieldSpec,
  ProductSchema,
  ProductSummary,
  SensitivityResponse,
} from "../api/client";
import { SweepChart } from "../components/Charts";
import { Formula } from "../components/Formula";
import {
  FormValues,
  defaultsFor,
  toPayload,
} from "../components/DynamicForm";
import { ErrorNote, PageHead, Skeleton, fmt } from "../components/Layout";

interface Measure {
  key: string;
  value: number;
  name?: string;
  symbol?: string;
  unit?: string;
  formula_latex?: string;
  definition?: string;
  interpretation?: string;
  business_meaning?: string;
  use_cases?: string;
}

/**
 * Live risk laboratory: drag a slider, watch every measure and the chart
 * reprice (~300ms debounce). Non-numeric terms (dates, frequency) stay at
 * their defaults; this page is about feeling the derivatives.
 */
export default function Sensitivity() {
  const [params, setParams] = useSearchParams();
  const productId = params.get("product") ?? "";

  const [catalog, setCatalog] = useState<ProductSummary[] | null>(null);
  const [schema, setSchema] = useState<ProductSchema | null>(null);
  const [values, setValues] = useState<FormValues>({});
  const [modelId, setModelId] = useState("");
  const [measures, setMeasures] = useState<Measure[] | null>(null);
  const [sweep, setSweep] = useState<SensitivityResponse | null>(null);
  const [sweepField, setSweepField] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    api.products().then(setCatalog).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!productId) return;
    setSchema(null);
    setMeasures(null);
    setSweep(null);
    setError(null);
    api
      .schema(productId)
      .then((s) => {
        setSchema(s);
        const v = defaultsFor(s.fields);
        setValues(v);
        setModelId(s.supported_models[0] ?? "");
        const numeric = numericFieldsOf(s.fields);
        setSweepField(numeric[0]?.name ?? "");
        refresh(s, s.supported_models[0] ?? "", v, numeric[0]?.name ?? "", 0);
      })
      .catch((e: Error) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productId]);

  /* -- Debounced refresh -------------------------------------------------- */

  const refresh = useCallback(
    (
      s: ProductSchema,
      model: string,
      vals: FormValues,
      field: string,
      delay = 300
    ) => {
      if (timer.current) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(async () => {
        setBusy(true);
        setError(null);
        try {
          const payload = toPayload(s.fields, vals);
          const [riskRes, sweepRes] = await Promise.all([
            // Some product/model pairs have no risk measures yet — that is
            // information, not an error, and must never sink the chart.
            api.risk(s.product_id, model, payload).catch(() => null),
            (async () => {
              const spec = s.fields.find((f) => f.name === field);
              if (!spec) return null;
              const current = Number(vals[field]);
              const range = sliderRange(spec, current);
              return api.sensitivity(s.product_id, model, payload, {
                field,
                min_value: range[0],
                max_value: range[1],
                points: 60,
              });
            })(),
          ]);
          setMeasures(riskRes ? riskRes.measures : []);
          if (sweepRes) setSweep(sweepRes);
        } catch (e) {
          setError(e instanceof Error ? e.message : "Recalculation failed.");
        } finally {
          setBusy(false);
        }
      }, delay);
    },
    []
  );

  const onSlide = (name: string, value: string) => {
    const next = { ...values, [name]: value };
    setValues(next);
    if (schema) refresh(schema, modelId, next, sweepField);
  };

  const numeric = useMemo(
    () => (schema ? numericFieldsOf(schema.fields) : []),
    [schema]
  );

  /* -- Product picker ------------------------------------------------------ */

  if (!productId) {
    return (
      <div>
        <PageHead
          eyebrow="Sensitivity Analysis"
          title="Feel the derivatives"
          blurb="Pick a product, then drag its inputs. Greeks, durations, and the price curve reprice live as you move."
        />
        {error && <ErrorNote>{error}</ErrorNote>}
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
        ) : (
          !error && <Skeleton h={120} />
        )}
      </div>
    );
  }

  /* -- Lab layout ----------------------------------------------------------- */

  return (
    <div>
      <PageHead
        eyebrow="Sensitivity Analysis"
        title={schema?.display_name ?? "…"}
        blurb="Amber sliders are your inputs. Every violet number below re-derives about a third of a second after you stop moving."
      />
      {error && <ErrorNote>{error}</ErrorNote>}

      <div className="grid split">
        <div className="card" style={{ margin: 0 }}>
          <div className="card-title">
            <h2>Drag the inputs</h2>
            <span className="tag user">user input</span>
          </div>
          {!schema && <Skeleton h={200} />}
          {schema && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {numeric.map((f) => {
                const current = Number(values[f.name]);
                const [lo, hi] = sliderRange(f, current);
                const fill = ((current - lo) / (hi - lo)) * 100;
                return (
                  <div className="field" key={f.name}>
                    <label htmlFor={`sl-${f.name}`}>
                      {f.label}
                      {f.unit && <span className="unit">{f.unit}</span>}
                    </label>
                    <div className="slider-row">
                      <input
                        id={`sl-${f.name}`}
                        type="range"
                        min={lo}
                        max={hi}
                        step={(hi - lo) / 200}
                        value={current}
                        style={{ "--fill": `${fill}%` } as React.CSSProperties}
                        onChange={(e) => onSlide(f.name, e.target.value)}
                      />
                      <input
                        type="number"
                        value={values[f.name] ?? ""}
                        onChange={(e) => onSlide(f.name, e.target.value)}
                        aria-label={`${f.label} (exact value)`}
                      />
                    </div>
                  </div>
                );
              })}
              <p className="small" style={{ color: "var(--faint)" }}>
                Dates, frequencies, and other non-numeric terms use their
                defaults here — set them precisely on the Valuation page.
              </p>
            </div>
          )}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="card" style={{ margin: 0 }}>
            <div className="card-title">
              <h2>Risk measures</h2>
              <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {busy && <span className="spin" aria-label="recalculating" />}
                <span className="tag derived">derived</span>
              </span>
            </div>
            {!measures && <Skeleton h={180} />}
            {measures && measures.length === 0 && (
              <p className="small muted">
                No risk measures are defined for this product yet — the price
                curve below still repriced live.
              </p>
            )}
            {measures && measures.length > 0 && (
              <div className="grid cols-2">
                {measures.map((m) => (
                  <div className="measure" key={m.key}>
                    <div className="head">
                      <span className="name">
                        {m.name ?? m.key}{" "}
                        {m.symbol && <Formula latex={m.symbol} />}
                      </span>
                      <span className="val">{fmt(m.value, 4)}</span>
                    </div>
                    {m.unit && <span className="unit">{m.unit}</span>}
                    {m.definition && <p className="def">{m.definition}</p>}
                    <details className="disclosure">
                      <summary className="small muted">full explanation</summary>
                      {m.formula_latex && (
                        <Formula latex={m.formula_latex} display />
                      )}
                      {m.interpretation && (
                        <p>
                          <span className="k">Reading it</span>
                          <br />
                          {m.interpretation}
                        </p>
                      )}
                      {m.business_meaning && (
                        <p>
                          <span className="k">Why desks care</span>
                          <br />
                          {m.business_meaning}
                        </p>
                      )}
                      {m.use_cases && (
                        <p>
                          <span className="k">Used for</span>
                          <br />
                          {m.use_cases}
                        </p>
                      )}
                    </details>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card" style={{ margin: 0 }}>
            <div className="card-title">
              <h2>Price curve</h2>
              <span className="tag derived">derived</span>
            </div>
            <div className="field" style={{ maxWidth: 260, marginBottom: 8 }}>
              <label htmlFor="sens-sweep">Fair value against</label>
              <select
                id="sens-sweep"
                value={sweepField}
                onChange={(e) => {
                  setSweepField(e.target.value);
                  if (schema) refresh(schema, modelId, values, e.target.value, 0);
                }}
              >
                {numeric.map((f) => (
                  <option key={f.name} value={f.name}>
                    {f.label}
                  </option>
                ))}
              </select>
            </div>
            {sweep ? (
              <SweepChart
                points={sweep.points}
                xLabel={
                  schema?.fields.find((f) => f.name === sweepField)?.label ??
                  sweepField
                }
              />
            ) : (
              <Skeleton h={260} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------- Helpers -------------------------------------------------------- */

function numericFieldsOf(fields: InputFieldSpec[]): InputFieldSpec[] {
  return fields.filter(
    (f) => (f.type === "number" || f.type === "percent") && f.required
  );
}

/** Slider window: default ±60% around the schema default, clamped to range. */
function sliderRange(spec: InputFieldSpec, current: number): [number, number] {
  const base = Number(spec.default ?? current) || current || 1;
  const half = Math.max(Math.abs(base) * 0.6, spec.step ?? 1);
  let lo = base - half;
  let hi = base + half;
  if (spec.min != null) lo = Math.max(lo, spec.min);
  if (spec.max != null) hi = Math.min(hi, spec.max);
  if (Number.isFinite(current)) {
    lo = Math.min(lo, current);
    hi = Math.max(hi, current);
  }
  return [lo, hi];
}
