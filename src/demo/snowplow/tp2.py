"""
src/demo/snowplow/tp2.py — Client Tracker Protocol 2 (TP2) cho CDP Demo.

Đây là "server-side tracker" của demo: cùng giao thức mà Snowplow Browser
Tracker dùng ở frontend, nên bot và web ghi vào cùng một pipeline Snowplow.

Gói TP2 gửi tới Collector:

    POST http://127.0.0.1:9090/com.snowplowanalytics.snowplow/tp2
    Content-Type: application/json

    {
      "schema": "iglu:com.snowplowanalytics.snowplow/payload_data/jsonschema/1-0-4",
      "data": [ { ...event... } ]
    }

Mỗi event của CDP Demo là *self-describing event* (``e = "ue"``). Định dạng
chuẩn (khớp 100% với Browser Tracker v4) là:

    {
      "e": "ue",
      "eid": "<uuid>", "dtm": "<ms>", "stm": "<ms>",
      "tv": "py-1.0.0", "tna": "cdpDemoBot", "aid": "cdp-demo", "p": "web",
      "uid": "<user id>", "url": "<page url>",
      "ue_pr": "{\"schema\":\"iglu:.../unstruct_event/jsonschema/1-0-0\","
               "\"data\":{\"schema\":\"iglu:com.cdp.demo/<event>/jsonschema/1-0-0\","
               "\"data\":{ ...payload... }}}",
      "co":    "{\"schema\":\"iglu:.../contexts/jsonschema/1-0-0\","
               "\"data\":[ {\"schema\":\"iglu:com.cdp.demo/session/...\","
               "\"data\":{...}} ]}"
    }

Hai điểm dễ sai:

1. ``ue_pr`` và ``co`` là **chuỗi JSON**, không phải object. Collector parse
   chúng bằng JSON parser; nếu truyền object thì collector báo
   ``INVALID_DATA_PAYLOAD`` và event rơi vào bad stream.
2. ``ue_pr`` bọc trong wrapper ``unstruct_event`` 1-0-0; ``co`` bọc trong
   wrapper ``contexts`` 1-0-0.

Snowplow Enrich sẽ validate payload theo Iglu schema; event không khớp sẽ bị
ghi vào bad stream với ``failed = true`` trong bảng ``events``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx

# ── Constants ─────────────────────────────────────────────────────────────────

COLLECTOR_URL = "http://127.0.0.1:9090"
TP2_PATH = "/com.snowplowanalytics.snowplow/tp2"

VENDOR = "com.cdp.demo"
SCHEMA_VERSION = "1-0-0"

APP_ID = "cdp-demo"
TRACKER_NAME = "cdpDemoBot"
TRACKER_VERSION = "py-1.0.0"
PLATFORM = "web"
BOT_USER_AGENT = "CDP-DemoBot/1.0"

# Wrapper schema của Snowplow.
PAYLOAD_DATA_SCHEMA = "iglu:com.snowplowanalytics.snowplow/payload_data/jsonschema/1-0-4"
UNSTRUCT_EVENT_SCHEMA = "iglu:com.snowplowanalytics.snowplow/unstruct_event/jsonschema/1-0-0"
CONTEXTS_SCHEMA = "iglu:com.snowplowanalytics.snowplow/contexts/jsonschema/1-0-0"

DEFAULT_TIMEOUT = 30.0


# ── Schema helpers ────────────────────────────────────────────────────────────

def schema_uri(name: str, version: str = SCHEMA_VERSION) -> str:
    """URI Iglu của một schema của app, ví dụ ``iglu:com.cdp.demo/page_view/jsonschema/1-0-0``."""
    return f"iglu:{VENDOR}/{name}/jsonschema/{version}"


def event_schema_uri(name: str) -> str:
    return schema_uri(name)


def entity_schema_uri(name: str) -> str:
    return schema_uri(name)


def _now_ms() -> str:
    return str(int(datetime.now(timezone.utc).timestamp() * 1000))


# ── Event builders ────────────────────────────────────────────────────────────

def build_event(
    event_type: str,
    data: dict[str, Any],
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    product: dict[str, Any] | None = None,
    url: str = "http://localhost:8081/",
    event_id: str | None = None,
    event_time_ms: str | None = None,
) -> dict[str, Any]:
    """
    Dựng một self-describing event theo TP2.

    :param event_type: tên event, khớp với schema trong
        ``config/snowplow/iglu-client-embedded/schemas/com.cdp.demo/``.
    :param data: payload theo schema. Phải khớp chính xác — schema khai báo
        ``additionalProperties: false`` nên field thừa sẽ fail validation.
    :param user_id: định danh người dùng (atomic ``user_id`` của Snowplow).
    :param session_id: định danh phiên, gửi kèm entity ``com.cdp.demo/session``.
    :param product: sản phẩm liên quan, gửi kèm entity ``com.cdp.demo/product``.
    """
    unstruct_event = {
        "schema": UNSTRUCT_EVENT_SCHEMA,
        "data": {
            "schema": event_schema_uri(event_type),
            "data": data,
        },
    }

    entities: list[dict[str, Any]] = []
    if session_id:
        entities.append({
            "schema": entity_schema_uri("session"),
            "data": {"session_id": session_id},
        })
    if product and product.get("product_id"):
        entities.append({
            "schema": entity_schema_uri("product"),
            "data": {
                "product_id": product["product_id"],
                "category_id": product.get("category_id", ""),
                "brand": product.get("brand", ""),
                "price": product.get("price", ""),
                "currency": product.get("currency", "USD"),
            },
        })

    now_ms = event_time_ms or _now_ms()
    event: dict[str, Any] = {
        "e": "ue",
        "eid": event_id or str(uuid.uuid4()),
        "dtm": now_ms,
        "stm": now_ms,
        "tv": TRACKER_VERSION,
        "tna": TRACKER_NAME,
        "aid": APP_ID,
        "p": PLATFORM,
        "url": url,
        # ue_pr là CHUỖI JSON, không phải object.
        "ue_pr": json.dumps(unstruct_event, separators=(",", ":")),
    }
    if user_id:
        event["uid"] = user_id
    if entities:
        event["co"] = json.dumps(
            {"schema": CONTEXTS_SCHEMA, "data": entities},
            separators=(",", ":"),
        )
    return event


def build_payload(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Bọc danh sách event thành gói TP2 hoàn chỉnh."""
    return {
        "schema": PAYLOAD_DATA_SCHEMA,
        "data": list(events),
    }


# ── Collector client ──────────────────────────────────────────────────────────

class SnowplowCollector:
    """
    Client nhỏ gửi gói TP2 tới Snowplow Collector.

    Dùng cho bot: mỗi worker giữ một ``httpx.Client`` riêng để tận dụng
    keep-alive, tránh mở connection mới cho từng event.
    """

    def __init__(
        self,
        collector_url: str = COLLECTOR_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.collector_url = collector_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(
            timeout=timeout,
            headers={"Content-Type": "application/json", "User-Agent": BOT_USER_AGENT},
        )

    @property
    def endpoint(self) -> str:
        return f"{self.collector_url}{TP2_PATH}"

    def send(self, events: list[dict[str, Any]]) -> bool:
        """Gửi một gói event. Trả về True nếu collector nhận (HTTP 2xx)."""
        if not events:
            return True
        body = json.dumps(build_payload(events), separators=(",", ":"))
        try:
            resp = self._client.post(
                self.endpoint,
                content=body.encode("utf-8"),
            )
        except Exception:
            return False
        return 200 <= resp.status_code < 300

    def send_one(self, event: dict[str, Any]) -> bool:
        return self.send([event])

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SnowplowCollector":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
