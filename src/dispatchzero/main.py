import logging
from pathlib import Path

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from dispatchzero.admin.routes import router as admin_router
from dispatchzero.auth.routes import router as auth_router
from dispatchzero.config import get_settings
from dispatchzero.db import get_engine
from dispatchzero.missions.routes import router as missions_router
from dispatchzero.places.routes import router as places_router
from dispatchzero.share.routes import router as share_router
from dispatchzero.submissions.routes import router as submissions_router

log = logging.getLogger(__name__)

app = FastAPI(title="Dispatch Zero")

# API routers — declared FIRST so they win over the SPA fallback.
app.include_router(auth_router)
app.include_router(places_router)
app.include_router(missions_router)
app.include_router(share_router)
app.include_router(submissions_router)
app.include_router(admin_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is up and serving. Intentionally shallow — used
    by the deploy script's post-start check, where we only need to know the
    app booted. Dependency health is /healthz/deep."""
    return {"status": "ok"}


@app.get("/healthz/deep")
async def healthz_deep() -> JSONResponse:
    """Readiness: ping every backing service (Postgres, Redis) with a short
    timeout. Returns 503 if any check fails so a cron-curl can alert on it.
    Each component's status is reported individually for quick diagnosis.

    Deliberately does NOT ping the Ollama endpoint: a cold model or a slow
    inference box would flap this check, and the app degrades gracefully
    when Ollama is slow (briefings just take longer / fall back). DB and
    Redis are the hard dependencies."""
    import asyncio

    settings = get_settings()
    checks: dict[str, str] = {}
    ok = True

    # Postgres. get_engine() makes a fresh engine (+ pool) per call, so we
    # dispose it after to avoid leaking a pool on every cron-hit.
    engine = get_engine()
    try:
        async with engine.connect() as conn:
            await asyncio.wait_for(conn.execute(text("SELECT 1")), timeout=3.0)
        checks["postgres"] = "ok"
    except Exception as e:  # noqa: BLE001
        ok = False
        checks["postgres"] = f"fail: {type(e).__name__}"
        log.warning("healthz/deep postgres check failed: %s", e)
    finally:
        await engine.dispose()

    # Redis
    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await asyncio.wait_for(r.ping(), timeout=3.0)
            checks["redis"] = "ok"
        finally:
            await r.aclose()
    except Exception as e:  # noqa: BLE001
        ok = False
        checks["redis"] = f"fail: {type(e).__name__}"
        log.warning("healthz/deep redis check failed: %s", e)

    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ok" if ok else "degraded", "checks": checks},
    )


# ----- Static + SPA -----

_FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
_INDEX_HTML = _FRONTEND_DIR / "index.html"

app.mount(
    "/static",
    StaticFiles(directory=str(_FRONTEND_DIR / "static"), check_dir=False),
    name="static",
)


@app.get("/manifest.webmanifest")
async def manifest() -> Response:
    return FileResponse(
        _FRONTEND_DIR / "manifest.webmanifest",
        media_type="application/manifest+json",
    )


@app.get("/service-worker.js")
async def service_worker() -> Response:
    return FileResponse(
        _FRONTEND_DIR / "service-worker.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@app.get("/favicon.svg")
async def favicon() -> Response:
    return FileResponse(_FRONTEND_DIR / "favicon.svg", media_type="image/svg+xml")


# SPA fallback — any unmatched path returns index.html so the client router takes over.
@app.get("/{full_path:path}", response_class=FileResponse)
async def spa(full_path: str) -> FileResponse:
    return FileResponse(_INDEX_HTML, media_type="text/html")
