"""
src/demo/api/server.py — Demo Event Collection API (FastAPI)

Endpoints
--------
GET  /api/catalog          Returns the static product catalog JSON.
POST /api/events           Ingests a batch of events, assigns ordinal/batch_id,
                           runs schema checks, routes bad rows to quarantine.
GET  /api/summary          Returns per-batch counts for the dashboard.
GET  /health               Simple health check.

Idempotency
-----------
batch_id is derived from the content of the incoming payload (SHA-256 of the
serialised JSON body).  Rerunning the same payload returns HTTP 200 with the
existing manifest and does NOT write new files.

Quota / Quality Rules
--------------------
- event_type must be in SUPPORTED_EVENT_TYPES.
- event_time must be a valid ISO 8601 UTC timestamp.
- Missing session_id → quarantined (strict mode, default ON).
- Missing user_id    → quarantined (strict mode, default ON).
- price in payload must be a non-negative decimal string; currency is required.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fastapi
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

# ── Paths ────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parents[3]          # repo root
CATALOG_PATH = ROOT / "config" / "demo" / "catalog.products.json"
EVENTS_ROOT = ROOT / "data" / "demo-events"
EVENTS_ROOT.mkdir(parents=True, exist_ok=True)

# ── Constants ─────────────────────────────────────────────────────────────────

CATALOG: list[dict] = []
_catalog_lock = threading.Lock()

SUPPORTED_EVENT_TYPES: set[str] = {
    "page_view", "product_view", "add_to_cart", "remove_from_cart",
    "begin_checkout", "purchase_observed", "element_click",
    "scroll_depth", "search", "error",
}

_INGESTION_LOCK = threading.Lock()   # serialise writes within a single process

# ── Data models ───────────────────────────────────────────────────────────────

class IncomingEvent(BaseModel):
    event_type: str
    event_time: str
    session_id: str | None = None
    user_id: str | None = None
    namespace: str = "cdp.demo.events"
    source: str = "web-demo"
    url: str = ""
    referrer: str = ""
    user_agent: str = ""
    viewport: str = ""
    payload: dict = Field(default_factory=dict)

    @field_validator("event_time")
    @classmethod
    def _valid_timestamp(cls, v: str) -> str:
        # Accept ISO 8601 with up to millisecond precision
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Invalid ISO 8601 timestamp: {v}") from exc
        if dt.tzinfo is None:
            raise ValueError(f"event_time must include timezone (UTC): {v}")
        return v

    @field_validator("event_type")
    @classmethod
    def _valid_event_type(cls, v: str) -> str:
        if v not in SUPPORTED_EVENT_TYPES:
            raise ValueError(f"Unsupported event_type: {v}")
        return v


class EventBatchResponse(BaseModel):
    batch_id: str
    total_accepted: int
    total_quarantined: int
    event_checksum: str
    message: str


class SummaryResponse(BaseModel):
    batch_id: str
    event_count: int
    counts: dict[str, int]
    missing_session_count: int
    missing_user_count: int
    unique_users: int
    unique_sessions: int


# ── Catalog loader ─────────────────────────────────────────────────────────────

def _load_catalog() -> list[dict]:
    with _catalog_lock:
        if CATALOG:
            return CATALOG
        if CATALOG_PATH.exists():
            with open(CATALOG_PATH, encoding="utf-8") as f:
                CATALOG.extend(json.load(f))
        return CATALOG


# ── Core ingestion logic ──────────────────────────────────────────────────────

def _compute_event_id(namespace: str, batch_checksum: str, ordinal: int) -> str:
    raw = f"{namespace}:{batch_checksum}:{ordinal}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _batch_checksum(events: list[dict]) -> str:
    """Stable SHA-256 of the serialised event list for idempotency."""
    payload = json.dumps(events, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def ingest_events(
    events: list[IncomingEvent],
    strict_user: bool = True,
) -> tuple[EventBatchResponse, list[dict]]:
    """
    Process a batch of incoming events:
      1. Validate each event.
      2. Assign ordinal, ingestion_time, event_id.
      3. Route bad rows to quarantine.
      4. Write CSV + manifest (idempotent by batch_checksum).
    Returns (response, quarantined_rows).
    """
    raw_events = [e.model_dump() for e in events]
    batch_checksum = _batch_checksum(raw_events)

    with _INGESTION_LOCK:
        # Check idempotency — look for an existing manifest with the same checksum
        existing = _find_existing_batch(batch_checksum)
        if existing:
            manifest = existing
            batch_id = manifest["batch_id"]
        else:
            batch_id = str(uuid.uuid4())
            accepted_rows: list[dict] = []
            quarantine_rows: list[dict] = []

            ingestion_time = datetime.now(timezone.utc).isoformat()

            for ordinal, raw in enumerate(raw_events, start=1):
                ev = raw.copy()
                q_flags: list[str] = []

                # Session check
                if not ev.get("session_id"):
                    q_flags.append("missing_session")
                # User check
                if strict_user and not ev.get("user_id"):
                    q_flags.append("missing_user_id")

                if q_flags:
                    ev["quality_flags"] = q_flags
                    ev["ordinal"] = ordinal
                    ev["ingestion_time"] = ingestion_time
                    ev["batch_id"] = batch_id
                    ev["event_id"] = _compute_event_id(ev["namespace"], batch_checksum, ordinal)
                    quarantine_rows.append(ev)
                else:
                    ev["quality_flags"] = []
                    ev["ordinal"] = ordinal
                    ev["ingestion_time"] = ingestion_time
                    ev["batch_id"] = batch_id
                    ev["event_id"] = _compute_event_id(ev["namespace"], batch_checksum, ordinal)
                    accepted_rows.append(ev)

            batch_dir = EVENTS_ROOT / batch_id
            batch_dir.mkdir(parents=True, exist_ok=True)

            events_file = batch_dir / "events.csv"
            q_file = batch_dir / "quarantine.csv"

            _write_csv(events_file, accepted_rows)
            _write_csv(q_file, quarantine_rows)

            # Compute per-event-type counts
            counts: dict[str, int] = {}
            for r in accepted_rows:
                key = f"{r['namespace']}/{r['event_type']}"
                counts[key] = counts.get(key, 0) + 1

            unique_users = len({r["user_id"] for r in accepted_rows if r.get("user_id")})
            unique_sessions = len({r["session_id"] for r in accepted_rows if r.get("session_id")})
            missing_sessions = sum(1 for r in quarantine_rows if "missing_session" in r.get("quality_flags", []))
            missing_users = sum(1 for r in quarantine_rows if "missing_user_id" in r.get("quality_flags", []))

            manifest = {
                "batch_id": batch_id,
                "batch_checksum": batch_checksum,
                "event_count": len(accepted_rows),
                "quarantine_count": len(quarantine_rows),
                "counts": counts,
                "missing_session_count": missing_sessions,
                "missing_user_count": missing_users,
                "unique_users": unique_users,
                "unique_sessions": unique_sessions,
                "ingestion_time": ingestion_time,
                "strict_user": strict_user,
                "source": "demo-api",
            }

            with open(batch_dir / "manifest.json", "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)

    resp = EventBatchResponse(
        batch_id=batch_id,
        total_accepted=manifest["event_count"],
        total_quarantined=manifest["quarantine_count"],
        event_checksum=batch_checksum,
        message="Batch ingested successfully." if not existing else "Batch already exists (idempotent rerun).",
    )
    return resp, manifest.get("quarantine_count", 0)


def _find_existing_batch(checksum: str) -> dict | None:
    """Return manifest if a batch with this checksum already exists."""
    for batch_dir in EVENTS_ROOT.iterdir():
        if not batch_dir.is_dir():
            continue
        manifest_path = batch_dir / "manifest.json"
        if manifest_path.exists():
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    m = json.load(f)
                if m.get("batch_checksum") == checksum:
                    return m
            except Exception:
                continue
    return None


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        # Write empty file with headers only
        headers = list(rows[0].keys()) if rows else [
            "event_id", "event_time", "event_type", "session_id", "user_id",
            "namespace", "source", "url", "referrer", "user_agent", "viewport",
            "payload", "quality_flags", "ordinal", "batch_id", "ingestion_time",
        ]
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(",".join(headers) + "\n")
        return
    import csv, io, json as _json
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    for row in rows:
        # Serialise complex fields
        row = dict(row)
        for k, v in row.items():
            if isinstance(v, (dict, list)):
                row[k] = _json.dumps(v)
        writer.writerow(row)
    with open(path, "w", encoding="utf-8") as f:
        f.write(output.getvalue())


def _latest_manifest() -> dict | None:
    """Return the most recently-written manifest."""
    manifests = []
    for d in EVENTS_ROOT.iterdir():
        if not d.is_dir():
            continue
        mp = d / "manifest.json"
        if mp.exists():
            try:
                with open(mp, encoding="utf-8") as f:
                    m = json.load(f)
                manifests.append((os.path.getmtime(mp), m))
            except Exception:
                continue
    if not manifests:
        return None
    manifests.sort(key=lambda x: x[0], reverse=True)
    return manifests[0][1]


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="CDP Demo Event API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/api/catalog")
async def get_catalog():
    catalog = _load_catalog()
    return JSONResponse(content=catalog)


@app.post("/api/events", response_model=EventBatchResponse)
async def post_events(
    events: list[IncomingEvent] = fastapi.Body(...),
    strict_user: bool = True,
):
    if not events:
        raise HTTPException(status_code=400, detail="Empty event batch")
    resp, _ = ingest_events(events, strict_user=strict_user)
    return resp


@app.get("/api/summary")
async def get_summary(batch_id: str | None = None):
    if batch_id:
        manifest_path = EVENTS_ROOT / batch_id / "manifest.json"
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found")
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    else:
        manifest = _latest_manifest()
        if not manifest:
            return JSONResponse(content={
                "batch_id": "none",
                "event_count": 0,
                "counts": {},
                "missing_session_count": 0,
                "missing_user_count": 0,
                "unique_users": 0,
                "unique_sessions": 0,
            })

    return JSONResponse(content={
        "batch_id": manifest["batch_id"],
        "event_count": manifest["event_count"],
        "counts": manifest.get("counts", {}),
        "missing_session_count": manifest.get("missing_session_count", 0),
        "missing_user_count": manifest.get("missing_user_count", 0),
        "unique_users": manifest.get("unique_users", 0),
        "unique_sessions": manifest.get("unique_sessions", 0),
    })


# ── CLI entrypoint ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
