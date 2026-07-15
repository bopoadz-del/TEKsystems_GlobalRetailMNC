"""FastAPI application factory for the RetailOps runtime.

Exposes /health and the documented API routes, serves the business frontend
(when built), and — in a deployed container — applies mandatory database
migrations on startup, failing startup if they cannot be applied.
"""

from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from app.retailops import BLOCKS_COMMIT, KIT_SNAPSHOT_ID, RETAILOPS_VERSION
from app.retailops.api import router as api_router
from app.retailops.db import get_engine, init_engine
from app.retailops.integrations.routes import router as integrations_router

logger = logging.getLogger("retailops")

_FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"
_FRONTEND_INDEX = _FRONTEND_DIST / "index.html"

# Paths that stay reachable without RETAILOPS_API_KEY (when that env is set).
_PUBLIC_PREFIXES = (
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/assets/",
)


def _cors_origins() -> list[str]:
    """Env allowlist for browsers; never use ``*`` when an allowlist is set.

    ``RETAILOPS_CORS_ORIGINS`` = comma-separated origins.
    If unset: local/dev keeps ``*``; when ``RETAILOPS_ENV`` is production/
    prod, defaults to empty (same-origin SPA / non-browser clients only).
    """
    raw = os.getenv("RETAILOPS_CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    env = (os.getenv("RETAILOPS_ENV") or os.getenv("ENV") or "").lower()
    if env in {"prod", "production"}:
        return []
    return ["*"]


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Optional shared-secret gate via ``RETAILOPS_API_KEY`` / ``X-API-Key``.

    When the env var is unset, the middleware is a no-op (local/dev). This is a
    deploy-time shared secret only — not end-user identity. Tenant isolation
    still relies on trusted ``X-User-Id`` / ``X-Tenant-Id`` / ``X-Project-Id``
    headers resolved server-side.
    """

    def __init__(self, app, api_key: str) -> None:
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method == "OPTIONS":
            return await call_next(request)
        if path == "/" or any(path == p or path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await call_next(request)
        # SPA deep links when the frontend dist is mounted.
        if not path.startswith("/v1/") and _FRONTEND_INDEX.is_file():
            return await call_next(request)
        provided = request.headers.get("X-API-Key") or request.headers.get("x-api-key") or ""
        if not provided or not secrets.compare_digest(provided, self.api_key):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid X-API-Key"},
            )
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_engine()
    if os.getenv("RETAILOPS_SKIP_MIGRATIONS", "").lower() not in ("1", "true", "yes"):
        from app.retailops.migrations_runner import upgrade_to_head

        try:
            upgrade_to_head()
            logger.info("RetailOps migrations applied")
        except Exception as exc:  # noqa: BLE001 - mandatory: fail startup
            logger.error("mandatory migrations failed: %s", exc)
            raise
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="CEREBRUM RetailOps",
        version=RETAILOPS_VERSION,
        lifespan=lifespan,
    )
    origins = _cors_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    api_key = (os.getenv("RETAILOPS_API_KEY") or "").strip()
    if api_key:
        app.add_middleware(ApiKeyMiddleware, api_key=api_key)
        logger.info("RETAILOPS_API_KEY gate enabled for non-public routes")

    @app.get("/health")
    def health():
        db_ok = True
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            db_ok = False
        # Deploy-evidence only (release certification DoD): Render sets
        # RENDER_GIT_COMMIT automatically for every service deploy; an
        # explicit RETAILOPS_RELEASE_COMMIT override is honoured first for
        # non-Render environments (e.g. Docker E2E in CI). Never fabricated.
        commit_sha = os.getenv("RETAILOPS_RELEASE_COMMIT") or os.getenv("RENDER_GIT_COMMIT")
        return {
            "status": "ok" if db_ok else "degraded",
            "version": RETAILOPS_VERSION,
            "kit_snapshot": KIT_SNAPSHOT_ID,
            # Legacy key retained for existing clients / Render smoke scripts.
            "blocks_commit": BLOCKS_COMMIT,
            "database": "ok" if db_ok else "unavailable",
            "commit_sha": commit_sha,
        }

    app.include_router(api_router)
    app.include_router(integrations_router)

    # Serve the business frontend when the Vite dist has been built into the image.
    if _FRONTEND_INDEX.is_file():
        assets = _FRONTEND_DIST / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/")
        def _index():
            return FileResponse(str(_FRONTEND_INDEX))

        @app.get("/{full_path:path}")
        def _spa(full_path: str):
            # Never shadow API/health; those are registered above.
            if full_path.startswith("v1/") or full_path in {"health", "docs", "openapi.json", "redoc"}:
                from fastapi import HTTPException

                raise HTTPException(status_code=404, detail="Not Found")
            candidate = _FRONTEND_DIST / full_path
            if full_path and candidate.is_file():
                return FileResponse(str(candidate))
            return FileResponse(str(_FRONTEND_INDEX))
    else:
        logger.warning("frontend dist missing at %s — UI will not be served", _FRONTEND_DIST)

    return app


app = create_app()
