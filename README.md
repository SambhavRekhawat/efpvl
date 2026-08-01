# EFPVL — Explainable Financial Product Valuation Laboratory

A professional, educational valuation lab that **teaches** how financial
products are priced. Every valuation returns its fair value **together with
the complete calculation behind it** — each discount factor, each
probability, each assumption — plus sensitivities, model comparison, an
interactive volatility smile, and exportable PDF reports, in a
terminal-inspired dark interface.

> Educational tool. Not investment advice, not a trading or booking system.

**11 products · 10 models · 200 automated tests** (133 engine + 67 API),
including golden values from the literature, machine-precision identities,
finite-difference verification of every Greek, and an automated "dogfood"
that prices every product × model pair and renders every PDF in CI.

---

## Screenshots

*(Add screenshots to `docs/screenshots/` and link them here — suggested set:
Home with the provenance legend, the Valuation trace rail, the Sensitivity
sliders mid-drag, the Vol Smile with its mispricing figure, a Model
Comparison run, and page one of an exported PDF.)*

---

## What's inside

| Asset class | Products | Models that price them |
|---|---|---|
| Rates | Zero Coupon Bond, Coupon Bond, FRA, Interest Rate Swap, Floating Rate Note | Discounted Cash Flow, Vasicek (ZCB) |
| Equity | European Call / Put | Black–Scholes, Binomial Tree (CRR), Monte Carlo, Heston, Merton Jump Diffusion, SABR |
| Credit | Credit Default Swap | Hazard Rate (reduced form) |
| FX | FX Forward, Currency Swap | Cost of Carry, Discounted Cash Flow |
| Commodity | Commodity Futures | Cost of Carry |
| Inflation | Inflation-Linked Bond | Discounted Cash Flow |

Risk measures ship with authored explanations (a 20-entry glossary): the
option Greeks, Macaulay/modified duration, convexity, DV01/PV01, CS01,
recovery sensitivity, default probability, FX and spot delta, inflation
DV01, and more.

## The three ideas that shape the codebase

**1. Explainability by construction.** A model that returns only a number is
*broken by definition* here: every `PricingModel.price()` must populate a
`ValuationResult` with an ordered trace of `CalculationStep`s (label, LaTeX
symbol and formula, inputs, value, teaching note). Tests enforce it. The UI
renders that trace as a ledger rail; the PDF prints it in full.

**2. Schema-driven everything.** Each product declares its inputs as typed
`InputField`s (units, ranges, defaults, tooltips). The API serves them at
`/api/products/{id}/schema`, and the frontend *builds its forms from that
response* — adding a product requires **zero frontend code**. The declared
ranges double as server-side abuse protection.

**3. Authored, versioned explanations.** Model essays and the risk glossary
are hand-written structured JSON under `engine/efpvl_engine/content/` —
never generated at request time — so the quant-teaching-a-quant voice stays
consistent and reviewable. CI fails if any registered model lacks complete
content.

## Architecture

```
                 one process serves everything (single-server mode)
   +------------------------------------------------------------------+
   |  FastAPI  (api/)                                                  |
   |  |-- /api/...        JSON API (surface listed below)              |
   |  +-- /*              built React app + SPA fallback               |
   +---------------+--------------------------------------------------+
                   | imports (never the reverse)
   +---------------v--------------------------------------------------+
   |  efpvl_engine  (engine/) - pure Python, zero web code             |
   |  |-- core/      Product / PricingModel / MarketData ABCs,         |
   |  |              ValuationResult + CalculationStep (the trace),    |
   |  |              InputField schema, plug-in registries             |
   |  |-- market/    day counts, zero curve, schedules,                |
   |  |              curated JSON snapshots (versioned, "as of")       |
   |  |-- products/  one module per product   (@register_product)      |
   |  |-- models/    one module per model     (@register_model)        |
   |  +-- content/   authored explanations (models/*.json, risk.json)  |
   +-------------------------------------------------------------------+

   frontend/ - React + TypeScript + Vite, Recharts, KaTeX
   Design system: ink-dark glass UI; three hues encode provenance
   everywhere (amber = user input, steel = market data, violet = derived)
```

**API surface** (live Swagger at `/docs`):
`GET /api/products` · `GET /api/products/{id}/schema` · `GET /api/models[/{id}]`
· `GET /api/market-data` · `GET /api/explain/risk` · `POST /api/valuate`
· `POST /api/sensitivity` · `POST /api/risk` · `POST /api/compare`
· `POST /api/export/report` · `GET /api/health`

The engine is deterministic (Monte Carlo is seeded), so identical requests
are served from a bounded response cache. Per-field validation errors return
as structured 422s that the UI maps back onto the exact offending inputs.

