"""
src/demo/api/server.py — Read-only query API trên top của Snowplow.

Backend KHÔNG còn tự thu thập, validate hay lưu event. Toàn bộ phần đó đã
được giao cho Snowplow:

    Snowplow Browser Tracker ──▶ Collector (Micro :9090)
                                          │
                                          ▼
                               Enrich (Iglu validate + YAUAA)
                                          │
                                          ▼
                               PostgreSQL (storage backend)

Endpoint còn lại ở đây chỉ phục vụ hai việc:

- ``GET /api/catalog``  — trả về danh mục sản phẩm tĩnh (không phải event data).
- ``GET /api/summary``  — tổng hợp số liệu từ enriched event trong PostgreSQL
  cho dashboard.

Tổng hợp được đọc trực tiếp từ bảng ``events`` mà Snowplow Micro ghi, theo
đúng cấu trúc enriched event của Snowplow:

    events(event_id, timestamp, event_json, failed, app_id, event_name,
           platform, name_tracker, domain_userid, v_tracker, user_id,
           network_userid)

Event của CDP Demo là *self-describing event*, nên:

- ``event_name`` = tên event lấy từ Iglu schema (``product_view``, ...).
- payload nằm trong ``event_json -> unstruct_event -> data -> data``.
- entity ``com.cdp.demo/session`` nằm trong ``event_json -> contexts``.

Nếu Snowplow chưa chạy, endpoint trả về payload rỗng kèm cờ
``snowplow_available=false`` để dashboard hiển thị hướng dẫn thay vì lỗi 500.
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ── Paths ────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATH = ROOT / "config" / "demo" / "catalog.products.json"

# ── Constants ─────────────────────────────────────────────────────────────────

CATALOG: list[dict] = []
_catalog_lock = threading.Lock()

# app_id gắn vào mọi event của CDP Demo (xem src/demo/web/js/tracker.js).
APP_ID = os.getenv("CDP_DEMO_APP_ID", "cdp-demo")

SNOWPLOW_PG_HOST = os.getenv("SNOWPLOW_PG_HOST", "127.0.0.1")
SNOWPLOW_PG_PORT = int(os.getenv("SNOWPLOW_PG_PORT", "5432"))
SNOWPLOW_PG_DATABASE = os.getenv("SNOWPLOW_PG_DATABASE", "snowplow")
SNOWPLOW_PG_USER = os.getenv("SNOWPLOW_PG_USER", "snowplow")
SNOWPLOW_PG_PASSWORD = os.getenv("SNOWPLOW_PG_PASSWORD", "cdp-local-snowplow")

# Cửa sổ thời gian dùng cho dashboard (mặc định 24 giờ gần nhất).
SUMMARY_WINDOW_HOURS = int(os.getenv("CDP_DEMO_WINDOW_HOURS", "24"))

# Vendor của schema CDP Demo — dùng để lọc entity khi rút session_id.
CDP_VENDOR = "com.cdp.demo"


# ── Catalog loader ────────────────────────────────────────────────────────────

def _load_catalog() -> list[dict]:
    with _catalog_lock:
        if not CATALOG and CATALOG_PATH.exists():
            with open(CATALOG_PATH, encoding="utf-8") as f:
                CATALOG.extend(json.load(f))
        return CATALOG


# ── Snowplow access ───────────────────────────────────────────────────────────

def _connect():
    return psycopg.connect(
        host=SNOWPLOW_PG_HOST,
        port=SNOWPLOW_PG_PORT,
        dbname=SNOWPLOW_PG_DATABASE,
        user=SNOWPLOW_PG_USER,
        password=SNOWPLOW_PG_PASSWORD,
        connect_timeout=5,
        row_factory=dict_row,
    )


def _payload_of(event_json: dict, event_name: str) -> dict:
    """
    Lấy payload của self-describing event.

    Payload được lưu ở cột phẳng ``unstruct_event_<vendor>_<name>_<số>``,
    ví dụ ``unstruct_event_com_cdp_demo_product_view_1``.
    """
    prefix = f"unstruct_event_com_cdp_demo_{event_name}_"
    for key, value in event_json.items():
        if key.startswith(prefix) and isinstance(value, dict):
            return value
    return {}


def _empty_summary(message: str = "", window_hours: int = SUMMARY_WINDOW_HOURS) -> dict[str, Any]:
    return {
        "event_count": 0,
        "counts": {},
        "failed_count": 0,
        "unique_users": 0,
        "unique_sessions": 0,
        "cart_abandon_rate": 0,
        "top_searches": [],
        "top_wishlist": [],
        "categories": [],
        "window_hours": window_hours,
        "snowplow_available": False,
        "message": message,
    }


def _query_summary(window_hours: int) -> dict[str, Any]:
    """Tổng hợp số liệu từ enriched event trong Snowplow PostgreSQL."""
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)

    counts: dict[str, int] = {}
    search_terms: dict[str, int] = {}
    wishlist_items: dict[str, int] = {}
    categories: dict[str, int] = {}
    unique_users: set[str] = set()
    unique_sessions: set[str] = set()
    failed_count = 0
    event_count = 0

    with closing(_connect()) as conn:
        with conn.cursor() as cur:
            # 1) Đếm theo loại event + số event lỗi.
            cur.execute(
                """
                SELECT event_name,
                       COUNT(*) AS n,
                       COUNT(*) FILTER (WHERE failed) AS n_failed
                FROM events
                WHERE timestamp >= %s AND app_id = %s
                GROUP BY event_name
                """,
                (since, APP_ID),
            )
            for row in cur.fetchall():
                name = row["event_name"] or "unknown"
                counts[name] = row["n"] - row["n_failed"]
                failed_count += row["n_failed"]
                event_count += row["n"] - row["n_failed"]

            # 2) Người dùng / phiên duy nhất.
            #    session_id nằm trong entity com.cdp.demo/session do app gửi lên.
            cur.execute(
                """
                SELECT DISTINCT user_id FROM events
                WHERE timestamp >= %s AND app_id = %s AND NOT failed
                  AND user_id IS NOT NULL
                """,
                (since, APP_ID),
            )
            unique_users = {r["user_id"] for r in cur.fetchall() if r["user_id"]}

            cur.execute(
                """
                SELECT DISTINCT session_id
                FROM (
                    SELECT e.event_json -> 'contexts_com_cdp_demo_session_1' -> 0 ->> 'session_id'
                           AS session_id
                    FROM events e
                    WHERE e.timestamp >= %s AND e.app_id = %s AND NOT e.failed
                ) s
                WHERE session_id IS NOT NULL
                """,
                (since, APP_ID),
            )
            unique_sessions = {r["session_id"] for r in cur.fetchall() if r["session_id"]}

            # 3) Payload cần cho các bảng top (search / wishlist / category).
            cur.execute(
                """
                SELECT event_name, event_json
                FROM events
                WHERE timestamp >= %s AND app_id = %s AND NOT failed
                  AND event_name IN ('search', 'wishlist_add', 'product_view')
                """,
                (since, APP_ID),
            )
            for row in cur.fetchall():
                name = row["event_name"]
                payload = _payload_of(row["event_json"] or {}, name)
                if name == "search":
                    query = (payload.get("query") or "").strip()
                    if query:
                        search_terms[query] = search_terms.get(query, 0) + 1
                elif name == "wishlist_add":
                    product_id = payload.get("product_id")
                    if product_id:
                        wishlist_items[product_id] = wishlist_items.get(product_id, 0) + 1
                elif name == "product_view":
                    category_id = payload.get("category_id")
                    if category_id:
                        categories[category_id] = categories.get(category_id, 0) + 1

    cart_add = counts.get("add_to_cart", 0)
    cart_abandoned = counts.get("cart_abandoned", 0)
    cart_abandon_rate = round(cart_abandoned / cart_add * 100) if cart_add else 0

    return {
        "event_count": event_count,
        "counts": counts,
        "failed_count": failed_count,
        "unique_users": len(unique_users),
        "unique_sessions": len(unique_sessions),
        "cart_abandon_rate": cart_abandon_rate,
        "top_searches": [
            {"query": q, "count": c}
            for q, c in sorted(search_terms.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        ],
        "top_wishlist": [
            {"product_id": p, "count": c}
            for p, c in sorted(wishlist_items.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        ],
        "categories": [
            {"category_id": c, "count": n}
            for c, n in sorted(categories.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
        ],
        "window_hours": window_hours,
        "snowplow_available": True,
        "message": "",
    }


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="CDP Demo API (Snowplow read layer)", version="2.0.0")

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
    return JSONResponse(content=_load_catalog())


@app.get("/api/summary")
async def get_summary():
    try:
        summary = _query_summary(SUMMARY_WINDOW_HOURS)
    except psycopg.Error as exc:
        detail = str(exc).strip()
        return JSONResponse(content=_empty_summary(
            message=(
                f"Không kết nối được Snowplow PostgreSQL ({SNOWPLOW_PG_HOST}:"
                f"{SNOWPLOW_PG_PORT}/{SNOWPLOW_PG_DATABASE}): {detail}"
            )
        ))
    return JSONResponse(content=summary)


# ── CLI entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
