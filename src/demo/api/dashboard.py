"""Dashboard queries for Kafka observer and legacy Snowplow Micro storage."""
from __future__ import annotations

import os
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

from src.demo.api import business

APP_ID = os.getenv("CDP_DEMO_APP_ID", "cdp-demo")
EVENT_SOURCE = os.getenv("CDP_EVENT_SOURCE", "kafka")

SNOWPLOW_PG_HOST = os.getenv("SNOWPLOW_PG_HOST", "127.0.0.1")
SNOWPLOW_PG_PORT = int(os.getenv("SNOWPLOW_PG_PORT", "5432"))
SNOWPLOW_PG_DATABASE = os.getenv("SNOWPLOW_PG_DATABASE", "snowplow")
SNOWPLOW_PG_USER = os.getenv("SNOWPLOW_PG_USER", "snowplow")
SNOWPLOW_PG_PASSWORD = os.getenv("SNOWPLOW_PG_PASSWORD", "cdp-local-snowplow")

# Cửa sổ thời gian dùng cho dashboard (mặc định 24 giờ gần nhất).
SUMMARY_WINDOW_HOURS = int(os.getenv("CDP_DEMO_WINDOW_HOURS", "24"))


def _connect():
    if EVENT_SOURCE == "kafka":
        return psycopg.connect(business.DSN, options="-c search_path=observer", connect_timeout=5, row_factory=dict_row)
    return psycopg.connect(
        host=SNOWPLOW_PG_HOST,
        port=SNOWPLOW_PG_PORT,
        dbname=SNOWPLOW_PG_DATABASE,
        user=SNOWPLOW_PG_USER,
        password=SNOWPLOW_PG_PASSWORD,
        connect_timeout=5,
        row_factory=dict_row,
    )


def payload_of(event_json: dict, event_name: str) -> dict:
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


def empty_summary(message: str = "", window_hours: int = SUMMARY_WINDOW_HOURS) -> dict[str, Any]:
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


def query_summary(window_hours: int) -> dict[str, Any]:
    """Tổng hợp số liệu từ enriched event trong Snowplow PostgreSQL."""
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)

    counts: dict[str, int] = {}
    search_terms: dict[str, int] = {}
    wishlist_items: dict[str, int] = {}
    categories: dict[str, int] = {}
    failed_count = 0
    event_count = 0

    kafka_metrics = {}
    with closing(_connect()) as conn:
        # All dashboard metrics describe the same database snapshot.
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
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

            # Return scalar counts rather than transferring every distinct ID.
            cur.execute(
                """
                SELECT COUNT(DISTINCT NULLIF(COALESCE(
                           event_json -> 'contexts_com_cdp_demo_source_1' -> 0 ->> 'anonymous_id',
                           user_id, domain_userid), '')) AS users,
                       COUNT(DISTINCT NULLIF(
                           event_json -> 'contexts_com_cdp_demo_session_1' -> 0 ->> 'session_id',
                           '')) AS sessions
                FROM events
                WHERE timestamp >= %s AND app_id = %s AND NOT failed
                """,
                (since, APP_ID),
            )
            unique = cur.fetchone()

        # A server-side cursor bounds memory while decoding event payloads.
        with conn.cursor(name="summary_payloads") as cur:
            cur.itersize = 1000
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
            for row in cur:
                name = row["event_name"]
                payload = payload_of(row["event_json"] or {}, name)
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

        if EVENT_SOURCE == "kafka":
            rows = conn.execute("SELECT persona,event_name,count(*) AS n FROM events "
                                "WHERE timestamp >= %s AND app_id = %s AND NOT failed AND persona IS NOT NULL GROUP BY 1,2", (since, APP_ID)).fetchall()
            personas = {}
            for row in rows:
                personas.setdefault(row["persona"], {})[row["event_name"]] = row["n"]
            kafka_metrics["personas"] = personas
            carts = conn.execute(
                "WITH s AS (SELECT COALESCE(event_json -> 'contexts_com_cdp_demo_source_1' -> 0 ->> 'anonymous_id', user_id, domain_userid),session_id,bool_or(event_name='add_to_cart') AS added, "
                "bool_or(event_name='cart_abandoned') AS abandoned FROM events "
                "WHERE timestamp >= %s AND app_id = %s AND NOT failed AND session_id IS NOT NULL GROUP BY 1,2) "
                "SELECT count(*) FILTER(WHERE added) AS carts,count(*) FILTER(WHERE added AND abandoned) AS abandoned FROM s",
                (since, APP_ID),
            ).fetchone()
            kafka_metrics["cart_abandon_rate"] = round(100*carts["abandoned"]/carts["carts"]) if carts["carts"] else 0
            kafka_metrics["transport"] = conn.execute(
                "SELECT topic,count(*) AS records,count(*) FILTER(WHERE decode_error IS NOT NULL) AS decode_errors "
                "FROM kafka_records GROUP BY topic ORDER BY topic").fetchall()

    cart_add = counts.get("add_to_cart", 0)
    cart_abandoned = counts.get("cart_abandoned", 0)
    cart_abandon_rate = round(cart_abandoned / cart_add * 100) if cart_add else 0

    result = {
        "event_count": event_count,
        "counts": counts,
        "failed_count": failed_count,
        "unique_users": unique["users"],
        "unique_sessions": unique["sessions"],
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
    result["source"] = "Kafka observer" if EVENT_SOURCE == "kafka" else "Snowplow Micro PostgreSQL"
    result.update(kafka_metrics)
    return result
