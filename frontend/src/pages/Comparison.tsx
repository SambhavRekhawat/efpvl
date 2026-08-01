import { useEffect, useMemo, useState } from "react";
import {
  api,
  ApiError,
  CompareResponse,
  ProductSchema,
  ProductSummary,
} from "../api/client";
import {
  DynamicForm,
  FormValues,
  defaultsFor,
  toPayload,
  validate,
} from "../components/DynamicForm";
import { ErrorNote, PageHead, Skeleton, fmt } from "../components/Layout";

/**
 * Same product, several models, side by side — values, runtimes, and gaps in
 * basis points, with the authored account of *why* they differ. Only products
 * supporting two or more models qualify.
 */
export default function Comparison() {
  const [catalog, setCatalog] = useState<ProductSummary[] | null>(null);
  const [productId, setProductId] = useState("");
  const [schema, setSchema] = useState<ProductSchema | null>(null);
  const [values, setValues] = useState<FormValues>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [chosen, setChosen] = useState<string[]>([]);
  const [result, setResult] = useState<CompareResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.products().then(setCatalog).catch((e: Error) => setError(e.message));
  }, []);

  const eligible = useMemo(
    () => (catalog ?? []).filter((p) => p.supported_models.length >= 2),
    [catalog]
  );

  useEffect(() => {
    if (!productId) return;
    setSchema(null);
    setResult(null);
    api
      .schema(productId)
      .then((s) => {
        setSchema(s);
        setValues(defaultsFor(s.fields));
        setFieldErrors({});
        setChosen(s.supported_models.slice(0, 3));
      })
      .catch((e: Error) => setError(e.message));
  }, [productId]);

  const run = async () => {
    if (!schema) return;
    const errors = validate(schema.fields, values);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0 || chosen.length < 2) return;
    setBusy(true);
    setError(null);
    try {
      setResult(
        await api.compare(schema.product_id, chosen, toPayload(schema.fields, values))
      );
    } catch (e) {
      setResult(null);
      setError(e instanceof ApiError ? e.message : "Comparison failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHead
        eyebrow="Model Comparison"
        title="Same product, several models"
        blurb="All models here share one economic world — so when their prices differ, the gap is numerical, and each model explains its own. Pick a product with at least two supported models."
      />
      {error && <ErrorNote>{error}</ErrorNote>}

      {!productId && (
        <>
          {catalog && eligible.length === 0 && (
            <div className="empty">No multi-model products available.</div>
          )}
          <div className="grid cols-3">
            {eligible.map((p) => (
              <button
                key={p.product_id}
                className="product-card"
                onClick={() => setProductId(p.product_id)}
              >
                <span className="name">{p.display_name}</span>
                <span className="models">
                  {p.supported_models.length} models: {p.supported_models.join(", ")}
                </span>
              </button>
            ))}
          </div>
          {catalog &&
            catalog.length > eligible.length && (
              <p className="small muted" style={{ marginTop: 16 }}>
                The other {catalog.length - eligible.length} products currently
                support a single model each; they'll appear here as alternative
                models are added.
              </p>
            )}
          {!catalog && <Skeleton h={110} />}
        </>
      )}

      {productId && (
        <div className="grid split">
          <div className="card" style={{ margin: 0 }}>
            <div className="card-title">
              <h2>{schema?.display_name ?? "…"}</h2>
              <button className="small" onClick={() => setProductId("")}>
                change product
              </button>
            </div>
            {!schema && <Skeleton h={200} />}
            {schema && (
              <>
                <DynamicForm
                  fields={schema.fields}
                  values={values}
                  errors={fieldErrors}
                  onChange={(n, v) => setValues((x) => ({ ...x, [n]: v }))}
                />
                <div className="field" style={{ marginTop: 16 }}>
                  <label>Models to run ({chosen.length} selected)</label>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                    {schema.supported_models.map((m) => {
                      const on = chosen.includes(m);
                      return (
                        <button
                          key={m}
                          className={on ? "primary" : ""}
                          onClick={() =>
                            setChosen((c) =>
                              on
                                ? c.filter((x) => x !== m)
                                : c.length >= 4
                                ? c
                                : [...c, m]
                            )
                          }
                        >
                          {m}
                        </button>
                      );
                    })}
                  </div>
                  {chosen.length < 2 && (
                    <span className="error">Pick at least two models.</span>
                  )}
                  <span className="hint">
                    Two to four models per run; the engine compares any subset.
                  </span>
                </div>
                <button
                  className="primary"
                  style={{ marginTop: 14 }}
                  disabled={busy || chosen.length < 2}
                  onClick={run}
                >
                  {busy ? "Running all models…" : "Run comparison"}
                </button>
                <p className="hint" style={{ marginTop: 8, color: "var(--faint)" }}>
                  The first selected model is the baseline for the gap columns.
                </p>
              </>
            )}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {!result && !busy && (
              <div className="empty">
                Run the comparison to see values, runtimes, and each model's
                account of its own gap.
              </div>
            )}
            {busy && <Skeleton h={180} />}
            {result && (
              <>
                <div className="card fade-in" style={{ margin: 0 }}>
                  <div className="card-title">
                    <h2>Results</h2>
                    <span className="tag derived">derived</span>
                  </div>
                  <div className="table-wrap"><table>
                    <thead>
                      <tr>
                        <th>Model</th>
                        <th className="num">Fair value</th>
                        <th className="num">Δ vs baseline</th>
                        <th className="num">bp</th>
                        <th className="num">Runtime</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.results.map((r) => (
                        <tr key={r.model_id}>
                          <td>
                            {r.display_name}
                            {r.model_id === result.baseline_model_id && (
                              <span className="mono muted small"> · baseline</span>
                            )}
                            {r.outputs.standard_error !== undefined && (
                              <div className="small" style={{ color: "var(--faint)" }}>
                                ± {fmt(r.outputs.standard_error, 4)} SE
                              </div>
                            )}
                          </td>
                          <td className="num" style={{ color: "var(--derived)" }}>
                            {fmt(r.fair_value)}
                          </td>
                          <td className="num">{fmt(r.diff_vs_baseline, 5)}</td>
                          <td className="num">
                            {r.diff_bps === null ? "—" : fmt(r.diff_bps, 2)}
                          </td>
                          <td className="num">{fmt(r.runtime_ms, 2)} ms</td>
                        </tr>
                      ))}
                    </tbody>
                  </table></div>
                  <p className="small muted" style={{ marginTop: 10 }}>
                    Runtime is the honest price of generality: the closed form
                    is microseconds, the tree pays for its lattice, Monte Carlo
                    for its 200,000 draws.
                  </p>
                </div>

                {result.results.map(
                  (r) =>
                    r.comparison_note && (
                      <div className="card fade-in" style={{ margin: 0 }} key={r.model_id}>
                        <div className="card-title">
                          <h3>Why {r.display_name} lands where it does</h3>
                        </div>
                        <p className="small muted">{r.comparison_note}</p>
                      </div>
                    )
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
