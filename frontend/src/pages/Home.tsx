import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, MarketDataResponse, ModelInfo, ProductSummary } from "../api/client";
import { Skeleton } from "../components/Layout";

/**
 * Home: the thesis, stated with the app's own vocabulary. The provenance
 * triad is introduced here because it is the reading key for every page.
 */
export default function Home() {
  const [products, setProducts] = useState<ProductSummary[] | null>(null);
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [market, setMarket] = useState<MarketDataResponse | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    api.products().then(setProducts).catch(() => setOffline(true));
    api.models().then(setModels).catch(() => undefined);
    api.marketData().then(setMarket).catch(() => undefined);
  }, []);

  return (
    <div className="fade-in">
      <header className="page-head" style={{ marginBottom: 30 }}>
        <span className="eyebrow">Explainable Financial Product Valuation Laboratory</span>
        <h1 style={{ fontSize: "2.3rem", maxWidth: "18ch" }}>
          The price is the least interesting number here.
        </h1>
        <p style={{ maxWidth: "58ch" }}>
          Every valuation in this laboratory returns its fair value together with
          the complete calculation behind it — each discount factor, each
          probability, each assumption — so you can see how the number was made,
          not just what it is.
        </p>
        <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
          <Link to="/products">
            <button className="primary">Choose a product</button>
          </Link>
          <Link to="/market-data">
            <button>Inspect the market data</button>
          </Link>
        </div>
      </header>

      <div className="card">
        <div className="card-title">
          <h2>How to read this laboratory</h2>
        </div>
        <p className="muted small" style={{ marginBottom: 12 }}>
          Every number on every page carries one of three colors telling you
          where it came from:
        </p>
        <div className="grid cols-3">
          <div>
            <span className="tag user">user input</span>
            <p className="small muted" style={{ marginTop: 8 }}>
              Terms you type into a product form — face value, strike,
              volatility. You control these.
            </p>
          </div>
          <div>
            <span className="tag market">market data</span>
            <p className="small muted" style={{ marginTop: 8 }}>
              From the curated snapshot — the yield curve, rates, FX. Static,
              versioned, and shown in full on the Market Data page.
            </p>
          </div>
          <div>
            <span className="tag derived">derived</span>
            <p className="small muted" style={{ marginTop: 8 }}>
              Computed by the engine — discount factors, d₁, fair values. Every
              one appears in a calculation trace.
            </p>
          </div>
        </div>
      </div>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <div className="card" style={{ margin: 0 }}>
          <div className="card-title">
            <h2>Products online</h2>
            {products && <span className="mono muted small">{products.length}</span>}
          </div>
          {offline ? (
            <p className="muted small">
              Engine offline — start the API to load the catalog.
            </p>
          ) : products ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {products.map((p) => (
                <Link
                  key={p.product_id}
                  to={`/valuation?product=${p.product_id}`}
                  className="small"
                >
                  {p.display_name}
                  <span className="mono muted"> · {p.asset_class}</span>
                </Link>
              ))}
              <p className="small muted" style={{ marginTop: 6 }}>
                More arrive with each phase — swaps, caps and floors, CDS, FX
                forwards, commodities.
              </p>
            </div>
          ) : (
            <Skeleton h={90} />
          )}
        </div>

        <div className="card" style={{ margin: 0 }}>
          <div className="card-title">
            <h2>Pricing models</h2>
            {models && <span className="mono muted small">{models.length}</span>}
          </div>
          {models ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {models.map((m) => (
                <div key={m.model_id}>
                  <p className="small" style={{ fontWeight: 600 }}>
                    {m.display_name}
                  </p>
                  <p className="small muted">{m.overview}</p>
                </div>
              ))}
            </div>
          ) : (
            <Skeleton h={90} />
          )}
          {market && (
            <p className="mono small" style={{ color: "var(--faint)", marginTop: 14 }}>
              MARKET SNAPSHOT AS OF {market.snapshot.as_of.slice(0, 10)} ·
              STATIC · EDUCATIONAL
            </p>
          )}
        </div>
      </div>

      <p className="small" style={{ color: "var(--faint)", marginTop: 22 }}>
        EFPVL is an educational tool for understanding valuation methodology.
        It is not investment advice and not a trading system.
      </p>
    </div>
  );
}
