import { useEffect, useState } from "react";
import {
  api,
  ApiError,
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
import { ErrorNote, PageHead, Skeleton } from "../components/Layout";

/**
 * Take the valuation with you: a professional PDF report (inputs, market
 * snapshot, model assumptions, the full calculation trace, risk measures,
 * a sensitivity chart, limitations, timestamp) or the raw JSON result.
 */
export default function Export() {
  const [catalog, setCatalog] = useState<ProductSummary[] | null>(null);
  const [productId, setProductId] = useState("");
  const [schema, setSchema] = useState<ProductSchema | null>(null);
  const [values, setValues] = useState<FormValues>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [modelId, setModelId] = useState("");
  const [busy, setBusy] = useState<"pdf" | "json" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    api.products().then(setCatalog).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!productId) return;
    setSchema(null);
    setDone(null);
    api
      .schema(productId)
      .then((s) => {
        setSchema(s);
        setValues(defaultsFor(s.fields));
        setFieldErrors({});
        setModelId(s.supported_models[0] ?? "");
      })
      .catch((e: Error) => setError(e.message));
  }, [productId]);

  const checkForm = (): Record<string, unknown> | null => {
    if (!schema) return null;
    const errors = validate(schema.fields, values);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return null;
    return toPayload(schema.fields, values);
  };

  const save = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
    setDone(filename);
  };

  const downloadPdf = async () => {
    const payload = checkForm();
    if (!payload || !schema) return;
    setBusy("pdf");
    setError(null);
    try {
      const blob = await api.exportReport(schema.product_id, modelId, payload);
      save(blob, `efpvl_${schema.product_id}_${modelId}.pdf`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Report generation failed.");
    } finally {
      setBusy(null);
    }
  };

  const downloadJson = async () => {
    const payload = checkForm();
    if (!payload || !schema) return;
    setBusy("json");
    setError(null);
    try {
      const result = await api.valuate(schema.product_id, modelId, payload);
      save(
        new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }),
        `efpvl_${schema.product_id}_${modelId}.json`
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Valuation failed.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <PageHead
        eyebrow="Export"
        title="Take the valuation with you"
        blurb="A professional PDF: product terms, market snapshot, model assumptions and limitations, the complete calculation trace, risk measures, a sensitivity chart, and a timestamp. Or the raw result as JSON."
      />
      {error && <ErrorNote>{error}</ErrorNote>}

      {!productId && (
        <>
          {catalog ? (
            <div className="grid cols-3">
              {catalog.map((p) => (
                <button
                  key={p.product_id}
                  className="product-card"
                  onClick={() => setProductId(p.product_id)}
                >
                  <span className="name">{p.display_name}</span>
                  <span className="desc">{p.summary}</span>
                </button>
              ))}
            </div>
          ) : (
            !error && <Skeleton h={120} />
          )}
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
                  onChange={(n, v) => {
                    setValues((x) => ({ ...x, [n]: v }));
                    setDone(null);
                  }}
                />
                <div className="field" style={{ marginTop: 14, maxWidth: 280 }}>
                  <label htmlFor="export-model">Pricing model</label>
                  <select
                    id="export-model"
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
              </>
            )}
          </div>

          <div className="card" style={{ margin: 0, alignSelf: "start" }}>
            <div className="card-title">
              <h2>Download</h2>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <button className="primary" disabled={busy !== null} onClick={downloadPdf}>
                {busy === "pdf" ? "Building report…" : "Download PDF report"}
              </button>
              <button disabled={busy !== null} onClick={downloadJson}>
                {busy === "json" ? "Valuing…" : "Download result as JSON"}
              </button>
            </div>
            {done && (
              <p className="small" style={{ color: "var(--ok)", marginTop: 12 }}>
                Saved {done} to your downloads.
              </p>
            )}
            <p className="small muted" style={{ marginTop: 12 }}>
              The PDF opens with the fair value, then shows its work: every
              input, every assumption, every intermediate step — the same
              transparency as the app, in a document you can hand to someone.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
