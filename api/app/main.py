"""EFPVL application server.

Serves two things from one process:

* the JSON API under ``/api/...`` (catalog, market data, valuation,
  sensitivity, risk, comparison, export — see app/routes.py), and
* the built frontend (``frontend/dist``) for every other path, with SPA
  fallback — so ``uvicorn app.main:app`` alone runs the entire laboratory.

During frontend *development*, Vite's dev server (:5173) proxies ``/api``
here instead, giving hot reload; production and casual local use need only
this one process.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from pathlib import Path

import efpvl_engine
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .routes import router

app = FastAPI(
    title="EFPVL API",
    description=(
        "Explainable Financial Product Valuation Laboratory. "
        "Educational valuation engine - not investment advice."
    ),
    version=efpvl_engine.__version__,
)

# CORS: locked to the local frontend in dev; in production set
# EFPVL_CORS_ORIGINS to your site's origin(s), comma separated, e.g.
#   https://efpvl.vercel.app,https://lab.yourdomain.com
origins = [
    o.strip()
    for o in os.environ.get("EFPVL_CORS_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---- Rate limiting -------------------------------------------------------- #
# A public engine needs a cap. Sliding window per client IP; heavy endpoints
# (PDF rendering, multi-model comparison) cost more than a simple quote.
_RATE_WINDOW_S = 60
# Requests allowed per IP per window. Set EFPVL_RATE_BUDGET=0 to disable
# (used by the test suite, which drives thousands of calls from one address).
_RATE_BUDGET = int(os.environ.get("EFPVL_RATE_BUDGET", "120"))
_COSTS = {"/api/export/report": 10, "/api/compare": 4, "/api/sensitivity": 2}
_hits: dict[str, deque[tuple[float, int]]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    # Render/Vercel sit behind proxies; trust the first hop of the chain.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def rate_limit_and_headers(request: Request, call_next):
    path = request.url.path
    if _RATE_BUDGET > 0 and path.startswith("/api"):
        now = time.monotonic()
        ip = _client_ip(request)
        bucket = _hits[ip]
        while bucket and now - bucket[0][0] > _RATE_WINDOW_S:
            bucket.popleft()
        spent = sum(c for _, c in bucket)
        cost = _COSTS.get(path, 1)
        if spent + cost > _RATE_BUDGET:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests - this is a free educational "
                    "service with a shared engine. Please wait a minute and "
                    "try again."
                },
                headers={"Retry-After": str(_RATE_WINDOW_S)},
            )
        bucket.append((now, cost))
        if len(_hits) > 5000:  # bound memory on a shared host
            for stale in [k for k, v in _hits.items() if not v][:1000]:
                _hits.pop(stale, None)

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


@app.exception_handler(Exception)
async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
    """Whatever breaks, the client gets calm JSON, never a stack trace."""
    return JSONResponse(
        status_code=500,
        content={
            "detail": "The valuation engine hit an unexpected error. "
            "The inputs were valid but this calculation could not complete; "
            "please try different parameters or report this combination."
        },
    )


app.include_router(router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    """Liveness check; also confirms the engine imports and reports coverage."""
    return {
        "status": "ok",
        "engine_version": efpvl_engine.__version__,
        "registered_products": len(efpvl_engine.list_products()),
        "registered_models": len(efpvl_engine.list_models()),
    }


@app.get("/api")
def api_root() -> dict:
    return {"app": "EFPVL", "docs": "/docs", "health": "/api/health"}


# ---- Static frontend (single-server mode) --------------------------------- #
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        """Serve the built app; unknown paths fall back to index.html so
        client-side routes (/valuation, /smile, ...) deep-link correctly."""
        candidate = _DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
else:

    @app.get("/", include_in_schema=False)
    def no_frontend() -> dict:
        return {
            "app": "EFPVL API (API-only mode)",
            "note": "frontend/dist not found - run `npm run build` in frontend/ "
            "to enable single-server mode, or use the Vite dev server.",
            "docs": "/docs",
        }
