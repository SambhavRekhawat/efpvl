import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { api, Health, MarketDataResponse } from "../api/client";

/**
 * App frame: persistent sidebar (spec: navigation always visible) and a
 * terminal-style status bar fed by /health and /market-data — real furniture,
 * not decoration.
 */
export default function Layout() {
  const [health, setHealth] = useState<Health | null>(null);
  const [market, setMarket] = useState<MarketDataResponse | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    // One silent retry: free hosting sleeps, and a first-visit wake-up
    // should look like patience, not a failure.
    api
      .health()
      .then(setHealth)
      .catch(() =>
        new Promise((r) => setTimeout(r, 4000))
          .then(() => api.health())
          .then(setHealth)
          .catch(() => setDown(true))
      );
    api.marketData().then(setMarket).catch(() => undefined);
  }, []);

  const pages: { to: string; label: string; badge?: string }[] = [
    { to: "/", label: "Home" },
    { to: "/products", label: "Products" },
    { to: "/market-data", label: "Market Data" },
    { to: "/valuation", label: "Valuation" },
    { to: "/sensitivity", label: "Sensitivity" },
    { to: "/explainability", label: "Explainability" },
    { to: "/smile", label: "Vol Smile" },
    { to: "/comparison", label: "Model Comparison" },
    { to: "/export", label: "Export" },
  ];

  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <div className="frame">
      <aside className="sidebar">
        <div className="brand">
          <div className="word">
            EFP<span>VL</span>
          </div>
          <div className="sub">VALUATION LABORATORY</div>
        </div>
        <nav className="nav-section" aria-label="Main">
          {pages.map((p) => (
            <NavLink
              key={p.to}
              to={p.to}
              end={p.to === "/"}
              className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
            >
              {p.label}
              {p.badge && <span className="badge">{p.badge}</span>}
            </NavLink>
          ))}
        </nav>
      </aside>

      <div className="main">
        <div className="statusbar" role="status">
          <span
            className={`dot${health ? " ok" : ""}`}
            title={health ? "Engine connected" : "Engine offline"}
          />
          <span>
            {down
              ? "ENGINE UNREACHABLE"
              : health
              ? `ENGINE v${health.engine_version} · ${health.registered_products} PRODUCTS · ${health.registered_models} MODELS`
              : "CONNECTING - THE FREE-TIER ENGINE MAY BE WAKING UP…"}
          </span>
          <span className="spacer" />
          {market && (
            <span>
              SNAPSHOT {market.snapshot.snapshot_id.toUpperCase()} · AS OF{" "}
              {market.snapshot.as_of.slice(0, 10)}
            </span>
          )}
        </div>
        <main className="page" id="main-content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
      </div>
    </>
  );
}

/* ---------- Small shared pieces ------------------------------------------ */

export function PageHead(props: { eyebrow: string; title: string; blurb?: string }) {
  return (
    <header className="page-head fade-in">
      <span className="eyebrow">{props.eyebrow}</span>
      <h1>{props.title}</h1>
      {props.blurb && <p>{props.blurb}</p>}
    </header>
  );
}

export function ErrorNote(props: { children: React.ReactNode }) {
  return (
    <div className="error-note" role="alert">
      {props.children}
    </div>
  );
}

export function Skeleton(props: { h?: number; w?: string }) {
  return (
    <div
      className="skeleton"
      style={{ height: props.h ?? 18, width: props.w ?? "100%" }}
      aria-hidden
    />
  );
}

export function fmt(x: number | null | undefined, digits = 4): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return x.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}
