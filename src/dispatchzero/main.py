from fastapi import FastAPI

app = FastAPI(title="Dispatch Zero")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
