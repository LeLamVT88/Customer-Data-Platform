"""HTTP entrypoint for the demo business API and observer dashboard."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import psycopg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from src.demo.api import business
from src.demo.catalog import load_catalog
from src.demo.api.dashboard import (
    EVENT_SOURCE,
    SUMMARY_WINDOW_HOURS,
    empty_summary,
    query_summary,
)


# ── FastAPI app ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app):
    await run_in_threadpool(business.seed_catalog, load_catalog())
    yield


app = FastAPI(title="CDP Demo — business source and Kafka observer", version="3.0.0", lifespan=lifespan)
app.include_router(business.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8081", "http://localhost:8081"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/api/catalog")
def get_catalog():
    return JSONResponse(content=business.catalog_from_db())


@app.get("/api/summary")
def get_summary():
    try:
        summary = query_summary(SUMMARY_WINDOW_HOURS)
    except psycopg.Error as exc:
        detail = str(exc).strip()
        return JSONResponse(content=empty_summary(
            message=(
                f"Không đọc được dữ liệu {EVENT_SOURCE}: {detail}"
            )
        ))
    return JSONResponse(content=summary)


# ── CLI entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
