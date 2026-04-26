from fastapi import FastAPI

app = FastAPI(title="Dispatch Zero")


@app.get("/")
async def root() -> dict[str, str]:
    return {"app": "dispatch-zero", "status": "operational"}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
