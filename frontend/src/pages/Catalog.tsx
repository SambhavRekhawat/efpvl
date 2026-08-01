import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Line,
  LineChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, MarketDataResponse, ProductSummary } from "../api/client";
import { ErrorNote, PageHead, Skeleton, fmt } from "../components/Layout";
import { chart } from "../components/Charts";

/* ========================================================================= */
/* Product Selection                                                          */
/* ========================================================================= */

export function Products() {
  const [products, setProducts] = useState<ProductSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    api.products().then(setProducts).catch((e: Error) => setError(e.message));
  }, []);

  const grouped = useMemo(() => {
    const g = new Map<string, ProductSummary[]>();
    for (const p of products ?? []) {
      g.set(p.asset_class, [...(g.get(p.asset_class) ?? []), p]);
    }
    return [...g.entries()];
  }, [products]);

  return (
    <div>
      <PageHead
        eyebrow="Product Selection"
        title="Choose an instrument"
        blurb="Each product declares its own inputs; the form on the Valuation page builds itself from that declaration. Select one to begin."
      />
      {error && <ErrorNote>{error}</ErrorNote>}
      {!products && !error && (
        <div className="grid cols-3">
          <Skeleton h={110} /> <Skeleton h={110} /> <Skeleton h={110} />
        </div>
      )}
      {grouped.map(([assetClass, items]) => (
        <section key={assetClass} style={{ marginBottom: 26 }}>
          <span className="eyebrow">{assetClass}</span>
          <div className="grid cols-3" style={{ marginTop: 10 }}>
            {items.map((p) => (
              <button
                key={p.product_id}
                className="product-card"
                onClick={() => navigate(`/valuation?product=${p.product_id}`)}
              >
                <span className="name">{p.display_name}</span>
                <span className="desc">{p.summary}</span>
                <span className="models">
                  models: {p.supported_models.join(", ")}
                </span>
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

/* ========================================================================= */
/* Market Data                                                                */
/* ========================================================================= */

const axisTick = { fill: chart.axis, fontSize: 11, fontFamily: "IBM Plex Mono" };
const tooltipStyle = {
  background: chart.tooltipBg,
  border: "1px solid rgba(148,170,210,0.25)",
  borderRadius: 9,
  fontFamily: "IBM Plex Mono",
  fontSize: 12,
};

export function MarketData() {
  const [data, setData] = useState<MarketDataResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.marketData().then(setData).catch((e: Error) => setError(e.message));
  }, []);

  if (error)
    return (
      <div>
        <PageHead eyebrow="Market Data" title="Market inputs" />
        <ErrorNote>{error}</ErrorNote>
      </div>
    );
  if (!data)
    return (
      <div>
        <PageHead eyebrow="Market Data" title="Market inputs" />
        <Skeleton h={280} />
      </div>
    );

  const s = data.snapshot;
  const curveData = s.yield_curve.tenors_years.map((t, i) => ({
    t,
    rate: s.yield_curve.zero_rates[i] * 100,
  }));
  const smileData = s.equity.vol_smile.moneyness.map((m, i) => ({
    m,
    vol: s.equity.vol_smile.implied_vols[i] * 100,
  }));

  return (
    <div>
      <PageHead
        eyebrow="Market Data"
        title="Every market input, in the open"
        blurb={`Valuations draw on this curated snapshot (${s.snapshot_id}, as of ${s.as_of.slice(0, 10)}). It is static and versioned — honest, reproducible teaching data rather than a live feed.`}
      />

      <div className="card">
        <div className="card-title">
          <h2>Provenance legend</h2>
        </div>
        <div className="grid cols-3">
          {(["user", "market", "derived"] as const).map((k) => (
            <div key={k}>
              <span className={`tag ${k}`}>{k}</span>
              <p className="small muted" style={{ marginTop: 6 }}>
                {data.provenance_legend[k]}
              </p>
            </div>
          ))}
        </div>
      </div>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <div className="card" style={{ margin: 0 }}>
          <div className="card-title">
            <h2>Zero curve</h2>
            <span className="tag market">market</span>
          </div>
          <div style={{ width: "100%", height: 240 }}>
            <ResponsiveContainer>
              <LineChart data={curveData} margin={{ top: 6, right: 12, bottom: 4, left: 0 }}>
                <CartesianGrid stroke={chart.grid} vertical={false} />
                <XAxis dataKey="t" tick={axisTick} tickLine={false}
                  axisLine={{ stroke: chart.grid }} unit="y" />
                <YAxis tick={axisTick} tickLine={false} axisLine={false}
                  width={52} unit="%" domain={["auto", "auto"]} />
                <Tooltip contentStyle={tooltipStyle}
                  labelFormatter={(v) => `${v}y tenor`}
                  formatter={(v) => [`${fmt(Number(v), 3)}%`, "zero rate"]} />
                <Line type="monotone" dataKey="rate" stroke={chart.market}
                  strokeWidth={2} dot={{ r: 3, fill: chart.market, strokeWidth: 0 }}
                  isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="small muted">
            Continuously compounded zero rates; the engine interpolates
            log-linearly on discount factors between pillars.
          </p>
        </div>

        <div className="card" style={{ margin: 0 }}>
          <div className="card-title">
            <h2>Volatility smile</h2>
            <span className="tag market">market</span>
          </div>
          <div style={{ width: "100%", height: 240 }}>
            <ResponsiveContainer>
              <LineChart data={smileData} margin={{ top: 6, right: 12, bottom: 4, left: 0 }}>
                <CartesianGrid stroke={chart.grid} vertical={false} />
                <XAxis dataKey="m" tick={axisTick} tickLine={false}
                  axisLine={{ stroke: chart.grid }} />
                <YAxis tick={axisTick} tickLine={false} axisLine={false}
                  width={52} unit="%" domain={["auto", "auto"]} />
                <Tooltip contentStyle={tooltipStyle}
                  labelFormatter={(v) => `moneyness ${v}`}
                  formatter={(v) => [`${fmt(Number(v), 1)}%`, "implied vol"]} />
                <Line type="monotone" dataKey="vol" stroke={chart.derived}
                  strokeWidth={2} dot={{ r: 3, fill: chart.derived, strokeWidth: 0 }}
                  isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="small muted">
            Implied volatility by strike/spot moneyness. Black–Scholes assumes
            this line is flat — the smile is the market disagreeing. Full
            treatment arrives in Phase 6.
          </p>
        </div>
      </div>

      <div className="grid cols-3" style={{ marginTop: 16 }}>
        <div className="card" style={{ margin: 0 }}>
          <div className="card-title"><h2>Rates &amp; equity</h2><span className="tag market">market</span></div>
          <div className="table-wrap"><table>
            <tbody>
              <tr><td>Risk-free rate</td><td className="num">{fmt(s.risk_free_rate * 100, 2)}%</td></tr>
              <tr><td>Dividend yield</td><td className="num">{fmt(s.equity.dividend_yield * 100, 2)}%</td></tr>
              <tr><td>Historical vol</td><td className="num">{fmt(s.equity.historical_volatility * 100, 1)}%</td></tr>
              <tr><td>ATM implied vol</td><td className="num">{fmt(s.equity.implied_vol_atm * 100, 1)}%</td></tr>
            </tbody>
          </table></div>
        </div>
        <div className="card" style={{ margin: 0 }}>
          <div className="card-title"><h2>FX</h2><span className="tag market">market</span></div>
          <div className="table-wrap"><table>
            <tbody>
              {Object.entries(s.fx).map(([pair, rate]) => (
                <tr key={pair}><td className="mono">{pair}</td><td className="num">{fmt(rate, 4)}</td></tr>
              ))}
            </tbody>
          </table></div>
        </div>
        <div className="card" style={{ margin: 0 }}>
          <div className="card-title"><h2>Credit &amp; commodity</h2><span className="tag market">market</span></div>
          <div className="table-wrap"><table>
            <tbody>
              <tr><td>IG 5y spread</td><td className="num">{fmt(s.credit.ig_5y_spread_bps, 0)} bp</td></tr>
              <tr><td>HY 5y spread</td><td className="num">{fmt(s.credit.hy_5y_spread_bps, 0)} bp</td></tr>
              <tr><td>Recovery rate</td><td className="num">{fmt(s.credit.recovery_rate * 100, 0)}%</td></tr>
              <tr><td>WTI spot</td><td className="num">{fmt(s.commodity.wti_spot, 2)}</td></tr>
            </tbody>
          </table></div>
        </div>
      </div>
    </div>
  );
}
