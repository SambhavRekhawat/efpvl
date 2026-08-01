# Phase 7 — Manual QA Checklist

Automated coverage handles the engine, the API, every product×model pair,
and the PDFs. What follows needs a human at real devices. Work top to
bottom; anything unchecked is a Phase 8 blocker.

Start the app in single-server mode (`cd api && uvicorn app.main:app --port
8000`, then <http://localhost:8000>) unless a step says otherwise.

---

## 1. Responsive pass

Use browser devtools device emulation, then at least one *real* phone.

| Width | Device profile | What to verify |
|---|---|---|
| 375px | iPhone SE | Sidebar collapses to a wrapping top bar; no horizontal page scroll anywhere; status bar readable |
| 390–430px | Modern phones | Forms are single-column; sliders draggable with a thumb; wide tables scroll *inside* their card, not the page |
| 768px | iPad portrait | Split layouts stack sensibly; charts keep their aspect |
| 1024px | iPad landscape / small laptop | Sidebar returns; two-column grids restored |
| 1440px+ | Desktop | Content stays within the max width; no ocean of empty space |

- [ ] Every page at 375px: Home, Products, Market Data, Valuation,
      Sensitivity, Explainability, Vol Smile, Comparison, Export
- [ ] Valuation trace rail readable on a phone (values not clipped)
- [ ] Comparison table scrolls horizontally within its card
- [ ] No text smaller than ~12px in practice
- [ ] Rotate the phone mid-session — layout recovers

## 2. Cross-browser

- [ ] **Chrome/Edge** — full pass (primary target)
- [ ] **Firefox** — check slider thumbs (separate CSS path), `backdrop-filter`
      glass effect, KaTeX rendering
- [ ] **Safari** (Mac or iPhone) — check `backdrop-filter`, date inputs
      (Safari renders them differently), `-webkit` slider styling
- [ ] Date fields accept keyboard entry in each browser
- [ ] PDF download works in each (Safari sometimes opens rather than saves)

## 3. Accessibility

- [ ] **Keyboard only, no mouse**: Tab from page load — the "Skip to content"
      link appears first; Tab reaches every nav item, input, select, slider,
      and button; Enter/Space activate buttons; arrow keys move sliders
- [ ] Focus ring is always visible (amber outline) and never clipped
- [ ] Tab order follows visual order on every page
- [ ] Trigger a validation error (e.g. strike `-5`) — the message is
      announced (`role="alert"`) and tied to the field (`aria-describedby`)
- [ ] Charts announce themselves to a screen reader (they carry
      `role="img"` and a descriptive label)
- [ ] Contrast: run axe DevTools or Lighthouse a11y — target ≥ 95.
      Known watch-points: `--faint` text on glass, and the amber primary
      button's dark label
- [ ] Zoom browser to 200% — nothing overlaps or disappears
- [ ] Set OS "reduce motion" — trace rail and fades stop animating

## 4. Performance (Lighthouse)

Run against the **production build in single-server mode**, not the Vite dev
server (dev builds are intentionally unoptimized).

```
Chrome DevTools → Lighthouse → Mobile → Analyze
```

- [ ] Performance ≥ 90
- [ ] Accessibility ≥ 95
- [ ] Best Practices ≥ 95
- [ ] SEO ≥ 90
- [ ] First Contentful Paint < 2s on the "Slow 4G" throttle

Reference numbers already measured server-side (see Phase 7 notes): slowest
engine path is Monte Carlo at ~5.5 ms; every other model is under 2.5 ms;
cached repeats return in ~2 ms. Bundle is route-split — the initial payload
is the React chunk (~59 kB gzipped) plus a ~5 kB entry; KaTeX (~78 kB gz)
and chart code load only on the pages that need them.

- [ ] Drag a Sensitivity slider continuously for 10 seconds — no jank, no
      runaway network tab (requests are debounced at ~300 ms)
- [ ] Repeat an identical valuation — confirm `"cached": true` in the
      response (DevTools → Network → Response)

## 5. Error paths

- [ ] **Backend down**: stop uvicorn, then use the app (dev mode makes this
      easiest). Expect calm "engine is unreachable" copy, never a blank
      screen or raw stack trace. Restart and confirm recovery without a
      page reload where possible
- [ ] **Invalid inputs**: negative strike, zero face value, maturity before
      settlement, blank required field, letters in a number field — each
      produces an inline field message
- [ ] **Slow responses**: DevTools → Network → throttle to "Slow 3G", then
      Calculate — skeletons appear, buttons disable, nothing double-fires
- [ ] **Deep links**: paste `http://localhost:8000/smile` directly — the SPA
      fallback serves it (this is why single-server mode has a catch-all)
- [ ] **Unknown route**: visit `/nonsense` — friendly not-found page
- [ ] **Rapid clicking**: mash Calculate and Run comparison — no duplicate
      or interleaved results
- [ ] **Back/forward buttons** across pages, and after selecting a product
      via `?product=` query — state stays coherent

## 6. Dogfood — read it like a user

Automated tests already price every pair. This pass is about *the writing
and the feel*.

- [ ] Price all 11 products on the Valuation page; skim each trace for a
      value that looks wrong (nonsense magnitudes, NaN, zeros)
- [ ] Options: run all six models on the same option; confirm the story
      holds (BS ≈ tree ≈ MC within its SE; Heston/SABR/Merton richer on OTM
      puts)
- [ ] Zero Coupon Bond: compare DCF vs Vasicek and read both comparison
      notes
- [ ] Read all 10 model essays end to end on Explainability — check for
      typos, broken formulas (a box glyph means a KaTeX or encoding
      problem), and any claim you would not defend in an interview
- [ ] Read all 20 risk glossary entries the same way
- [ ] Verify the identity demos still land: par swap rate → NPV ≈ 0;
      zero-spread FRN = par; CDS at par spread ≈ 0; FX forward at parity ≈ 0;
      linker at 0% breakeven = nominal bond
- [ ] Export a PDF for at least three different products; check the trace
      table, the chart, and that no glyph renders as a black box
- [ ] Vol Smile: slide a put to K/S 0.80 and confirm the mispricing figure
      grows and turns red

## 7. Portfolio readiness

- [ ] Capture screenshots into `docs/screenshots/` and link them in the
      README (Home, trace rail, sliders mid-drag, smile, comparison, PDF)
- [ ] README architecture diagram matches the current code
- [ ] "How to add a new product" instructions actually work — follow them
      once with a throwaway product, then delete it
- [ ] Ask the gate question honestly: **would I demo this live, on this
      laptop, in an interview tomorrow?** If no, list what stops you and fix
      that before Phase 8.
