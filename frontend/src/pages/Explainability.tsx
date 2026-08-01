import { useEffect, useState } from "react";
import { api, ModelInfo } from "../api/client";
import { Formula } from "../components/Formula";
import { ErrorNote, PageHead, Skeleton } from "../components/Layout";

interface Variable {
  symbol: string;
  name: string;
  why_it_matters: string;
}

interface RichModel extends ModelInfo {
  formula_latex?: string;
  variables?: Variable[];
  when_to_use?: string;
  when_not_to_use?: string;
  industry_usage?: string;
}

interface RiskEntry {
  name: string;
  symbol: string;
  unit: string;
  formula_latex: string;
  definition: string;
  interpretation: string;
  business_meaning: string;
  use_cases: string;
}

/**
 * The library of the laboratory: authored, quant-to-quant accounts of each
 * model, plus the risk-measure glossary. Nothing here is generated — it is
 * written, versioned content served verbatim from the engine.
 */
export default function Explainability() {
  const [models, setModels] = useState<RichModel[] | null>(null);
  const [risk, setRisk] = useState<Record<string, RiskEntry> | null>(null);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .models()
      .then((ms) => {
        setModels(ms as RichModel[]);
        setSelected(ms[0]?.model_id ?? "");
      })
      .catch((e: Error) => setError(e.message));
    api
      .explainRisk()
      .then((r) => setRisk(r as unknown as Record<string, RiskEntry>))
      .catch(() => undefined);
  }, []);

  const model = models?.find((m) => m.model_id === selected);

  return (
    <div>
      <PageHead
        eyebrow="Explainability"
        title="The why behind every number"
        blurb="Written the way one quant explains to another: what the model believes, what each symbol is doing, where it breaks, and when to put it down and pick up a different one."
      />
      {error && <ErrorNote>{error}</ErrorNote>}
      {!models && !error && <Skeleton h={300} />}

      {models && (
        <>
          <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
            {models.map((m) => (
              <button
                key={m.model_id}
                className={selected === m.model_id ? "primary" : ""}
                onClick={() => setSelected(m.model_id)}
              >
                {m.display_name}
              </button>
            ))}
          </div>

          {model && (
            <div className="fade-in" key={model.model_id}>
              <div className="card">
                <div className="card-title">
                  <h2>{model.display_name}</h2>
                  <span className="mono muted small">
                    {model.computational_complexity}
                  </span>
                </div>
                <p className="muted" style={{ marginBottom: 12 }}>
                  {model.overview}
                </p>
                {model.formula_latex && (
                  <Formula latex={model.formula_latex} display />
                )}
              </div>

              {model.variables && (
                <div className="card">
                  <div className="card-title">
                    <h2>What each symbol is doing</h2>
                  </div>
                  <div className="table-wrap"><table>
                    <thead>
                      <tr>
                        <th style={{ width: 70 }}>Symbol</th>
                        <th style={{ width: 140 }}>Name</th>
                        <th>Why it matters</th>
                      </tr>
                    </thead>
                    <tbody>
                      {model.variables.map((v) => (
                        <tr key={v.symbol}>
                          <td>
                            <Formula latex={v.symbol} />
                          </td>
                          <td>{v.name}</td>
                          <td className="muted small">{v.why_it_matters}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table></div>
                </div>
              )}

              <div className="grid cols-2" style={{ marginTop: 16 }}>
                <div className="card" style={{ margin: 0 }}>
                  <div className="card-title">
                    <h2>Assumptions</h2>
                    <span className="tag market">what it believes</span>
                  </div>
                  <ul className="small muted" style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 8 }}>
                    {model.assumptions.map((a, i) => (
                      <li key={i}>{a}</li>
                    ))}
                  </ul>
                </div>
                <div className="card" style={{ margin: 0 }}>
                  <div className="card-title">
                    <h2>Limitations</h2>
                    <span className="tag user">where it breaks</span>
                  </div>
                  <ul className="small muted" style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 8 }}>
                    {model.limitations.map((l, i) => (
                      <li key={i}>{l}</li>
                    ))}
                  </ul>
                </div>
              </div>

              <div className="grid cols-2" style={{ marginTop: 16 }}>
                <div className="card" style={{ margin: 0 }}>
                  <div className="card-title">
                    <h2>Reach for it when</h2>
                  </div>
                  <p className="small muted">{model.when_to_use}</p>
                  {model.industry_usage && (
                    <p className="small" style={{ color: "var(--faint)", marginTop: 10 }}>
                      In industry: {model.industry_usage}
                    </p>
                  )}
                </div>
                <div className="card" style={{ margin: 0 }}>
                  <div className="card-title">
                    <h2>Put it down when</h2>
                  </div>
                  <p className="small muted">{model.when_not_to_use}</p>
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {risk && (
        <section style={{ marginTop: 34 }}>
          <span className="eyebrow">Risk measure glossary</span>
          <div className="grid cols-2" style={{ marginTop: 12 }}>
            {Object.entries(risk).map(([key, m]) => (
              <div className="measure" key={key}>
                <div className="head">
                  <span className="name">
                    {m.name} <Formula latex={m.symbol} />
                  </span>
                  <span className="unit">{m.unit}</span>
                </div>
                <Formula latex={m.formula_latex} display />
                <p className="def">{m.definition}</p>
                <details className="disclosure">
                  <summary className="small muted">interpretation &amp; use</summary>
                  <p className="small muted" style={{ marginTop: 6 }}>{m.interpretation}</p>
                  <p className="small muted" style={{ marginTop: 6 }}>{m.business_meaning}</p>
                  <p className="small" style={{ color: "var(--faint)", marginTop: 6 }}>
                    Used for: {m.use_cases}
                  </p>
                </details>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
