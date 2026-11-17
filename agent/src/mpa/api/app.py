"""FastAPI app. Skeleton: task s3-api replaces this with the real API (keep GET /health)."""

from fastapi import FastAPI

app = FastAPI(title="meeting-prep-agent")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
