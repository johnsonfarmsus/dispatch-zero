from fastapi import FastAPI

from dispatchzero.auth.routes import router as auth_router

app = FastAPI(title="Dispatch Zero")
app.include_router(auth_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"app": "dispatch-zero", "status": "operational"}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