## Run it

**Single server (recommended)** — one process, one URL:

```bash
pip install -e "./engine[dev]" && pip install -r api/requirements.txt
cd frontend && npm install && npm run build && cd ..
cd api && uvicorn app.main:app --port 8000
# -> http://localhost:8000   (app, API under /api, Swagger at /docs)
```

Rebuild the frontend (`npm run build`) only when frontend code changes.

**Dev mode (hot reload)** — `uvicorn` as above in one terminal, and
`cd frontend && npm run dev` in another (Vite on :5173 proxies `/api`).

**Docker** — `docker compose up --build`.

## Testing philosophy

Correctness is demonstrated, not asserted:

* **Golden values** — Hull's Black–Scholes example to the printed digits
  (call 4.76, d1 = 0.7693).
* **Machine-precision identities** — par bond prices to 100; put–call parity
  to 1e-10; the swap floating leg telescoping to N(1-DF(T)); a zero-spread
  FRN worth *exactly* par; an inflation linker at pi = 0 reproducing the
  nominal bond to 1e-12; payer/receiver and buyer/seller mirrors to 1e-12.
* **Finite-difference verification** — every analytic Greek checked against
  central differences of the pricing function; durations, convexity and DV01
  against bump-and-reprice.
* **Collapse-to-baseline** — Heston (xi -> 0), SABR (nu = 0), Merton
  (lambda = 0, exact to 1e-12) and Vasicek (sigma = 0, against an
  independent hand formula) must each reproduce their simpler ancestor.
* **The dogfood** — CI prices every product with every supported model from
  schema defaults, checks risk where offered, and renders a PDF per product.
* **Content gates** — every registered model must serve a complete authored
  essay; every emitted risk key must have a glossary entry.

```bash
cd engine && pytest tests -q      # 133 tests
cd api    && pytest tests -q      #  67 tests
cd frontend && npm run build      # strict TypeScript is the frontend gate
```

## How to add a new product

This is the point of the architecture — engine work only, zero frontend
work. Example: a **Bond Future**.

1. **Create the product** at `engine/efpvl_engine/products/bond_future.py`:

   ```python
   @register_product
   class BondFuture(Product):
       product_id = "bond_future"

       def __init__(self, ...):        # contract terms, validated here
       @classmethod
       def meta(cls) -> ProductMeta:   # name, asset class, summary,
                                       # supported_models=("cost_of_carry",)
       @classmethod
       def input_schema(cls):          # one InputField per input: label,
                                       # type, unit, min/max, default,
                                       # tooltip -- this IS the form
       @classmethod
       def from_inputs(cls, inputs):   # raw dict -> instance
   ```

2. **Register it** — one import line in `products/__init__.py`.

3. **Price it** — either extend an existing model's `supports()` and add a
   pricing branch, or add a new `@register_model` class whose `price()`
   returns a `ValuationResult` **with a populated step trace** (tests reject
   a bare number). Optionally implement `risk_measures()`; every key you
   emit must exist in `content/risk.json`.

4. **Explain it** — if you added a model, write
   `content/models/<model_id>.json` (overview, formula_latex, at least four
   variables, assumptions, limitations, when to use / when not to). The
   content gate in CI enforces completeness.

5. **Test it** — add golden values and at least one identity under
   `engine/tests/`. The dogfood picks the new product up automatically.

Run the app: the product card, its self-built form, sliders, charts,
comparison eligibility, and PDF export all appear without touching
`frontend/`.

## Repository layout

```
efpvl/
|-- engine/          pricing library (see Architecture) + 133 tests
|-- api/             FastAPI app, PDF report builder, cache + 67 tests
|-- frontend/        React/TS app: design system, 9 pages, dynamic forms
|-- docs/            phase7-checklist.md, screenshots/
|-- docker-compose.yml
+-- .github/workflows/ci.yml    engine | api | frontend jobs on every push
```

## Deployment

The website deploys to **Vercel** (static build from `frontend/`) and the
Python engine to **Render** (`render.yaml` blueprint included). Production
guards: CORS locked to the site's origin, an IP rate limiter with
per-endpoint costs (PDF rendering costs more than a quote), security
headers, structured 500s, and a client that tolerates free-tier cold starts.

Step-by-step instructions, written for a first-time deployer, are in
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

```
Vercel (website)  ──HTTPS──>  Render (FastAPI + engine)
      ^                              ^
      └──────── GitHub push redeploys both ────────┘
```

## Status

Phases 0-8 complete: skeleton, engine, API, UI, explainability, 11 products
/ 10 models, comparison + smile + export, local hardening, and public
deployment.

EFPVL is an educational project. Market data is a static curated snapshot.
Nothing here is investment advice.
