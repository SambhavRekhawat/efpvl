/** Typed client for the EFPVL API. Mirrors the FastAPI contract exactly. */

import { API_BASE_URL } from "../config";

/* ---------- Types mirroring the API ------------------------------------- */

export interface ProductSummary {
  product_id: string;
  display_name: string;
  asset_class: string;
  summary: string;
  supported_models: string[];
}

export interface InputFieldSpec {
  name: string;
  label: string;
  type: "number" | "percent" | "date" | "select" | "currency";
  unit: string | null;
  default: unknown;
  min: number | null;
  max: number | null;
  step: number | null;
  choices: string[] | null;
  tooltip: string | null;
  description: string | null;
  required: boolean;
}

export interface ProductSchema {
  product_id: string;
  display_name: string;
  supported_models: string[];
  fields: InputFieldSpec[];
}

export interface CalculationStep {
  label: string;
  value: number;
  symbol: string | null;
  formula: string | null;
  inputs: Record<string, number>;
  note: string | null;
}

export interface ValuationResult {
  fair_value: number;
  currency: string;
  product_id: string;
  model_id: string;
  outputs: Record<string, number>;
  steps: CalculationStep[];
  explanation_key: string | null;
  warnings: string[];
  runtime_ms: number | null;
  as_of: string;
}

export interface ModelInfo {
  model_id: string;
  display_name: string;
  overview: string;
  assumptions: string[];
  limitations: string[];
  typical_usage: string;
  computational_complexity: string;
}

export interface SweepPoint {
  x: number;
  fair_value: number | null;
  outputs: Record<string, number>;
}

export interface SensitivityResponse {
  product_id: string;
  model_id: string;
  swept_field: string;
  points: SweepPoint[];
}

export interface MarketDataResponse {
  provenance_legend: Record<string, string>;
  snapshot: {
    snapshot_id: string;
    as_of: string;
    description: string;
    currency: string;
    risk_free_rate: number;
    yield_curve: { tenors_years: number[]; zero_rates: number[] };
    equity: {
      dividend_yield: number;
      historical_volatility: number;
      implied_vol_atm: number;
      vol_smile: { moneyness: number[]; implied_vols: number[] };
    };
    fx: Record<string, number>;
    credit: Record<string, number>;
    commodity: Record<string, number>;
  };
  curve: { pillars: { tenor_years: number; zero_rate: number }[] };
}

export interface Health {
  status: string;
  engine_version: string;
  registered_products: number;
  registered_models: number;
}

export interface FieldError {
  field: string;
  message: string;
}

/** Error carrying per-field validation messages from a 422 response. */
export class ApiError extends Error {
  status: number;
  fieldErrors: FieldError[];

  constructor(status: number, message: string, fieldErrors: FieldError[] = []) {
    super(message);
    this.status = status;
    this.fieldErrors = fieldErrors;
  }
}

/* ---------- Fetch machinery ---------------------------------------------- */

// Free-tier hosts sleep when idle and can take ~50s to wake, so the budget
// must exceed that or first-visit requests would spuriously "fail".
const REQUEST_TIMEOUT_MS = 75_000;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  // A hung request is worse than a failed one: bound every call so the UI
  // always resolves to either data or a message it can display.
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      ...init,
    });
  } catch (e) {
    throw new ApiError(
      0,
      e instanceof DOMException && e.name === "AbortError"
        ? "The engine did not respond in time. It may be waking from sleep — wait a moment and try again."
        : "Cannot reach the valuation engine. If this is the public demo the free-tier server may be waking up (up to a minute on first visit) — please retry. Running locally? Start the API with: uvicorn app.main:app"
    );
  } finally {
    window.clearTimeout(timer);
  }
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* non-JSON error body */
    }
    if (
      detail &&
      typeof detail === "object" &&
      "errors" in (detail as Record<string, unknown>)
    ) {
      const d = detail as { message: string; errors: FieldError[] };
      throw new ApiError(res.status, d.message, d.errors);
    }
    throw new ApiError(
      res.status,
      typeof detail === "string" ? detail : `Request failed (${res.status}).`
    );
  }
  return res.json() as Promise<T>;
}

/* ---------- Endpoints ----------------------------------------------------- */

export interface RiskMeasure {
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

export interface RiskResponse {
  product_id: string;
  model_id: string;
  measures: RiskMeasure[];
}

export interface CompareRow {
  model_id: string;
  display_name: string;
  fair_value: number;
  runtime_ms: number | null;
  outputs: Record<string, number>;
  warnings: string[];
  comparison_note: string | null;
  assumptions: string[];
  limitations: string[];
  diff_vs_baseline: number;
  diff_bps: number | null;
}

export interface CompareResponse {
  product_id: string;
  baseline_model_id: string;
  results: CompareRow[];
}

export const api = {
  health: () => request<Health>("/health"),
  compare: (
    productId: string,
    modelIds: string[],
    inputs: Record<string, unknown>
  ) =>
    request<CompareResponse>("/compare", {
      method: "POST",
      body: JSON.stringify({
        product_id: productId,
        model_ids: modelIds,
        inputs,
      }),
    }),
  exportReport: async (
    productId: string,
    modelId: string,
    inputs: Record<string, unknown>
  ): Promise<Blob> => {
    const res = await fetch(`${API_BASE_URL}/export/report`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        product_id: productId,
        model_id: modelId,
        inputs,
      }),
    });
    if (!res.ok) {
      let detail = `Report generation failed (${res.status}).`;
      try {
        const d = (await res.json()).detail;
        if (typeof d === "string") detail = d;
      } catch {
        /* keep default */
      }
      throw new ApiError(res.status, detail);
    }
    return res.blob();
  },
  risk: (productId: string, modelId: string, inputs: Record<string, unknown>) =>
    request<RiskResponse>("/risk", {
      method: "POST",
      body: JSON.stringify({ product_id: productId, model_id: modelId, inputs }),
    }),
  products: () => request<ProductSummary[]>("/products"),
  schema: (productId: string) =>
    request<ProductSchema>(`/products/${productId}/schema`),
  models: () => request<ModelInfo[]>("/models"),
  marketData: () => request<MarketDataResponse>("/market-data"),
  explainRisk: () => request<Record<string, unknown>>("/explain/risk"),
  valuate: (productId: string, modelId: string, inputs: Record<string, unknown>) =>
    request<ValuationResult>("/valuate", {
      method: "POST",
      body: JSON.stringify({ product_id: productId, model_id: modelId, inputs }),
    }),
  sensitivity: (
    productId: string,
    modelId: string,
    inputs: Record<string, unknown>,
    sweep: { field: string; min_value: number; max_value: number; points: number }
  ) =>
    request<SensitivityResponse>("/sensitivity", {
      method: "POST",
      body: JSON.stringify({
        product_id: productId,
        model_id: modelId,
        inputs,
        sweep,
      }),
    }),
};
