import { Suspense, lazy } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout, { Skeleton } from "./components/Layout";
import Home from "./pages/Home";

// Route-level code splitting: heavy pages (charts, KaTeX) load on demand,
// keeping the first paint light.
const Products = lazy(() =>
  import("./pages/Catalog").then((m) => ({ default: m.Products }))
);
const MarketData = lazy(() =>
  import("./pages/Catalog").then((m) => ({ default: m.MarketData }))
);
const Valuation = lazy(() => import("./pages/Valuation"));
const Sensitivity = lazy(() => import("./pages/Sensitivity"));
const Explainability = lazy(() => import("./pages/Explainability"));
const Smile = lazy(() => import("./pages/Smile"));
const Comparison = lazy(() => import("./pages/Comparison"));
const Export = lazy(() => import("./pages/Export"));
const ComingSoon = lazy(() => import("./pages/ComingSoon"));

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route
            index
            element={<Home />}
          />
          {[
            ["/products", <Products />],
            ["/market-data", <MarketData />],
            ["/valuation", <Valuation />],
            ["/sensitivity", <Sensitivity />],
            ["/explainability", <Explainability />],
            ["/smile", <Smile />],
            ["/comparison", <Comparison />],
            ["/export", <Export />],
          ].map(([path, el]) => (
            <Route
              key={path as string}
              path={path as string}
              element={
                <Suspense fallback={<Skeleton h={320} />}>{el}</Suspense>
              }
            />
          ))}
          <Route
            path="*"
            element={
              <Suspense fallback={<Skeleton h={320} />}>
                <ComingSoon
                  eyebrow="Not found"
                  title="This page doesn't exist"
                  phase="no phase"
                  description="Check the address, or use the navigation on the left."
                />
              </Suspense>
            }
          />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
