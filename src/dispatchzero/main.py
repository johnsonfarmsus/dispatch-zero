from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from dispatchzero.auth.routes import router as auth_router
from dispatchzero.config import get_settings
from dispatchzero.missions.routes import router as missions_router
from dispatchzero.places.routes import router as places_router

app = FastAPI(title="Dispatch Zero")

# API routers — declared FIRST so they win over the SPA fallback.
app.include_router(auth_router)
app.include_router(places_router)
app.include_router(missions_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config")
async def public_config() -> dict[str, bool]:
    """Public, unauthenticated config the frontend may need at render time.

    Append new public flags here rather than creating additional config endpoints.
    """
    s = get_settings()
    return {
        "show_beta_banner": s.show_beta_banner,
    }


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
