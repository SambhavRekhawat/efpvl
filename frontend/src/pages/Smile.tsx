import { useCallback, useEffect, useRef, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, MarketDataResponse } from "../api/client";
import { chart } from "../components/Charts";
import { ErrorNote, PageHead, Skeleton, fmt } from "../components/Layout";

/**
 * The market's polite disagreement with Black–Scholes, made interactive:
 * slide the strike along the smile and watch the price gap between constant
 * ATM volatility and the market's strike-dependent implied volatility.
 */
export default function Smile() {
  const [market, setMarket] = useState<MarketDataResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [moneyness, setMoneyness] = useState(1.0);
  const [optionType, setOptionType] = useState<"Call" | "Put">("Put");
  const [prices, setPrices] = useState<{ flat: number; smile: number } | null>(
    null
  );
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);

  const SPOT = 100;
  const EXPIRY = 1.0;

  useEffect(() => {
    api.marketData().then(setMarket).catch((e: Error) => setError(e.message));
  }, []);

  const smileVolAt = useCallback(
    (m: number): number => {
      if (!market) return 0.2;
      const { moneyness: xs, implied_vols: ys } = market.snapshot.equity.vol_smile;
      if (m <= xs[0]) return ys[0];
      if (m >= xs[xs.length - 1]) return ys[ys.length - 1];
      for (let i = 0; i < xs.length - 1; i++) {
        if (m >= xs[i] && m <= xs[i + 1]) {
          const w = (m - xs[i]) / (xs[i + 1] - xs[i]);
          return ys[i] + w * (ys[i + 1] - ys[i]);
        }
      }
      return ys[0];
    },
    [market]
  );

  const reprice = useCallback(
    (m: number, kind: "Call" | "Put") => {
      if (!market) return;
      if (timer.current) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(async () => {
        setBusy(true);
        try {
          const atm = market.snapshot.equity.implied_vol_atm;
          const sv = smileVolAt(m);
          const base = {
            option_type: kind,
            spot: SPOT,
            strike: SPOT * m,
            time_to_expiry: EXPIRY,
          };
          const [flat, smile] = await Promise.all([
            api.valuate("european_option", "black_scholes", {
              ...base,
              volatility: atm * 100,
            }),
            api.valuate("european_option", "black_scholes", {
              ...base,
              volatility: sv * 100,
            }),
          ]);
          setPrices({ flat: flat.fair_value, smile: smile.fair_value });
        } catch {
          setPrices(null);
        } finally {
          setBusy(false);
        }
      }, 250);
    },
    [market, smileVolAt]
  );

  useEffect(() => {
    reprice(moneyness, optionType);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [market]);

  if (error)
    return (
      <div>
        <PageHead eyebrow="Volatility Smile" title="The smile" />
        <ErrorNote>{error}</ErrorNote>
      </div>
    );
  if (!market)
    return (
      <div>
        <PageHead eyebrow="Volatility Smile" title="The smile" />
        <Skeleton h={300} />
      </div>
    );

  const atm = market.snapshot.equity.implied_vol_atm;
  const data = market.snapshot.equity.vol_smile.moneyness.map((m, i) => ({
    m,
    vol: market.snapshot.equity.vol_smile.implied_vols[i] * 100,
  }));
  const currentVol = smileVolAt(moneyness);
  const gap = prices ? prices.smile - prices.flat : null;
  const axisTick = { fill: chart.axis, fontSize: 11, fontFamily: "IBM Plex Mono" };

  return (
    <div>
      <PageHead
        eyebrow="Volatility Smile"
        title="The market's polite disagreement"
        blurb="Black–Scholes assumes one volatility for every strike — a flat line. The market begs to differ: implied volatility rises away from the money, steepest for low strikes. Slide the strike and watch what that disagreement is worth."
      />

      <div className="grid split">
        <div className="card" style={{ margin: 0 }}>
          <div className="card-title">
            <h2>Implied volatility by strike</h2>
            <span className="tag market">market</span>
          </div>
          <div style={{ width: "100%", height: 280 }}>
            <ResponsiveContainer>
              <LineChart data={data} margin={{ top: 8, right: 14, bottom: 4, left: 0 }}>
                <CartesianGrid stroke={chart.grid} vertical={false} />
                <XAxis
                  dataKey="m"
                  type="number"
                  domain={[0.8, 1.2]}
                  tick={axisTick}
                  tickLine={false}
                  axisLine={{ stroke: chart.grid }}
                  label={{ value: "moneyness K/S", position: "insideBottom", offset: -2, fill: chart.axis, fontSize: 11 }}
                />
                <YAxis tick={axisTick} tickLine={false} axisLine={false} width={48} unit="%" domain={[16, 30]} />
                <Tooltip
                  contentStyle={{ background: chart.tooltipBg, border: "1px solid rgba(148,170,210,0.25)", borderRadius: 9, fontFamily: "IBM Plex Mono", fontSize: 12 }}
                  formatter={(v) => [`${fmt(Number(v), 1)}%`, "implied vol"]}
                  labelFormatter={(v) => `K/S = ${v}`}
                />
                <ReferenceLine y={atm * 100} stroke={chart.market} strokeDasharray="5 4" label={{ value: "constant ATM vol (Black–Scholes)", fill: chart.axis, fontSize: 10, position: "insideTopRight" }} />
                <Line type="monotone" dataKey="vol" stroke={chart.derived} strokeWidth={2} dot={{ r: 3, fill: chart.derived, strokeWidth: 0 }} isAnimationActive={false} />
                <ReferenceDot x={moneyness} y={currentVol * 100} r={6} fill={chart.user} stroke="none" />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="field" style={{ marginTop: 8 }}>
            <label htmlFor="moneyness">
              Strike: {fmt(SPOT * moneyness, 0)} <span className="unit">K/S = {fmt(moneyness, 2)}</span>
            </label>
            <input
              id="moneyness"
              type="range"
              min={0.8}
              max={1.2}
              step={0.01}
              value={moneyness}
              style={{ "--fill": `${((moneyness - 0.8) / 0.4) * 100}%` } as React.CSSProperties}
              onChange={(e) => {
                const m = Number(e.target.value);
                setMoneyness(m);
                reprice(m, optionType);
              }}
            />
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            {(["Put", "Call"] as const).map((k) => (
              <button
                key={k}
                className={optionType === k ? "primary" : ""}
                onClick={() => {
                  setOptionType(k);
                  reprice(moneyness, k);
                }}
              >
                {k}
              </button>
            ))}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="card" style={{ margin: 0 }}>
            <div className="card-title">
              <h2>What the smile is worth here</h2>
              <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
                {busy && <span className="spin" />}
                <span className="tag derived">derived</span>
              </span>
            </div>
            <div className="stat-grid">
              <div className="stat">
                <span className="k">Constant ATM vol</span>
                <span className="v">{fmt(atm * 100, 1)}%</span>
              </div>
              <div className="stat">
                <span className="k">Smile vol at this strike</span>
                <span className="v" style={{ color: "var(--user)" }}>
                  {fmt(currentVol * 100, 1)}%
                </span>
              </div>
              <div className="stat">
                <span className="k">Price @ constant vol</span>
                <span className="v">{prices ? fmt(prices.flat) : "—"}</span>
              </div>
              <div className="stat">
                <span className="k">Price @ smile vol</span>
                <span className="v">{prices ? fmt(prices.smile) : "—"}</span>
              </div>
            </div>
            <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
              <span className="eyebrow">Mispricing if you ignore the smile</span>
              <div className="figure mono" style={{ fontSize: "1.8rem", color: gap && Math.abs(gap) > 0.005 ? "var(--err)" : "var(--ok)" }}>
                {gap === null ? "—" : `${gap >= 0 ? "+" : ""}${fmt(gap)}`}
              </div>
              <p className="small muted" style={{ marginTop: 4 }}>
                {optionType} at K/S {fmt(moneyness, 2)}, 1y expiry, spot {SPOT}.
              </p>
            </div>
          </div>

          <div className="card" style={{ margin: 0 }}>
            <div className="card-title">
              <h2>How to read it</h2>
            </div>
            <p className="small muted" style={{ marginBottom: 8 }}>
              <b style={{ color: "var(--text)" }}>Constant volatility</b> is the
              Black–Scholes assumption: one lognormal world, one σ, the dashed
              flat line. Under it, every strike would trade at the same implied
              vol.
            </p>
            <p className="small muted" style={{ marginBottom: 8 }}>
              <b style={{ color: "var(--text)" }}>Market implied volatility</b>{" "}
              is what you get by inverting actual option prices — the violet
              curve. Its <b style={{ color: "var(--text)" }}>strike dependence</b>{" "}
              is steepest on the left: low-strike puts are crash insurance, real
              return distributions have fat left tails, and buyers pay up for
              both. Slide to K/S = 0.80 and the market charges ~27% vol where
              the model assumes 20%.
            </p>
            <p className="small muted">
              <b style={{ color: "var(--text)" }}>Interpretation:</b> the smile
              is not a bug in the market — it is the market pricing what the
              lognormal assumption leaves out. Desks quote *through* the smile
              (each strike with its own vol, as this page's right-hand price
              does), and smile-consistent models — local vol, Heston, SABR —
              exist to make one coherent model reproduce this whole curve at
              once.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
