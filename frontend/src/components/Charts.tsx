import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CalculationStep, SweepPoint } from "../api/client";
import { Formula } from "./Formula";
import { fmt } from "./Layout";

/* Chart tokens (Recharts needs literal colors; keep in sync with index.css). */
export const chart = {
  derived: "#b79cf5",
  market: "#7da9e8",
  user: "#f0b45c",
  grid: "rgba(148, 170, 210, 0.10)",
  axis: "#5c6a82",
  tooltipBg: "#101a2e",
};

/** The signature element: every intermediate value as a node on a ledger rail. */
export function TraceRail(props: { steps: CalculationStep[] }) {
  return (
    <ol className="trace">
      {props.steps.map((s, i) => (
        <li key={i} style={{ "--i": i } as React.CSSProperties}>
          <div className="row">
            <span className="label">
              {s.label}
              {s.symbol && (
                <span className="mono muted small"> · {s.symbol}</span>
              )}
            </span>
            <span className="value">{fmt(s.value, 6)}</span>
          </div>
          {s.formula && (
            <span className="formula">
              <Formula latex={s.formula} />
            </span>
          )}
          {s.note && <p className="note">{s.note}</p>}
        </li>
      ))}
    </ol>
  );
}

const axisTick = { fill: chart.axis, fontSize: 11, fontFamily: "IBM Plex Mono" };

/** Line chart over a swept input — the Phase 3 "first chart". */
export function SweepChart(props: {
  points: SweepPoint[];
  xLabel: string;
  currentX?: number;
}) {
  const data = useMemo(
    () => props.points.filter((p) => p.fair_value !== null),
    [props.points]
  );
  return (
    <div
      style={{ width: "100%", height: 300 }}
      role="img"
      aria-label={`Line chart of fair value against ${props.xLabel}, ${data.length} points`}
    >
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 6 }}>
          <CartesianGrid stroke={chart.grid} vertical={false} />
          <XAxis
            dataKey="x"
            tick={axisTick}
            tickLine={false}
            axisLine={{ stroke: chart.grid }}
            tickFormatter={(v: number) => fmt(v, 2)}
            label={{
              value: props.xLabel,
              position: "insideBottom",
              offset: -2,
              fill: chart.axis,
              fontSize: 11,
            }}
          />
          <YAxis
            tick={axisTick}
            tickLine={false}
            axisLine={false}
            width={70}
            tickFormatter={(v: number) => fmt(v, 2)}
          />
          <Tooltip
            contentStyle={{
              background: chart.tooltipBg,
              border: "1px solid rgba(148,170,210,0.25)",
              borderRadius: 9,
              fontFamily: "IBM Plex Mono",
              fontSize: 12,
            }}
            labelFormatter={(v) => `${props.xLabel}: ${fmt(Number(v), 4)}`}
            formatter={(v) => [fmt(Number(v), 4), "Fair value"]}
          />
          <Line
            type="monotone"
            dataKey="fair_value"
            stroke={chart.derived}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: chart.user, stroke: "none" }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
