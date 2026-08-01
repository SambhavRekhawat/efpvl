"""Professional valuation report (PDF) builder.

Design notes (per the PDF tooling guidance):
* Platypus flowables, not raw canvas.
* Standard fonts cover WinAnsi only — Greek/math glyphs render as boxes —
  so all engine text passes through :func:`pdf_safe`, which transliterates
  sigma/lambda/pi/arrows into ASCII-safe equivalents.
* Sub/superscripts, if ever needed, must use <sub>/<super> markup, never
  Unicode sub/superscript characters.

The report deliberately mirrors the app's teaching order: what was priced,
with which inputs, under which model and assumptions, the full calculation
trace, risk measures, one sensitivity chart, then limitations and the
educational disclaimer.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

import matplotlib

matplotlib.use("Agg")
import efpvl_engine as engine
import matplotlib.pyplot as plt
import numpy as np
from efpvl_engine.content import risk_content
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Brand palette (print-adjusted: ink on white, amber/violet accents)
INK = colors.HexColor("#0b1120")
AMBER = colors.HexColor("#b57a1e")
VIOLET = colors.HexColor("#6d4fc4")
STEEL = colors.HexColor("#3b6db0")
FAINT = colors.HexColor("#8a93a6")
RULE = colors.HexColor("#d8dde8")

_TRANSLIT = {
    "σ": "sigma",
    "λ": "lambda",
    "π": "pi",
    "Δ": "Delta",
    "Γ": "Gamma",
    "Θ": "Theta",
    "ρ": "rho",
    "τ": "tau",
    "φ": "phi",
    "δ": "delta",
    "Σ": "Sum",
    "√": "sqrt",
    "≈": "~",
    "≥": ">=",
    "≤": "<=",
    "⇒": "=>",
    "−": "-",
    "±": "+/-",
    "×": "x",
    "·": ".",
    "α": "alpha",
    "β": "beta",
    "μ": "mu",
    "∂": "d",
    "∞": "inf",
    "€": "EUR",
    "①": "1",
}


def pdf_safe(text: str) -> str:
    """Transliterate glyphs outside WinAnsi so standard fonts never box."""
    if not text:
        return ""
    out = []
    for ch in str(text):
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        elif ord(ch) < 0x2500 or ch in "–—''\"\"…":
            out.append(ch)
        else:
            out.append("?")
    return "".join(out).replace("&", "&amp;").replace("<", "&lt;")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "t",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=19,
            textColor=INK,
            spaceAfter=2,
            alignment=0,
        ),
        "sub": ParagraphStyle(
            "s",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            textColor=FAINT,
            spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11.5,
            textColor=INK,
            spaceBefore=13,
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "b",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12.5,
            textColor=INK,
        ),
        "small": ParagraphStyle(
            "sm",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10,
            textColor=FAINT,
        ),
        "cell": ParagraphStyle(
            "c",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=10.5,
            textColor=INK,
        ),
        "cellnote": ParagraphStyle(
            "cn",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=7.2,
            leading=9.5,
            textColor=FAINT,
        ),
    }


def _kv_table(rows: list[tuple[str, str]], st, col1=52 * mm) -> Table:
    data = [
        [Paragraph(pdf_safe(k), st["cell"]), Paragraph(pdf_safe(v), st["cell"])]
        for k, v in rows
    ]
    t = Table(data, colWidths=[col1, None])
    t.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TEXTCOLOR", (0, 0), (0, -1), FAINT),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return t


_SWEEP_PREFERENCE = [
    "volatility",
    "coupon_rate",
    "fixed_rate",
    "spot",
    "spot_price",
    "market_spread_bps",
    "spot_fx",
    "breakeven_inflation",
    "spread_bps",
    "face_value",
    "notional",
]


def _sensitivity_png(
    product_cls, model, inputs: dict[str, Any], market
) -> bytes | None:
    """One matplotlib chart: fair value across the product's headline input."""
    fields = {f.name: f for f in product_cls.input_schema()}
    field = next(
        (
            n
            for n in _SWEEP_PREFERENCE
            if n in fields and fields[n].field_type.value in ("number", "percent")
        ),
        None,
    )
    if field is None:
        return None
    spec = fields[field]
    try:
        center = float(inputs[field])
    except (KeyError, TypeError, ValueError):
        return None
    half = max(abs(center) * 0.4, spec.step or 1.0)
    lo, hi = center - half, center + half
    if spec.min_value is not None:
        lo = max(lo, spec.min_value)
    if spec.max_value is not None:
        hi = min(hi, spec.max_value)
    if hi <= lo:
        return None

    xs, ys = [], []
    for x in np.linspace(lo, hi, 40):
        candidate = dict(inputs)
        candidate[field] = float(x)
        try:
            ys.append(
                model.price(product_cls.from_inputs(candidate), market).fair_value
            )
            xs.append(float(x))
        except Exception:  # noqa: BLE001, S112 - chart is best-effort
            continue
    if len(xs) < 5:
        return None

    fig, ax = plt.subplots(figsize=(6.4, 2.6), dpi=150)
    ax.plot(xs, ys, color="#6d4fc4", linewidth=1.8)
    ax.axvline(center, color="#b57a1e", linewidth=1.0, linestyle="--", alpha=0.8)
    ax.set_xlabel(f"{spec.label}{f' ({spec.unit})' if spec.unit else ''}", fontsize=8)
    ax.set_ylabel("Fair value", fontsize=8)
    ax.tick_params(labelsize=7)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="y", color="#e3e7ef", linewidth=0.6)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def build_report(
    product_id: str,
    model_id: str,
    inputs: dict[str, Any],
    result: dict[str, Any],
    risk: dict[str, float] | None,
    market,
) -> bytes:
    """Assemble the full valuation report; returns PDF bytes."""
    st = _styles()
    product_cls = engine.get_product(product_id)
    model_cls = engine.get_model(model_id)
    meta = product_cls.meta()
    described = model_cls.describe()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    snap = market.snapshot

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"EFPVL Valuation Report - {meta.display_name}",
        author="EFPVL - Explainable Financial Product Valuation Laboratory",
    )

    def _footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 6.8)
        canvas.setFillColor(FAINT)
        canvas.drawString(
            18 * mm,
            9 * mm,
            "EFPVL - educational valuation report - not investment advice",
        )
        canvas.drawRightString(A4[0] - 18 * mm, 9 * mm, f"Page {_doc.page}")
        canvas.restoreState()

    story: list[Any] = []
    story.append(Paragraph("Valuation Report", st["title"]))
    story.append(
        Paragraph(
            f"{pdf_safe(meta.display_name)} &nbsp;|&nbsp; "
            f"{pdf_safe(described.get('display_name', model_id))} &nbsp;|&nbsp; "
            f"generated {now}",
            st["sub"],
        )
    )

    # -- Headline value --------------------------------------------------- #
    fv = result["fair_value"]
    headline = Table(
        [
            [
                Paragraph("FAIR VALUE", st["small"]),
                Paragraph(
                    f"<font size=16 color='#6d4fc4'><b>{fv:,.4f}</b></font>"
                    f"<font size=8 color='#8a93a6'> {result['currency']}</font>",
                    st["body"],
                ),
                Paragraph(
                    f"runtime {result.get('runtime_ms', 0):.2f} ms<br/>"
                    f"{len(result['steps'])} calculation steps",
                    st["small"],
                ),
            ]
        ],
        colWidths=[28 * mm, None, 38 * mm],
    )
    headline.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.7, RULE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(headline)
    for w in result.get("warnings", []):
        story.append(Spacer(1, 3))
        story.append(Paragraph(pdf_safe(w), st["cellnote"]))

    # -- Inputs ------------------------------------------------------------ #
    story.append(Paragraph("Contract Terms (user inputs)", st["h2"]))
    field_labels = {f.name: f for f in product_cls.input_schema()}
    rows = []
    for k, v in inputs.items():
        spec = field_labels.get(k)
        label = spec.label if spec else k
        unit = f" {spec.unit}" if spec and spec.unit else ""
        rows.append((label, f"{v}{unit}"))
    story.append(_kv_table(rows, st))

    # -- Market data ------------------------------------------------------- #
    story.append(Paragraph("Market Data (curated snapshot)", st["h2"]))
    story.append(
        _kv_table(
            [
                ("Snapshot", snap.get("snapshot_id", "-")),
                ("As of", snap.get("as_of", "-")[:10]),
                ("Risk-free rate", f"{snap.get('risk_free_rate', 0) * 100:.2f} %"),
                ("Nature", "Static, versioned, educational - not live market data"),
            ],
            st,
        )
    )

    # -- Model ------------------------------------------------------------- #
    story.append(Paragraph("Pricing Model", st["h2"]))
    story.append(Paragraph(pdf_safe(described.get("overview", "")), st["body"]))
    story.append(Spacer(1, 4))
    ass = described.get("assumptions", [])[:5]
    lim = described.get("limitations", [])[:5]
    two_col = Table(
        [
            [
                Paragraph("<b>Assumptions</b>", st["cell"]),
                Paragraph("<b>Limitations</b>", st["cell"]),
            ],
            [
                Paragraph("<br/>".join(f"- {pdf_safe(a)}" for a in ass), st["cell"]),
                Paragraph("<br/>".join(f"- {pdf_safe(li)}" for li in lim), st["cell"]),
            ],
        ],
        colWidths=[None, None],
    )
    two_col.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.4, RULE),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
            ]
        )
    )
    story.append(two_col)

    # -- Outputs ----------------------------------------------------------- #
    outputs = result.get("outputs", {})
    if outputs:
        story.append(Paragraph("Valuation Outputs", st["h2"]))
        story.append(
            _kv_table(
                [
                    (k.replace("_", " ").title(), f"{v:,.6f}")
                    for k, v in outputs.items()
                ],
                st,
            )
        )

    # -- Calculation trace -------------------------------------------------- #
    story.append(Paragraph("Calculation Trace (full derivation)", st["h2"]))
    trace_rows: list[list[Any]] = [
        [
            Paragraph("<b>Step</b>", st["cell"]),
            Paragraph("<b>Symbol</b>", st["cell"]),
            Paragraph("<b>Value</b>", st["cell"]),
        ]
    ]
    steps = result["steps"]
    shown = steps if len(steps) <= 30 else steps[:29]
    for s in shown:
        trace_rows.append(
            [
                Paragraph(
                    pdf_safe(s["label"])
                    + (
                        f"<br/><font size=7 color='#8a93a6'>{pdf_safe(s['note'])}</font>"
                        if s.get("note")
                        else ""
                    ),
                    st["cell"],
                ),
                Paragraph(pdf_safe(s.get("symbol") or ""), st["cell"]),
                Paragraph(f"{s['value']:,.6f}", st["cell"]),
            ]
        )
    if len(steps) > 30:
        trace_rows.append(
            [
                Paragraph(
                    f"... {len(steps) - 29} further per-period steps omitted "
                    "for brevity (all visible in the application)",
                    st["cellnote"],
                ),
                Paragraph("", st["cell"]),
                Paragraph("", st["cell"]),
            ]
        )
    trace = Table(trace_rows, colWidths=[None, 30 * mm, 34 * mm], repeatRows=1)
    trace.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 0.7, INK),
                ("LINEBELOW", (0, 1), (-1, -1), 0.3, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (2, 1), (2, -1), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
            ]
        )
    )
    story.append(trace)

    # -- Risk --------------------------------------------------------------- #
    if risk:
        story.append(Paragraph("Risk Measures", st["h2"]))
        glossary = risk_content()
        rows = []
        for k, v in risk.items():
            g = glossary.get(k, {})
            name = g.get("name", k.replace("_", " ").title())
            unit = g.get("unit", "")
            rows.append((f"{name}" + (f"  ({unit})" if unit else ""), f"{v:,.6f}"))
        story.append(_kv_table(rows, st, col1=78 * mm))

    # -- Chart --------------------------------------------------------------- #
    model = model_cls()
    png = _sensitivity_png(product_cls, model, inputs, market)
    if png:
        story.append(Paragraph("Sensitivity", st["h2"]))
        story.append(Image(io.BytesIO(png), width=168 * mm, height=68 * mm))
        story.append(
            Paragraph(
                "Fair value across the headline input, everything else held "
                "fixed; the dashed line marks the valued position.",
                st["small"],
            )
        )

    # -- Disclaimer ---------------------------------------------------------- #
    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "This report was generated by the Explainable Financial Product "
            "Valuation Laboratory (EFPVL), an educational tool. Market data is "
            "a static curated snapshot. Nothing here is investment advice, an "
            "offer, or a solicitation; models embed the assumptions and "
            "limitations stated above.",
            st["small"],
        )
    )

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
