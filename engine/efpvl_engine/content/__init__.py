"""Authored explainability content.

Explanations are written by a human (structured JSON), never generated at
request time — the consistent quant-teaching-a-quant voice is the product.
Loaders here are the single access point; the API serves this verbatim.

Files are UTF-8 and MUST be read as UTF-8 explicitly: Windows' default text
encoding is cp1252, which silently mangles en-dashes, Greek letters, and
typographic punctuation (the "Blackâ€“Scholes" bug).
"""

import json
from functools import cache
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).parent


def content_dir() -> Path:
    """Where this process is reading content from (diagnostic aid)."""
    return _ROOT


@cache
def model_content(model_id: str) -> dict[str, Any] | None:
    """Full authored content for one model, or None if not yet written."""
    path = _ROOT / "models" / f"{model_id}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@cache
def risk_content() -> dict[str, Any]:
    """The complete risk-measure glossary keyed by measure id."""
    with open(_ROOT / "risk.json", encoding="utf-8") as f:
        return json.load(f)
