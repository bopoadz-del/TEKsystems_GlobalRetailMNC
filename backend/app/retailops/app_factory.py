"""FastAPI application factory for the RetailOps runtime.

Exposes /health and the documented API routes, serves the business frontend
(when built), and — in a deployed container — applies mandatory database
migrations on startup, failing startup if they cannot be applied.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.retailops import BLOCKS_COMMIT, KIT_SNAPSHOT_ID, RETAILOPS_VERSION
from app.retailops.api import router as api_router
from app.retailops.db import get_engine, init_engine

logger = logging.getLogger("retailops")

_FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"
_FRONTEND_INDEX = _FRONTEND_DIST / "index.html"


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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        db_ok = True
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            db_ok = False
        return {
            "status": "ok" if db_ok else "degraded",
            "version": RETAILOPS_VERSION,
            "kit_snapshot": KIT_SNAPSHOT_ID,
            # Legacy key retained for existing clients / Render smoke scripts.
            "blocks_commit": BLOCKS_COMMIT,
            "database": "ok" if db_ok else "unavailable",
        }

    app.include_router(api_router)

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
